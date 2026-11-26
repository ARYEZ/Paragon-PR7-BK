import json
import os
import subprocess
import sys

from PySide6.QtCore import Qt

from conftest import fill_wizard, needs_restic
from pr7bk import __version__, jobs, secrets


def test_empty_home_and_wizard_checks(window, studio, tmp_path):
    assert window.empty.isVisible() and window.status.text().startswith("0 backups")
    window.add()
    assert window.pages.currentIndex() == 1 and window.next_button.text() == "NEXT"
    assert not window.next_step() and window.said[-1] == ("warning", "Give the backup a name.")
    window.w_name.setText("Studio projects")
    window.w_pass.setText("a")
    window.w_pass2.setText("b")
    assert not window.next_step() and "aren't the same" in window.said[-1][1]
    window.w_pass2.setText("a")
    assert window.next_step() and window.steps.currentIndex() == 1
    assert not window.next_step()                                 # no destination yet
    window.w_kind.setCurrentIndex(window.w_kind.findData("b2"))
    assert window.w_dest["bucket"].isVisibleTo(window) and not window.w_browse.isVisibleTo(window)
    window.w_dest["bucket"].setText("ari-backup")
    window.w_dest["user"].setText("0012ab")
    assert not window.next_step() and "key" in window.said[-1][1]   # B2 needs its key
    window.w_kind.setCurrentIndex(window.w_kind.findData("local"))
    window.w_dest["path"].setText(str(studio / "Projects" / "backup"))
    window.chosen = [str(studio / "Projects")]
    assert not window.next_step() and "inside a folder being backed up" in window.said[-1][1]
    window.grab()


def test_add_backup_saves_job_schedule_and_password(window, studio, tmp_path):
    assert fill_wizard(window, studio, tmp_path / "backups")
    assert window.pages.currentIndex() == 0 and len(window.jobs) == 1
    j = jobs.load()[0]
    assert j.name == "Studio projects" and j.sources == [str(studio / "Projects"), str(studio / "Assets")]
    assert j.schedule.kind == "daily" and j.keep.mode == "smart" and secrets.get(j.id) == "correct horse"
    assert "correct horse" not in open(jobs.jobs_path()).read()
    assert window.tasks[-1][:5] == ["schtasks", "/create", "/f", "/tn", f"\\Paragon\\PR7-BK\\{j.id}"]
    card = window.cards[j.id]
    assert card.values["Schedule"].text() == "Every day at 03:00" and card.values["Last run"].text() == "Never"
    assert window.status.text().startswith("1 backup  ·  next: Studio projects")
    window.grab()


def test_source_tree_ticks_and_excludes(window, studio, tmp_path):
    window.add()
    window.chosen = [str(studio)]
    window._fill_tree()
    window.w_tree.blockSignals(True)
    root = window._folder_item(str(studio), "Studio")
    window.w_tree.addTopLevelItem(root)
    window.w_tree.blockSignals(False)
    window._expand(root)
    assert root.checkState(0) == Qt.CheckState.Checked
    proj = next(root.child(i) for i in range(root.childCount()) if root.child(i).text(0) == "Projects")
    proj.setCheckState(0, Qt.CheckState.Unchecked)                # inside a chosen folder: an exclude
    assert str(studio / "Projects") in [window.w_filters.topLevelItem(i).text(0)
                                        for i in range(window.w_filters.topLevelItemCount())]
    proj.setCheckState(0, Qt.CheckState.Checked)                  # and back
    assert window.w_filters.topLevelItemCount() == 0
    root.setCheckState(0, Qt.CheckState.Unchecked)
    assert window.chosen == []
    proj.setCheckState(0, Qt.CheckState.Checked)
    assert window.chosen == [str(studio / "Projects")] and root.checkState(0) == Qt.CheckState.PartiallyChecked
    window.w_pattern.setText("*.psd~")
    window._add_pattern()
    assert window.w_filters.topLevelItem(0).text(0) == "*.psd~"


def test_edit_and_delete(window, studio, tmp_path):
    fill_wizard(window, studio, tmp_path / "backups")
    j = window.jobs[0]
    window.edit(j)
    assert window.w_name.text() == "Studio projects" and window.w_pass.text() == ""
    assert "Leave the password empty" in window.w_pass_note.text()
    window.w_name.setText("Studio")
    for _ in range(3):
        window.next_step()
    window.w_sched_weekly.setChecked(True)
    window.w_day.setCurrentIndex(window.w_day.findData("SUN"))
    window.next_step()
    assert window.next_step()                                     # saved, password kept
    j = jobs.load()[0]
    assert j.name == "Studio" and j.schedule.kind == "weekly" and secrets.get(j.id) == "correct horse"
    assert window.tasks[-1][-6:-2] == ["/sc", "WEEKLY", "/d", "SUN"]
    assert not window.delete(window.jobs[0])                      # said no
    window.answers["confirm"] = True
    assert window.delete(window.jobs[0]) and jobs.load() == [] and secrets.get(j.id) == ""
    assert window.tasks[-1] == ["schtasks", "/delete", "/f", "/tn", f"\\Paragon\\PR7-BK\\{j.id}"]
    assert window.empty.isVisible()


@needs_restic
def test_run_restore_and_log(window, studio, tmp_path):
    fill_wizard(window, studio, tmp_path / "backups", keep_last=5)
    j = window.jobs[0]
    assert window.run_now(j) and not window.running
    assert j.last.ok and j.last.files_new == 5            # node_modules included: no filter set here
    assert window.cards[j.id].values["Last run"].text().startswith("Today")
    (studio / "Projects" / "titles" / "titles_notes.txt").write_text("credits order v2\n")
    window.run_now(j)
    assert jobs.load()[0].last.files_changed == 1                  # written back for the scheduled runs too
    window.show_restore(j)
    assert window.r_versions.topLevelItemCount() == 2
    window.r_versions.setCurrentItem(window.r_versions.topLevelItem(1))       # the first version
    item = window.r_files.findItems("titles_notes.txt", Qt.MatchFlag.MatchRecursive)[0]
    item.setCheckState(0, Qt.CheckState.Checked)
    assert item.parent().checkState(0) == Qt.CheckState.PartiallyChecked
    assert window.r_button.text() == "RESTORE 1 ITEM"
    window.answers["confirm"] = True
    window.r_original.setChecked(True)
    window.r_exists.setCurrentIndex(window.r_exists.findData("overwrite"))
    window.restore()
    assert (studio / "Projects" / "titles" / "titles_notes.txt").read_text() == "credits order\n"   # the old one back
    assert window.said[-1] == ("info", "1 file restored.")
    window.r_search.setText("logo")
    assert window.r_files.findItems("logo.png", Qt.MatchFlag.MatchRecursive)
    assert not window.r_files.findItems("main.py", Qt.MatchFlag.MatchRecursive)
    window.grab()
    shown = []
    window.answers["log"] = shown.append
    window.show_log(j)
    assert "Backup started" in shown[0] and "Finished in" in shown[0]


@needs_restic
def test_wrong_password_shows_on_the_card(window, studio, tmp_path):
    fill_wizard(window, studio, tmp_path / "backups")
    j = window.jobs[0]
    window.run_now(j)
    secrets.put(j.id, "not it")
    window.run_now(j)
    assert not j.last.ok and "password" in j.last.message
    assert window.cards[j.id].warn.text().startswith("Last run failed")


def test_scheduled_run_entry(data, studio, tmp_path):
    from pr7bk import runs
    assert runs.run_by_id("nope") == 2


def test_selftest(tmp_path):
    out = tmp_path / "self.json"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-m", "pr7bk", "--selftest", str(out)], cwd=root, capture_output=True,
                       text=True, timeout=300)
    got = json.loads(out.read_text())
    if "error" in got and "restic isn't there" in got["error"]:
        return                                                     # no restic on this machine
    assert r.returncode == 0, (got, r.stderr)
    assert got["version"] == __version__ and got["restored"] == "version two\n" and got["versions"] == 2
    assert got["temp_left_out"] and got["fonts"]


def test_second_start_hands_over():
    code = ("import sys, os; sys.path.insert(0, sys.argv[1]); os.environ['QT_QPA_PLATFORM']='offscreen';"
            "from PySide6.QtWidgets import QApplication; a = QApplication([]);"
            "from pr7bk import app; print(app.hand_over())")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-c", code, root], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "False"


def test_family_list_is_whole():
    """Every family app once, every AppId once, this app included (PR7-HW's slip must not come back)."""
    from pr7bk import family
    assert len(set(family.APPS)) == len(family.APPS) and len(set(family.APPS.values())) == len(family.APPS)
    assert {"PR7-Z", "PR7-LN", "PR7-HW", "PR7-BK"} <= set(family.APPS)
