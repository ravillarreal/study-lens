"""Atajos de Study Lens: leerlos de Hyprland, guardarlos y la ventana para cambiarlos.

Los atajos viven en ~/.config/study-lens/shortcuts.lua (lo escribe esta ventana).
~/.config/hypr/study_lens.lua (ver hyprsetup.py) lo carga y registra cada atajo con la descripción
"Study Lens: … (--acción)", que es como la app sabe cuál es cuál.
"""

import json
import re
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import hyprsetup  # noqa: E402

SHORTCUTS_FILE = Path.home() / ".config" / "study-lens" / "shortcuts.lua"

# Orden en que aparecen en la ventana, con su nombre.
ACTIONS = [
    ("region", "Analizar región", "Selecciona una región con el mouse y la captura"),
    ("more", "Otra captura", "Vuelve a capturar lo mismo (tras hacer scroll) y lo suma"),
    ("analyze", "Analizar capturas", "Manda las capturas pendientes al modelo"),
    ("new", "Nuevo ejercicio", "Vacía el ejercicio y recaptura la misma región"),
    ("window", "Analizar ventana", "Captura la ventana activa"),
    ("toggle", "Mostrar/ocultar panel", ""),
]
DEFAULT_BINDS = {"region": ["SUPER + ALT + X"], "more": ["SUPER + ALT + C"],
                 "analyze": ["SUPER + ALT + V"], "new": ["SUPER + ALT + Z"],
                 "window": ["SUPER + ALT + A"], "toggle": ["SUPER + ALT + Q"]}

MODS = [(64, "SUPER"), (4, "CTRL"), (8, "ALT"), (1, "SHIFT")]
MOUSE_NAMES = {"mouse:272": "Clic izquierdo", "mouse:273": "Clic derecho",
               "mouse:274": "Clic de la rueda", "mouse:275": "Botón lateral atrás",
               "mouse:276": "Botón lateral adelante"}
DESC_RE = re.compile(r"Study Lens:.*\(--(\w+)\)")


def _hypr_binds():
    out = subprocess.run(["hyprctl", "-j", "binds"], capture_output=True, text=True,
                         timeout=5, check=True)
    return json.loads(out.stdout)


def _combo(modmask, key):
    """modmask + tecla de Hyprland -> "SUPER + ALT + X"."""
    if len(key) == 1:
        key = key.upper()
    return " + ".join([name for bit, name in MODS if modmask & bit] + [key])


def _parse(combo):
    """"SUPER + ALT + X" -> (modmask, "x") para comparar sin importar mayúsculas."""
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    names = dict((n, b) for b, n in MODS)
    mask = sum(names.get(p.upper(), 0) for p in parts[:-1])
    return mask, parts[-1].lower() if parts else ""


def label(combo):
    """"SUPER + ALT + X" -> "Super+Alt+X"; los botones del mouse con nombre."""
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    if not parts:
        return combo
    key = parts[-1]
    key = MOUSE_NAMES.get(key, key.replace("mouse:", "Botón ") if key.startswith("mouse:")
                          else key.upper() if len(key) == 1 else key)
    return "+".join([p.capitalize() for p in parts[:-1]] + [key])


def current_binds():
    """{acción: ["SUPER + ALT + X", …]} tal como están cargados en Hyprland."""
    found = {}
    try:
        for b in _hypr_binds():
            m = DESC_RE.search(b.get("description", ""))
            if m and b.get("key"):
                found.setdefault(m.group(1), []).append(_combo(b.get("modmask", 0), b["key"]))
    except Exception:
        return {a: list(v) for a, v in DEFAULT_BINDS.items()}
    return {a: found.get(a, []) for a in DEFAULT_BINDS}


def labels():
    """{acción: "Super+Alt+X / Botón lateral atrás"} para los mensajes del panel."""
    return {a: " / ".join(label(c) for c in combos) or "sin atajo"
            for a, combos in current_binds().items()}


def other_binding(combo):
    """Descripción del atajo de Hyprland (que no sea de Study Lens) que ya usa esa combinación."""
    want = _parse(combo)
    try:
        for b in _hypr_binds():
            if DESC_RE.search(b.get("description", "")) or b.get("submap"):
                continue
            if (b.get("modmask", 0), b.get("key", "").lower()) == want and b.get("key"):
                return b.get("description") or b.get("dispatcher") or "otro atajo"
    except Exception:
        pass
    return None


def save(binds):
    """Escribe shortcuts.lua y recarga Hyprland. Devuelve el texto de error o None."""
    lines = ["-- Lo escribe Study Lens (ventana de Atajos). Mejor cámbialo desde ahí.", "return {"]
    for action, _name, _desc in ACTIONS:
        combos = ", ".join(json.dumps(c) for c in binds.get(action, []))
        lines.append(f"  {action} = {{ {combos} }},")
    lines.append("}")
    SHORTCUTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SHORTCUTS_FILE.write_text("\n".join(lines) + "\n")
    return hyprsetup.reload()


# ------------------------------------------------------------------ ventanas ---

MODIFIER_KEYS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L",
                 "Meta_R", "Super_L", "Super_R", "Hyper_L", "Hyper_R", "ISO_Level3_Shift",
                 "Caps_Lock", "Num_Lock"}
# Teclas que se pueden usar solas sin estorbar al escribir (las que suelen mandar
# los botones extra de los mouse configurados con su software).
SOLO_OK = re.compile(r"^(F([1-9]|1\d|2[0-4])|XF86.*|Pause|Scroll_Lock|Menu|Insert)$")


class CaptureDialog(Gtk.Window):
    """Escucha la próxima combinación de teclas o botón del mouse."""

    def __init__(self, parent, action_name, on_done):
        super().__init__(transient_for=parent, modal=True, title="Nuevo atajo")
        self.set_default_size(420, 260)
        self.on_done = on_done
        self.finished = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(16)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{GLib.markup_escape_text(action_name)}</b>")
        box.append(title)
        box.append(Gtk.Label(xalign=0, wrap=True, label=(
            "Presiona la combinación de teclas que quieras usar, "
            "o haz clic en el recuadro con el botón del mouse (puedes sostener Super/Alt/Ctrl).")))

        zone = Gtk.Frame(vexpand=True)
        zone.add_css_class("view")
        self.zone_label = Gtk.Label(label="Esperando…", wrap=True, justify=Gtk.Justification.CENTER)
        self.zone_label.add_css_class("title-2")
        zone.set_child(self.zone_label)
        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self.on_click)
        zone.add_controller(click)
        box.append(zone)

        self.msg = Gtk.Label(xalign=0, wrap=True)
        self.msg.add_css_class("dim-label")
        box.append(self.msg)

        cancel = Gtk.Button(label="Cancelar (Esc)", halign=Gtk.Align.END)
        cancel.connect("clicked", lambda *_: self.close())
        box.append(cancel)
        self.set_child(box)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        keys.connect("modifiers", self.on_mods)
        self.add_controller(keys)

        # Pide a Hyprland que le pase todas las teclas (incluso Super+…) a esta ventana.
        self.connect("map", self._inhibit)
        self.connect("close-request", self._on_close)

    def _inhibit(self, *_):
        surface = self.get_surface()
        if hasattr(surface, "inhibit_system_shortcuts"):
            surface.inhibit_system_shortcuts(None)

    def _on_close(self, *_):
        surface = self.get_surface()
        if surface is not None and hasattr(surface, "restore_system_shortcuts"):
            surface.restore_system_shortcuts()
        if not self.finished:
            self.finished = True
            self.on_done(None)
        return False

    @staticmethod
    def _mods(state):
        mods = []
        if state & Gdk.ModifierType.SUPER_MASK or state & Gdk.ModifierType.META_MASK:
            mods.append("SUPER")
        if state & Gdk.ModifierType.CONTROL_MASK:
            mods.append("CTRL")
        if state & Gdk.ModifierType.ALT_MASK:
            mods.append("ALT")
        if state & Gdk.ModifierType.SHIFT_MASK:
            mods.append("SHIFT")
        return mods

    def on_mods(self, _ctrl, state):
        if not self.finished:
            mods = self._mods(state)
            self.zone_label.set_text("+".join(m.capitalize() for m in mods) + "+…" if mods
                                     else "Esperando…")
        return False

    def on_key(self, ctrl, keyval, keycode, state):
        # Tecla sin modificadores aplicados (Shift+1 debe ser "1", no "!").
        ok, base, *_ = self.get_display().translate_key(keycode, 0, ctrl.get_group())
        name = Gdk.keyval_name(Gdk.keyval_to_lower(base if ok else keyval)) or ""
        if name in MODIFIER_KEYS or not name:
            return True
        mods = self._mods(state)
        if name == "Escape" and not mods:
            self.close()
            return True
        if not (set(mods) - {"SHIFT"}) and not SOLO_OK.match(name):
            self.show_msg(f"«{label(' + '.join(mods + [name]))}» sola estorbaría al escribir. "
                          "Agrégale Super, Alt o Ctrl (o usa F13–F24 / un botón del mouse).")
            return True
        self.finish(" + ".join(mods + [name.upper() if len(name) == 1 else name]))
        return True

    def on_click(self, gesture, _n, _x, _y):
        btn = gesture.get_current_button()
        # GTK numera 1 izq., 2 rueda, 3 der., y 8, 9… los laterales (BTN_LEFT + n − 5).
        code = {1: 272, 2: 274, 3: 273}.get(btn, 267 + btn if btn >= 8 else None)
        if code is None:
            return
        mods = self._mods(gesture.get_current_event_state())
        if code in (272, 273) and not mods:
            self.show_msg("El clic izquierdo o derecho solo dejaría de funcionar en todo el sistema. "
                          "Sostén Super, Alt o Ctrl mientras haces clic, o usa otro botón.")
            return
        self.finish(" + ".join(mods + [f"mouse:{code}"]))

    def show_msg(self, text):
        self.msg.set_text(text)

    def taken_by_study_lens(self, action_name):
        # Si Hyprland no respetó la inhibición, la combinación disparó un atajo nuestro.
        self.show_msg(f"Esa combinación ya es «{action_name}». Prueba otra, o quítasela primero.")

    def finish(self, combo):
        conflict = other_binding(combo)
        if conflict:
            self.show_msg(f"«{label(combo)}» ya lo usa Omarchy/Hyprland: {conflict}. Prueba otra.")
            return
        self.finished = True
        self.zone_label.set_text(label(combo))
        self.on_done(combo)
        GLib.timeout_add(250, lambda: (self.close(), False)[1])


class ShortcutsWindow(Gtk.Window):
    def __init__(self, parent, on_changed):
        super().__init__(transient_for=parent, title="Atajos de Study Lens")
        self.set_default_size(520, 560)
        self.set_hide_on_close(True)
        self.on_changed = on_changed
        self.capture = None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{side}")(14)
        outer.append(Gtk.Label(xalign=0, wrap=True, label=(
            "Pulsa «Agregar» y presiona la combinación o el botón del mouse que quieras. "
            "Cada acción puede tener varios atajos. Los cambios se aplican al instante.")))

        # Aviso si la configuración de Hyprland no está instalada (los atajos no harían nada).
        self.setup_bar = Gtk.Box(spacing=8)
        warn = Gtk.Label(xalign=0, wrap=True, hexpand=True, label=(
            "Los atajos todavía no están instalados en Hyprland."))
        self.setup_bar.append(warn)
        setup_btn = Gtk.Button(label="Instalar")
        setup_btn.add_css_class("suggested-action")
        setup_btn.connect("clicked", lambda *_: self.run_setup())
        self.setup_bar.append(setup_btn)
        outer.append(self.setup_bar)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(self.list)
        outer.append(scroll)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class("dim-label")
        outer.append(self.status)

        bottom = Gtk.Box(spacing=6)
        reset = Gtk.Button(label="Restaurar predeterminados")
        reset.connect("clicked", lambda *_: self.apply({a: list(v) for a, v in DEFAULT_BINDS.items()},
                                                        "Atajos predeterminados restaurados."))
        bottom.append(reset)
        close = Gtk.Button(label="Cerrar", hexpand=True, halign=Gtk.Align.END)
        close.connect("clicked", lambda *_: self.close())
        bottom.append(close)
        outer.append(bottom)
        self.set_child(outer)
        self.refresh()

    def run_setup(self):
        ok, msg = hyprsetup.setup()
        self.status.set_text(msg)
        self.refresh()
        self.on_changed()

    def refresh(self):
        self.setup_bar.set_visible(not hyprsetup.is_installed())
        self.binds = current_binds()
        while (row := self.list.get_first_child()) is not None:
            self.list.remove(row)
        for action, name, desc in ACTIONS:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            for side in ("top", "bottom", "start", "end"):
                getattr(row, f"set_margin_{side}")(8)
            title = Gtk.Label(xalign=0)
            title.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>")
            row.append(title)
            if desc:
                d = Gtk.Label(xalign=0, label=desc, wrap=True)
                d.add_css_class("dim-label")
                row.append(d)
            chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                                column_spacing=6, row_spacing=6)
            for combo in self.binds.get(action, []):
                chip = Gtk.Box(spacing=2)
                chip.append(Gtk.Label(label=label(combo), margin_start=6))
                rm = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Quitar")
                rm.add_css_class("flat")
                rm.connect("clicked", lambda *_a, a=action, c=combo: self.remove(a, c))
                chip.append(rm)
                frame = Gtk.Frame(child=chip)
                chips.append(frame)
            add = Gtk.Button(label="+ Agregar")
            add.connect("clicked", lambda *_a, a=action, n=name: self.start_capture(a, n))
            chips.append(add)
            row.append(chips)
            self.list.append(row)

    def apply(self, binds, ok_msg):
        err = save(binds)
        self.refresh()
        self.status.set_text(f"Hyprland reportó un error: {err}" if err else ok_msg)
        self.on_changed()

    def remove(self, action, combo):
        binds = {a: [c for c in v if not (a == action and c == combo)] for a, v in self.binds.items()}
        self.apply(binds, f"Quitado {label(combo)}.")

    def start_capture(self, action, name):
        def done(combo):
            self.capture = None
            if combo is None:
                return
            want = _parse(combo)
            moved = [n for a, n, _ in ACTIONS
                     if a != action and any(_parse(c) == want for c in self.binds.get(a, []))]
            binds = {a: [c for c in v if _parse(c) != want] for a, v in self.binds.items()}
            binds.setdefault(action, []).append(combo)
            msg = f"{label(combo)} → {name}."
            if moved:
                msg += f" (Se lo quité a «{moved[0]}».)"
            self.apply(binds, msg)

        self.capture = CaptureDialog(self, name, done)
        self.capture.present()

    def triggered(self, action):
        """study-lens recibió --acción mientras se escucha un atajo: no ejecutarla."""
        if self.capture is None:
            return False
        name = next((n for a, n, _ in ACTIONS if a == action), action)
        self.capture.taken_by_study_lens(name)
        return True
