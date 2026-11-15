#!/usr/bin/env bash
# Instala Study Lens desde el código fuente (sin sudo). Para usarlo sin instalar
# nada, baja el ejecutable del último release.
#   ./install.sh              instala o actualiza
#   ./install.sh --uninstall  lo quita (deja tus atajos y configuración en ~/.config/study-lens)
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
if [[ "${1:-}" == "--uninstall" ]]; then
  "$DIR/study-lens" --unsetup || true
  rm -rf "$DIR/.venv"
  echo "Study Lens desinstalado. Puedes borrar esta carpeta."
  exit 0
fi

missing=()
for cmd in hyprctl grim slurp opencode python3; do
  command -v "$cmd" >/dev/null || missing+=("$cmd")
done
python3 -c 'import gi; gi.require_version("Gtk", "4.0")' 2>/dev/null || missing+=("python-gobject + gtk4")
if ((${#missing[@]})); then
  echo "Faltan: ${missing[*]}"
  echo "En Arch/Omarchy: sudo pacman -S --needed python-gobject gtk4 grim slurp  (y opencode: https://opencode.ai)"
  exit 1
fi

echo "→ Entorno de Python (.venv) con las dependencias…"
python3 -m venv --system-site-packages "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q --upgrade -r "$DIR/requirements.txt"

echo "→ Comando, lanzador y atajos de Hyprland…"
"$DIR/study-lens" --setup

case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "Nota: agrega ~/.local/bin a tu PATH.";; esac
