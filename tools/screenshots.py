"""Screenshots of the real PR7-BK window with real backups made by restic, offscreen:
QT_SCALE_FACTOR=2 python tools/screenshots.py OUT_DIR

home.png            three backups: one just run, one never run, one whose last run failed (OBSIDIAN)
add_aurora.png      Add backup, step 3 (source data) (AURORA)
restore.png         Restore: the versions and a version's files, two ticked (OBSIDIAN)
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PR7BK_DATA"] = str(tmp / "data")
os.environ["PR7BK_MEMORY_KEYRING"] = "1"
os.environ["PARAGON_FAMILY_FILE"] = str(tmp / "finish")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp / "settings"))

from pr7bk import jobs, secrets, theme  # noqa: E402
from pr7bk.jobs import Destination, Job, Keep, LastRun, Schedule  # noqa: E402
from pr7bk.main_window import MainWindow  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setFont(QFont("Inter", 10))
studio = tmp / "Studio"
for rel, text in (("Projects/ELSEWORLD/titles/elseworld_titles_v6.blend", "x" * 4000),
                  ("Projects/ELSEWORLD/titles/titles_notes.txt", "credits\n"),
                  ("Projects/ELSEWORLD/titles/titles_font_tests.psd", "y" * 9000),
                  ("Projects/ELSEWORLD/edit/cut_v12.prproj", "z" * 3000), ("Assets/logo.png", "p" * 2000)):
    p = studio / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
a = Job("Studio projects", sources=[str(studio / "Projects"), str(studio / "Assets")],
        excludes=["node_modules", "*.blend1"], destination=Destination("local", str(tmp / "Backups" / "Studio")),
        keep=Keep("smart", 0, 7, 4, 12))
b = Job("Documents and photos", sources=["C:\\Users\\Ari\\Documents", "C:\\Users\\Ari\\Pictures"],
        destination=Destination("sftp", "/backups/documents", "nas.local", "ari"), schedule=Schedule("hourly", every=6),
        keep=Keep("last", 30))
c = Job("Laptop settings", sources=["C:\\Users\\Ari\\AppData\\Roaming\\Paragon"],
        destination=Destination("b2", "laptop", user="0012ab", bucket="ari-backup"),
        schedule=Schedule("weekly", day="SUN", at="10:00"), keep=Keep("last", 10))
c.last = LastRun(when="2026-11-23T10:00:04+00:00", ok=False, seconds=3.2,
                 message="Fatal: unable to open B2 bucket: the application key isn't valid any more.")
for j in (a, b, c):
    secrets.put(j.id, "correct horse battery")
jobs.save([a, b, c])
w = MainWindow(sync=True)
w.answers.update({"say": lambda k, t: None, "confirm": False, "schtasks": lambda args: (0, "")})
w.resize(1320, 860)
w.show()
w.run_now(w.jobs[0])
(studio / "Projects" / "ELSEWORLD" / "titles" / "titles_notes.txt").write_text("credits, final order\n")
w.run_now(w.jobs[0])


def shoot(name):
    app.processEvents()
    w.grab().save(str(out / name))


w.set_finish("obsidian")
w.show_page("home")
shoot("home.png")
w.set_finish("aurora")
w.edit(w.jobs[0])
w.go_step(2)
shoot("add_aurora.png")
w.set_finish("obsidian")
w.show_restore(w.jobs[0])
w.r_versions.setCurrentItem(w.r_versions.topLevelItem(1))
for name in ("titles_notes.txt", "elseworld_titles_v6.blend"):
    w.r_files.findItems(name, Qt.MatchFlag.MatchRecursive)[0].setCheckState(0, Qt.CheckState.Checked)
w.r_other.setChecked(True)
w.r_folder.setText("D:\\Restored\\24 Nov")
shoot("restore.png")
w.answers["confirm"] = True
w.close()
print("ok", out)
