"""Native widgets for the install stages and parallel sprite captures."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class StageRibbon(tk.Frame):
    PALETTE = {
        "done": ("✓", "#80d6b0", "#477f69", "Ran"),
        "active": ("●", "#91e4fc", "#62cce9", "In progress"),
        "pending": ("○", "#b0bec9", "#344552", "If needed"),
        "skipped": ("–", "#99a7b2", "#344552", "Skipped"),
    }

    def __init__(self, parent):
        super().__init__(parent, background=parent.cget("background"))
        self.cells = []
        self.stages = ()
        self.subrow = tk.Frame(self, background=self.cget("background"))
        self.subrow.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        self.subtitles = []
        self.window = None
        self.selected = 0
        self.displayed_stage = None

    def reset(self):
        self._close_details()
        self.stages = ()
        self.grid_remove()

    def show(self, stages):
        if not stages:
            self.reset()
            return
        self.stages = stages
        if len(self.cells) != len(stages):
            for i, (button, rule) in enumerate(self.cells):
                self.columnconfigure(i, weight=0, uniform="")
                button.destroy()
                rule.destroy()
            self.cells.clear()
            for index in range(len(stages)):
                self.columnconfigure(index, weight=1, uniform="stage")
                button = tk.Button(
                    self,
                    background=self.cget("background"),
                    relief="flat",
                    borderwidth=0,
                    activebackground="#253745",
                    activeforeground="#f1f6f8",
                    anchor="w",
                    width=1,
                    padx=0,
                    pady=0,
                    cursor="hand2",
                    takefocus=True,
                    highlightcolor="#91e4fc",
                    highlightbackground=self.cget("background"),
                    highlightthickness=1,
                    font=("Segoe UI Semibold", 9),
                    command=lambda i=index: self._open_details(i),
                )
                button.bind("<Return>", lambda event: event.widget.invoke())
                rule = tk.Frame(self, height=3)
                padding = (0, 5 if index + 1 < len(stages) else 0)
                button.grid(row=0, column=index, sticky="ew", padx=padding)
                rule.grid(row=1, column=index, sticky="ew", padx=padding, pady=(1, 0))
                self.cells.append((button, rule))
            self.subrow.grid_configure(columnspan=len(stages))

        for (button, rule), stage in zip(self.cells, stages):
            symbol, text, color, _ = self.PALETTE[stage.state]
            button.configure(text=f"{symbol}  {stage.name}  ›", foreground=text)
            rule.configure(background=color)
        active = next(stage for stage in stages if stage.state == "active")
        while len(self.subtitles) < len(active.steps):
            self.subtitles.append(
                tk.Label(
                    self.subrow,
                    background=self.cget("background"),
                    font=("Segoe UI", 9),
                    anchor="w",
                    padx=0,
                    pady=1,
                )
            )
        for index, label in enumerate(self.subtitles):
            if index >= len(active.steps):
                label.pack_forget()
                continue
            step = active.steps[index]
            symbol, text, _, _ = self.PALETTE[step.state]
            label.configure(text=f"{symbol} {step.name}", foreground=text)
            label.pack(side="left", padx=(0, 12))
        if self.window is not None:
            self._update_details()
        self.grid()

    def _open_details(self, index):
        self.selected = index
        if self.window is None:
            self.window = tk.Toplevel(self)
            self.window.transient(self.winfo_toplevel())
            self.window.configure(background="#141a20", padx=16, pady=12)
            self.window.protocol("WM_DELETE_WINDOW", self._close_details)
            self.window.bind("<Escape>", lambda _: self._close_details())
            body = tk.Frame(self.window, background="#141a20")
            body.pack(fill="both", expand=True)
            self.details = tk.Text(
                body,
                background="#141a20",
                foreground="#edf3f7",
                relief="flat",
                wrap="word",
                width=48,
                height=12,
                font=("Segoe UI", 10),
                cursor="arrow",
                highlightthickness=0,
            )
            scrollbar = ttk.Scrollbar(body, command=self.details.yview)
            scrollbar.pack(side="right", fill="y")
            self.details.configure(yscrollcommand=scrollbar.set)
            self.details.pack(side="left", fill="both", expand=True)
            for state, (_, color, _, _) in self.PALETTE.items():
                self.details.tag_configure(state, foreground=color, font=("Segoe UI Semibold", 10))
            self.details.tag_configure(
                "task", foreground="#c1ccd3", lmargin1=14, lmargin2=14, spacing3=5
            )
            dismiss = ttk.Button(self.window, text="Close", command=self._close_details)
            dismiss.pack(anchor="e", pady=(6, 0))
            dismiss.focus_set()
        self._update_details()
        self.window.lift()

    def _update_details(self):
        stage = self.stages[self.selected]
        if self.displayed_stage == stage:
            return
        scroll = (
            self.details.yview()[0]
            if self.displayed_stage and self.displayed_stage.name == stage.name
            else 0
        )
        self.displayed_stage = stage
        self.window.title(f"{stage.name} · Steps")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        for step in stage.steps:
            symbol, _, _, status = self.PALETTE[step.state]
            self.details.insert("end", f"{symbol}  {step.name}  ·  {status}\n", step.state)
            for task in step.tasks or (step.description,):
                self.details.insert("end", task + "\n", "task")
        self.details.configure(state="disabled")
        self.details.yview_moveto(scroll)

    def _close_details(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None
            self.displayed_stage = None


class CaptureWorkers(tk.Frame):
    COLORS = {
        "queued": ("#202a34", "#b3c2cc", "#637684"),
        "running": ("#1b3040", "#a0dfff", "#67c6e6"),
        "saved": ("#19332d", "#a1e8c8", "#68bb9b"),
        "restored": ("#19332d", "#a1e8c8", "#68bb9b"),
        "waiting": ("#393123", "#f0cf8c", "#e7b764"),
        "retrying": ("#393123", "#ffda92", "#e7b764"),
        "stopped": ("#402b31", "#f2afb5", "#e58b95"),
    }

    def __init__(self, parent):
        super().__init__(parent, background=parent.cget("background"))
        style = ttk.Style(self)
        for status, (_, _, accent) in self.COLORS.items():
            style.configure(
                f"{status}.Worker.Horizontal.TProgressbar",
                background=accent,
                troughcolor="#0f1c26",
                borderwidth=0,
                thickness=3,
                lightcolor=accent,
                darkcolor=accent,
            )
        self.tiles = []

    def show(self, states, counts):
        if not states:
            self.grid_remove()
            return
        while len(self.tiles) < len(states):
            index = len(self.tiles)
            card = tk.Frame(self, padx=5, pady=4)
            card.columnconfigure(0, weight=1)
            title = tk.Label(
                card, text=f"Worker {index + 1}", font=("Segoe UI", 8), anchor="w", width=1
            )
            status = tk.Label(card, font=("Segoe UI Semibold", 10), anchor="w", width=1)
            bar = ttk.Progressbar(card, length=1, mode="determinate")
            count = tk.Label(card, font=("Segoe UI", 8), anchor="w", width=1)
            title.grid(row=0, column=0, sticky="ew")
            status.grid(row=1, column=0, sticky="ew")
            bar.grid(row=2, column=0, sticky="ew", pady=(3, 1))
            count.grid(row=3, column=0, sticky="ew")
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 3))
            self.tiles.append((card, title, status, bar, count))
        for index, (card, title, label, bar, count) in enumerate(self.tiles):
            if index >= len(states):
                card.grid_remove()
                self.columnconfigure(index, weight=0, uniform="")
                continue
            self.columnconfigure(index, weight=1, uniform="worker")
            state = states[index]
            background, foreground, _ = self.COLORS[state]
            card.configure(background=background)
            title.configure(background=background, foreground="#c1ccd3")
            label.configure(text=state.capitalize(), background=background, foreground=foreground)
            if index < len(counts):
                done, total = counts[index]
                bar.configure(
                    style=f"{state}.Worker.Horizontal.TProgressbar",
                    value=done,
                    maximum=max(1, total),
                )
                count.configure(
                    text=f"{done:,} / {total:,}", background=background, foreground="#c1ccd3"
                )
                count.grid()
                bar.grid()
            else:
                bar.grid_remove()
                count.grid_remove()
            card.grid()
        self.grid()
