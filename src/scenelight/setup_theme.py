"""Small, dependency-free ttk surfaces for Setup's buttons and tabs."""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk


def soft_controls(master: tk.Misc, style: ttk.Style) -> list[tk.PhotoImage]:
    """Keep native ttk behavior, with rounded surfaces and visible keyboard focus.

    Images are nine-sliced by Tk, so resizing preserves the corners. The caller
    retains the images for the lifetime of its Tcl interpreter. No Pillow or Qt
    is needed to open Setup before installing components.
    """
    images: list[tk.PhotoImage] = []
    radius = 7
    # ttk tiles the middle of an image element rather than stretching it. A
    # one-pixel center costs tens of thousands of native blits on a wide button.
    # Keep a useful tile size, while declaring a small minimum element size below.
    size = radius * 2 + 65

    def surface(fill: str, border: str) -> tk.PhotoImage:
        image = tk.PhotoImage(master=master, width=size, height=size)
        for inset, color in ((0, border), (1, fill)):
            r = radius - inset
            for y in range(inset, size - inset):
                dy = max(0, r - (y - inset), r - (size - inset - 1 - y))
                x = inset + math.ceil(r - math.sqrt(max(0, r * r - dy * dy)))
                image.put(color, to=(x, y, size - x, y + 1))
        images.append(image)
        return image

    def element(name: str, fill: str, border: str, states: list[tuple]) -> str:
        name = "SceneLight." + name
        style.element_create(
            name,
            "image",
            surface(fill, border),
            *states,
            border=radius + 1,
            width=radius * 2 + 3,
            height=radius * 2 + 3,
            sticky="nsew",
        )
        return name

    for name, fill, hover, pressed, border, disabled in (
        ("Primary", "#70caf2", "#95dcfb", "#50b1de", "#70caf2", "#2a3038"),
        ("Secondary", "#20262e", "#303b49", "#19222d", "#354150", "#171b21"),
        ("Quiet", "#0d1014", "#1c2530", "#131b24", "#252e39", "#101419"),
        ("Cancel", "#3a2023", "#553034", "#2d191c", "#694047", "#211719"),
    ):
        background = element(
            name,
            fill,
            border,
            [
                ("disabled", surface(disabled, disabled)),
                ("pressed", "focus", surface(pressed, "#b4e8ff")),
                ("pressed", surface(pressed, border)),
                ("active", "focus", surface(hover, "#b4e8ff")),
                ("focus", surface(fill, "#b4e8ff")),
                ("active", surface(hover, border)),
            ],
        )
        style.layout(
            name + ".TButton",
            [
                (
                    background,
                    {
                        "sticky": "nsew",
                        "children": [
                            (
                                "Button.padding",
                                {
                                    "sticky": "nsew",
                                    "children": [
                                        ("Button.label", {"sticky": "nsew"}),
                                    ],
                                },
                            ),
                        ],
                    },
                )
            ],
        )

    tab = element(
        "tab",
        "#12171e",
        "#252f3a",
        [
            ("disabled", surface("#101419", "#1b222b")),
            ("selected", "focus", surface("#203d4c", "#b4e8ff")),
            ("selected", surface("#203d4c", "#508ca7")),
            ("active", surface("#202d39", "#445767")),
        ],
    )
    style.layout("Scene.TNotebook", [("Notebook.client", {"sticky": "nsew"})])
    style.layout(
        "Scene.TNotebook.Tab",
        [
            (
                tab,
                {
                    "sticky": "nsew",
                    "children": [
                        (
                            "Notebook.padding",
                            {
                                "sticky": "nsew",
                                "children": [
                                    ("Notebook.label", {"sticky": "nsew"}),
                                ],
                            },
                        ),
                    ],
                },
            )
        ],
    )
    style.configure("Scene.TNotebook", tabmargins=(0, 0, 0, 10))
    style.configure("Scene.TNotebook.Tab", padding=(17, 10), font=("Segoe UI Semibold", 10))
    style.map(
        "Scene.TNotebook.Tab",
        foreground=[("disabled", "#626b76"), ("selected", "#b9e9ff"), ("active", "#f4f7fa")],
        expand=[("selected", (0, 0, 0, 0))],
        padding=[("selected", (17, 10))],
    )
    style.map(
        "Dark.Vertical.TScrollbar",
        background=[("active", "#46576a"), ("!active", "#303844")],
        arrowcolor=[("disabled", "#566270"), ("!disabled", "#b4c3d2")],
    )
    return images
