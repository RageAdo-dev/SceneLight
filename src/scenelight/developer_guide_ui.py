"""Native help browser; works before any optional components are installed."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from .developer_guide import CATEGORIES, GuideTopic, search_topics

BG = "#0d1219"
PANEL = "#131c26"
TEXT = "#e8eef5"
MUTED = "#a0afbf"
ACCENT = "#83d7f2"
HELP_HINT = "Ctrl+F to search  ·  Replace example image names with your own."


class DeveloperGuide(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("SceneLight · Developer guide")
        self.configure(background=BG)
        self.geometry("1000x690")
        self.minsize(760, 500)
        self.query = tk.StringVar(self)
        self.category = tk.StringVar(self, value="All topics")
        self.status = tk.StringVar(self, value=HELP_HINT)
        self._search_after: str | None = None
        self._copy_after: str | None = None
        self._closed = False
        self._traces: list[tuple[tk.StringVar, str]] = []
        self._visible_topics: dict[str, GuideTopic] = {}
        self.current_topic: GuideTopic | None = None
        self._styles()
        self._build()
        for variable in (self.query, self.category):
            self._traces.append((variable, variable.trace_add("write", self._schedule_search)))
        self.bind("<Control-f>", self._focus_search)
        self.bind("<Escape>", lambda _event: self.destroy())
        self._refresh_topics()

    def _styles(self) -> None:
        style = ttk.Style(self)
        style.configure(
            "Guide.Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=MUTED,
            borderwidth=0,
            rowheight=33,
            font=("Segoe UI", 10),
            indent=8,
        )
        style.layout("Guide.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.map(
            "Guide.Treeview",
            background=[("selected", "#234657")],
            foreground=[("selected", "#d4f3ff")],
        )
        style.configure(
            "Guide.TCombobox",
            fieldbackground=PANEL,
            background="#243242",
            foreground=TEXT,
            arrowcolor=ACCENT,
            bordercolor="#334455",
            padding=7,
        )
        style.map(
            "Guide.TCombobox",
            fieldbackground=[("readonly", PANEL)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", PANEL)],
            selectforeground=[("readonly", TEXT)],
        )
        # Scope the popdown colors to this window, leaving other menus alone.
        self.option_add(f"{self}*TCombobox*Listbox.background", PANEL)
        self.option_add(f"{self}*TCombobox*Listbox.foreground", TEXT)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = tk.Frame(self, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(14, 8))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="SCENELIGHT  /  FOR MOD DEVELOPERS",
            bg=BG,
            fg=ACCENT,
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="Commands & examples",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 22),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 2))
        tk.Label(
            header,
            text="Find a setting, see what it does, and copy the code into your mod.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
            anchor="w",
        ).grid(row=2, column=0, sticky="w")
        search_row = tk.Frame(self, bg=BG)
        search_row.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 10))
        search_row.columnconfigure(0, weight=1)
        tk.Label(
            search_row,
            text="SEARCH COMMANDS OR TASKS",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI Semibold", 8),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        tk.Label(
            search_row,
            text="CATEGORY",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI Semibold", 8),
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 5))
        self.search_entry = ttk.Entry(search_row, textvariable=self.query, style="Dark.TEntry")
        self.search_entry.grid(row=1, column=0, sticky="ew")
        self.search_entry.bind("<Down>", self._focus_results)
        self.search_entry.bind("<Return>", self._focus_results)
        self.category_picker = ttk.Combobox(
            search_row,
            textvariable=self.category,
            values=("All topics", *CATEGORIES),
            state="readonly",
            width=22,
            style="Guide.TCombobox",
        )
        self.category_picker.grid(row=1, column=1, padx=(12, 8), sticky="ew")
        ttk.Button(
            search_row,
            text="Clear",
            command=self.clear_search,
            style="Quiet.TButton",
        ).grid(row=1, column=2, sticky="e")

        content = tk.Frame(self, bg=BG)
        content.grid(row=2, column=0, sticky="nsew", padx=24)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        sidebar = tk.Frame(content, bg=PANEL, width=250)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(1, weight=1)
        self.count_label = tk.Label(
            sidebar,
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            font=("Segoe UI Semibold", 9),
        )
        self.count_label.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        self.results = ttk.Treeview(
            sidebar,
            show="tree",
            selectmode="browse",
            style="Guide.Treeview",
            takefocus=True,
        )
        self.results.column("#0", width=228, minwidth=0, stretch=True)
        self.results.grid(row=1, column=0, sticky="nsew", padx=(4, 0), pady=(0, 8))
        scrollbar = ttk.Scrollbar(
            sidebar,
            orient="vertical",
            command=self.results.yview,
            style="Dark.Vertical.TScrollbar",
        )
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(0, 8))
        self.results.configure(yscrollcommand=scrollbar.set)
        self.results.bind("<<TreeviewSelect>>", self._selected)

        detail = tk.Frame(content, bg=PANEL, highlightbackground="#2a3949", highlightthickness=1)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(1, weight=1)
        detail_top = tk.Frame(detail, bg=PANEL)
        detail_top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(12, 4))
        detail_top.columnconfigure(0, weight=1)
        self.section_label = tk.Label(
            detail_top,
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI Semibold", 9),
            anchor="w",
        )
        self.section_label.grid(row=0, column=0, sticky="w")
        self.copy_button = ttk.Button(
            detail_top,
            text="Copy example",
            command=self.copy_example,
            style="Secondary.TButton",
        )
        self.copy_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.reader = tk.Text(
            detail,
            bg=PANEL,
            fg=TEXT,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            font=("Segoe UI", 11),
            padx=18,
            pady=12,
            width=1,
            height=1,
            cursor="arrow",
            takefocus=True,
            selectbackground="#2c556b",
            selectforeground="#ffffff",
            spacing3=9,
        )
        self.reader.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        detail_scroll = ttk.Scrollbar(
            detail,
            orient="vertical",
            command=self.reader.yview,
            style="Dark.Vertical.TScrollbar",
        )
        detail_scroll.grid(row=1, column=1, sticky="ns", pady=(8, 12))
        self.reader.configure(yscrollcommand=detail_scroll.set)
        self.reader.tag_configure("title", font=("Segoe UI Semibold", 21), spacing3=12)
        self.reader.tag_configure(
            "summary", foreground=ACCENT, font=("Segoe UI Semibold", 11), spacing3=15
        )
        self.reader.tag_configure("body", spacing3=13)
        self.reader.tag_configure(
            "eyebrow", font=("Segoe UI Semibold", 8), foreground=ACCENT, spacing1=10, spacing3=6
        )
        self.reader.tag_configure("placement", foreground=MUTED, font=("Segoe UI", 10), spacing3=14)
        self.reader.tag_configure(
            "code",
            font=("Consolas", 10),
            background="#09121b",
            foreground="#d8e8f4",
            lmargin1=12,
            lmargin2=12,
            rmargin=12,
            spacing1=3,
            spacing3=3,
        )
        self.reader.tag_configure("string", foreground="#b6e1b7")
        self.reader.tag_configure("number", foreground="#f0d0a0")
        self.reader.tag_configure("keyword", foreground="#a8d9ff")
        self.reader.tag_configure("comment", foreground="#859aac")
        self.reader.bind("<Control-a>", self._select_all)

        self.footer = tk.Label(
            self,
            textvariable=self.status,
            bg=BG,
            fg=MUTED,
            anchor="w",
            font=("Segoe UI", 9),
            wraplength=940,
            justify="left",
        )
        self.footer.grid(row=3, column=0, sticky="ew", padx=24, pady=(12, 16))
        self.bind("<Configure>", self._resized)

    def _resized(self, event: tk.Event) -> None:
        if event.widget is self:
            self.footer.configure(wraplength=max(200, event.width - 48))

    def _focus_search(self, _event=None) -> str:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")
        return "break"

    def _focus_results(self, _event=None) -> str:
        self._refresh_topics()
        self.results.focus_set()
        return "break"

    def _select_all(self, _event=None) -> str:
        self.reader.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _schedule_search(self, *_args) -> None:
        if self._search_after is not None:
            self.after_cancel(self._search_after)
        self._search_after = self.after(100, self._refresh_topics)

    def clear_search(self) -> None:
        self.query.set("")
        self.category.set("All topics")
        self._refresh_topics()
        self.search_entry.focus_set()

    def _refresh_topics(self) -> None:
        if self._search_after is not None:
            self.after_cancel(self._search_after)
            self._search_after = None
        previous = self.current_topic.key if self.current_topic is not None else None
        topics = search_topics(self.query.get(), self.category.get())
        self._visible_topics = {topic.key: topic for topic in topics}
        children = self.results.get_children()
        if children:
            self.results.delete(*children)
        for topic in topics:
            self.results.insert("", "end", iid=topic.key, text=topic.title)
        self.count_label.configure(text=f"{len(topics)} topic{'s' if len(topics) != 1 else ''}")
        if topics:
            key = previous if previous in self._visible_topics else topics[0].key
            self.results.selection_set(key)
            self.results.focus(key)
            self.results.see(key)
            self._show_topic(self._visible_topics[key])
        else:
            self._show_topic(None)

    def _selected(self, _event=None) -> None:
        selection = self.results.selection()
        if selection:
            topic = self._visible_topics.get(selection[0])
            if topic is not None and topic != self.current_topic:
                self._show_topic(topic)

    def _show_topic(self, topic: GuideTopic | None) -> None:
        self.current_topic = topic
        if self._copy_after is not None:
            self.after_cancel(self._copy_after)
            self._copy_after = None
        self.copy_button.configure(
            text="Copy example", state="normal" if topic and topic.example else "disabled"
        )
        self.status.set(HELP_HINT)
        self.reader.configure(state="normal")
        self.reader.delete("1.0", "end")
        if topic is None:
            self.section_label.configure(text="SEARCH")
            self.reader.insert("end", "No matching topics\n", "title")
            self.reader.insert(
                "end",
                "Try a command name, brightness, color, or turn off. Clear the search to see everything.",
                "body",
            )
        else:
            self.section_label.configure(text=topic.category.upper())
            self.reader.insert("end", topic.title + "\n", "title")
            self.reader.insert("end", topic.summary + "\n", "summary")
            leading_details = topic.details[:1] if topic.example else topic.details
            for paragraph in leading_details:
                self.reader.insert("end", paragraph + "\n", "body")
            if topic.example:
                self.reader.insert("end", "WHERE TO PUT IT\n", "eyebrow")
                self.reader.insert("end", topic.placement + "\n", "placement")
                self.reader.insert("end", "EXAMPLE\n", "eyebrow")
                start = self.reader.index("end-1c")
                self.reader.insert("end", topic.example + "\n", "code")
                # Color the displayed example only; the copied text stays exact.
                tokens = re.compile(
                    r'(?P<comment>\#[^\n]*)|(?P<string>"[^"\n]*"|\x27[^\x27\n]*\x27)|(?P<keyword>\b(?:init|python|True|False|scene|show|label|return|textbutton|action)\b)|(?P<number>\b\d+(?:\.\d+)?\b)'
                )
                for match in tokens.finditer(topic.example):
                    self.reader.tag_add(
                        match.lastgroup, f"{start}+{match.start()}c", f"{start}+{match.end()}c"
                    )
                if len(topic.details) > 1:
                    self.reader.insert("end", "DETAILS\n", "eyebrow")
                    for paragraph in topic.details[1:]:
                        self.reader.insert("end", paragraph + "\n", "body")
        self.reader.configure(state="disabled")
        self.reader.yview_moveto(0)

    def copy_example(self) -> None:
        topic = self.current_topic
        if topic is None or not topic.example:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(topic.example)
        except tk.TclError:
            self.status.set("Clipboard unavailable. Select the example and copy it manually.")
            return
        self.copy_button.configure(text="Copied")
        self.status.set(f"Copied: {topic.title}.  Paste it in the location shown above.")
        if self._copy_after is not None:
            self.after_cancel(self._copy_after)
        self._copy_after = self.after(1800, self._reset_copy_label)

    def _reset_copy_label(self) -> None:
        self._copy_after = None
        self.copy_button.configure(text="Copy example")

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        for callback in (self._search_after, self._copy_after):
            if callback is not None:
                self.after_cancel(callback)
        self._search_after = self._copy_after = None
        for variable, trace in self._traces:
            variable.trace_remove("write", trace)
        self._traces.clear()
        super().destroy()
