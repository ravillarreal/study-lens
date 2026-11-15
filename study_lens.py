#!/usr/bin/env python3
"""Study Lens: captura una ventana o región, se la manda a un modelo vía
opencode (cualquier proveedor que tengas conectado ahí) y muestra la
explicación en un panel con scroll. Pensado para estudiar y practicar.

Uso (una sola instancia; las llamadas siguientes se mandan a la que ya corre):
  study-lens              abre o enfoca el panel
  study-lens --window     analiza la ventana activa (empieza un análisis nuevo)
  study-lens --region     selecciona una región con el mouse y la analiza
  study-lens --more       vuelve a capturar el mismo objetivo (p. ej. después de
                          hacer scroll) y lo agrega a la conversación actual
  study-lens --new        vacía el ejercicio actual (capturas, sesión y respuesta)
  study-lens --toggle     muestra u oculta el panel
  study-lens --shortcuts  abre la ventana para cambiar los atajos (teclado o mouse)
"""

import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import mathrender  # noqa: E402
import shortcuts  # noqa: E402

APP_ID = "dev.zavu.StudyLens"
APP_DIR = Path(__file__).resolve().parent      # contiene .opencode/agent/tutor.md
CONFIG_FILE = Path.home() / ".config" / "study-lens" / "config.json"
CACHE_DIR = Path.home() / ".cache" / "study-lens"
DEFAULT_MODEL = "opencode-go/glm-5.3-flash"
REQUEST_TIMEOUT = 240  # segundos
LOG_FILE = CACHE_DIR / "study-lens.log"
GO_API = "https://opencode.ai/inference/go/openai/v1/chat/completions"
GO_KEY_FILE = Path.home() / ".config" / "study-lens" / "opencode_key"


OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def go_api_key():
    """Key de OpenCode Go: variable de entorno, archivo propio, o el login de opencode."""
    key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if not key and GO_KEY_FILE.exists():
        key = GO_KEY_FILE.read_text().strip()
    if not key:
        key = opencode_login_token()
    return key or None


def opencode_login_token():
    """Token del login de opencode (`opencode auth login`). Se lee en cada pedido
    porque es OAuth y opencode lo renueva solo."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute("select value from credential where integration_id='opencode' "
                              "and active=1 order by time_updated desc limit 1").fetchone()
        finally:
            con.close()
        if not row:
            return None
        cred = json.loads(row[0])
        if cred.get("expires") and cred["expires"] / 1000 < time.time():
            log("el token de opencode venció: abre opencode una vez para renovarlo")
            return None
        return cred.get("access")
    except Exception as e:  # noqa: BLE001
        log(f"no pude leer el login de opencode: {e}")
        return None


def tutor_prompt():
    """Las instrucciones del tutor (mismo archivo que usa el agente de opencode)."""
    t = (APP_DIR / ".opencode" / "agent" / "tutor.md").read_text()
    return t.split("---", 2)[2].strip() if t.startswith("---") else t


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def list_models():
    try:
        out = subprocess.run(["opencode", "models"], capture_output=True, text=True, timeout=60)
        return [m.strip() for m in out.stdout.splitlines() if "/" in m]
    except Exception:
        return []


# ---------------------------------------------------------------- capture ---

def hypr_json(*args):
    out = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def active_window():
    try:
        w = hypr_json("activewindow")
        return w if w and w.get("address") else None
    except Exception:
        return None


def window_by_address(address):
    for c in hypr_json("clients"):
        if c.get("address") == address:
            return c
    return None


def geometry_of(win):
    (x, y), (w, h) = win["at"], win["size"]
    return f"{x},{y} {w}x{h}"


def grim(geometry):
    out = subprocess.run(["grim", "-t", "png", "-g", geometry, "-"], capture_output=True, check=True)
    return out.stdout


def select_region():
    out = subprocess.run(["slurp"], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return out.stdout.strip()


# --------------------------------------------------------------- markdown ---

INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")

SUP = str.maketrans("0123456789+-=()nixabk", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣᵃᵇᵏ")
SUB = str.maketrans("0123456789+-=()aeioxnk", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒₓₙₖ")
LATEX_SYMBOLS = {
    r"\cdot": "·", r"\times": "×", r"\div": "÷", r"\le": "≤", r"\leq": "≤", r"\ge": "≥",
    r"\geq": "≥", r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\pm": "±", r"\infty": "∞",
    r"\to": "→", r"\rightarrow": "→", r"\Rightarrow": "⇒", r"\Leftrightarrow": "⇔",
    r"\implies": "⇒", r"\int": "∫", r"\sum": "∑", r"\prod": "∏", r"\pi": "π",
    r"\alpha": "α", r"\beta": "β", r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ",
    r"\sigma": "σ", r"\Delta": "Δ", r"\delta": "δ", r"\in": "∈", r"\subset": "⊂",
    r"\cup": "∪", r"\cap": "∩", r"\forall": "∀", r"\exists": "∃", r"\checkmark": "✓",
    r"\quad": "  ", r"\qquad": "    ", r"\,": " ", r"\;": " ", r"\!": "", r"\ ": " ",
    r"\%": "%", r"\{": "{", r"\}": "}", r"\ldots": "…", r"\dots": "…", r"\circ": "°",
}


SUP_KEYS, SUB_KEYS = "0123456789+-=()nixabk", "0123456789+-=()aeioxnk"


def _script(m, table):
    body = m.group(1) if m.group(1) is not None else m.group(2)
    keys = SUP_KEYS if table is SUP else SUB_KEYS
    if all(c in keys for c in body.replace(" ", "")):
        return body.replace(" ", "").translate(table)
    return ("^" if table is SUP else "_") + "(" + body + ")"


def latex_to_unicode(text, keep_dollars=False):
    if "\\" not in text and "$" not in text and "^" not in text:
        return text
    t = text if keep_dollars else text.replace("$$", "").replace("$", "")
    t = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)\s*([()\[\]|.])", lambda m: "" if m.group(1) == "." else m.group(1), t)
    for _ in range(3):  # anidados
        t = re.sub(r"\\(?:d|t)?frac\{([^{}]*)\}\{([^{}]*)\}", lambda m: (m.group(1) if re.fullmatch(r"[\w.]+", m.group(1)) else f"({m.group(1)})") + "/" + (m.group(2) if re.fullmatch(r"[\w.]+", m.group(2)) else f"({m.group(2)})"), t)
        t = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", t)
        t = re.sub(r"\\(?:text|textbf|mathbf|mathrm|operatorname|boxed|underbrace|overline)\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\displaystyle\s*", "", t)
    for k in sorted(LATEX_SYMBOLS, key=len, reverse=True):
        t = re.sub(re.escape(k) + r"(?![A-Za-z])", lambda _m, v=LATEX_SYMBOLS[k]: v, t)
    t = re.sub(r"\^\{([^{}]*)\}|\^(\w)", lambda m: _script(m, SUP), t)
    t = re.sub(r"_\{([^{}]*)\}|_(\d)", lambda m: _script(m, SUB), t)
    return t


MATH_BLOCK = "\x00M{}\x00"
MATH_BLOCK_RE = re.compile(r"^\s*\x00M(\d+)\x00\s*$")


def _split_display_math(text):
    """Saca $$…$$ / \\[…\\] (fuera de bloques de código) a líneas propias con un marcador."""
    blocks, out = [], []
    for k, chunk in enumerate(re.split(r"(```.*?(?:```|$))", text, flags=re.S)):
        if k % 2:  # bloque de código: intacto
            out.append(chunk)
            continue

        def repl(m):
            blocks.append((m.group(1) or m.group(2)).strip())
            return "\n" + MATH_BLOCK.format(len(blocks) - 1) + "\n"
        out.append(mathrender.DISPLAY_RE.sub(repl, chunk))
    return "".join(out), blocks


class _MathCtx:
    def __init__(self, view):
        self.view, self.buf = view, view.get_buffer()
        self.color = mathrender.color_hex(view.get_color())
        self.scale = view.get_scale_factor()
        fd = view.get_pango_context().get_font_description()
        pts = fd.get_size() / Pango.SCALE if fd and fd.get_size() else 11
        self.px = pts * 96 / 72
        self.max_w = max(200, view.get_width() - 40)

    def insert(self, it, latex, display, tags=()):
        r = mathrender.render(latex, display, self.color, self.px * (1.15 if display else 1.0), self.scale)
        if r is None:  # no se pudo dibujar: versión Unicode
            text = latex_to_unicode("$" + latex + "$")
            self.buf.insert_with_tags_by_name(it, text, *tags) if tags else self.buf.insert(it, text)
            return
        tex, w, h, descent = r
        if w > self.max_w:  # no desbordar el panel
            h, descent, w = round(h * self.max_w / w), descent * self.max_w / w, self.max_w
        pic = Gtk.Picture.new_for_paintable(tex)
        pic.set_can_shrink(True)
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        pic.set_size_request(w, h)
        pic.set_tooltip_text(latex)
        start = it.get_offset()
        anchor = self.buf.create_child_anchor(it)
        # Baja la imagen para que su línea base coincida con la del texto.
        name = f"rise{round(descent)}"
        if self.buf.get_tag_table().lookup(name) is None:
            self.buf.create_tag(name, rise=-round(descent) * Pango.SCALE)
        self.buf.apply_tag_by_name(name, self.buf.get_iter_at_offset(start), it)
        self.view.add_child_at_anchor(pic, anchor)


def _insert_inline(buf, it, line, math, base_tags=()):
    """Inserta una línea con **negritas**, `código` y $fórmulas$."""
    pos = 0
    for m in mathrender.INLINE_RE.finditer(line) if math else ():
        _insert_text(buf, it, line[pos:m.start()], base_tags, True)
        math.insert(it, (m.group(1) or m.group(2)).strip(), False, base_tags)
        pos = m.end()
    _insert_text(buf, it, line[pos:], base_tags, bool(math))


def _insert_text(buf, it, text, base_tags=(), keep_dollars=False):
    # Con fórmulas activas, un $ suelto que quedó aquí es texto (p. ej. un precio).
    text = latex_to_unicode(text, keep_dollars)
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            buf.insert_with_tags_by_name(it, part[2:-2], "bold", *base_tags)
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            buf.insert_with_tags_by_name(it, part[1:-1], "icode", *base_tags)
        elif base_tags:
            buf.insert_with_tags_by_name(it, part, *base_tags)
        else:
            buf.insert(it, part)


def render_markdown(view, text, reasoning=""):
    buf = view.get_buffer()
    buf.set_text("")
    it = buf.get_end_iter()
    if reasoning:
        tail = reasoning if len(reasoning) < 2500 else "…" + reasoning[-2500:]
        buf.insert_with_tags_by_name(it, "💭 Razonamiento\n", "think_h")
        buf.insert_with_tags_by_name(it, latex_to_unicode(tail.strip()) + "\n\n", "think")
    math = _MathCtx(view) if mathrender.AVAILABLE else None
    blocks = []
    if math:
        text, blocks = _split_display_math(text)
    in_code = after_block = False
    for line in text.split("\n"):
        if after_block and not line.strip():
            continue  # la fórmula de bloque ya deja su propio espacio
        after_block = False
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            buf.insert_with_tags_by_name(it, line + "\n", "code")
            continue
        mb = MATH_BLOCK_RE.match(line)
        if mb:
            start = it.get_offset()
            math.insert(it, blocks[int(mb.group(1))], True)
            buf.insert(it, "\n")
            buf.apply_tag_by_name("mathblock", buf.get_iter_at_offset(start), it)
            after_block = True
            continue
        if re.fullmatch(r"\s*(-{3,}|\*{3,}|_{3,})\s*", line):
            buf.insert_with_tags_by_name(it, "─" * 40 + "\n", "rule")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            _insert_inline(buf, it, m.group(2), math, ("h" if len(m.group(1)) <= 2 else "h3",))
            buf.insert(it, "\n")
            continue
        if re.match(r"^\s*[-*]\s+", line):
            line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)
        _insert_inline(buf, it, line, math)
        buf.insert(it, "\n")


# -------------------------------------------------------------------- app ---

class StudyLens(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None
        self.cfg = load_config()
        self.model = self.cfg.get("model", DEFAULT_MODEL)
        self.session = None         # sesión de opencode de la conversación actual
        self.proc = None
        self.shot_n = 0
        self.shots = []             # capturas del ejercicio actual
        self.sent = 0               # cuántas de ellas ya vio el modelo
        self.history = []           # conversación (modo API directa)
        self.reasoning = ""
        self.target = None          # ("window", address) o ("region", geometry)
        self.busy = False
        self.req_id = 0             # cambia al cancelar; descarta respuestas viejas
        self.answer = ""
        self.render_pending = False
        self.keys = {a: shortcuts.label(v[0]) for a, v in shortcuts.DEFAULT_BINDS.items()}
        self.shortcuts_win = None

    # ---- arranque / línea de comandos

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        # La ventana activa se lee AHORA, antes de que el panel tome el foco.
        active = active_window()
        self.keys = shortcuts.labels()
        if self.win is None:
            self.build_ui()
        # Mientras la ventana de Atajos escucha una combinación, no ejecutar acciones.
        flag = next((a[2:] for a in args if a.startswith("--")), None)
        if flag and self.shortcuts_win is not None and self.shortcuts_win.triggered(flag):
            return 0
        if "--shortcuts" in args:
            self.open_shortcuts()
        elif "--toggle" in args:
            self.win.set_visible(not self.win.get_visible())
        elif "--region" in args:
            GLib.idle_add(self.capture_region)
        elif "--new" in args:
            # Ejercicio nuevo con la MISMA región/ventana: vacía y captura de una vez.
            self.reset_exercise()
            if self.target is not None:
                self.capture(new=False, active=None)
            else:
                self.show_panel()
        elif "--analyze" in args:
            self.analyze()
            self.show_panel()
        elif "--more" in args:
            self.capture(new=False, active=active)
        elif "--window" in args:
            self.capture(new=True, active=active)
        else:
            self.win.present()
        return 0

    def build_ui(self):
        self.win = Gtk.ApplicationWindow(application=self, title="Study Lens")
        self.win.set_default_size(560, 820)
        self.win.set_hide_on_close(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(10)

        bar = Gtk.Box(spacing=6)
        for label, cb in (("Ventana", lambda *_: self.capture(True, self.last_non_self())),
                          ("Región", lambda *_: self.capture_region()),
                          ("+ Captura", lambda *_: self.capture(False, None)),
                          ("Re-analizar", lambda *_: self.reanalyze()),
                          ("Logs", lambda *_: self.open_logs())):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            bar.append(b)
        self.analyze_btn = Gtk.Button(label="Analizar")
        self.analyze_btn.add_css_class("suggested-action")
        self.analyze_btn.set_hexpand(True)
        self.analyze_btn.set_halign(Gtk.Align.END)
        self.analyze_btn.connect("clicked", lambda *_: self.analyze())
        bar.append(self.analyze_btn)
        box.append(bar)

        # Selector de modelo (lista de `opencode models`, se carga en segundo plano).
        self.models = Gtk.StringList.new([self.model])
        self.model_dd = Gtk.DropDown(model=self.models, enable_search=True)
        self.model_dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        # Buscar en cualquier parte del nombre ("dee" encuentra "opencode-go/deepseek…").
        if hasattr(Gtk, "StringFilterMatchMode") and hasattr(self.model_dd, "set_search_match_mode"):
            self.model_dd.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
        self.model_dd.connect("notify::selected", self.on_model_changed)
        self.model_dd.set_hexpand(True)
        model_row = Gtk.Box(spacing=6)
        model_row.append(self.model_dd)
        keys_btn = Gtk.Button(label="⌨ Atajos", tooltip_text="Cambiar atajos de teclado y mouse")
        keys_btn.connect("clicked", lambda *_: self.open_shortcuts())
        model_row.append(keys_btn)
        box.append(model_row)
        threading.Thread(target=lambda: GLib.idle_add(self._fill_models, list_models()),
                         daemon=True).start()

        self.status = Gtk.Label(xalign=0)
        self.status.add_css_class("dim-label")
        self.set_status(f"Listo. {self.keys['region']}: región · {self.keys['window']}: ventana activa.")
        box.append(self.status)

        head = Gtk.Box(spacing=6)
        self.shots_label = Gtk.Label(xalign=0, hexpand=True)
        head.append(self.shots_label)
        reset_btn = Gtk.Button(label="Nuevo ejercicio")
        reset_btn.connect("clicked", lambda *_: self.reset_exercise())
        head.append(reset_btn)
        box.append(head)

        self.thumbs = Gtk.Box(spacing=6)
        thumbs_scroll = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER)
        thumbs_scroll.set_min_content_height(100)
        thumbs_scroll.set_child(self.thumbs)
        box.append(thumbs_scroll)
        self.refresh_thumbs()

        self.view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for side in ("top", "bottom", "left", "right"):
            getattr(self.view, f"set_{side}_margin")(8)
        buf = self.view.get_buffer()
        buf.create_tag("h", weight=Pango.Weight.BOLD, scale=1.3, pixels_above_lines=8)
        buf.create_tag("h3", weight=Pango.Weight.BOLD, scale=1.1, pixels_above_lines=6)
        buf.create_tag("bold", weight=Pango.Weight.BOLD)
        buf.create_tag("rule", foreground="#585b70")
        buf.create_tag("think_h", foreground="#7f849c", weight=Pango.Weight.BOLD, scale=0.9)
        buf.create_tag("think", foreground="#7f849c", style=Pango.Style.ITALIC, scale=0.9)
        buf.create_tag("code", family="monospace", paragraph_background="#1e1e2e", foreground="#cdd6f4")
        buf.create_tag("mathblock", justification=Gtk.Justification.CENTER,
                       pixels_above_lines=6, pixels_below_lines=6)
        buf.create_tag("icode", family="monospace", background="#313244", foreground="#f5c2e7")

        self.scroller = Gtk.ScrolledWindow(vexpand=True)
        self.scroller.set_child(self.view)
        box.append(self.scroller)

        self.entry = Gtk.Entry(placeholder_text="Pregunta de seguimiento (Enter)…")
        self.entry.connect("activate", self.on_followup)
        box.append(self.entry)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.win.add_controller(keys)

        self.win.set_child(box)

    def on_key(self, _ctrl, keyval, _code, _state):
        if self.entry.has_focus():
            if keyval == Gdk.KEY_Escape:
                self.view.grab_focus()
                return True
            return False
        adj = self.scroller.get_vadjustment()
        step, page = 60, adj.get_page_size() * 0.9
        moves = {Gdk.KEY_j: step, Gdk.KEY_Down: step, Gdk.KEY_k: -step, Gdk.KEY_Up: -step,
                 Gdk.KEY_space: page, Gdk.KEY_Page_Down: page, Gdk.KEY_Page_Up: -page,
                 Gdk.KEY_d: page / 2, Gdk.KEY_u: -page / 2}
        if keyval in moves:
            adj.set_value(adj.get_value() + moves[keyval])
        elif keyval == Gdk.KEY_g:
            adj.set_value(0)
        elif keyval == Gdk.KEY_G:
            adj.set_value(adj.get_upper())
        elif keyval == Gdk.KEY_r:
            self.reanalyze()
        elif keyval in (Gdk.KEY_e, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.analyze()
        elif keyval == Gdk.KEY_n:
            self.reset_exercise()
        elif keyval == Gdk.KEY_c:
            self.capture(False, None)
        elif keyval == Gdk.KEY_slash:
            self.entry.grab_focus()
        elif keyval == Gdk.KEY_Escape:
            self.win.set_visible(False)
        else:
            return False
        return True

    def _fill_models(self, models):
        if not models:
            return False
        if self.model not in models:
            models.insert(0, self.model)
        self._filling = True
        self.models.splice(0, self.models.get_n_items(), models)
        self.model_dd.set_selected(models.index(self.model))
        self._filling = False
        return False

    def on_model_changed(self, dd, _pspec):
        item = dd.get_selected_item()
        if getattr(self, "_filling", False) or item is None:
            return
        if item.get_string() != self.model:
            self.model = item.get_string()
            self.cfg["model"] = self.model
            save_config(self.cfg)
            self.set_status(f"Modelo: {self.model}")

    def open_shortcuts(self):
        if self.shortcuts_win is None:
            def changed():
                self.keys = shortcuts.labels()
                self.refresh_thumbs()
            self.shortcuts_win = shortcuts.ShortcutsWindow(self.win, changed)
        self.shortcuts_win.refresh()
        self.shortcuts_win.present()

    def open_logs(self):
        LOG_FILE.touch()
        subprocess.Popen(["xdg-terminal-exec", "tail", "-n", "200", "-f", str(LOG_FILE)])

    def set_status(self, text):
        self.status.set_text(text)

    def is_self(self, win):
        return bool(win) and win.get("pid") == os.getpid()

    def last_non_self(self):
        # Botón "Ventana" desde el panel: usa la ventana enfocada antes del panel.
        try:
            clients = sorted(hypr_json("clients"), key=lambda c: c.get("focusHistoryID", 99))
        except Exception:
            return None
        return next((c for c in clients if c.get("pid") != os.getpid() and c.get("mapped")), None)

    # ---- captura

    def cancel(self):
        """Corta la respuesta en curso (si la hay)."""
        if not self.busy:
            return
        self.req_id += 1
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        self.busy = False
        log("respuesta en curso cancelada por el usuario")

    def capture(self, new, active):
        """Captura y la agrega a la lista. No manda nada al modelo.
        new=True  -> captura la ventana activa (y la fija como objetivo)
        new=False -> vuelve a capturar el último objetivo (tras hacer scroll)"""
        if new:
            if not active or self.is_self(active):
                active = self.last_non_self()
            if not active:
                self.set_status("No encontré una ventana para capturar.")
                return
            self.target = ("window", active["address"])
        elif self.target is None:
            self.set_status(f"Primero elige qué capturar: Región ({self.keys['region']}) o Ventana ({self.keys['window']}).")
            return

        def do_grab():
            try:
                if self.target[0] == "window":
                    win = window_by_address(self.target[1])
                    if not win:
                        raise RuntimeError("La ventana objetivo ya no existe.")
                    log(f"capturando VENTANA '{win.get('class')}' — {win.get('title', '')[:60]} @ {geometry_of(win)}")
                    png = grim(geometry_of(win))
                else:
                    log(f"capturando REGIÓN (misma de antes) @ {self.target[1]}")
                    png = grim(self.target[1])
            except Exception as e:  # noqa: BLE001
                self.restore_panel()
                self.set_status(f"Error al capturar: {e}")
                return False
            self.restore_panel()
            self.add_shot(png, new_target=new)
            return False

        self.hide_panel_then(do_grab)

    def capture_region(self):
        def pick():
            geom = select_region()
            GLib.idle_add(self._region_done, geom)

        self.hide_panel_then(lambda: threading.Thread(target=pick, daemon=True).start() and False)
        return False

    def _region_done(self, geom):
        if not geom:
            self.restore_panel()
            self.set_status("Selección cancelada.")
            return False
        self.target = ("region", geom)
        try:
            log(f"capturando REGIÓN seleccionada @ {geom}")
            png = grim(geom)
        except Exception as e:  # noqa: BLE001
            self.restore_panel()
            self.set_status(f"Error al capturar: {e}")
            return False
        self.restore_panel()
        self.add_shot(png, new_target=True)
        return False

    def hide_panel_then(self, fn):
        """Oculta el panel un instante para que no salga en la captura."""
        self._was_visible = self.win.get_visible()
        if self._was_visible:
            self.win.set_visible(False)
            GLib.timeout_add(250, fn)
        else:
            GLib.idle_add(fn)

    def restore_panel(self):
        if getattr(self, "_was_visible", True):
            self.show_panel()

    def show_panel(self):
        """Muestra el panel SIN quitarle el foco (ni el mouse) a tu ventana."""
        if not self.win.get_visible():
            self.win.set_visible(True)

    # ---- lista de capturas

    def reset_exercise(self, quiet=False):
        """Empieza un ejercicio nuevo: borra capturas, sesión y respuesta."""
        self.cancel()
        for f in self.shots:
            f.unlink(missing_ok=True)
        self.shots = []
        self.sent = 0
        self.session = None
        self.history = []
        self.answer = ""
        self.schedule_render()
        if not quiet:
            self.set_status(f"Ejercicio nuevo. Toma las capturas y luego presiona Analizar ({self.keys['analyze']}).")
            log("ejercicio reiniciado")
        self.refresh_thumbs()

    def remove_shot(self, path):
        idx = self.shots.index(path)
        if idx < self.sent:
            self.set_status("Esa captura ya se envió al modelo; usa Nuevo ejercicio para empezar de cero.")
            return
        self.shots.remove(path)
        path.unlink(missing_ok=True)
        log(f"captura quitada: {path.name}")
        self.refresh_thumbs()

    def refresh_thumbs(self):
        while (child := self.thumbs.get_first_child()) is not None:
            self.thumbs.remove(child)
        n, pending = len(self.shots), len(self.shots) - self.sent
        if not n:
            self.shots_label.set_text("Sin capturas todavía")
        else:
            self.shots_label.set_text(f"Capturas: {n}" + (f" · presiona {self.keys['analyze']} para analizarlas" if pending == n
                                      else f" · {pending} nueva(s) sin analizar" if pending else " · analizadas ✓"))
        self.analyze_btn.set_label(f"Analizar ({pending})" if pending else "Analizar")
        self.analyze_btn.set_sensitive(pending > 0)
        for i, path in enumerate(self.shots, 1):
            sent = i <= self.sent
            pic = Gtk.Picture.new_for_filename(str(path))
            pic.set_can_shrink(True)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(150, 95)
            pic.set_tooltip_text(f"Captura {i} · clic: ver en grande"
                                 + ("" if sent else " · clic derecho: quitar"))
            click = Gtk.GestureClick()
            click.connect("released", lambda *_a, p=path: subprocess.Popen(["xdg-open", str(p)]))
            pic.add_controller(click)
            rclick = Gtk.GestureClick(button=3)
            rclick.connect("released", lambda *_a, p=path: self.remove_shot(p))
            pic.add_controller(rclick)
            frame = Gtk.Frame(child=pic, label=f"{i} ✓" if sent else f"{i}")
            self.thumbs.append(frame)

    def add_shot(self, png, new_target):
        # Si el ejercicio anterior ya se analizó y eliges una región/ventana nueva,
        # empieza un ejercicio nuevo. "+ Captura" (study-lens --more) siempre suma al actual.
        if new_target and self.sent > 0:
            self.reset_exercise(quiet=True)
            log("ejercicio nuevo (región/ventana nueva tras un análisis)")
        shots_dir = CACHE_DIR / "capturas"
        shots_dir.mkdir(parents=True, exist_ok=True)
        self.shot_n += 1
        path = shots_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{self.shot_n}.png"
        path.write_bytes(png)
        self.shots.append(path)
        log(f"captura {len(self.shots)} agregada ({len(png) // 1024} KB) — pendiente")
        self.refresh_thumbs()
        pending = len(self.shots) - self.sent
        self.set_status(f"{len(self.shots)} captura(s). {self.keys['more']}: otra (tras scroll) · "
                        f"{self.keys['analyze']}: analizar todas")

    # ---- modelo (vía opencode)

    def analyze(self):
        pending = self.shots[self.sent:]
        if self.busy:
            self.set_status("Ya está analizando…")
            return
        if not pending:
            self.set_status(f"No hay capturas pendientes. Toma una con {self.keys['region']} o {self.keys['window']}.")
            return
        n = len(pending)
        if self.session is None:
            text = ("Analiza el ejercicio de estas capturas." if n == 1 else
                    f"Te mando {n} capturas en orden: son partes del mismo ejercicio "
                    "(hice scroll entre una y otra). Únelas y analiza el ejercicio completo.")
        else:
            text = (f"Te mando {n} captura(s) más del mismo ejercicio (continuación, hice scroll). "
                    "Intégralas con lo anterior y actualiza el análisis.")
        self.run_request(text, images=list(pending), reset_view=self.session is None)

    def reanalyze(self):
        """Vuelve a mandar TODAS las capturas en una conversación nueva."""
        if not self.shots:
            return
        self.cancel()
        self.session = None
        self.history = []
        self.sent = 0
        self.refresh_thumbs()
        self.analyze()

    def on_followup(self, entry):
        q = entry.get_text().strip()
        if not q or self.busy:
            return
        if self.session is None:
            self.set_status("Primero analiza las capturas.")
            return
        entry.set_text("")
        self.answer += f"\n\n---\n\n## Tú: {q}\n\n"
        self.run_request(q, images=[], reset_view=False)

    def run_request(self, text, images, reset_view):
        self.busy = True
        if reset_view:
            self.answer = ""
        self.reasoning = ""
        self.t_start = time.time()
        self.phase = "esperando al modelo"
        self.set_status(f"Analizando con {self.model}…")
        GLib.timeout_add(1000, self._tick)
        self.schedule_render()
        self.req_id += 1
        key = go_api_key()
        if self.model.startswith("opencode-go/") and key:
            target = self._worker_api
            log("modo: API directa (streaming)")
        else:
            target = self._worker
            if self.model.startswith("opencode-go/"):
                log(f"modo: opencode CLI (lento) — falta la key en {GO_KEY_FILE}")
        threading.Thread(target=target, args=(text, images, self.req_id), daemon=True).start()

    def _worker(self, text, images, my_id):
        t0 = time.time()
        current = lambda: my_id == self.req_id  # noqa: E731
        cmd = ["opencode", "run", "--standalone", "--agent", "tutor", "--format", "json", "-m", self.model]
        if self.session and self.session.startswith("ses"):
            cmd += ["-s", self.session]
        for img in images:
            cmd += ["-f", str(img)]
        cmd += ["--", text]
        error = None
        got_text = False
        el = lambda: f"+{time.time() - t0:5.1f}s"  # noqa: E731
        log("=" * 60)
        log(f"modelo={self.model} sesión={self.session or '(nueva)'}")
        for img in images:
            log(f"imagen={img.name} ({img.stat().st_size // 1024} KB)")
        log(f"cmd: {' '.join(cmd[:-1])} '{text[:60]}'")
        try:
            proc = self.proc = subprocess.Popen(cmd, cwd=APP_DIR, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True)
            log(f"{el()} opencode iniciado (pid {proc.pid})")

            def pump_stderr(stream):
                for ln in stream:
                    if ln.strip():
                        log(f"{el()} [stderr] {ln.rstrip()[:300]}")
            threading.Thread(target=pump_stderr, args=(proc.stderr,), daemon=True).start()
            # Si el modelo se cuelga (p. ej. opencode esperando para reintentar),
            # se corta a los REQUEST_TIMEOUT segundos.
            timer = threading.Timer(REQUEST_TIMEOUT, proc.kill)
            timer.start()
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if not current():
                    break  # cancelada: ignorar el resto
                if ev.get("sessionID") and not self.session:
                    self.session = ev["sessionID"]
                    log(f"{el()} sesión {self.session}")
                etype = ev.get("type")
                part = ev.get("part") or {}
                if etype == "step_start":
                    self.phase = "modelo pensando"
                    log(f"{el()} paso iniciado (el modelo está procesando)")
                elif etype == "step_finish":
                    log(f"{el()} paso terminado: motivo={part.get('reason')} "
                        f"tokens={json.dumps(part.get('tokens'))} costo={part.get('cost')}")
                elif etype == "text":
                    log(f"{el()} texto recibido ({len(part.get('text', ''))} caracteres)")
                elif etype == "error":
                    log(f"{el()} ERROR: {json.dumps(ev.get('error'), ensure_ascii=False)[:500]}")
                else:
                    log(f"{el()} evento {etype} {part.get('tool', '')}")
                if etype == "text" and part.get("text"):
                    self.phase = "recibiendo respuesta"
                    sep = "\n\n" if got_text else ""
                    self.answer += sep + ev["part"]["text"]
                    got_text = True
                    self.schedule_render()
                elif ev.get("type") == "error":
                    error = ev.get("error", {}).get("message") or "error desconocido"
                    proc.kill()  # no esperar reintentos
                    break
            proc.wait()
            timer.cancel()
            log(f"{el()} opencode terminó (código {proc.returncode})")
            if error is None and not got_text:
                error = ("sin respuesta (tiempo agotado)" if time.time() - t0 >= REQUEST_TIMEOUT
                         else "el modelo no devolvió texto")
        except FileNotFoundError:
            error = "no encontré el comando opencode"
        except Exception as e:  # noqa: BLE001 - nunca dejar la app en "Analizando…"
            error = str(e)
        log(f"{el()} resultado: {'ERROR ' + error if error else 'ok'}")
        if error:
            if "free" in error.lower() and "limit" in error.lower():
                error = "Se acabó la cuota gratis de opencode. Cambia de modelo o conecta un proveedor (opencode auth login)."
            status = f"Error: {error}"
        else:
            status = f"Listo en {time.time() - t0:.0f}s · j/k scroll · c continuar · r re-analizar · / preguntar"
        if current():
            GLib.idle_add(self._finish, status, None if error else len(images))

    def _worker_api(self, text, images, my_id):
        t0 = time.time()
        current = lambda: my_id == self.req_id  # noqa: E731
        el = lambda: f"+{time.time() - t0:5.1f}s"  # noqa: E731
        model = self.model.split("/", 1)[1]
        content = [{"type": "text", "text": text}]
        for img in images:
            b64 = base64.standard_b64encode(img.read_bytes()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        user_msg = {"role": "user", "content": content}
        if not self.history or not getattr(self, "go_session", None):
            self.go_session = f"study-lens-{uuid.uuid4().hex}"
        body = {"model": model, "stream": True,
                "messages": [{"role": "system", "content": tutor_prompt()}, *self.history, user_msg]}
        log("=" * 60)
        log(f"API directa · modelo={model} · imágenes={len(images)} · historial={len(self.history)}")
        error, answer, first = None, "", None
        try:
            req = urllib.request.Request(GO_API, data=json.dumps(body).encode(), headers={
                "Authorization": f"Bearer {go_api_key()}", "Content-Type": "application/json",
                "Accept": "text/event-stream", "User-Agent": "study-lens/1.0",
                # Go pide una sesión estable por conversación (routing y caché).
                "x-opencode-session": self.go_session})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                log(f"{el()} conectado (HTTP {resp.status})")
                for raw in resp:
                    if not current():
                        log(f"{el()} cancelada")
                        return
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        error = str(chunk["error"].get("message", chunk["error"]))
                        break
                    for ch in chunk.get("choices") or []:
                        d = ch.get("delta") or {}
                        r = d.get("reasoning_content") or d.get("reasoning") or ""
                        c = d.get("content") or ""
                        if r:
                            if first is None:
                                first = time.time() - t0
                                log(f"{el()} primer token (razonamiento)")
                            self.phase = "razonando"
                            self.reasoning += r
                        if c:
                            if not answer:
                                log(f"{el()} empieza la respuesta")
                            if first is None:
                                first = time.time() - t0
                            self.phase = "escribiendo respuesta"
                            answer += c
                            self.answer += c
                        if r or c:
                            self.schedule_render()
                    if chunk.get("usage"):
                        log(f"{el()} tokens={json.dumps(chunk['usage'])}")
            if not error and not answer:
                error = "el modelo no devolvió texto"
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            error = f"HTTP {e.code}: {detail}"
            if e.code in (401, 403):
                error = f"La API key no es válida (HTTP {e.code}). Revisa {GO_KEY_FILE}"
        except Exception as e:  # noqa: BLE001
            error = str(e)
        log(f"{el()} resultado: {'ERROR ' + error if error else 'ok'}")
        if not current():
            return
        if error:
            status = f"Error: {error}"
        else:
            self.history += [user_msg, {"role": "assistant", "content": answer}]
            self.session = "api"
            status = f"Listo en {time.time() - t0:.0f}s (primer token a los {first or 0:.1f}s)"
        GLib.idle_add(self._finish, status, None if error else len(images))

    def _tick(self):
        if not self.busy:
            return False
        secs = time.time() - self.t_start
        self.set_status(f"{self.model} · {self.phase} · {secs:.0f}s  (botón Logs para ver detalle)")
        return True

    def _finish(self, status, sent_now=None):
        self.busy = False
        self.scroll_to_final = sent_now is not None or "Listo" in status
        if sent_now:
            self.sent += sent_now   # solo se marcan enviadas si el modelo respondió
            self.refresh_thumbs()
        self.set_status(status)
        self.schedule_render()
        return False

    def schedule_render(self):
        if not self.render_pending:
            self.render_pending = True
            GLib.timeout_add(80, self._render)

    def _render(self):
        self.render_pending = False
        adj = self.scroller.get_vadjustment()
        pos = adj.get_value()
        buf = self.view.get_buffer()
        render_markdown(self.view, self.answer, self.reasoning)
        if getattr(self, "scroll_to_final", False):
            self.scroll_to_final = False
            GLib.timeout_add(120, self._jump_to_final)
        else:
            GLib.idle_add(lambda: adj.set_value(pos) or False)  # no saltar al inicio
        return False

    def _jump_to_final(self):
        """Lleva la vista a la sección 'Respuesta final' (o al final del texto)."""
        buf = self.view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        idx = max(text.lower().rfind(k) for k in ("respuesta final", "solución final", "resultado final"))
        if idx >= 0:
            it = buf.get_iter_at_offset(idx)
            self.view.scroll_to_iter(it, 0.0, True, 0.0, 0.0)
        else:
            adj = self.scroller.get_vadjustment()
            adj.set_value(adj.get_upper())
        return False


if __name__ == "__main__":
    sys.exit(StudyLens().run(sys.argv))
