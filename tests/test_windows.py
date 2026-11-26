"""What only real Windows can show (CI runs these): the bundled restic, a real Task Scheduler task and the real
Credential Manager, each cleaned up in `finally`."""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only (CI)")


def test_bundled_restic_and_windows_paths(tmp_path, data):
    from pr7bk import restic
    from pr7bk.jobs import Destination, Job
    assert restic.find_restic() and restic.version()
    src = tmp_path / "Src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    j = Job("w", sources=[str(src)], destination=Destination("local", str(tmp_path / "repo")))
    r = restic.Restic(j, "pw")
    r.ensure()
    r.backup()
    snap = r.snapshots()[0]
    paths = [n.path for n in r.ls(snap.id)]
    assert restic.snapshot_path(str(src / "a.txt")) in paths            # /C/Users/... as restic stores it
    (src / "a.txt").write_text("changed")
    res = r.restore(snap, [restic.snapshot_path(str(src / "a.txt"))], None, exists="overwrite")
    assert res["restored"] == 1 and (src / "a.txt").read_text() == "hello"


@pytest.mark.skipif(not os.environ.get("CI"), reason="makes a scheduled task: CI only")
def test_real_scheduled_task():
    from pr7bk import schedule
    from pr7bk.jobs import Job, Schedule
    j = Job("ci", schedule=Schedule("daily", at="04:17"))
    try:
        ok, why = schedule.apply(j)
        assert ok, why
        assert schedule.exists(j)
    finally:
        schedule.remove(j)
    assert not schedule.exists(j)


@pytest.mark.skipif(not os.environ.get("CI"), reason="writes Credential Manager: CI only")
def test_real_credential_manager(monkeypatch):
    from pr7bk import secrets
    monkeypatch.delenv("PR7BK_MEMORY_KEYRING", raising=False)
    try:
        assert secrets.available()
        secrets.put("ci-test-job", "s3cret")
        assert secrets.get("ci-test-job") == "s3cret"
    finally:
        secrets.forget("ci-test-job")
    assert secrets.get("ci-test-job") == ""
