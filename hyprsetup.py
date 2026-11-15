"""Instala Study Lens para el usuario: comando, lanzador y configuración de Hyprland (Omarchy).

- Pone el comando `study-lens` en ~/.local/bin (copia el ejecutable, o enlaza el
  lanzador si corre desde el código fuente) y la entrada del lanzador de aplicaciones.
- Copia hypr/study_lens.lua (del proyecto) a ~/.config/hypr/study_lens.lua.
- Agrega una línea `require("hypr.study_lens")` al final de ~/.config/hypr/bindings.lua
  (guardando antes una copia bindings.lua.bak.<fecha>).
Al arrancar, la app vuelve a copiar la plantilla si cambió (p. ej. tras actualizar).
"""

import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
TEMPLATE = APP_DIR / "hypr" / "study_lens.lua"
HYPR_DIR = Path.home() / ".config" / "hypr"
TARGET = HYPR_DIR / "study_lens.lua"
BINDINGS = HYPR_DIR / "bindings.lua"
BIN = Path.home() / ".local" / "bin" / "study-lens"
DESKTOP = Path.home() / ".local" / "share" / "applications" / "study-lens.desktop"
DESKTOP_ENTRY = f"""[Desktop Entry]
Type=Application
Name=Study Lens
Comment=Analiza ejercicios en pantalla y te explica la solución
Exec={BIN}
Icon=accessories-dictionary
Terminal=false
Categories=Education;Utility;
StartupWMClass=dev.zavu.StudyLens
"""
REQUIRE_LINE = 'require("hypr.study_lens")  -- Study Lens (lo agregó `study-lens --setup`)'


def is_installed():
    try:
        return 'require("hypr.study_lens")' in BINDINGS.read_text()
    except OSError:
        return False


def reload():
    """Recarga Hyprland y devuelve sus errores de configuración (o None)."""
    try:
        subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=10)
        errs = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True,
                              timeout=5).stdout.strip()
        return errs or None
    except Exception as e:
        return str(e)


def _copy_template():
    """Copia la plantilla si falta o cambió. Devuelve True si escribió algo."""
    new = TEMPLATE.read_text()
    if TARGET.exists() and TARGET.read_text() == new:
        return False
    TARGET.write_text(new)
    return True


def _executable():
    """El archivo único del release (si corre desde él) o None si corre desde el código."""
    exe = Path(sys.argv[0]).resolve()
    return exe if exe.is_file() and zipfile.is_zipfile(exe) else None


def install_command():
    """Pone `study-lens` en ~/.local/bin y la entrada del lanzador."""
    BIN.parent.mkdir(parents=True, exist_ok=True)
    exe = _executable()
    if exe is not None:
        if exe != BIN.resolve():
            tmp = BIN.with_name(".study-lens.new")
            shutil.copy2(exe, tmp)
            tmp.chmod(0o755)
            if BIN.is_symlink():
                BIN.unlink()
            os.replace(tmp, BIN)
    else:
        launcher = APP_DIR / "study-lens"
        if BIN.is_symlink() or BIN.exists():
            BIN.unlink()
        BIN.symlink_to(launcher)
    DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP.write_text(DESKTOP_ENTRY)


def setup():
    """Instala (o repara) todo. Devuelve (ok, mensaje)."""
    if not HYPR_DIR.is_dir() or not BINDINGS.exists():
        return False, f"No encontré {BINDINGS}. ¿Usas Hyprland con la configuración Lua de Omarchy?"
    install_command()
    _copy_template()
    if not is_installed():
        text = BINDINGS.read_text()
        BINDINGS.with_name(f"bindings.lua.bak.{int(time.time())}").write_text(text)
        BINDINGS.write_text(text.rstrip("\n") + "\n\n" + REQUIRE_LINE + "\n")
    err = reload()
    if err:
        return False, f"Instalado, pero Hyprland reportó errores:\n{err}"
    return True, ("Listo: comando study-lens, lanzador, atajos y regla de ventana instalados.\n"
                  "Abre Study Lens desde el lanzador o con Super+Alt+X (analizar región).")


def sync():
    """Al arrancar: si está instalado y la plantilla cambió, actualizarla."""
    try:
        if is_installed() and _copy_template():
            reload()
    except Exception:
        pass


def unsetup():
    """Quita la línea de bindings.lua y el archivo copiado. Devuelve (ok, mensaje)."""
    if BINDINGS.exists():
        lines = BINDINGS.read_text().splitlines()
        kept = [ln for ln in lines if 'require("hypr.study_lens")' not in ln]
        if kept != lines:
            BINDINGS.write_text("\n".join(kept).rstrip("\n") + "\n")
    TARGET.unlink(missing_ok=True)
    DESKTOP.unlink(missing_ok=True)
    if BIN.is_symlink() or BIN.exists():
        BIN.unlink()
    err = reload()
    return (False, err) if err else (True, "Study Lens desinstalado (tu configuración sigue en "
                                           "~/.config/study-lens).")
