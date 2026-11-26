"""PR7-BK's window, Duplicati's pages: the backups (home), Add / Edit backup in five steps, Restore, and the log.

restic runs on threads (`sync = True` runs everything inline: tests); news comes back through `_Bridge`'s queued
signals. Every question goes through `_ask(kind)` (tests: `answers`), every message through `_say`."""

from __future__ import annotations

import copy
import datetime as dt
import os
import posixpath
import string
import sys
import threading

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QRadioButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
                               QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import __version__, finish, jobs, restic, runs, schedule, secrets, settings, theme, widgets
from .jobs import DAY_NAMES, DAYS, DEST_KINDS, Destination, Job, Keep, Schedule

PATH_ROLE = Qt.ItemDataRole.UserRole + 1
STEPS = ("General", "Destination", "Source data", "Schedule", "Options")
EXISTS = (("keepboth", "Keep both (add the version's date)"), ("overwrite", "Replace it"), ("skip", "Skip it"))


def _dim(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    lab.setWordWrap(True)
    return lab


def _field(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def _heading(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "heading")
    return lab


def drives() -> list[str]:
    if sys.platform == "win32":
        return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
    return [os.path.expanduser("~"), "/"]


class _Bridge(QObject):
    progress = Signal(str, object)           # job id, restic.Progress
    finished = Signal(str, object)           # job id, LastRun
    loaded = Signal(str, object, object)     # what, result, error


# ==================================================================== a backup's card on the home page
class JobCard(QFrame):
    def __init__(self, window: "MainWindow", job: Job):
        super().__init__()
        self.window, self.job = window, job
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(6)
        top = QHBoxLayout()
        self.title = _heading(job.name)
        top.addWidget(self.title)
        top.addStretch(1)
        self.state = QLabel("")
        self.state.setProperty("role", "ok")
        top.addWidget(self.state)
        self.buttons = {}
        for key, text, slot in (("run", "RUN NOW", lambda: window.run_now(self.job)),
                                ("stop", "STOP", lambda: window.stop(self.job)),
                                ("restore", "RESTORE", lambda: window.show_restore(self.job)),
                                ("edit", "EDIT", lambda: window.edit(self.job)),
                                ("more", "…", self.more)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=slot: s())
            top.addWidget(b)
            self.buttons[key] = b
        v.addLayout(top)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(4)
        self.values: dict[str, QLabel] = {}
        for i, k in enumerate(("Source", "Destination", "Schedule", "Keep", "Last run", "Next run")):
            self.grid.addWidget(_field(k), i // 2, (i % 2) * 2, Qt.AlignmentFlag.AlignTop)
            lab = QLabel("")
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(lab, i // 2, (i % 2) * 2 + 1)
            self.values[k] = lab
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(3, 1)
        v.addLayout(self.grid)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setRange(0, 1000)
        self.detail = _dim("")
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        v.addWidget(self.bar)
        v.addWidget(self.detail)
        v.addWidget(self.warn)
        self.fill()

    def fill(self, progress: restic.Progress | None = None):
        j = self.job
        running = j.id in self.window.running
        self.title.setText(j.name)
        self.values["Source"].setText("  ·  ".join(j.sources) or "(nothing chosen)")
        self.values["Destination"].setText(j.destination.text())
        self.values["Schedule"].setText(j.schedule.text())
        self.values["Keep"].setText(j.keep.text())
        last = j.last
        if last.when:
            bits = [jobs.when_text(last.when), jobs.duration(last.seconds)]
            if last.ok:
                bits.append("ok" if not last.warnings else f"{last.warnings} warning{'s' if last.warnings > 1 else ''}")
                if last.files_new or last.files_changed:
                    n = last.files_new + last.files_changed
                    bits.append(f"{n:,} file{'s' if n != 1 else ''} changed, {jobs.size(last.data_added)} added")
            else:
                bits.append("failed")
            self.values["Last run"].setText("  ·  ".join(bits))
        else:
            self.values["Last run"].setText("Never")
        nxt = j.schedule.next_run(dt.datetime.now(), None)
        self.values["Next run"].setText(jobs.when_text(nxt.isoformat()) if nxt else "When you click Run now")
        self.buttons["run"].setVisible(not running)
        self.buttons["stop"].setVisible(running)
        self.buttons["edit"].setEnabled(not running)
        self.bar.setVisible(running)
        self.detail.setVisible(running)
        if running:
            p = progress or self.window.progress.get(j.id) or restic.Progress()
            self.bar.setValue(int(p.percent * 10))
            self.state.setText(f"RUNNING  ·  {p.percent:.0f} %")
            bits = [p.phase]
            if p.total_files:
                bits.append(f"{p.files_done:,} of {p.total_files:,} files")
            if p.total_bytes:
                bits.append(f"{jobs.size(p.bytes_done)} of {jobs.size(p.total_bytes)}")
            if p.seconds_left:
                bits.append(f"about {jobs.duration(p.seconds_left)} left")
            self.detail.setText("  ·  ".join(bits))
        else:
            self.state.setText("")
        warn = ""
        if not running and last.when and not last.ok:
            warn = f"Last run failed: {last.message}"
        elif not running and last.warnings:
            warn = f"Last run finished with warnings: {last.message} (see LOG)."
        self.warn.setText(warn)
        self.warn.setVisible(bool(warn))
        self.warn.setStyleSheet(f"color: {theme.LED_ORANGE};")

    def more(self):
        m = QMenu(self)
        m.addAction("Show log", lambda: self.window.show_log(self.job))
        m.addAction("Verify backup", lambda: self.window.verify(self.job))
        m.addAction("Copy", lambda: self.window.duplicate(self.job))
        m.addSeparator()
        m.addAction("Delete…", lambda: self.window.delete(self.job))
        if self.window.answers.get("menu"):
            self.window.last_menu = m
            return
        m.exec(self.buttons["more"].mapToGlobal(self.buttons["more"].rect().bottomLeft()))


# ==================================================================== the window
class MainWindow(QMainWindow):
    def __init__(self, sync: bool = False):
        super().__init__()
        self.answers: dict = {}
        self.said: list = []
        self.sync = sync
        self.jobs: list[Job] = jobs.load()
        self.running: dict[str, runs.Run] = {}
        self.progress: dict[str, restic.Progress] = {}
        self.cards: dict[str, JobCard] = {}
        self.editing: Job | None = None
        self.editing_new = False
        self.restore_job: Job | None = None
        self.snapshots: list[restic.Snapshot] = []
        self.nodes: list[restic.Node] = []
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._progress)
        self.bridge.finished.connect(self._finished)
        self.bridge.loaded.connect(self._loaded)
        self.setWindowTitle("Paragon PR7-BK")
        self.resize(1320, 860)
        self._build()
        self._menus()
        self.restyle()
        self.fill_home()
        self.show_page("home")
        self.clock = QTimer(self)                  # the scheduled process writes jobs.json: notice its results
        self.clock.timeout.connect(self.reload_jobs)
        self.clock.start(15000)

    # ================================================================ building
    def _build(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = widgets.Header("BACKUP")
        lay.addWidget(self.header)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 6)
        bl.setSpacing(6)
        self.keys: dict[str, widgets.KeyButton] = {}
        groups = [[("add", "add", "Add backup", self.add), ("run", "play", "Run now", lambda: self.run_now(self.current())),
                   ("restore", "undo", "Restore", lambda: self.show_restore(self.current()))],
                  [("stop", "stop", "Stop", lambda: self.stop(self.current())),
                   ("log", "list", "Log", lambda: self.show_log(self.current()))],
                  [("settings", "gear", "Settings", self.options)]]
        for i, group in enumerate(groups):
            if i:
                sep = QLabel()
                sep.setObjectName("sep")
                sep.setFixedSize(1, 40)
                bl.addSpacing(8)
                bl.addWidget(sep)
                bl.addSpacing(8)
            for key, icon, label, slot in group:
                k = widgets.KeyButton(icon, label)
                k.setFixedSize(QSize(100, 62))
                k.clicked.connect(lambda _=False, s=slot: s())
                bl.addWidget(k)
                self.keys[key] = k
        bl.addStretch(1)
        lay.addWidget(bar)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._home_page())
        self.pages.addWidget(self._wizard_page())
        self.pages.addWidget(self._restore_page())
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 6, 16, 8)
        wl.addWidget(self.pages)
        lay.addWidget(wrap, 1)
        foot = QFrame()
        foot.setObjectName("foot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 6, 16, 6)
        self.status = _dim("")
        self.status.setWordWrap(False)
        fl.addWidget(self.status, 1)
        self.state = _dim("Encrypted with AES-256 by restic  ·  Windows' Task Scheduler runs them when PR7-BK is closed")
        self.state.setWordWrap(False)
        fl.addWidget(self.state)
        lay.addWidget(foot)

    def _home_page(self):
        self.home_scroll = QScrollArea()
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.home_body = QWidget()
        self.home_body.setObjectName("plain")
        self.home_lay = QVBoxLayout(self.home_body)
        self.home_lay.setContentsMargins(0, 0, 0, 0)
        self.home_lay.setSpacing(10)
        self.empty = QFrame()
        self.empty.setObjectName("card")
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(24, 24, 24, 24)
        el.addWidget(_heading("No backups yet"))
        el.addWidget(_dim("ADD BACKUP chooses the folders, where they go (a drive, a NAS, SFTP, S3, Backblaze B2) and "
                          "when. restic encrypts everything with your password and keeps each piece only once."))
        b = QPushButton("ADD BACKUP")
        b.setProperty("kind", "primary")
        b.clicked.connect(self.add)
        el.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.home_lay.addWidget(self.empty)
        self.home_lay.addStretch(1)
        self.home_scroll.setWidget(self.home_body)
        return self.home_scroll

    # ---------------------------------------------------------------- the wizard
    def _wizard_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        steps = QHBoxLayout()
        self.step_labels = []
        for i, name in enumerate(STEPS):
            lab = QPushButton(f"{i + 1}  {name.upper()}")
            lab.setObjectName("step")
            lab.clicked.connect(lambda _=False, i=i: self.go_step(i))
            steps.addWidget(lab, 1)
            self.step_labels.append(lab)
        lay.addLayout(steps)
        lay.addSpacing(8)
        self.steps = QStackedWidget()
        for page in (self._step_general(), self._step_destination(), self._step_sources(), self._step_schedule(),
                     self._step_options()):
            self.steps.addWidget(page)
        lay.addWidget(self.steps, 1)
        nav = QHBoxLayout()
        cancel = QPushButton("CANCEL")
        cancel.clicked.connect(lambda: self.show_page("home"))
        nav.addWidget(cancel)
        nav.addStretch(1)
        self.back_button = QPushButton("BACK")
        self.back_button.clicked.connect(lambda: self.go_step(self.steps.currentIndex() - 1))
        self.next_button = QPushButton("NEXT")
        self.next_button.setProperty("kind", "primary")
        self.next_button.clicked.connect(self.next_step)
        nav.addWidget(self.back_button)
        nav.addWidget(self.next_button)
        lay.addLayout(nav)
        return w

    def _panel(self) -> tuple[QFrame, QVBoxLayout]:
        f = QFrame()
        f.setObjectName("card")
        v = QVBoxLayout(f)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)
        return f, v

    def _step_general(self):
        f, v = self._panel()
        v.addWidget(_heading("General"))
        form = QFormLayout()
        self.w_name = QLineEdit()
        self.w_name.setPlaceholderText("Studio projects")
        self.w_pass = QLineEdit()
        self.w_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.w_pass2 = QLineEdit()
        self.w_pass2.setEchoMode(QLineEdit.EchoMode.Password)
        self.w_show = QCheckBox("Show the password")
        self.w_show.toggled.connect(lambda on: [e.setEchoMode(QLineEdit.EchoMode.Normal if on else
                                                              QLineEdit.EchoMode.Password)
                                                for e in (self.w_pass, self.w_pass2)])
        form.addRow(_field("Name"), self.w_name)
        form.addRow(_field("Password"), self.w_pass)
        form.addRow(_field("Repeat it"), self.w_pass2)
        form.addRow("", self.w_show)
        v.addLayout(form)
        self.w_pass_note = _dim("")
        v.addWidget(self.w_pass_note)
        v.addStretch(1)
        return f

    def _step_destination(self):
        f, v = self._panel()
        v.addWidget(_heading("Destination"))
        form = QFormLayout()
        self.w_kind = QComboBox()
        for k, text in DEST_KINDS.items():
            self.w_kind.addItem(text, k)
        self.w_kind.currentIndexChanged.connect(lambda _i: self._dest_fields())
        form.addRow(_field("Where"), self.w_kind)
        self.w_dest = {}
        row = QHBoxLayout()
        self.w_dest["path"] = QLineEdit()
        browse = QPushButton("BROWSE…")
        browse.clicked.connect(self._browse_dest)
        self.w_browse = browse
        row.addWidget(self.w_dest["path"], 1)
        row.addWidget(browse)
        self.w_path_label = _field("Folder")
        form.addRow(self.w_path_label, row)
        for key, label in (("host", "Server"), ("port", "Port"), ("user", "User"), ("bucket", "Bucket"),
                           ("secret", "Key / password")):
            e = QLineEdit()
            if key == "secret":
                e.setEchoMode(QLineEdit.EchoMode.Password)
            if key == "port":
                e.setPlaceholderText("22")
            lab = _field(label)
            form.addRow(lab, e)
            self.w_dest[key] = e
            self.w_dest[key + "_label"] = lab
        v.addLayout(form)
        self.w_dest_note = _dim("")
        v.addWidget(self.w_dest_note)
        t = QHBoxLayout()
        test = QPushButton("TEST CONNECTION")
        test.clicked.connect(self.test_destination)
        t.addWidget(test)
        self.w_test = _dim("")
        t.addWidget(self.w_test, 1)
        v.addLayout(t)
        v.addStretch(1)
        return f

    def _dest_fields(self):
        k = self.w_kind.currentData()
        shown = {"local": ("path",), "sftp": ("host", "port", "user", "path"), "rest": ("host", "user", "secret"),
                 "s3": ("host", "bucket", "path", "user", "secret"), "b2": ("bucket", "path", "user", "secret")}[k]
        for key in ("host", "port", "user", "bucket", "secret"):
            self.w_dest[key].setVisible(key in shown)
            self.w_dest[key + "_label"].setVisible(key in shown)
        self.w_dest["path"].setVisible("path" in shown)
        self.w_path_label.setVisible("path" in shown)
        self.w_browse.setVisible(k == "local")
        self.w_path_label.setText({"local": "FOLDER", "sftp": "PATH ON THE SERVER"}.get(k, "FOLDER IN THE BUCKET"))
        self.w_dest["host_label"].setText({"rest": "URL", "s3": "ENDPOINT"}.get(k, "SERVER"))
        self.w_dest["user_label"].setText({"s3": "ACCESS KEY ID", "b2": "ACCOUNT ID"}.get(k, "USER"))
        self.w_dest["secret_label"].setText({"s3": "SECRET KEY", "b2": "APPLICATION KEY"}.get(k, "PASSWORD"))
        self.w_dest_note.setText({
            "local": "A folder on another drive, or a network share (\\\\server\\share\\folder).",
            "sftp": "restic signs in with your SSH key (Windows' OpenSSH, as `ssh user@server` does): a password "
                    "isn't asked for, so set up a key for this server first.",
            "rest": "A restic REST server (rest-server), e.g. https://backup.local:8000/ari.",
            "s3": "Amazon S3 or any S3-compatible service (MinIO, Wasabi ...): e.g. s3.eu-central-1.amazonaws.com.",
            "b2": "Backblaze B2: an application key with access to the bucket."}[k])

    def _browse_dest(self):
        path = self._ask("folder", self.w_dest["path"].text())
        if path:
            self.w_dest["path"].setText(os.path.normpath(path))

    def _step_sources(self):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        self.w_tree = QTreeWidget()
        self.w_tree.setHeaderLabels(["FOLDER"])
        self.w_tree.setIconSize(QSize(18, 18))
        self.w_tree.itemExpanded.connect(self._expand)
        self.w_tree.itemChanged.connect(self._ticked)
        left.addWidget(self.w_tree, 1)
        add = QHBoxLayout()
        b = QPushButton("ADD FOLDER…")
        b.clicked.connect(self._add_folder)
        add.addWidget(b)
        add.addStretch(1)
        left.addLayout(add)
        row.addLayout(left, 3)
        side, sl = self._panel()
        sl.addWidget(_heading("Chosen"))
        self.w_chosen = QTreeWidget()
        self.w_chosen.setHeaderHidden(True)
        self.w_chosen.setRootIsDecorated(False)
        self.w_chosen.setFixedHeight(110)
        sl.addWidget(self.w_chosen)
        sl.addWidget(_heading("Filters"))
        self.w_filters = QTreeWidget()
        self.w_filters.setHeaderLabels(["EXCLUDE"])
        self.w_filters.setRootIsDecorated(False)
        sl.addWidget(self.w_filters, 1)
        fr = QHBoxLayout()
        self.w_pattern = QLineEdit()
        self.w_pattern.setPlaceholderText("*.psd~   node_modules   C:\\Users\\Ari\\Downloads")
        self.w_pattern.returnPressed.connect(self._add_pattern)
        addp = QPushButton("ADD")
        addp.clicked.connect(self._add_pattern)
        rem = QPushButton("REMOVE")
        rem.clicked.connect(self._remove_pattern)
        fr.addWidget(self.w_pattern, 1)
        fr.addWidget(addp)
        fr.addWidget(rem)
        sl.addLayout(fr)
        sl.addWidget(_heading("Exclude"))
        self.w_hidden = QCheckBox("Hidden files (names starting with a dot)")
        self.w_system = QCheckBox("System files (pagefile, hibernation file, Recycle Bin)")
        self.w_temp = QCheckBox("Temporary files (*.tmp, Office's ~$ lock files, Thumbs.db)")
        lr = QHBoxLayout()
        self.w_large = QCheckBox("Files larger than")
        self.w_large_gb = QSpinBox()
        self.w_large_gb.setRange(1, 1000)
        self.w_large_gb.setSuffix(" GB")
        lr.addWidget(self.w_large)
        lr.addWidget(self.w_large_gb)
        lr.addStretch(1)
        for c in (self.w_hidden, self.w_system, self.w_temp):
            sl.addWidget(c)
        sl.addLayout(lr)
        row.addWidget(side, 2)
        return w

    def _step_schedule(self):
        f, v = self._panel()
        v.addWidget(_heading("Schedule"))
        self.w_sched = QButtonGroup(self)               # siblings need a group (PR7-HB's lesson)
        self.w_sched_none = QRadioButton("Only when I click Run now")
        hr = QHBoxLayout()
        self.w_sched_hourly = QRadioButton("Every")
        self.w_every = QSpinBox()
        self.w_every.setRange(1, 23)
        self.w_every.setSuffix(" hours")
        hr.addWidget(self.w_sched_hourly)
        hr.addWidget(self.w_every)
        hr.addStretch(1)
        dr = QHBoxLayout()
        self.w_sched_daily = QRadioButton("Every day at")
        self.w_daily_at = QTimeEdit()
        self.w_daily_at.setDisplayFormat("HH:mm")
        dr.addWidget(self.w_sched_daily)
        dr.addWidget(self.w_daily_at)
        dr.addStretch(1)
        wr = QHBoxLayout()
        self.w_sched_weekly = QRadioButton("Every")
        self.w_day = QComboBox()
        for d in DAYS:
            self.w_day.addItem(DAY_NAMES[d], d)
        self.w_weekly_at = QTimeEdit()
        self.w_weekly_at.setDisplayFormat("HH:mm")
        wr.addWidget(self.w_sched_weekly)
        wr.addWidget(self.w_day)
        wr.addWidget(QLabel("at"))
        wr.addWidget(self.w_weekly_at)
        wr.addStretch(1)
        for b in (self.w_sched_none, self.w_sched_hourly, self.w_sched_daily, self.w_sched_weekly):
            self.w_sched.addButton(b)
        v.addWidget(self.w_sched_none)
        for r in (hr, dr, wr):
            v.addLayout(r)
        v.addWidget(_dim("Windows' Task Scheduler starts the backup at that time even when PR7-BK is closed (a task "
                         "of yours, under Paragon\\PR7-BK). A missed time (the PC was off) runs at the next one."))
        v.addStretch(1)
        return f

    def _step_options(self):
        f, v = self._panel()
        v.addWidget(_heading("Keep"))
        self.w_keep = QButtonGroup(self)
        self.w_keep_all = QRadioButton("Every version")
        lr = QHBoxLayout()
        self.w_keep_last = QRadioButton("The last")
        self.w_last = QSpinBox()
        self.w_last.setRange(1, 9999)
        self.w_last.setSuffix(" versions")
        lr.addWidget(self.w_keep_last)
        lr.addWidget(self.w_last)
        lr.addStretch(1)
        sr = QHBoxLayout()
        self.w_keep_smart = QRadioButton("One a day for")
        self.w_daily = QSpinBox()
        self.w_daily.setRange(0, 365)
        self.w_daily.setSuffix(" days,")
        self.w_weekly = QSpinBox()
        self.w_weekly.setRange(0, 520)
        self.w_weekly.setSuffix(" weeks,")
        self.w_monthly = QSpinBox()
        self.w_monthly.setRange(0, 1200)
        self.w_monthly.setSuffix(" months")
        sr.addWidget(self.w_keep_smart)
        sr.addWidget(self.w_daily)
        sr.addWidget(QLabel("one a week for"))
        sr.addWidget(self.w_weekly)
        sr.addWidget(QLabel("one a month for"))
        sr.addWidget(self.w_monthly)
        sr.addStretch(1)
        for b in (self.w_keep_all, self.w_keep_last, self.w_keep_smart):
            self.w_keep.addButton(b)
        v.addWidget(self.w_keep_all)
        v.addLayout(lr)
        v.addLayout(sr)
        v.addWidget(_dim("Older versions are removed after each backup, and the space they alone used is freed."))
        v.addSpacing(10)
        v.addWidget(_heading("Open files"))
        self.w_vss = QCheckBox("Back up files other programs have open (Volume Shadow Copy; needs PR7-BK to run as "
                               "administrator)")
        v.addWidget(self.w_vss)
        v.addSpacing(10)
        v.addWidget(_heading("Summary"))
        self.w_summary = _dim("")
        v.addWidget(self.w_summary)
        v.addStretch(1)
        return f

    # ---------------------------------------------------------------- restore
    def _restore_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(_field("Backup"))
        self.r_job = QComboBox()
        self.r_job.setFixedWidth(280)
        self.r_job.currentIndexChanged.connect(self._restore_job_changed)
        top.addWidget(self.r_job)
        top.addSpacing(20)
        self.r_search = QLineEdit()
        self.r_search.setPlaceholderText("Search this version")
        self.r_search.setFixedWidth(300)
        self.r_search.textChanged.connect(lambda _t: self._fill_files())
        top.addWidget(self.r_search)
        top.addStretch(1)
        self.r_note = _dim("")
        self.r_note.setWordWrap(False)
        top.addWidget(self.r_note)
        lay.addLayout(top)
        split = QSplitter()
        self.r_versions = QTreeWidget()
        self.r_versions.setHeaderLabels(["VERSION", "FILES", "ADDED"])
        self.r_versions.setRootIsDecorated(False)
        self.r_versions.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.r_versions.currentItemChanged.connect(lambda *_: self._version_chosen())
        self.r_files = QTreeWidget()
        self.r_files.setHeaderLabels(["NAME", "SIZE", "MODIFIED"])
        self.r_files.setIconSize(QSize(18, 18))
        self.r_files.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            self.r_files.header().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.r_files.itemChanged.connect(self._file_ticked)
        split.addWidget(self.r_versions)
        split.addWidget(self.r_files)
        split.setSizes([520, 760])
        lay.addWidget(split, 1)
        opts = QHBoxLayout()
        opts.addWidget(_field("Restore to"))
        self.r_where = QButtonGroup(self)
        self.r_original = QRadioButton("Where they were")
        self.r_other = QRadioButton("Another folder")
        self.r_original.setChecked(True)
        for b in (self.r_original, self.r_other):
            self.r_where.addButton(b)
            opts.addWidget(b)
        self.r_folder = QLineEdit()
        self.r_folder.setMinimumWidth(240)
        opts.addWidget(self.r_folder)
        browse = QPushButton("…")
        browse.clicked.connect(lambda: (lambda p: p and (self.r_folder.setText(os.path.normpath(p)),
                                                         self.r_other.setChecked(True)))(
            self._ask("folder", self.r_folder.text())))
        opts.addWidget(browse)
        opts.addSpacing(20)
        opts.addWidget(_field("If a file exists"))
        self.r_exists = QComboBox()
        for k, text in EXISTS:
            self.r_exists.addItem(text, k)
        opts.addWidget(self.r_exists)
        opts.addStretch(1)
        self.r_button = QPushButton("RESTORE")
        self.r_button.setProperty("kind", "primary")
        self.r_button.clicked.connect(self.restore)
        opts.addWidget(self.r_button)
        lay.addLayout(opts)
        return w

    # ---------------------------------------------------------------- menus
    def _act(self, menu, text, slot, keys=None, key=None, checkable=False):
        a = QAction(text, self)
        if keys:
            a.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, (list, tuple)) else [keys])])
        a.setCheckable(checkable)
        a.triggered.connect(lambda *_: slot())
        menu.addAction(a)
        if key:
            self.acts[key] = a
        return a

    def _menus(self):
        self.acts: dict[str, QAction] = {}
        mb = self.menuBar()
        m = mb.addMenu("&Backup")
        self._act(m, "Add Backup…", self.add, "Ctrl+N", "add")
        self._act(m, "Run Now", lambda: self.run_now(self.current()), "F5", "run")
        self._act(m, "Stop", lambda: self.stop(self.current()), None, "stop")
        self._act(m, "Restore…", lambda: self.show_restore(self.current()), "Ctrl+R", "restore")
        m.addSeparator()
        self._act(m, "Exit", self.close, "Alt+F4")
        m = mb.addMenu("&View")
        self._act(m, "Backups", lambda: self.show_page("home"), "Ctrl+1", "home")
        self._act(m, "Log", lambda: self.show_log(self.current()), "Ctrl+L", "log")
        fm = m.addMenu("Finish")
        self.finish_acts = {}
        fg = QActionGroup(self)
        for name in ("obsidian", "aurora"):
            a = self._act(fm, name.upper(), lambda n=name: self.set_finish(n), checkable=True)
            fg.addAction(a)
            self.finish_acts[name] = a
        m = mb.addMenu("&Tools")
        self._act(m, "Settings…", self.options, None, "settings")
        m = mb.addMenu("&Help")
        self._act(m, "Check for Updates…", self.check_updates, None, "updates")
        self._act(m, "About PR7-BK", lambda: self._say("info", f"Paragon PR7-BK {__version__}\nBackups, the way Duplicati "
                                                               f"makes them. restic {restic.version() or '(not found)'} "
                                                               "does the work."))

    # ================================================================ look
    def restyle(self):
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.palette())
            app.setStyleSheet(theme.stylesheet())
        self.centralWidget().setStyleSheet(
            f"QWidget#central, QWidget#plain {{ background: {theme.BACKGROUND}; }} "
            f"QLabel#sep {{ background: {theme.PANEL_EDGE}; }} "
            f"QFrame#foot {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }} "
            f"QFrame#card {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; border-radius: 8px; }} "
            f"QPushButton[kind=\"primary\"] {{ background: {theme.qss_gradient()}; color: #FFFFFF; border: none; "
            f"font-weight: 600; padding: 7px 22px; }} QPushButton[kind=\"primary\"]:disabled {{ background: "
            f"{theme.BUTTON}; color: {theme.TEXT_DIM}; }} "
            f"QPushButton#step {{ background: {theme.BUTTON}; color: {theme.TEXT_DIM}; border: none; border-radius: 6px; "
            f"padding: 8px 18px; font-weight: 600; }} QPushButton#step[state=\"done\"] {{ color: {theme.ON_DARK}; }} "
            f"QPushButton#step[state=\"now\"] {{ background: {theme.qss_gradient()}; color: #FFFFFF; }} "
            f"QTreeView::item:selected {{ background: {theme.qss_gradient(theme.LIT, 0.22)}; }} "
            f"QTreeView::branch:selected {{ background: transparent; }} "
            f"QTreeView {{ selection-background-color: transparent; }} "
            # tick boxes in the trees: the theme styles only check boxes, and Qt's own unticked box is invisible
            # on OBSIDIAN
            f"QTreeView::indicator {{ width: 12px; height: 12px; border-radius: 3px; border: 1px solid {theme.TEXT_DIM}; "
            f"background: transparent; }} QTreeView::indicator:checked {{ background: {theme.qss_gradient()}; "
            f"border: none; }} QTreeView::indicator:indeterminate {{ background: {theme.qss_gradient(theme.LIT, 0.4)}; "
            f"border: 1px solid {theme.ACCENT}; }}")
        self.header.update()
        for name, a in getattr(self, "finish_acts", {}).items():
            a.setChecked(name == theme.FINISH)
        for c in self.cards.values():
            c.fill()

    def set_finish(self, name: str):
        theme.set_finish(name)
        finish.set(theme.FINISH)
        settings.set("finish", theme.FINISH)
        self.restyle()

    # ================================================================ home
    def current(self) -> Job | None:
        """The backup the toolbar acts on: the one being restored / edited, else the first (or the running one)."""
        if self.pages.currentIndex() == 2 and self.restore_job:
            return self.restore_job
        if self.running:
            return self.job(next(iter(self.running)))
        return self.jobs[0] if self.jobs else None

    def job(self, job_id: str) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def fill_home(self):
        for c in self.cards.values():
            self.home_lay.removeWidget(c)
            c.deleteLater()
        self.cards = {}
        for i, j in enumerate(self.jobs):
            c = JobCard(self, j)
            self.cards[j.id] = c
            self.home_lay.insertWidget(i, c)
        self.empty.setVisible(not self.jobs)
        self._sync()

    def reload_jobs(self):
        """Pick up results written by scheduled runs (another process) without disturbing what's running here."""
        fresh = {j.id: j for j in jobs.load()}
        changed = False
        for j in self.jobs:
            f = fresh.get(j.id)
            if f is not None and f.last != j.last and j.id not in self.running:
                j.last = f.last
                changed = True
        if changed:
            for c in self.cards.values():
                c.fill()
            self._sync()

    def show_page(self, page: str):
        self.pages.setCurrentIndex({"home": 0, "wizard": 1, "restore": 2}[page])
        self._sync()

    # ================================================================ running
    def run_now(self, job: Job | None) -> bool:
        if job is None or job.id in self.running:
            return False
        run = runs.Run(job)
        self.running[job.id] = run
        self.progress[job.id] = restic.Progress()
        if job.id in self.cards:
            self.cards[job.id].fill()
        self.show_page("home")

        def work():
            last = run(on_progress=lambda p: self.bridge.progress.emit(job.id, p))
            self.bridge.finished.emit(job.id, last)
        if self.sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()
        return True

    def stop(self, job: Job | None):
        if job is not None and job.id in self.running:
            self.running[job.id].stop()

    def _progress(self, job_id: str, p):
        self.progress[job_id] = p
        if job_id in self.cards:
            self.cards[job_id].fill(p)

    def _finished(self, job_id: str, last):
        self.running.pop(job_id, None)
        self.progress.pop(job_id, None)
        j = self.job(job_id)
        if j is not None:
            j.last = last
        if job_id in self.cards:
            self.cards[job_id].fill()
        self._sync()

    def verify(self, job: Job | None):
        if job is None:
            return
        self._background("verify", lambda: self._engine(job).check())

    def show_log(self, job: Job | None):
        if job is None:
            return
        text = runs.read_log(job) or "Nothing has run yet."
        if "log" in self.answers:
            self.answers["log"](text)
            return
        d = QDialog(self)
        d.setWindowTitle(f"Log  ·  {job.name}")
        d.resize(900, 560)
        v = QVBoxLayout(d)
        e = QPlainTextEdit(text)
        e.setReadOnly(True)
        e.moveCursor(e.textCursor().MoveOperation.End)
        v.addWidget(e)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        b.rejected.connect(d.reject)
        v.addWidget(b)
        d.exec()

    def delete(self, job: Job | None) -> bool:
        if job is None or job.id in self.running:
            return False
        if not self._ask("confirm", f"Delete the backup \u201c{job.name}\u201d from PR7-BK?\n\nIts schedule and saved "
                                    "password go; what's at the destination stays (it can be added again)."):
            return False
        schedule.remove(job, self.answers.get("schtasks"))
        secrets.forget(job.id)
        self.jobs = [j for j in self.jobs if j.id != job.id]
        jobs.save(self.jobs)
        self.fill_home()
        return True

    def duplicate(self, job: Job | None):
        if job is None:
            return
        j = copy.deepcopy(job)
        j.id = Job("x").id
        j.name = f"{job.name} (copy)"
        j.last = jobs.LastRun()
        self._open_wizard(j, new=True)

    # ================================================================ the wizard
    def add(self):
        self._open_wizard(Job(""), new=True)

    def edit(self, job: Job | None):
        if job is not None and job.id not in self.running:
            self._open_wizard(copy.deepcopy(job), new=False)

    def _open_wizard(self, job: Job, new: bool):
        self.editing, self.editing_new = job, new
        self.w_name.setText(job.name)
        self.w_pass.clear()
        self.w_pass2.clear()
        self.w_show.setChecked(False)
        has = bool(secrets.get(job.id)) and not new
        self.w_pass_note.setText(("Leave the password empty to keep the one saved for this backup. " if has else "")
                                 + "Without it nobody can open the backup, you included: restic has no back door. "
                                   "It's saved in Windows' Credential Manager, never in PR7-BK's files.")
        d = job.destination
        self.w_kind.setCurrentIndex(max(0, self.w_kind.findData(d.kind)))
        self.w_dest["path"].setText(d.path)
        self.w_dest["host"].setText(d.host)
        self.w_dest["port"].setText(str(d.port) if d.port else "")
        self.w_dest["user"].setText(d.user)
        self.w_dest["bucket"].setText(d.bucket)
        self.w_dest["secret"].setText("")
        self.w_dest["secret"].setPlaceholderText("(saved; leave empty to keep)" if secrets.get(job.id, "secret") else "")
        self.w_test.setText("")
        self._dest_fields()
        self.chosen = list(job.sources)
        self.w_filters.clear()
        for p in job.excludes:
            self.w_filters.addTopLevelItem(QTreeWidgetItem([p]))
        self.w_hidden.setChecked(job.skip_hidden)
        self.w_system.setChecked(job.skip_system)
        self.w_temp.setChecked(job.skip_temp)
        self.w_large.setChecked(bool(job.larger_than_gb))
        self.w_large_gb.setValue(job.larger_than_gb or 4)
        self._fill_tree()
        s = job.schedule
        {"none": self.w_sched_none, "hourly": self.w_sched_hourly, "daily": self.w_sched_daily,
         "weekly": self.w_sched_weekly}.get(s.kind, self.w_sched_daily).setChecked(True)
        self.w_every.setValue(s.every)
        from PySide6.QtCore import QTime
        self.w_daily_at.setTime(QTime.fromString(s.at, "HH:mm"))
        self.w_weekly_at.setTime(QTime.fromString(s.at, "HH:mm"))
        self.w_day.setCurrentIndex(max(0, self.w_day.findData(s.day)))
        k = job.keep
        {"all": self.w_keep_all, "last": self.w_keep_last, "smart": self.w_keep_smart}[k.mode].setChecked(True)
        self.w_last.setValue(k.last)
        self.w_daily.setValue(k.daily)
        self.w_weekly.setValue(k.weekly)
        self.w_monthly.setValue(k.monthly)
        self.w_vss.setChecked(job.open_files)
        self.show_page("wizard")
        self.go_step(0)

    def go_step(self, i: int):
        if not (0 <= i < len(STEPS)):
            return
        self.steps.setCurrentIndex(i)
        for n, lab in enumerate(self.step_labels):
            lab.setProperty("state", "now" if n == i else "done" if n < i else "")
            lab.style().unpolish(lab)
            lab.style().polish(lab)
        self.back_button.setEnabled(i > 0)
        self.next_button.setText("SAVE" if i == len(STEPS) - 1 else "NEXT")
        if i == len(STEPS) - 1:
            j = self.wizard_job()
            self.w_summary.setText(f"\u201c{j.name}\u201d backs up {len(j.sources)} folder"
                                   f"{'s' if len(j.sources) != 1 else ''} to {j.destination.text()}, "
                                   f"{j.schedule.text().lower()}; keeps {j.keep.text().lower()}.")
        self._sync()

    def step_problem(self, i: int) -> str:
        if i == 0:
            if not self.w_name.text().strip():
                return "Give the backup a name."
            if any(j.name == self.w_name.text().strip() and j.id != self.editing.id for j in self.jobs):
                return "Another backup has that name."
            has = bool(secrets.get(self.editing.id)) and not self.editing_new
            if not self.w_pass.text() and not has:
                return "Choose a password: restic encrypts the backup with it."
            if self.w_pass.text() != self.w_pass2.text():
                return "The two passwords aren't the same."
        if i == 1:
            k = self.w_kind.currentData()
            need = {"local": ("path",), "sftp": ("host", "path"), "rest": ("host",), "s3": ("host", "bucket", "user"),
                    "b2": ("bucket", "user")}[k]
            if any(not self.w_dest[n].text().strip() for n in need):
                return "Fill in where the backup goes."
            if self.w_dest["port"].text().strip() and not self.w_dest["port"].text().strip().isdigit():
                return "The port is a number."
            if k in ("s3", "b2") and not self.w_dest["secret"].text() and not secrets.get(self.editing.id, "secret"):
                return "The key is needed for this destination."
            if k == "local":
                dest = os.path.abspath(self.w_dest["path"].text().strip())
                for s in self.chosen:
                    if os.path.abspath(s) == dest or dest.startswith(os.path.abspath(s).rstrip("\\/") + os.sep):
                        return "The destination is inside a folder being backed up: choose another place."
        if i == 2 and not self.chosen:
            return "Tick at least one folder to back up."
        return ""

    def next_step(self):
        i = self.steps.currentIndex()
        problem = self.step_problem(i)
        if problem:
            self._say("warning", problem)
            return False
        if i < len(STEPS) - 1:
            self.go_step(i + 1)
            return True
        return self.save_wizard()

    def wizard_job(self) -> Job:
        j = copy.deepcopy(self.editing)
        j.name = self.w_name.text().strip()
        k = self.w_kind.currentData()
        port = self.w_dest["port"].text().strip()
        j.destination = Destination(k, self.w_dest["path"].text().strip(), self.w_dest["host"].text().strip(),
                                    self.w_dest["user"].text().strip(), self.w_dest["bucket"].text().strip(),
                                    int(port) if port.isdigit() else 0)
        j.sources = list(self.chosen)
        j.excludes = [self.w_filters.topLevelItem(i).text(0) for i in range(self.w_filters.topLevelItemCount())]
        j.skip_hidden, j.skip_system, j.skip_temp = (self.w_hidden.isChecked(), self.w_system.isChecked(),
                                                     self.w_temp.isChecked())
        j.larger_than_gb = self.w_large_gb.value() if self.w_large.isChecked() else 0
        kind = ("none" if self.w_sched_none.isChecked() else "hourly" if self.w_sched_hourly.isChecked() else
                "weekly" if self.w_sched_weekly.isChecked() else "daily")
        at = (self.w_weekly_at if kind == "weekly" else self.w_daily_at).time().toString("HH:mm")
        j.schedule = Schedule(kind, at, self.w_every.value(), self.w_day.currentData())
        mode = "all" if self.w_keep_all.isChecked() else "last" if self.w_keep_last.isChecked() else "smart"
        j.keep = Keep(mode, self.w_last.value(), self.w_daily.value(), self.w_weekly.value(), self.w_monthly.value())
        j.open_files = self.w_vss.isChecked()
        return j

    def save_wizard(self) -> bool:
        for i in range(len(STEPS)):
            problem = self.step_problem(i)
            if problem:
                self.go_step(i)
                self._say("warning", problem)
                return False
        j = self.wizard_job()
        if self.w_pass.text():
            secrets.put(j.id, self.w_pass.text())
        if self.w_dest["secret"].text():
            secrets.put(j.id, self.w_dest["secret"].text(), "secret")
        if self.editing_new:
            self.jobs.append(j)
        else:
            self.jobs = [j if x.id == j.id else x for x in self.jobs]
        jobs.save(self.jobs)
        ok, why = schedule.apply(j, self.answers.get("schtasks"))
        if not ok and j.schedule.kind != "none" and why:
            self._say("warning", f"The schedule couldn't be set up in Task Scheduler:\n{why}")
        self.fill_home()
        self.show_page("home")
        if self.editing_new and self._ask("confirm", f"Run \u201c{j.name}\u201d now? The first backup sends "
                                                     "everything; later ones only what changed."):
            self.run_now(j)
        self.editing = None
        return True

    def test_destination(self):
        j = self.wizard_job()
        password = self.w_pass.text() or secrets.get(j.id)
        secret = self.w_dest["secret"].text() or secrets.get(j.id, "secret")
        self.w_test.setText("Testing…")

        def work():
            r = restic.Restic(j, password or "-", secret)
            if j.destination.kind == "local" and not os.path.isdir(j.destination.path):
                return "The folder doesn't exist yet: it will be made on the first run."
            return ("A backup is there and the password opens it: this one adds to it." if r.exists() else
                    "Reachable and empty: a new backup will be made here.")
        self._background("test", work)

    # ---------------------------------------------------------------- the folder tree
    def _fill_tree(self):
        self.w_tree.blockSignals(True)
        self.w_tree.clear()
        roots = list(dict.fromkeys(drives() + [s for s in self.chosen if not any(
            s.startswith(d) for d in drives())]))
        for d in roots:
            self.w_tree.addTopLevelItem(self._folder_item(d, d))
        self.w_tree.blockSignals(False)
        self._refresh_ticks()

    def _folder_item(self, path: str, label: str) -> QTreeWidgetItem:
        it = QTreeWidgetItem([label])
        it.setData(0, PATH_ROLE, path)
        it.setIcon(0, widgets.file_icon("folder", 18))
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(0, Qt.CheckState.Unchecked)
        try:
            if any(e.is_dir() for e in os.scandir(path)):
                it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        except OSError:
            pass
        return it

    def _expand(self, it: QTreeWidgetItem):
        if it.childCount():
            return
        path = it.data(0, PATH_ROLE)
        self.w_tree.blockSignals(True)
        try:
            names = sorted((e.name for e in os.scandir(path) if e.is_dir(follow_symlinks=False)), key=str.casefold)
        except OSError:
            names = []
        for n in names:
            it.addChild(self._folder_item(os.path.join(path, n), n))
        self.w_tree.blockSignals(False)
        self._refresh_ticks()

    def _ticked(self, it: QTreeWidgetItem, col: int):
        path = it.data(0, PATH_ROLE)
        if col != 0 or not path:
            return
        on = it.checkState(0) == Qt.CheckState.Checked
        norm = os.path.normcase(os.path.abspath(path))
        if on:
            self.chosen = [s for s in self.chosen if not os.path.normcase(os.path.abspath(s)).startswith(
                norm.rstrip("\\/") + os.sep)]
            if not self._covered(path):
                self.chosen.append(path)
            self._unexclude(path)
        else:
            if path in self.chosen:
                self.chosen.remove(path)
            elif self._covered(path):            # inside a chosen folder: leave it out with an exclude
                self._add_pattern(path)
        self._refresh_ticks()

    def _covered(self, path: str) -> bool:
        p = os.path.normcase(os.path.abspath(path))
        return any(p == os.path.normcase(os.path.abspath(s)) or p.startswith(
            os.path.normcase(os.path.abspath(s)).rstrip("\\/") + os.sep) for s in self.chosen)

    def _unexclude(self, path: str):
        for i in reversed(range(self.w_filters.topLevelItemCount())):
            if os.path.normcase(self.w_filters.topLevelItem(i).text(0)) == os.path.normcase(path):
                self.w_filters.takeTopLevelItem(i)

    def _refresh_ticks(self):
        excluded = {os.path.normcase(self.w_filters.topLevelItem(i).text(0))
                    for i in range(self.w_filters.topLevelItemCount())}
        self.w_tree.blockSignals(True)

        def walk(it: QTreeWidgetItem):
            path = it.data(0, PATH_ROLE)
            p = os.path.normcase(os.path.abspath(path))
            if p in excluded:
                state = Qt.CheckState.Unchecked
            elif self._covered(path):
                state = Qt.CheckState.Checked
            elif any(os.path.normcase(os.path.abspath(s)).startswith(p.rstrip("\\/") + os.sep) for s in self.chosen):
                state = Qt.CheckState.PartiallyChecked
            else:
                state = Qt.CheckState.Unchecked
            it.setCheckState(0, state)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.w_tree.topLevelItemCount()):
            walk(self.w_tree.topLevelItem(i))
        self.w_tree.blockSignals(False)
        self.w_chosen.clear()
        for s in self.chosen:
            it = QTreeWidgetItem([s])
            it.setIcon(0, widgets.file_icon("folder", 18))
            self.w_chosen.addTopLevelItem(it)

    def _add_folder(self):
        path = self._ask("folder", "")
        if path:
            path = os.path.normpath(path)
            if not self._covered(path):
                self.chosen.append(path)
            self._fill_tree()

    def _add_pattern(self, text: str | None = None):
        pat = (text if isinstance(text, str) else self.w_pattern.text()).strip()
        if not pat:
            return
        existing = {self.w_filters.topLevelItem(i).text(0) for i in range(self.w_filters.topLevelItemCount())}
        if pat not in existing:
            self.w_filters.addTopLevelItem(QTreeWidgetItem([pat]))
        if not isinstance(text, str):
            self.w_pattern.clear()
        self._refresh_ticks()

    def _remove_pattern(self):
        for it in self.w_filters.selectedItems():
            self.w_filters.takeTopLevelItem(self.w_filters.indexOfTopLevelItem(it))
        self._refresh_ticks()

    # ================================================================ restore
    def _engine(self, job: Job) -> restic.Restic:
        return restic.Restic(job, secrets.get(job.id), secrets.get(job.id, "secret"))

    def show_restore(self, job: Job | None):
        if not self.jobs:
            self._say("info", "Add a backup first: there's nothing to restore from yet.")
            return
        job = job or self.jobs[0]
        self.r_job.blockSignals(True)
        self.r_job.clear()
        for j in self.jobs:
            self.r_job.addItem(j.name, j.id)
        self.r_job.setCurrentIndex(max(0, self.r_job.findData(job.id)))
        self.r_job.blockSignals(False)
        self.show_page("restore")
        self._restore_job_changed()

    def _restore_job_changed(self):
        self.restore_job = self.job(self.r_job.currentData())
        self.r_versions.clear()
        self.r_files.clear()
        self.snapshots, self.nodes = [], []
        if self.restore_job is None:
            return
        self.r_note.setText("Reading the versions…")
        job = self.restore_job
        self._background("snapshots", lambda: self._engine(job).snapshots())

    def _version_chosen(self):
        it = self.r_versions.currentItem()
        if it is None or self.restore_job is None:
            return
        snap = self.snapshots[self.r_versions.indexOfTopLevelItem(it)]
        self.r_note.setText("Reading the files…")
        job = self.restore_job
        self._background("ls", lambda: (snap.id, self._engine(job).ls(snap.id)))

    def chosen_version(self) -> restic.Snapshot | None:
        it = self.r_versions.currentItem()
        return self.snapshots[self.r_versions.indexOfTopLevelItem(it)] if it is not None else None

    def _fill_versions(self):
        self.r_versions.clear()
        if not self.snapshots:
            self.r_note.setText("No versions yet: run the backup first.")
            return
        labels = [jobs.when_text(s.time.astimezone().isoformat()) for s in self.snapshots]
        for i, s in enumerate(self.snapshots):
            label = labels[i]
            if labels.count(label) > 1:                       # two in the same minute: tell them apart
                label += s.time.astimezone().strftime(":%S")
            it = QTreeWidgetItem([label,
                                  f"{s.files:,}" if s.files is not None else "",
                                  jobs.size(s.added) if s.added is not None else ""])
            for c in (1, 2):
                it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setToolTip(0, f"{s.time.astimezone():%Y-%m-%d %H:%M:%S}  ·  {s.short}")
            self.r_versions.addTopLevelItem(it)
        self.r_note.setText(f"{len(self.snapshots)} version{'s' if len(self.snapshots) != 1 else ''}")
        self.r_versions.setCurrentItem(self.r_versions.topLevelItem(0))

    def _fill_files(self):
        self.r_files.blockSignals(True)
        self.r_files.clear()
        q = self.r_search.text().strip().casefold()
        items: dict[str, QTreeWidgetItem] = {}
        nodes = self.nodes
        if q:   # a search keeps the matches and the folders leading to them
            keep = set()
            for n in nodes:
                if q in n.name.casefold():
                    p = n.path
                    while p and p != "/":
                        keep.add(p)
                        p = posixpath.dirname(p)
            nodes = [n for n in nodes if n.path in keep]
        snap = self.chosen_version()
        roots = [p.rstrip("/") for p in (snap.paths if snap else [])]
        roots = [restic.snapshot_path(p) if sys.platform == "win32" else p for p in roots]
        for n in nodes:
            parent = items.get(posixpath.dirname(n.path))
            if parent is None and roots and not any(n.path == r or n.path.startswith(r + "/") for r in roots):
                continue                  # the folders above what was backed up (C:\, Users ...): not listed
            label = n.name
            if parent is None:            # a backed-up folder: its whole path, as the mock-up shows it
                label = restic.local_path(n.path) if sys.platform == "win32" else n.path
            when = n.mtime[:16].replace("T", " ") if n.mtime and not n.is_dir else ""
            it = QTreeWidgetItem([label, jobs.size(n.size) if not n.is_dir else "", when])
            it.setData(0, PATH_ROLE, n.path)
            it.setIcon(0, widgets.file_icon("folder" if n.is_dir else "file", 18))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Unchecked)
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            (parent.addChild(it) if parent is not None else self.r_files.addTopLevelItem(it))
            items[n.path] = it
        self.r_files.blockSignals(False)
        if q or len(nodes) < 400:
            self.r_files.expandAll()
        else:
            for i in range(self.r_files.topLevelItemCount()):
                self.r_files.topLevelItem(i).setExpanded(True)
        self._sync()

    def _file_ticked(self, it: QTreeWidgetItem, col: int):
        if col != 0:
            return
        self.r_files.blockSignals(True)
        state = it.checkState(0)
        if state != Qt.CheckState.PartiallyChecked:
            def down(x):
                for i in range(x.childCount()):
                    x.child(i).setCheckState(0, state)
                    down(x.child(i))
            down(it)
        p = it.parent()
        while p is not None:
            kids = [p.child(i).checkState(0) for i in range(p.childCount())]
            p.setCheckState(0, Qt.CheckState.Checked if all(k == Qt.CheckState.Checked for k in kids) else
                            Qt.CheckState.Unchecked if all(k == Qt.CheckState.Unchecked for k in kids) else
                            Qt.CheckState.PartiallyChecked)
            p = p.parent()
        self.r_files.blockSignals(False)
        self._sync()

    def ticked_files(self) -> list[str]:
        """The fewest snapshot paths covering what's ticked: a fully ticked folder is one item."""
        out = []

        def walk(it):
            if it.checkState(0) == Qt.CheckState.Checked:
                out.append(it.data(0, PATH_ROLE))
            elif it.checkState(0) == Qt.CheckState.PartiallyChecked:
                for i in range(it.childCount()):
                    walk(it.child(i))
        for i in range(self.r_files.topLevelItemCount()):
            walk(self.r_files.topLevelItem(i))
        return out

    def restore(self) -> dict | None:
        snap = self.chosen_version()
        items = self.ticked_files()
        if snap is None or not items or self.restore_job is None:
            self._say("info", "Tick the files or folders to restore.")
            return None
        target = None
        if self.r_other.isChecked():
            target = self.r_folder.text().strip()
            if not target:
                self._say("warning", "Choose the folder to restore into.")
                return None
        exists = self.r_exists.currentData()
        job = self.restore_job
        self.r_note.setText("Restoring…")
        self.r_button.setEnabled(False)
        self._background("restore", lambda: self._engine(job).restore(snap, items, target, exists))
        return {"pending": True}

    # ================================================================ background work
    def _background(self, what: str, fn):
        def work():
            try:
                result, error = fn(), None
            except restic.ResticError as e:
                result, error = None, e
            except OSError as e:
                result, error = None, restic.ResticError(str(e))
            self.bridge.loaded.emit(what, result, error)
        if self.sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _loaded(self, what: str, result, error):
        if what == "test":
            self.w_test.setText(result if error is None else (
                "A backup is there, but this password doesn't open it." if error.kind == "password" else str(error)))
            return
        if what == "verify":
            self._say("info" if error is None else "error", "The backup checks out: everything restic needs to restore "
                      "it is there and intact." if error is None else f"Verify found a problem:\n{error}")
            return
        if what == "snapshots":
            if error is not None:
                self.r_note.setText("")
                self._say("error", str(error) if error.kind != "no_repo" else
                          "There's nothing at the destination yet: run the backup first.")
                return
            self.snapshots = result
            self._fill_versions()
            return
        if what == "ls":
            if error is not None:
                self._say("error", str(error))
                return
            snap_id, nodes = result
            cur = self.chosen_version()
            if cur is not None and cur.id == snap_id:
                self.nodes = nodes
                self._fill_files()
                n = sum(1 for x in nodes if not x.is_dir)
                self.r_note.setText(f"{n:,} files in this version")
            return
        if what == "restore":
            self.r_button.setEnabled(True)
            if error is not None:
                self.r_note.setText("")
                self._say("error", f"The restore failed:\n{error}")
                return
            bits = [f"{result['restored']} file{'s' if result['restored'] != 1 else ''} restored"]
            if result["renamed"]:
                bits.append(f"{result['renamed']} kept beside the existing one with the version's date")
            if result["skipped"]:
                bits.append(f"{result['skipped']} skipped (already there)")
            self.r_note.setText(bits[0])
            self.last_restore = result
            self._say("info", ". ".join(bits) + ".")

    # ================================================================ settings
    def options(self) -> bool:
        if "options" in self.answers:
            return self._ask("options")
        d = QDialog(self)
        d.setWindowTitle("Settings")
        form = QFormLayout()
        fin = QComboBox()
        fin.addItem("OBSIDIAN", "obsidian")
        fin.addItem("AURORA", "aurora")
        fin.setCurrentIndex(0 if theme.FINISH == "obsidian" else 1)
        from . import update_ui
        upd = QCheckBox("Check for updates once a day")
        upd.setChecked(update_ui.auto_enabled())
        form.addRow(_field("Finish"), fin)
        form.addRow("", upd)
        v = QVBoxLayout(d)
        v.addLayout(form)
        v.addWidget(_dim(f"restic {restic.version() or '(not found)'}  ·  data in {jobs.data_folder()}"))
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(d.accept)
        b.rejected.connect(d.reject)
        v.addWidget(b)
        if not d.exec():
            return False
        if fin.currentData() != theme.FINISH:
            self.set_finish(fin.currentData())
        update_ui.set_auto(upd.isChecked())
        return True

    def check_updates(self):
        from . import update_ui
        update_ui.check(self, manual=True)

    # ================================================================ status
    def _sync(self):
        page = self.pages.currentIndex()
        if page == 0:
            nxt = [(j.schedule.next_run(dt.datetime.now()), j) for j in self.jobs]
            nxt = sorted((t, j) for t, j in nxt if t is not None) if nxt else []
            text = f"{len(self.jobs)} backup{'s' if len(self.jobs) != 1 else ''}"
            if self.running:
                text += f"  ·  running: {', '.join(self.job(i).name for i in self.running if self.job(i))}"
            elif nxt:
                text += f"  ·  next: {nxt[0][1].name} {jobs.when_text(nxt[0][0].isoformat()).lower()}"
            self.status.setText(text)
        elif page == 1:
            name = self.w_name.text().strip() or "New backup"
            self.status.setText(f"{'ADD' if self.editing_new else 'EDIT'} BACKUP  ·  {name}  ·  step "
                                f"{self.steps.currentIndex() + 1} of {len(STEPS)}")
        else:
            snap = self.chosen_version()
            self.status.setText("RESTORE" + (f"  ·  {self.restore_job.name}" if self.restore_job else "") +
                                (f"  ·  version of {snap.time.astimezone():%a %d %b %H:%M}" if snap else ""))
            n = len(self.ticked_files())
            self.r_button.setText(f"RESTORE {n} ITEM{'S' if n != 1 else ''}" if n else "RESTORE")
        cur = self.current()
        self.keys["run"].setEnabled(bool(cur) and cur.id not in self.running)
        self.keys["stop"].setEnabled(bool(self.running))
        self.keys["restore"].setEnabled(bool(self.jobs))
        self.keys["log"].setEnabled(bool(cur))

    # ================================================================ asking
    def _ask(self, kind: str, payload=None):
        if kind in self.answers:
            a = self.answers[kind]
            return a(payload) if callable(a) else a
        if kind == "confirm":
            return QMessageBox.question(self, "PR7-BK", payload) == QMessageBox.StandardButton.Yes
        if kind == "folder":
            return QFileDialog.getExistingDirectory(self, "Choose a folder", payload or os.path.expanduser("~"))
        if kind == "text":
            text, ok = QInputDialog.getText(self, "PR7-BK", payload)
            return text if ok else None
        return None

    def _say(self, kind: str, text: str):
        self.said.append((kind, text))
        if "say" in self.answers:
            self.answers["say"](kind, text)
            return
        icon = QMessageBox.Icon.Warning if kind in ("error", "warning") else QMessageBox.Icon.Information
        QMessageBox(icon, "PR7-BK", text, parent=self).exec()

    def closeEvent(self, e):
        if self.running and not self._ask("confirm", "A backup is running. Stop it and close PR7-BK?"):
            e.ignore()
            return
        for r in list(self.running.values()):
            r.stop()
        self.clock.stop()
        super().closeEvent(e)
