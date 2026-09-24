"""Cairo drawing for the native components that GTK has no widget for."""

import math

import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk  # noqa: E402

WHITE = (1.0, 1.0, 1.0, 1.0)


def rgba(value, fallback=WHITE):
    """A CSS color string → (r, g, b, a). Gradients and bad values fall back."""
    if isinstance(value, str):
        color = Gdk.RGBA()
        if color.parse(value.strip()):
            return (color.red, color.green, color.blue, color.alpha)
    return fallback


def rounded_rect(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def fraction(value, maximum) -> float:
    if value is None or not maximum:
        return 0.0
    return max(0.0, min(1.0, value / maximum))


def ring(cr, w, h, frac, thickness, color, track, start_deg=-90.0):
    size = min(w, h)
    radius = (size - thickness) / 2
    cx, cy = w / 2, h / 2
    cr.set_line_width(thickness)
    cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND
    cr.set_source_rgba(*track)
    cr.arc(cx, cy, radius, 0, 2 * math.pi)
    cr.stroke()
    if frac > 0:
        start = math.radians(start_deg)
        cr.set_source_rgba(*color)
        cr.arc(cx, cy, radius, start, start + 2 * math.pi * frac)
        cr.stroke()


def bar(cr, w, h, frac, color, track, radius):
    cr.set_source_rgba(*track)
    rounded_rect(cr, 0, 0, w, h, radius)
    cr.fill()
    if frac > 0:
        cr.set_source_rgba(*color)
        rounded_rect(cr, 0, 0, max(w * frac, min(h, w)), h, radius)
        cr.fill()


def sparkline(cr, w, h, values, lo, hi, color, fill, line_width):
    pts = [v for v in values if v is not None]
    if len(pts) < 2:
        return
    lo = min(pts) if lo is None else lo
    hi = max(pts) if hi is None else hi
    span = (hi - lo) or 1.0
    step = w / (len(pts) - 1)
    pad = line_width / 2
    coords = [(i * step, pad + (h - 2 * pad) * (1 - (min(max(v, lo), hi) - lo) / span)) for i, v in enumerate(pts)]
    if fill:
        cr.move_to(coords[0][0], h)
        for x, y in coords:
            cr.line_to(x, y)
        cr.line_to(coords[-1][0], h)
        cr.close_path()
        cr.set_source_rgba(*fill)
        cr.fill()
    cr.set_line_width(line_width)
    cr.set_line_join(1)  # cairo.LINE_JOIN_ROUND
    cr.move_to(*coords[0])
    for x, y in coords[1:]:
        cr.line_to(x, y)
    cr.set_source_rgba(*color)
    cr.stroke()


def pixbuf(cr, w, h, pb, radius, fit):
    """Draw a pixbuf into w×h, cropped (cover) or letterboxed (contain), with rounded corners."""
    from gi.repository import Gdk as _Gdk  # local: keeps module import cheap
    pw, ph = pb.get_width(), pb.get_height()
    if not pw or not ph:
        return
    scale = (max if fit == "cover" else min)(w / pw, h / ph)
    dw, dh = pw * scale, ph * scale
    rounded_rect(cr, 0, 0, w, h, radius)
    cr.clip()
    cr.translate((w - dw) / 2, (h - dh) / 2)
    cr.scale(scale, scale)
    _Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    cr.paint()
