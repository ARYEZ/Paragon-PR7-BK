"""Mock-up pictures of PR7-BK, drawn offscreen in the family theme (the backups are made up):
QT_SCALE_FACTOR=2 python tools/mockup.py OUT_DIR

1_home.png      The backups (Duplicati's home): each one's source, destination, schedule, last run and versions; one
                running with its progress (OBSIDIAN)
2_add.png       Add backup, step 3 of 5 (General, Destination, Source data, Schedule, Options): folders ticked in a tree,
                filters and exclusions (AURORA)
3_restore.png   Restore: the versions on the left, the chosen version's files ticked on the right, where to put them
                (OBSIDIAN)
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,  # noqa: E402
                               QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from pr7bk import theme, widgets  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/mockup")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setFont(QFont("Inter", 10))


def style():
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())


def dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def toolbar():
    bar = QWidget()
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(16, 10, 16, 6)
    lay.setSpacing(6)
    groups = [[("add", "Add backup"), ("play", "Run now"), ("undo", "Restore")],
              [("stop", "Stop"), ("list", "Log")], [("gear", "Settings")]]
    for i, group in enumerate(groups):
        if i:
            sep = QLabel()
            sep.setFixedSize(1, 40)
            sep.setStyleSheet(f"background: {theme.PANEL_EDGE};")
            lay.addSpacing(8)
            lay.addWidget(sep)
            lay.addSpacing(8)
        for icon, label in group:
            k = widgets.KeyButton(icon, label)
            k.setFixedSize(QSize(100, 62))
            lay.addWidget(k)
    lay.addStretch(1)
    return bar


def status(left, right):
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }}")
    lay = QHBoxLayout(f)
    lay.setContentsMargins(16, 6, 16, 6)
    lay.addWidget(dim(left))
    lay.addStretch(1)
    lay.addWidget(dim(right))
    return f


def window(body, status_bar):
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header("BACKUP"))
    lay.addWidget(toolbar())
    wrap = QWidget()
    wl = QVBoxLayout(wrap)
    wl.setContentsMargins(16, 6, 16, 8)
    wl.addWidget(body)
    lay.addWidget(wrap, 1)
    lay.addWidget(status_bar)
    w.resize(1320, 860)
    return w


def card(title, rows, extra=None):
    f = QFrame()
    f.setObjectName("card")
    f.setStyleSheet(f"QFrame#card {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; "
                    f"border-radius: 8px; }}")
    v = QVBoxLayout(f)
    v.setContentsMargins(14, 10, 14, 12)
    v.setSpacing(6)
    h = QLabel(title)
    h.setProperty("role", "heading")
    v.addWidget(h)
    g = QGridLayout()
    g.setHorizontalSpacing(14)
    g.setVerticalSpacing(4)
    for i, (k, val) in enumerate(rows):
        g.addWidget(field(k), i, 0, Qt.AlignmentFlag.AlignTop)
        lab = QLabel(val)
        lab.setWordWrap(True)
        g.addWidget(lab, i, 1)
    g.setColumnStretch(1, 1)
    v.addLayout(g)
    if extra is not None:
        v.addWidget(extra)
    v.addStretch(1)
    return f


def chips(names, on):
    w = QWidget()
    lay = QGridLayout(w)
    lay.setContentsMargins(0, 6, 0, 0)
    lay.setSpacing(4)
    for i, n in enumerate(names):
        lab = QLabel(n)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lit = n in on
        lab.setStyleSheet(f"QLabel {{ background: {theme.qss_gradient() if lit else theme.BUTTON}; color: "
                          f"{'#FFFFFF' if lit else theme.TEXT_DIM}; border-radius: 4px; padding: 3px 6px; "
                          f"font-size: 10.5px; font-weight: 600; }}")
        lay.addWidget(lab, i // 7, i % 7)
    return w


def shoot(widget, name):
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / name))
    widget.close()


def primary(text):
    b = QPushButton(text)
    b.setStyleSheet(f"QPushButton {{ background: {theme.qss_gradient()}; color: #FFFFFF; border: none; "
                    f"font-weight: 600; padding: 7px 22px; }}")
    return b


def job(name, rows, state=None, progress=None, warn=None):
    f = QFrame()
    f.setObjectName("card")
    f.setStyleSheet(f"QFrame#card {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; "
                    f"border-radius: 8px; }}")
    v = QVBoxLayout(f)
    v.setContentsMargins(16, 12, 16, 14)
    v.setSpacing(6)
    top = QHBoxLayout()
    h = QLabel(name)
    h.setProperty("role", "heading")
    top.addWidget(h)
    top.addStretch(1)
    if state:
        s = QLabel(state)
        s.setProperty("role", "ok")
        top.addWidget(s)
    for t in ("RUN NOW", "RESTORE", "EDIT"):
        b = QPushButton(t)
        top.addWidget(b)
    v.addLayout(top)
    g = QGridLayout()
    g.setHorizontalSpacing(14)
    g.setVerticalSpacing(4)
    for i, (k, val) in enumerate(rows):
        g.addWidget(field(k), i // 2, (i % 2) * 2, Qt.AlignmentFlag.AlignTop)
        lab = QLabel(val)
        lab.setWordWrap(True)
        g.addWidget(lab, i // 2, (i % 2) * 2 + 1)
    g.setColumnStretch(1, 1)
    g.setColumnStretch(3, 1)
    v.addLayout(g)
    if progress is not None:
        bar = QProgressBar()
        bar.setValue(progress)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        v.addWidget(bar)
        v.addWidget(dim("Uploading  ·  1,842 of 2,876 files changed  ·  6.1 GB of 9.4 GB  ·  48 MB/s  ·  about 1 min left"))
    if warn:
        lab = QLabel(warn)
        lab.setStyleSheet("color: #FF7A1A;")
        v.addWidget(lab)
    return f


# ------------------------------------------------------------------ 1: home
theme.set_finish("obsidian")
style()
body = QWidget()
bl = QVBoxLayout(body)
bl.setContentsMargins(0, 0, 0, 0)
bl.setSpacing(10)
bl.addWidget(job("Studio projects", [
    ("Source", "D:\\Studio\\Projects  ·  D:\\Studio\\Assets"), ("Destination", "E:\\Backups\\Studio  (local drive)"),
    ("Schedule", "Every day at 03:00"), ("Keep", "Daily for 7 days, weekly for 4 weeks, monthly for 12 months"),
    ("Last run", "Yesterday 03:00  ·  4 min  ·  ok"), ("Versions", "41  ·  612 GB stored for 1.04 TB of files")],
    state="RUNNING  ·  64 %", progress=64))
bl.addWidget(job("Documents and photos", [
    ("Source", "C:\\Users\\Ari\\Documents  ·  C:\\Users\\Ari\\Pictures"),
    ("Destination", "sftp:nas.local:/backups/documents  (SFTP)"), ("Schedule", "Every 6 hours"),
    ("Keep", "Last 30 versions"), ("Last run", "Today 12:00  ·  38 s  ·  ok  ·  212 files changed, 1.3 GB added"),
    ("Next run", "Today 18:00")]))
bl.addWidget(job("Laptop settings", [
    ("Source", "C:\\Users\\Ari\\AppData\\Roaming\\Paragon"), ("Destination", "B2 bucket ari-backup  (Backblaze B2)"),
    ("Schedule", "Every Sunday at 10:00"), ("Keep", "Last 10 versions"),
    ("Last run", "Sunday 10:00  ·  12 s  ·  2 files couldn't be read"), ("Next run", "Sunday 10:00")],
    warn="Last run finished with warnings: 2 files were open in another program (see LOG)."))
bl.addStretch(1)
shoot(window(body, status("3 backups  ·  next: Documents and photos at 18:00", "Encrypted with AES-256 by restic  ·  "
                          "Windows' Task Scheduler runs them when PR7-BK is closed")), "1_home.png")

# ------------------------------------------------------------------ 2: add backup, source data
theme.set_finish("aurora")
style()
body = QWidget()
bl = QVBoxLayout(body)
bl.setContentsMargins(0, 0, 0, 0)
steps = QHBoxLayout()
for i, name in enumerate(("General", "Destination", "Source data", "Schedule", "Options")):
    lab = QLabel(f"{i + 1}  {name.upper()}")
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lit = i == 2
    done = i < 2
    lab.setStyleSheet(f"QLabel {{ background: {theme.qss_gradient() if lit else theme.BUTTON}; color: "
                      f"{'#FFFFFF' if lit or done else theme.TEXT_DIM}; border-radius: 6px; padding: 8px 18px; "
                      f"font-weight: 600; }}")
    steps.addWidget(lab, 1)
bl.addLayout(steps)
bl.addSpacing(8)
row = QHBoxLayout()
tree = QTreeWidget()
tree.setHeaderLabels(["FOLDER", "SIZE"])
tree.setIconSize(QSize(18, 18))


def node(parent, name, sz, state, kids=()):
    it = QTreeWidgetItem([name, sz])
    it.setIcon(0, widgets.file_icon("folder", 18))
    it.setCheckState(0, state)
    it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(it)
    for k in kids:
        node(it, *k)
    return it


C, U, P = Qt.CheckState.Checked, Qt.CheckState.Unchecked, Qt.CheckState.PartiallyChecked
node(tree, "C:\\  Windows", "1.86 TB", P, [
    ("Users", "212 GB", P, [("Ari", "208 GB", P, [("Desktop", "1.2 GB", C), ("Documents", "41.6 GB", C),
                                                  ("Downloads", "88.0 GB", U), ("Music", "36.4 GB", U),
                                                  ("Pictures", "39.1 GB", C), ("Videos", "1.8 GB", U)])]),
    ("Program Files", "48.2 GB", U)])
node(tree, "D:\\  Studio", "3.64 TB", P, [("Projects", "702 GB", C), ("Assets", "338 GB", C), ("Renders", "1.91 TB", U)])
node(tree, "E:\\  Archive", "7.28 TB", U)
tree.expandAll()
tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
row.addWidget(tree, 3)
side = QFrame()
side.setObjectName("card")
side.setStyleSheet(f"QFrame#card {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; "
                   f"border-radius: 8px; }}")
sl = QVBoxLayout(side)
sl.setContentsMargins(16, 12, 16, 12)
h = QLabel("Filters")
h.setProperty("role", "heading")
sl.addWidget(h)
filt = QTreeWidget()
filt.setHeaderLabels(["RULE", "PATTERN"])
filt.setRootIsDecorated(False)
for rule, pat in (("Exclude", "*.tmp"), ("Exclude", "node_modules\\"), ("Exclude", "~$*"), ("Exclude", "*.blend1"),
                  ("Include", "*.blend")):
    filt.addTopLevelItem(QTreeWidgetItem([rule, pat]))
filt.setFixedHeight(190)
sl.addWidget(filt)
add = QHBoxLayout()
add.addWidget(QLineEdit("*.psd~"))
add.addWidget(QPushButton("ADD"))
sl.addLayout(add)
sl.addSpacing(8)
h = QLabel("Exclude")
h.setProperty("role", "heading")
sl.addWidget(h)
for text, on in (("Hidden files", False), ("System files", True), ("Temporary files", True),
                 ("Files larger than 4 GB", False)):
    c = QCheckBox(text)
    c.setChecked(on)
    sl.addWidget(c)
sl.addStretch(1)
sl.addWidget(dim("Selected: 822 GB in 4 folders  ·  the first backup sends it all; later ones only what changed "
                 "(restic stores each piece once)"))
row.addWidget(side, 2)
bl.addLayout(row, 1)
nav = QHBoxLayout()
nav.addStretch(1)
nav.addWidget(QPushButton("BACK"))
nav.addWidget(primary("NEXT"))
bl.addLayout(nav)
shoot(window(body, status("ADD BACKUP  ·  Studio projects", "Step 3 of 5")), "2_add.png")

# ------------------------------------------------------------------ 3: restore
theme.set_finish("obsidian")
style()
body = QWidget()
bl = QVBoxLayout(body)
bl.setContentsMargins(0, 0, 0, 0)
top = QHBoxLayout()
top.addWidget(field("Backup"))
cb = QComboBox()
cb.addItem("Studio projects")
cb.setFixedWidth(260)
top.addWidget(cb)
top.addSpacing(20)
s = QLineEdit()
s.setPlaceholderText("Search this version")
s.setText("titles")
s.setFixedWidth(300)
top.addWidget(s)
top.addStretch(1)
bl.addLayout(top)
split = QSplitter()
vers = QTreeWidget()
vers.setHeaderLabels(["VERSION", "FILES", "ADDED"])
vers.setRootIsDecorated(False)
for i, (when, files, added) in enumerate((("Today 03:00", "48,212", "1.2 GB"), ("Yesterday 03:00", "48,190", "820 MB"),
                                           ("Mon 24 Nov 03:00", "48,102", "2.4 GB"), ("Sun 23 Nov 03:00", "47,988", "96 MB"),
                                           ("Sun 16 Nov 03:00  ·  weekly", "47,511", "3.1 GB"),
                                           ("Sun 9 Nov 03:00  ·  weekly", "46,870", "5.8 GB"),
                                           ("Sat 1 Nov 03:00  ·  monthly", "45,902", "11.2 GB"),
                                           ("Wed 1 Oct 03:00  ·  monthly", "43,118", "24.0 GB"))):
    it = QTreeWidgetItem([when, files, added])
    for c in (1, 2):
        it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    vers.addTopLevelItem(it)
    if i == 2:
        vers.setCurrentItem(it)
vers.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
files = QTreeWidget()
files.setHeaderLabels(["NAME", "SIZE", "MODIFIED"])
files.setIconSize(QSize(18, 18))
root = QTreeWidgetItem(["D:\\Studio\\Projects\\ELSEWORLD", "", ""])
root.setIcon(0, widgets.file_icon("folder", 18))
root.setCheckState(0, P)
files.addTopLevelItem(root)
for name, sz, when, on in (("titles", "", "", P), ("elseworld_titles_v5.blend", "40.8 MB", "2026-11-22 21:14", U),
                           ("elseworld_titles_v6.blend", "41.2 MB", "2026-11-23 23:51", C),
                           ("titles_font_tests.psd", "212 MB", "2026-11-19 10:02", U),
                           ("titles_notes.txt", "4 KB", "2026-11-23 23:40", C)):
    it = QTreeWidgetItem([name, sz, when])
    it.setIcon(0, widgets.file_icon("folder" if not sz else ("text" if name.endswith(".txt") else "file"), 18))
    it.setCheckState(0, on)
    for c in (1,):
        it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    (root if not sz else root.child(0)).addChild(it)
files.expandAll()
files.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
split.addWidget(vers)
split.addWidget(files)
split.setSizes([560, 720])
bl.addWidget(split, 1)
opts = QHBoxLayout()
opts.addWidget(field("Restore to"))
g1 = QRadioButton("Where they were")
g2 = QRadioButton("Another folder")
g2.setChecked(True)
opts.addWidget(g1)
opts.addWidget(g2)
r = QLineEdit("D:\\Restored\\24 Nov")
r.setMinimumWidth(240)
opts.addWidget(r)
opts.addSpacing(20)
opts.addWidget(field("If a file exists"))
ex = QComboBox()
ex.addItem("Keep both (add the version's date)")
opts.addWidget(ex)
opts.addStretch(1)
opts.addWidget(primary("RESTORE 2 FILES"))
bl.addLayout(opts)
shoot(window(body, status("RESTORE  ·  Studio projects  ·  version of Mon 24 Nov 03:00", "2 files  ·  41.2 MB")),
      "3_restore.png")
print("ok", out)
