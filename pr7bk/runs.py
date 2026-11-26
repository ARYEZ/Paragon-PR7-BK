"""One backup run (no Qt), the same for Run now in the window and for Task Scheduler's `PR7-BK.exe --run ID`: the
password from Credential Manager, the destination made the first time, restic's backup and Keep rules, a log in
<data>/logs/<job id>.log, and the result written back to jobs.json (LastRun) so the window shows it."""

from __future__ import annotations

import datetime as dt
import os
import time

from . import jobs, restic, secrets
from .jobs import Job, LastRun


def log_path(job: Job) -> str:
    return os.path.join(jobs.data_folder(), "logs", f"{job.id}.log")


def log(job: Job, text: str):
    os.makedirs(os.path.dirname(log_path(job)), exist_ok=True)
    try:
        if os.path.exists(log_path(job)) and os.path.getsize(log_path(job)) > 2_000_000:   # keep the last ~1 MB
            with open(log_path(job), "rb") as f:
                f.seek(-1_000_000, os.SEEK_END)
                tail = f.read()
            with open(log_path(job), "wb") as f:
                f.write(tail)
        with open(log_path(job), "a", encoding="utf-8") as f:
            for line in text.splitlines() or [""]:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
    except OSError:
        pass


def read_log(job: Job) -> str:
    try:
        with open(log_path(job), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


class Run:
    """A backup run that can be stopped from another thread (Stop)."""

    def __init__(self, job: Job, exe: str | None = None):
        self.job = job
        self.exe = exe
        self.engine: restic.Restic | None = None
        self.stopped = False

    def stop(self):
        self.stopped = True
        if self.engine is not None:
            self.engine.stop()

    def __call__(self, on_progress=None, on_warning=None) -> LastRun:
        job = self.job
        started = dt.datetime.now().astimezone()
        log(job, f"Backup started: {', '.join(job.sources)} -> {job.destination.text()}")
        password = secrets.get(job.id)
        if not password:
            last = LastRun(when=started.isoformat(timespec="seconds"), ok=False,
                           message="No password is saved for this backup (Edit it to enter the password).")
            log(job, last.message)
            jobs.update_last(job.id, last)
            return last
        self.engine = r = restic.Restic(job, password, secrets.get(job.id, "secret"), exe=self.exe)
        try:
            if r.ensure():
                log(job, "A new backup was made at the destination.")
            last = r.backup(on_progress=on_progress,
                            on_warning=lambda w: (log(job, f"Warning: {w}"), on_warning and on_warning(w)))
            log(job, f"Finished in {jobs.duration(last.seconds)}: {last.files_new} new, {last.files_changed} changed, "
                     f"{jobs.size(last.data_added)} added" + (f", {last.warnings} warnings" if last.warnings else ""))
        except restic.ResticError as e:
            if e.kind == "cancelled" or self.stopped:
                r.cancelled.clear()
                r.unlock()                                  # a stopped restic leaves its lock behind
                msg = "Stopped."
            else:
                msg = str(e)
            last = LastRun(when=started.isoformat(timespec="seconds"), ok=False,
                           seconds=round((dt.datetime.now().astimezone() - started).total_seconds(), 1), message=msg)
            log(job, f"Failed: {msg}")
        jobs.update_last(job.id, last)
        return last


def run_by_id(job_id: str) -> int:
    """Task Scheduler's entry: 0 ok, 1 finished with warnings, 2 failed or no such backup."""
    job = next((j for j in jobs.load() if j.id == job_id), None)
    if job is None:
        return 2
    last = Run(job)()
    return 0 if last.ok and not last.warnings else 1 if last.ok else 2
