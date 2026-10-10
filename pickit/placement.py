"""Where a widget goes on screen. No GTK, so it's unit-testable.

X11 places windows at absolute coordinates. Wayland's layer-shell instead anchors a surface
to screen edges with margins: anchored to one edge it's centered along that edge, anchored
to none it's centered on the screen. Both are computed from the same `position` names.
"""

MARGIN = 24
EDGES = ("top", "bottom", "left", "right")


def split(position: str) -> tuple[str, str]:
    """"top-right" -> ("top", "right"); "center" -> ("center", "center")."""
    if position == "center":
        return "center", "center"
    vert, _, horiz = position.partition("-")
    if vert not in ("top", "center", "bottom") or horiz not in ("left", "center", "right"):
        return "top", "right"
    return vert, horiz


def anchor_xy(position: str, area: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int]:
    """Absolute top-left for an anchor `position` inside `area` (x, y, w, h), for X11."""
    ax, ay, aw, ah = area
    vert, horiz = split(position)
    x = {"left": ax + MARGIN, "center": ax + (aw - width) // 2, "right": ax + aw - width - MARGIN}[horiz]
    y = {"top": ay + MARGIN, "center": ay + (ah - height) // 2, "bottom": ay + ah - height - MARGIN}[vert]
    return x, y


def layer_anchors(position: str) -> dict[str, int]:
    """Layer-shell anchors for a `position`: {edge: margin} for each anchored edge."""
    vert, horiz = split(position)
    return {edge: MARGIN for edge in (vert, horiz) if edge != "center"}


def layer_moved(x: int, y: int) -> dict[str, int]:
    """Anchors for a widget the user moved: pinned by its top-left corner."""
    return {"top": max(0, int(y)), "left": max(0, int(x))}


def layer_top_left(anchors: dict[str, int], screen: tuple[int, int], size: tuple[int, int]) -> tuple[int, int]:
    """Where layer `anchors` put a surface of `size` on a `screen` (w, h): its top-left corner."""
    (sw, sh), (w, h) = screen, size
    if "left" in anchors:
        x = anchors["left"]
    elif "right" in anchors:
        x = sw - w - anchors["right"]
    else:
        x = (sw - w) // 2
    if "top" in anchors:
        y = anchors["top"]
    elif "bottom" in anchors:
        y = sh - h - anchors["bottom"]
    else:
        y = (sh - h) // 2
    return x, y


MIN_SIZE = (80, 40)
MAX_SIZE = (1600, 1200)


def clamp_size(width: int, height: int, area: tuple[int, int] | None = None) -> tuple[int, int]:
    """A requested window size, limited to the widget bounds and to the monitor's work area
    `area` (w, h) minus a margin on each side. The smaller limit wins."""
    w = max(MIN_SIZE[0], min(MAX_SIZE[0], int(width)))
    h = max(MIN_SIZE[1], min(MAX_SIZE[1], int(height)))
    if area:
        w = max(MIN_SIZE[0], min(w, area[0] - 2 * MARGIN))
        h = max(MIN_SIZE[1], min(h, area[1] - 2 * MARGIN))
    return w, h


def safe_size(width, height, area: tuple[int, int] | None, fallback: tuple[int, int]) -> tuple[int, int]:
    """clamp_size for values read from a widget.json that may have been edited by hand: anything
    that isn't a plain finite number (strings, inf, NaN, lists, None) gives `fallback`, not an error."""
    try:
        if any(type(v) not in (int, float) for v in (width, height)):  # no bools, strings, None
            return fallback
        return clamp_size(width, height, area)
    except (TypeError, ValueError, OverflowError):
        return fallback


def clamp(x: float, y: float, screen: tuple[int, int], size: tuple[int, int]) -> tuple[int, int]:
    """Keep a dragged widget on screen."""
    (sw, sh), (w, h) = screen, size
    return int(min(max(x, 0), max(sw - w, 0))), int(min(max(y, 0), max(sh - h, 0)))
