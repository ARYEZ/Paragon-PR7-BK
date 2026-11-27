"""Schedules as Windows Task Scheduler tasks (no Qt), so a backup runs even when PR7-BK is closed (Duplicati runs a
service for that; a per-user task needs no administrator rights and no program in the background).

Each job is the task "\\Paragon\\PR7-BK\\<job id>" running `PR7-BK.exe --run <job id>`. schtasks.exe does the work;
`run=` is injectable (tests keep the commands).

On Linux (PR7-OS) the same as a systemd user timer: ~/.config/systemd/user/pr7bk-<job id>.timer + .service running
`pr7-bk --run <job id>`; Persistent=true runs a backup missed while the PC was off as soon as it's on again (no root,
nothing in the background but systemd). `systemctl --user` does the rest."""

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


# ------------------------------------------------------------------------------------------------ Linux: systemd timers
LINUX = sys.platform.startswith("linux")   # the shared tests (Windows' schtasks, a stand-in) set it False


def linux() -> bool:
    return LINUX


def unit_dir() -> str:
    import os
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "systemd", "user")


def unit_name(job: Job) -> str:
    return f"pr7bk-{job.id}"


def on_calendar(job: Job) -> str | None:
    """The schedule in systemd's calendar words (None: no schedule)."""
    s = job.schedule
    days = {"MON": "Mon", "TUE": "Tue", "WED": "Wed", "THU": "Thu", "FRI": "Fri", "SAT": "Sat", "SUN": "Sun"}
    if s.kind == "hourly":
        return f"*-*-* 00/{max(1, min(23, s.every))}:00:00"
    if s.kind == "daily":
        return f"*-*-* {s.at}:00"
    if s.kind == "weekly":
        return f"{days.get(s.day, 'Sun')} *-*-* {s.at}:00"
    return None


def linux_command(job: Job) -> str:
    import shlex
    import shutil
    exe = shutil.which("pr7-bk")
    base = exe if exe else f"{shlex.quote(sys.executable)} -m pr7bk"
    return f"{base} --run {job.id}"


def _linux_apply(job: Job, run) -> tuple[bool, str]:
    import os
    cal = on_calendar(job)
    if cal is None:
        _linux_remove(job, run)
        return True, ""
    os.makedirs(unit_dir(), exist_ok=True)
    name = unit_name(job)
    with open(os.path.join(unit_dir(), name + ".service"), "w", encoding="utf-8") as f:
        f.write(f"[Unit]\nDescription=Paragon PR7-BK backup: {job.name}\n\n[Service]\nType=oneshot\n"
                f"ExecStart={linux_command(job)}\n")
    with open(os.path.join(unit_dir(), name + ".timer"), "w", encoding="utf-8") as f:
        f.write(f"[Unit]\nDescription=Paragon PR7-BK backup: {job.name} ({job.schedule.text()})\n\n[Timer]\n"
                f"OnCalendar={cal}\nPersistent=true\nRandomizedDelaySec=60\n\n[Install]\nWantedBy=timers.target\n")
    run(["systemctl", "--user", "daemon-reload"])
    code, out = run(["systemctl", "--user", "enable", "--now", name + ".timer"])
    return code == 0, out


def _linux_remove(job: Job, run) -> bool:
    import os
    name = unit_name(job)
    had = os.path.exists(os.path.join(unit_dir(), name + ".timer"))
    run(["systemctl", "--user", "disable", "--now", name + ".timer"])
    for ext in (".timer", ".service"):
        try:
            os.remove(os.path.join(unit_dir(), name + ext))
        except OSError:
            pass
    run(["systemctl", "--user", "daemon-reload"])
    return had


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
    if linux():
        return _linux_apply(job, run)
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
    if linux():
        return _linux_remove(job, run)
    if sys.platform != "win32" and run is _run:
        return False
    code, _out = run(["schtasks", "/delete", "/f", "/tn", task_name(job)])
    return code == 0


def exists(job: Job, run=None) -> bool:
    run = run or _run
    if linux():
        import os
        return os.path.exists(os.path.join(unit_dir(), unit_name(job) + ".timer"))
    if sys.platform != "win32" and run is _run:
        return False
    code, _out = run(["schtasks", "/query", "/tn", task_name(job)])
    return code == 0
