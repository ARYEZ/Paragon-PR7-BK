"""PR7-BK on Linux (PR7-OS): schedules as systemd user timers (written for real in a stand-in config folder,
systemctl's commands recorded), and the ready-made home backup Paragon Welcome opens."""
import os

import pytest

from pr7bk import schedule
from pr7bk.jobs import Job, Schedule


@pytest.fixture
def linux(monkeypatch, tmp_path):
    monkeypatch.setattr(schedule, "LINUX", True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    calls = []
    return calls, lambda args: calls.append(args) or (0, ""), tmp_path / "config/systemd/user"


def test_a_daily_backup_is_a_user_timer(linux):
    calls, run, units = linux
    job = Job("Home folder", schedule=Schedule("daily", "03:00"))
    ok, _ = schedule.apply(job, run)
    timer = (units / f"pr7bk-{job.id}.timer").read_text()
    service = (units / f"pr7bk-{job.id}.service").read_text()
    assert ok and "OnCalendar=*-*-* 03:00:00" in timer and "Persistent=true" in timer   # missed while off: run at once
    assert f"--run {job.id}" in service and "Type=oneshot" in service
    assert calls == [["systemctl", "--user", "daemon-reload"],
                     ["systemctl", "--user", "enable", "--now", f"pr7bk-{job.id}.timer"]]
    assert schedule.exists(job, run)


@pytest.mark.parametrize("sched, calendar", [(Schedule("hourly", every=6), "*-*-* 00/6:00:00"),
                                             (Schedule("weekly", "21:30", day="SAT"), "Sat *-*-* 21:30:00")])
def test_other_schedules(linux, sched, calendar):
    calls, run, units = linux
    job = Job("x", schedule=sched)
    schedule.apply(job, run)
    assert f"OnCalendar={calendar}" in (units / f"pr7bk-{job.id}.timer").read_text()


def test_no_schedule_and_deleting_remove_the_timer(linux):
    calls, run, units = linux
    job = Job("x", schedule=Schedule("daily", "03:00"))
    schedule.apply(job, run)
    job.schedule = Schedule("none")
    assert schedule.apply(job, run) == (True, "")
    assert not (units / f"pr7bk-{job.id}.timer").exists() and not schedule.exists(job, run)
    assert ["systemctl", "--user", "disable", "--now", f"pr7bk-{job.id}.timer"] in calls


def test_the_ready_made_home_backup(qapp, monkeypatch, tmp_path):
    from pr7bk.main_window import MainWindow
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))        # Path.home() on Windows
    w = MainWindow(sync=True)
    j = w.new_home_backup()
    assert j.sources == [str(tmp_path)] and (j.schedule.kind, j.schedule.at) == ("daily", "03:00")
    assert os.path.join(str(tmp_path), ".cache") in j.excludes
    assert w.pages.currentIndex() == 1 and w.w_name.text() == "Home folder"    # the wizard, ready for drive + password
    w.close()
