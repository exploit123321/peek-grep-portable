"""Where the window opens: on a screen that is on, not on one that was switched off or unplugged.

Pure math (no Windows calls), so it can be tested. desktop_app.py asks Windows for the screens.
A screen is (handle, (left, top, right, bottom)) of its work area in physical pixels.
"""

from typing import Optional, Tuple

Screen = Tuple[int, Tuple[int, int, int, int]]
Pair = Tuple[int, int]


def place_window(position: Optional[Pair], size: Pair, scale: float,
                 target: Optional[Screen], current: Optional[Screen],
                 nearest: Optional[Screen]) -> Optional[Tuple[Pair, Pair]]:
    """((x, y), (width, height)) in logical pixels, or None (let the system choose).

    position, size: the remembered window (logical pixels). target: the screen with the mouse
    pointer (None: no preference). current: the screen under the remembered window's center
    (None: that screen is gone). nearest: the screen closest to the remembered window.
    """
    w, h = size[0] * scale, size[1] * scale
    if current and (target is None or current[0] == target[0]):
        target = current  # still on a screen that is on, and the right one
    elif target is None:
        target = nearest
    if target is None:
        return None
    left, top, right, bottom = target[1]
    w = min(w, right - left)
    h = min(h, bottom - top)
    if position and current and current[0] == target[0]:
        x, y = position[0] * scale, position[1] * scale
    elif position and current:
        # Same place on the new screen as on the old one
        ol, ot, orr, ob = current[1]
        fx = (position[0] * scale - ol) / max(1, (orr - ol) - w)
        fy = (position[1] * scale - ot) / max(1, (ob - ot) - h)
        x = left + min(1, max(0, fx)) * ((right - left) - w)
        y = top + min(1, max(0, fy)) * ((bottom - top) - h)
    else:
        # No usable position: centered, a little above the middle
        x = left + ((right - left) - w) / 2
        y = top + ((bottom - top) - h) / 3
    x = min(max(x, left), right - w)
    y = min(max(y, top), bottom - h)
    return (int(x / scale), int(y / scale)), (int(w / scale), int(h / scale))
