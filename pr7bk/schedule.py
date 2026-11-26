"""Schedules as Windows Task Scheduler tasks (no Qt), so a backup runs even when PR7-BK is closed (Duplicati runs a
service for that; a per-user task needs no administrator rights and no program in the background).

Each job is the task "\\Paragon\\PR7-BK\\<job id>" running `PR7-BK.exe --run <job id>`. schtasks.exe does the work;
`run=` is injectable (tests keep the commands). Only on Windows."""

from __future__ import annotations

import subprocess
import sys

from .jobs import Job

FOLDER = "\\Paragon\\PR7-BK\\"


def task_name(job: Job) -> str:
    return FOLDER + job.id


def command(exe_args: list[str], job: Job) -> str:
    return " ".join(f'"{a}"' if " " in a or not a else a for a in exe_args) + f" --run {job.id}"


def create_args(job: Job, exe_args: list[str]) -> list[str] | None:
    """schtasks /create for the job's schedule (None: no schedule)."""
    s = job.schedule
    base = ["schtasks", "/create", "/f", "/tn", task_name(job), "/tr", command(exe_args, job)]
    if s.kind == "hourly":
        return base + ["/sc", "HOURLY", "/mo", str(max(1, min(23, s.every)))]
    if s.kind == "daily":
        return base + ["/sc", "DAILY", "/st", s.at]
    if s.kind == "weekly":
        return base + ["/sc", "WEEKLY", "/d", s.day, "/st", s.at]
    return None


def _run(args: list[str]) -> tuple[int, str]:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    r = subprocess.run(args, capture_output=True, text=True, timeout=60, creationflags=flags)
    return r.returncode, (r.stdout + r.stderr).strip()


def self_command() -> list[str]:
    """How Task Scheduler starts PR7-BK: the exe, or Python with the package when run from source."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable.replace("python.exe", "pythonw.exe"), "-m", "pr7bk"]


def apply(job: Job, run=None, exe_args: list[str] | None = None) -> tuple[bool, str]:
    """Create, replace or remove the job's task to match its schedule."""
    run = run or _run
    if sys.platform != "win32" and run is _run:
        return False, "Schedules need Windows' Task Scheduler."
    args = create_args(job, exe_args or self_command())
    if args is None:
        remove(job, run)
        return True, ""
    code, out = run(args)
    return code == 0, out


def remove(job: Job, run=None) -> bool:
    run = run or _run
    if sys.platform != "win32" and run is _run:
        return False
    code, _out = run(["schtasks", "/delete", "/f", "/tn", task_name(job)])
    return code == 0


def exists(job: Job, run=None) -> bool:
    run = run or _run
    if sys.platform != "win32" and run is _run:
        return False
    code, _out = run(["schtasks", "/query", "/tn", task_name(job)])
    return code == 0
