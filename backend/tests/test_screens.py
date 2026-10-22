"""Window placement: the window opens on a screen that is on (the one with the mouse pointer)."""

from app.screens import place_window

LEFT = (1, (0, 0, 1920, 1040))           # work area of the main screen
RIGHT = (2, (1920, 0, 4480, 1400))       # a second screen to the right


def test_stays_where_it_was_on_the_pointer_screen():
    assert place_window((100, 120), (880, 620), 1.0, LEFT, LEFT, LEFT) == ((100, 120), (880, 620))


def test_screen_switched_off_moves_to_pointer_screen():
    # Remembered on the right screen, which is gone now (no current screen)
    (x, y), (w, h) = place_window((2500, 300), (880, 620), 1.0, LEFT, None, LEFT)
    assert 0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1040
    assert (w, h) == (880, 620)


def test_other_screen_keeps_the_same_place():
    # Right screen still on, but the pointer is on the left one: same relative spot
    (x, y), _ = place_window((1920 + 2560 - 880, 0), (880, 620), 1.0, LEFT, RIGHT, RIGHT)
    assert x == 1920 - 880 and y == 0


def test_size_fits_a_smaller_screen():
    small = (3, (0, 0, 1280, 680))
    (x, y), (w, h) = place_window(None, (1360, 860), 1.0, small, None, None)
    assert (w, h) == (1280, 680) and (x, y) == (0, 0)


def test_dpi_scale_and_no_preference():
    # 150 %: logical in, logical out; without a pointer screen the remembered screen is used
    big = (4, (0, 0, 3840, 2100))
    assert place_window((100, 100), (880, 620), 1.5, None, big, big) == ((100, 100), (880, 620))
    # At 150 % the window (930 px high) would leave a 1040 px screen at y=150: it moves up
    assert place_window((100, 100), (880, 620), 1.5, None, LEFT, LEFT) == ((100, 73), (880, 620))
    # Nothing known at all: the system decides
    assert place_window(None, (880, 620), 1.0, None, None, None) is None
