"""Bound the native paint work of Setup's nine-sliced control images."""

import math

from scenelight import setup_theme


def test_wide_buttons_do_not_tile_tiny_transparent_images_thousands_of_times(monkeypatch):
    class Image:
        def __init__(self, master, width, height):
            self.width = width
            self.height = height

        def put(self, *args, **kwargs):
            pass

    class Style:
        def __init__(self):
            self.elements = []

        def element_create(self, name, kind, normal, *states, **options):
            self.elements.append(([normal, *(state[-1] for state in states)], options))

        def layout(self, *args, **kwargs):
            pass

        def configure(self, *args, **kwargs):
            pass

        def map(self, *args, **kwargs):
            pass

    monkeypatch.setattr(setup_theme.tk, "PhotoImage", Image)
    style = Style()
    images = setup_theme.soft_controls(None, style)
    assert style.elements and images
    for variants, options in style.elements:
        border = options["border"]
        # ttk repeats the center instead of scaling it. Even a 1200px-wide
        # primary action must stay below 100 center-tile blits in every state.
        for image in variants:
            columns = math.ceil(1200 / (image.width - 2 * border))
            rows = math.ceil(80 / (image.height - 2 * border))
            assert columns * rows < 100
        # Larger tiles must not force tabs/buttons to be equally tall or wide.
        assert options["width"] < 32 and options["height"] < 32
