"""Small native log browsers; shared report format, no web service required."""

from __future__ import annotations

from pathlib import Path

from . import diagnostics


def mount_activity(parent):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    frame = ttk.Frame(parent, style="Card.TFrame")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(3, weight=1)
    controls = ttk.Frame(frame, style="Card.TFrame")
    controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    chosen = ttk.Combobox(controls, state="readonly", width=48)
    chosen.pack(side="left", fill="x", expand=True)
    summary = tk.StringVar(value="Local sessions are kept after closing SceneLight.")
    ttk.Label(frame, textvariable=summary, style="Card.TLabel", wraplength=700).grid(
        row=1, column=0, sticky="w"
    )
    filters = ttk.Frame(frame, style="Card.TFrame")
    filters.grid(row=2, column=0, sticky="ew", pady=8)
    query = ttk.Entry(filters)
    query.pack(side="left", expand=True, fill="x")
    query.insert(0, "")
    level = ttk.Combobox(
        filters,
        values=("all", "error", "warning", "info", "raw console"),
        state="readonly",
        width=10,
    )
    level.set("all")
    level.pack(side="left", padx=8)
    text = tk.Text(
        frame, wrap="word", bg="#07090c", fg="#dbe8f7", font=("Cascadia Mono", 9), state="disabled"
    )
    text.grid(row=3, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    scroll.grid(row=3, column=1, sticky="ns")
    text.configure(yscrollcommand=scroll.set)
    state = {"rows": [], "signature": None, "game": None}

    def refresh(_event=None, force=False):
        rows = diagnostics.sessions()
        previous = chosen.current()
        previous_path = (
            state["rows"][previous]["path"] if 0 < previous < len(state["rows"]) else None
        )
        state["rows"] = rows
        chosen.configure(
            values=[
                f"{r['started'][:19]} · {r.get('operation', r['area'])} · {r['status']}"
                for r in rows
            ]
        )
        if rows:
            chosen.current(next((i for i, r in enumerate(rows) if r["path"] == previous_path), 0))
            row = rows[chosen.current()]
            signature = (
                str(row["path"]),
                query.get(),
                level.get(),
                diagnostics.session_signature(row["path"]),
            )
            summary.set(
                f"Session {row['id']} · {row['status']} · {row.get('failure', 'Search below or export a report to share.')}\nShowing the newest 1,500 matching events; exported journals retain more."
            )
            if force or signature != state["signature"]:
                state["signature"] = signature
                records = diagnostics.read_events(row["path"], query=query.get(), level=level.get())
                text.configure(state="normal")
                text.delete("1.0", "end")
                text.insert(
                    "end",
                    diagnostics.read_console(row["path"], query=query.get())
                    if level.get() == "raw console"
                    else "\n".join(diagnostics.event_text(r) for r in records),
                )
                text.configure(state="disabled")

    def export():
        index = chosen.current()
        if index < 0:
            return
        row = state["rows"][index]
        output = filedialog.asksaveasfilename(
            parent=frame,
            title="Save support report",
            defaultextension=".zip",
            initialfile=f"SceneLight-report-{row['id']}.zip",
            filetypes=[("Support report", "*.zip")],
        )
        if not output:
            return
        try:
            project = state["game"] or row.get("managed_project") or row.get("project")
            diagnostics.export_report(
                row["path"], Path(output), game_root=Path(project) if project else None
            )
        except (OSError, ValueError) as error:
            messagebox.showerror("Report export failed", str(error), parent=frame)
        else:
            messagebox.showinfo(
                "Support report saved",
                "Send this ZIP to the developer. It includes a searchable report.html and diagnostic logs, without game artwork or saves. Review it before sharing.",
                parent=frame,
            )

    def select_game():
        selected = filedialog.askdirectory(
            parent=frame, title="Include logs from this game's main folder"
        )
        if selected:
            state["game"] = selected
            summary.set("Game logs will be included from: " + selected)

    ttk.Button(filters, text="Include game logs…", command=select_game).pack(side="left")
    ttk.Button(controls, text="Export report…", command=export, style="Secondary.TButton").pack(
        side="right", padx=(8, 0)
    )
    ttk.Button(filters, text="Search / refresh", command=lambda: refresh(force=True)).pack(
        side="left"
    )
    chosen.bind("<<ComboboxSelected>>", lambda e: refresh(e, force=True))
    level.bind("<<ComboboxSelected>>", lambda e: refresh(e, force=True))
    query.bind("<Return>", lambda e: refresh(e, force=True))

    def poll():
        if frame.winfo_exists():
            refresh()
            frame.after(2500, poll)

    frame.after(10, poll)
    return frame


def show_preview_reports(parent):
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle("SceneLight · Activity & support reports")
    dialog.resize(950, 650)
    layout = QVBoxLayout(dialog)
    row = QHBoxLayout()
    sessions = QComboBox()
    records = diagnostics.sessions()
    for record in records:
        sessions.addItem(
            f"{record['started'][:19]} · {record.get('operation', record['area'])} · {record['status']}"
        )
    row.addWidget(sessions, 1)
    export = QPushButton("Export report…")
    row.addWidget(export)
    layout.addLayout(row)
    layout.addWidget(
        QLabel(
            "Search errors, stages, sprites, worker IDs, or renderers. Reports include full details and retained journals."
        )
    )
    filters = QHBoxLayout()
    search = QLineEdit()
    search.setPlaceholderText("Search log…")
    filters.addWidget(search, 1)
    level = QComboBox()
    level.addItems(("all", "error", "warning", "info", "raw console"))
    filters.addWidget(level)
    refresh = QPushButton("Refresh")
    filters.addWidget(refresh)
    layout.addLayout(filters)
    text = QPlainTextEdit()
    text.setReadOnly(True)
    layout.addWidget(text, 1)
    notes = QLineEdit()
    notes.setPlaceholderText("Optional: what happened and steps to reproduce (included in export)")
    layout.addWidget(notes)
    game_folder = [None]
    include = QPushButton("Include game logs…")
    layout.addWidget(include)

    def choose_game():
        selected = QFileDialog.getExistingDirectory(dialog, "Select the game's main folder")
        if selected:
            game_folder[0] = Path(selected)
            include.setText("Game logs: " + Path(selected).name)

    include.clicked.connect(choose_game)

    def update():
        if sessions.currentIndex() >= 0:
            path = records[sessions.currentIndex()]["path"]
            if level.currentText() == "raw console":
                text.setPlainText(diagnostics.read_console(path, query=search.text()))
                return
            text.setPlainText(
                "\n".join(
                    diagnostics.event_text(r)
                    for r in diagnostics.read_events(
                        path, query=search.text(), level=level.currentText()
                    )
                )
            )

    def save():
        if sessions.currentIndex() < 0:
            return
        record = records[sessions.currentIndex()]
        path, _ = QFileDialog.getSaveFileName(
            dialog, "Export support report", f"SceneLight-report-{record['id']}.zip", "ZIP (*.zip)"
        )
        if not path:
            return
        try:
            diagnostics.export_report(
                record["path"], Path(path), notes=notes.text(), game_root=game_folder[0]
            )
            QMessageBox.information(
                dialog,
                "Report saved",
                "Send this ZIP to the developer. Open report.html to browse it first. No artwork or saves are included.",
            )
        except (OSError, ValueError) as error:
            QMessageBox.critical(dialog, "Report export failed", str(error))

    refresh.clicked.connect(update)
    search.returnPressed.connect(update)
    level.currentIndexChanged.connect(update)
    sessions.currentIndexChanged.connect(update)
    export.clicked.connect(save)
    update()
    dialog.exec()
