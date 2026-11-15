"""Fórmulas LaTeX -> imágenes nítidas para el panel, con ziamath (Python puro, sin TeX).

Si ziamath no está instalado o una fórmula falla, devuelve None y el panel
muestra la versión Unicode de siempre.
"""

import re

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib  # noqa: E402

try:
    import ziamath
except Exception:  # sin .venv: se usa el respaldo Unicode
    ziamath = None

AVAILABLE = ziamath is not None
_cache = {}  # (latex, display, color, size, scale) -> (textura, ancho, alto) o None

# $$…$$ y \[…\] (pueden ocupar varias líneas)
DISPLAY_RE = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)
# $…$ (sin espacio pegado a los $, para no confundir precios) y \(…\)
INLINE_RE = re.compile(r"(?<![\\$])\$(?=\S)([^$\n]+?)(?<=\S)\$(?!\$)|\\\((.+?)\\\)")


def render(latex, display, color, size, scale):
    """Devuelve (Gdk.Texture, ancho, alto, descenso) en píxeles lógicos, o None si falló.

    descenso = cuánto baja la fórmula bajo la línea base del texto (para alinearla)."""
    key = (latex, display, color, size, scale)
    if key in _cache:
        return _cache[key]
    result = None
    if AVAILABLE:
        try:
            ziamath.config.svg2 = False  # SVG 1.1: lo entiende el lector de gdk-pixbuf
            src = latex if not display else r"\displaystyle " + latex
            m = ziamath.Latex(src, size=size * scale, color=color, inline=not display)
            descent = max(0.0, -m.getyofst()) / scale
            loader = GdkPixbuf.PixbufLoader()
            loader.write(m.svg().encode())
            loader.close()
            pb = loader.get_pixbuf()
            tex = Gdk.Texture.new_for_pixbuf(pb)
            result = (tex, max(1, round(pb.get_width() / scale)),
                      max(1, round(pb.get_height() / scale)), descent)
        except Exception:
            result = None
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = result
    return result


def color_hex(rgba):
    return "#%02x%02x%02x" % (round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255))


__all__ = ["AVAILABLE", "DISPLAY_RE", "INLINE_RE", "render", "color_hex", "GLib"]
