import datetime as dt
import os

import pytest

from conftest import needs_restic
from pr7bk import jobs, restic, schedule
from pr7bk.jobs import Destination, Job, Keep, Schedule


def make_job(studio, tmp_path, **kw):
    j = Job("Studio projects", sources=[str(studio / "Projects"), str(studio / "Assets")],
            excludes=["node_modules"], destination=Destination("local", str(tmp_path / "backups")), **kw)
    return j


def test_texts_and_rules():
    assert Schedule("daily", at="03:00").text() == "Every day at 03:00"
    assert Schedule("hourly", every=6).text() == "Every 6 hours" and Schedule("none").text().startswith("Only when")
    assert Schedule("weekly", day="SUN", at="10:00").text() == "Every Sunday at 10:00"
    assert Keep("smart", daily=7, weekly=4, monthly=12).text() == "Daily for 7 days, weekly for 4 weeks, monthly for 12 months"
    assert Keep("smart").args() == ["--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "12"]
    assert Keep("last", last=30).args() == ["--keep-last", "30"] and Keep("all").args() == []
    now = dt.datetime(2026, 11, 26, 14, 0)                       # a Thursday
    assert Schedule("daily", at="03:00").next_run(now) == dt.datetime(2026, 11, 27, 3, 0)
    assert Schedule("daily", at="18:00").next_run(now) == dt.datetime(2026, 11, 26, 18, 0)
    assert Schedule("weekly", day="SUN", at="10:00").next_run(now) == dt.datetime(2026, 11, 29, 10, 0)
    assert Schedule("hourly", every=6).next_run(now, dt.datetime(2026, 11, 26, 12, 0)) == dt.datetime(2026, 11, 26, 18, 0)
    assert jobs.when_text("2026-11-26T03:00:00", now) == "Today 03:00"
    assert jobs.when_text("2026-11-25T03:00:00", now) == "Yesterday 03:00"
    assert jobs.when_text("2026-11-22T10:00:00", now) == "Sunday 10:00"
    assert jobs.size(1_300_000_000) == "1.3 GB" and jobs.duration(38) == "38 s" and jobs.duration(250) == "4 min 10 s"


def test_destinations():
    d = Destination("sftp", "/backups/documents", "nas.local", "ari")
    j = Job("x", destination=d)
    assert restic.Restic(j, "pw").repository() == ("sftp:ari@nas.local:/backups/documents", {})
    d.port = 2222
    assert restic.Restic(j, "pw").repository()[0] == "sftp://ari@nas.local:2222//backups/documents"
    j.destination = Destination("b2", "studio", user="0012ab", bucket="ari-backup")
    repo, env = restic.Restic(j, "pw", "k3y").repository()
    assert repo == "b2:ari-backup:studio" and env == {"B2_ACCOUNT_ID": "0012ab", "B2_ACCOUNT_KEY": "k3y"}
    j.destination = Destination("s3", "", "s3.eu-central-1.amazonaws.com", "AKIA", "bucket1")
    assert restic.Restic(j, "pw", "s").repository()[0] == "s3:s3.eu-central-1.amazonaws.com/bucket1"
    j.destination = Destination("rest", host="https://backup.local:8000/ari", user="ari")
    repo, env = restic.Restic(j, "pw", "rest-pw").repository()
    assert repo == "rest:https://backup.local:8000/ari" and env["RESTIC_REST_PASSWORD"] == "rest-pw"
    e = restic.Restic(j, "s3cret", "rest-pw").env()
    assert e["RESTIC_PASSWORD"] == "s3cret" and e["RESTIC_CACHE_DIR"].endswith("cache")


def test_backup_args_and_paths(studio, tmp_path):
    j = make_job(studio, tmp_path, larger_than_gb=4, open_files=True)
    r = restic.Restic(j, "pw")
    win = r.backup_args(windows=True)
    assert win[:4] == ["backup", "--json", "--tag", j.tag()]
    assert ["--iexclude", "node_modules"] == win[4:6] and ["--iexclude", "*.tmp"] in [win[i:i + 2] for i in range(len(win))]
    assert "--use-fs-snapshot" in win and win[win.index("--exclude-larger-than") + 1] == "4G"
    assert win[-3:] == ["--", str(studio / "Projects"), str(studio / "Assets")]
    assert "--use-fs-snapshot" not in r.backup_args(windows=False) and "--exclude" in r.backup_args(windows=False)
    assert restic.snapshot_path("C:\\Users\\Ari\\Documents", windows=True) == "/C/Users/Ari/Documents"
    assert restic.local_path("/C/Users/Ari/a.txt", windows=True) == "C:\\Users\\Ari\\a.txt"
    assert restic.parse_time("2026-11-26T00:51:10.130408426Z").microsecond == 130408


def test_jobs_file_keeps_no_secrets(data, studio, tmp_path):
    from pr7bk import secrets
    j = make_job(studio, tmp_path)
    secrets.put(j.id, "correct horse")
    jobs.save([j])
    text = open(jobs.jobs_path()).read()
    assert "correct horse" not in text and j.id in text
    back = jobs.load()[0]
    assert back.name == "Studio projects" and back.destination.path == str(tmp_path / "backups")
    assert back.keep.mode == "smart" and back.schedule.at == "03:00" and secrets.get(j.id) == "correct horse"


def test_schedule_commands():
    j = Job("x", schedule=Schedule("weekly", day="SUN", at="10:00"))
    kept = []
    ok, _ = schedule.apply(j, run=lambda a: kept.append(a) or (0, ""), exe_args=["C:\\Program Files\\PR7-BK\\PR7-BK.exe"])
    assert ok and kept[0][:5] == ["schtasks", "/create", "/f", "/tn", f"\\Paragon\\PR7-BK\\{j.id}"]
    assert kept[0][6] == f'"C:\\Program Files\\PR7-BK\\PR7-BK.exe" --run {j.id}'
    assert kept[0][7:] == ["/sc", "WEEKLY", "/d", "SUN", "/st", "10:00"]
    j.schedule = Schedule("hourly", every=6)
    assert schedule.create_args(j, ["x.exe"])[-4:] == ["/sc", "HOURLY", "/mo", "6"]
    j.schedule = Schedule("none")
    kept.clear()
    schedule.apply(j, run=lambda a: kept.append(a) or (0, ""))
    assert kept == [["schtasks", "/delete", "/f", "/tn", f"\\Paragon\\PR7-BK\\{j.id}"]]


@needs_restic
def test_backup_versions_and_restore(data, studio, tmp_path):
    j = make_job(studio, tmp_path, keep=Keep("last", last=2))
    r = restic.Restic(j, "correct horse")
    assert r.ensure() and not r.ensure()                         # created the first time only
    seen = []
    last = r.backup(on_progress=seen.append)
    assert last.ok and last.files_new == 4 and last.snapshot and seen and seen[-1].percent == 100
    # what was left out: temp files, Office lock files, node_modules
    snaps = r.snapshots()
    assert len(snaps) == 1 and snaps[0].tags == [j.tag()]
    names = {n.name for n in r.ls(snaps[0].id)}
    assert {"elseworld_titles_v6.blend", "titles_notes.txt", "main.py", "logo.png"} <= names
    assert not names & {"cache.tmp", "~$draft.docx", "node_modules", "index.js"}
    # a change, two more runs: only the last two versions are kept (Keep: last 2)
    (studio / "Projects" / "titles" / "titles_notes.txt").write_text("credits order v2\n")
    second = r.backup()
    assert second.files_changed == 1 and second.files_new == 0
    r.backup()
    assert len(r.snapshots()) == 2
    # restore the first kept version's notes to another folder, then where they were (keep both / overwrite / skip)
    old = r.snapshots()[-1]
    notes = next(n.path for n in r.ls(old.id) if n.name == "titles_notes.txt")
    out = tmp_path / "Restored"
    res = r.restore(old, [notes], str(out), windows=False)
    assert res["restored"] == 1 and (out / "titles_notes.txt").read_text() == "credits order v2\n"
    folder = next(n.path for n in r.ls(old.id) if n.name == "titles" and n.is_dir)
    (studio / "Projects" / "titles" / "titles_notes.txt").write_text("edited since\n")
    res = r.restore(old, [folder], None, exists="keepboth", windows=False)
    assert res["renamed"] == 2 and (studio / "Projects" / "titles" / "titles_notes.txt").read_text() == "edited since\n"
    kept = [p for p in os.listdir(studio / "Projects" / "titles") if p.startswith("titles_notes (")]
    assert len(kept) == 1 and open(studio / "Projects" / "titles" / kept[0]).read() == "credits order v2\n"
    res = r.restore(old, [notes], None, exists="overwrite", windows=False)
    assert res["restored"] == 1 and (studio / "Projects" / "titles" / "titles_notes.txt").read_text() == "credits order v2\n"
    assert r.restore(old, [notes], None, exists="skip", windows=False)["skipped"] == 1
    assert not [p for p in os.listdir(studio / "Projects") if p.startswith(".pr7bk-restore")]      # staging gone


@needs_restic
def test_wrong_password_missing_and_partial(data, studio, tmp_path):
    j = make_job(studio, tmp_path)
    restic.Restic(j, "right").ensure()
    with pytest.raises(restic.ResticError) as e:
        restic.Restic(j, "wrong").snapshots()
    assert e.value.kind == "password"
    other = make_job(studio, tmp_path)
    other.destination = Destination("local", str(tmp_path / "nothing-here"))
    assert not restic.Restic(other, "pw").exists()
    j.sources.append(str(studio / "Gone"))                       # one source missing: a warning, not a failure
    last = restic.Restic(j, "right").backup()
    assert last.warnings == 1 and "Gone" in last.message
    j.sources = [str(studio / "Gone")]
    with pytest.raises(restic.ResticError):
        restic.Restic(j, "right").backup()


@needs_restic
def test_two_jobs_share_a_destination(data, studio, tmp_path):
    a = make_job(studio, tmp_path, keep=Keep("last", last=1))
    b = make_job(studio, tmp_path, keep=Keep("last", last=1))
    b.sources = [str(studio / "Assets")]
    restic.Restic(a, "pw").ensure()
    for _ in range(2):
        restic.Restic(a, "pw").backup()
        restic.Restic(b, "pw").backup()
    assert len(restic.Restic(a, "pw").snapshots()) == 1 and len(restic.Restic(b, "pw").snapshots()) == 1   # by tag


@needs_restic
def test_stop(data, studio, tmp_path):
    import threading
    j = make_job(studio, tmp_path)
    r = restic.Restic(j, "pw")
    r.ensure()
    r.stop()
    with pytest.raises(restic.ResticError) as e:
        r.backup()
    assert e.value.kind == "cancelled"
    assert restic.version()
    threading.Thread(target=lambda: None).start()
