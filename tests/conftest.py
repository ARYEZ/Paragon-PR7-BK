import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(tempfile.mkdtemp(prefix="family-"), "finish")  # never the real choice
os.environ["PR7BK_DATA"] = tempfile.mkdtemp(prefix="pr7bk-data-")      # never the real data folder
os.environ["PR7BK_MEMORY_KEYRING"] = "1"                               # never the real Credential Manager

needs_restic = pytest.mark.skipif(not (os.environ.get("PR7BK_RESTIC") or shutil.which("restic")
                                       or (ROOT / "engine" / "restic.exe").exists()), reason="no restic here")


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)           # never the real settings
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    from pr7bk import theme
    theme.load_fonts()
    yield app
    app.clipboard().clear()


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A fresh data folder (jobs.json, cache) for each test."""
    d = tmp_path / "data"
    monkeypatch.setenv("PR7BK_DATA", str(d))
    from pr7bk import secrets
    secrets._memory.clear()
    return d


@pytest.fixture
def studio(tmp_path):
    """Folders to back up: projects with a temp file, a node_modules folder and a big file."""
    src = tmp_path / "Studio"
    (src / "Projects" / "titles").mkdir(parents=True)
    (src / "Projects" / "titles" / "elseworld_titles_v6.blend").write_bytes(b"BLENDER" * 1000)
    (src / "Projects" / "titles" / "titles_notes.txt").write_text("credits order\n")
    (src / "Projects" / "~$draft.docx").write_bytes(b"lock")
    (src / "Projects" / "cache.tmp").write_bytes(b"tmp")
    (src / "Projects" / "app" / "node_modules" / "left-pad").mkdir(parents=True)
    (src / "Projects" / "app" / "node_modules" / "left-pad" / "index.js").write_text("pad")
    (src / "Projects" / "app" / "main.py").write_text("print('hi')\n")
    (src / "Assets").mkdir()
    (src / "Assets" / "logo.png").write_bytes(bytes(range(256)) * 40)
    return src


@pytest.fixture
def window(qapp, data, tmp_path):
    from pr7bk.main_window import MainWindow
    w = MainWindow(sync=True)
    w.said = []
    w.tasks = []
    w.answers.update({"say": lambda kind, text: w.said.append((kind, text)), "confirm": False,
                      "schtasks": lambda args: w.tasks.append(args) or (0, ""), "menu": True})
    w.resize(1320, 860)
    w.show()
    yield w
    w.answers["confirm"] = True
    w.close()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def fill_wizard(w, studio, dest, name="Studio projects", password="correct horse", keep_last=None):
    """Walk the five steps as a person would."""
    w.add()
    w.w_name.setText(name)
    w.w_pass.setText(password)
    w.w_pass2.setText(password)
    assert w.next_step()
    w.w_dest["path"].setText(str(dest))
    assert w.next_step()
    w.chosen = [str(studio / "Projects"), str(studio / "Assets")]
    w._refresh_ticks()
    assert w.next_step()
    w.w_sched_daily.setChecked(True)
    assert w.next_step()
    if keep_last:
        w.w_keep_last.setChecked(True)
        w.w_last.setValue(keep_last)
    return w.next_step()



@pytest.fixture(autouse=True)
def windows_schedules(monkeypatch):
    """The shared tests check Windows' Task Scheduler commands (a stand-in schtasks) on any system; tests/test_linux.py
    switches Linux's systemd timers back on."""
    from pr7bk import schedule
    monkeypatch.setattr(schedule, "LINUX", False)
