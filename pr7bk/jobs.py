"""The backups (no Qt): each `Job` is what Duplicati's five steps set (General, Destination, Source data, Schedule,
Options) plus how its last run went. Kept in <data>/jobs.json (%APPDATA%\\Paragon\\PR7-BK; PR7BK_DATA in tests).
Passwords and destination keys are never in this file: secrets.py keeps them in Windows' Credential Manager."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field

DEST_KINDS = {"local": "Local or network folder", "sftp": "SFTP server", "rest": "REST server (restic's own)",
              "s3": "Amazon S3 or compatible", "b2": "Backblaze B2"}
SCHEDULES = ("none", "hourly", "daily", "weekly")
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
DAY_NAMES = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday", "FRI": "Friday",
             "SAT": "Saturday", "SUN": "Sunday"}
TEMP_PATTERNS = ["*.tmp", "*.temp", "~$*", "Thumbs.db", "desktop.ini", "*.~*"]
SYSTEM_PATTERNS = ["pagefile.sys", "hiberfil.sys", "swapfile.sys", "$RECYCLE.BIN", "System Volume Information"]
HIDDEN_PATTERNS = [".*"]                     # restic can't read Windows' hidden attribute: names starting with a dot


def data_folder() -> str:
    env = os.environ.get("PR7BK_DATA")
    if env:
        return env
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.path.join(os.path.expanduser("~"), ".local",
                                                                                    "share")
    return os.path.join(base or os.path.expanduser("~"), "Paragon", "PR7-BK")


@dataclass
class Destination:
    kind: str = "local"            # DEST_KINDS
    path: str = ""                 # local folder; the path on an SFTP server; the folder inside a bucket
    host: str = ""                 # SFTP / REST host (REST: the whole URL), S3 endpoint
    user: str = ""                 # SFTP / REST user; S3 access key id; B2 account id
    bucket: str = ""
    port: int = 0

    def text(self) -> str:
        k = self.kind
        if k == "local":
            return f"{self.path}  (local or network folder)"
        if k == "sftp":
            return f"sftp:{self.user + '@' if self.user else ''}{self.host}:{self.path}  (SFTP)"
        if k == "rest":
            return f"{self.host}  (REST server)"
        if k == "s3":
            return f"{self.host}/{self.bucket}{('/' + self.path.strip('/')) if self.path.strip('/') else ''}  (S3)"
        if k == "b2":
            return f"B2 bucket {self.bucket}{('/' + self.path.strip('/')) if self.path.strip('/') else ''}  (Backblaze B2)"
        return k


@dataclass
class Schedule:
    kind: str = "daily"            # SCHEDULES
    at: str = "03:00"              # daily / weekly: the time
    every: int = 6                 # hourly: every N hours
    day: str = "SUN"               # weekly

    def text(self) -> str:
        if self.kind == "none":
            return "Only when I click Run now"
        if self.kind == "hourly":
            return "Every hour" if self.every == 1 else f"Every {self.every} hours"
        if self.kind == "daily":
            return f"Every day at {self.at}"
        return f"Every {DAY_NAMES.get(self.day, self.day)} at {self.at}"

    def next_run(self, now: dt.datetime, last: dt.datetime | None = None) -> dt.datetime | None:
        """When Task Scheduler will start it next (Windows' own rules: daily / weekly at a time; hourly from the
        time it was set up, which we approximate from the last run or the next full hour)."""
        if self.kind == "none":
            return None
        if self.kind == "hourly":
            base = last or now.replace(minute=0, second=0, microsecond=0)
            nxt = base + dt.timedelta(hours=max(1, self.every))
            while nxt <= now:
                nxt += dt.timedelta(hours=max(1, self.every))
            return nxt
        h, m = (int(x) for x in self.at.split(":"))
        nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if self.kind == "daily":
            return nxt if nxt > now else nxt + dt.timedelta(days=1)
        target = DAYS.index(self.day) if self.day in DAYS else 6
        nxt += dt.timedelta(days=(target - now.weekday()) % 7)
        return nxt if nxt > now else nxt + dt.timedelta(days=7)


@dataclass
class Keep:
    mode: str = "smart"            # all / last / smart
    last: int = 30
    daily: int = 7
    weekly: int = 4
    monthly: int = 12

    def text(self) -> str:
        if self.mode == "all":
            return "Every version"
        if self.mode == "last":
            return f"Last {self.last} versions"
        bits = [f"daily for {self.daily} days" if self.daily else "", f"weekly for {self.weekly} weeks" if self.weekly
                else "", f"monthly for {self.monthly} months" if self.monthly else ""]
        t = ", ".join(b for b in bits if b)
        return (t[0].upper() + t[1:]) if t else "Every version"

    def args(self) -> list[str]:
        """restic forget's rules; empty = keep everything (no forget run)."""
        if self.mode == "last":
            return ["--keep-last", str(max(1, self.last))]
        if self.mode == "smart":
            out = []
            for flag, n in (("--keep-daily", self.daily), ("--keep-weekly", self.weekly),
                            ("--keep-monthly", self.monthly)):
                if n:
                    out += [flag, str(n)]
            return out or ["--keep-last", "1"]
        return []


@dataclass
class LastRun:
    when: str = ""                 # ISO time
    ok: bool = True
    warnings: int = 0
    seconds: float = 0.0
    files_new: int = 0
    files_changed: int = 0
    data_added: int = 0
    total_files: int = 0
    total_bytes: int = 0
    snapshot: str = ""
    message: str = ""


@dataclass
class Job:
    name: str
    sources: list = field(default_factory=list)
    excludes: list = field(default_factory=list)          # restic patterns (case-insensitive on Windows: --iexclude)
    skip_hidden: bool = False
    skip_system: bool = True
    skip_temp: bool = True
    larger_than_gb: int = 0                               # 0 = no limit
    destination: Destination = field(default_factory=Destination)
    schedule: Schedule = field(default_factory=Schedule)
    keep: Keep = field(default_factory=Keep)
    open_files: bool = False                              # Volume Shadow Copy (restic --use-fs-snapshot; admin)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    last: LastRun = field(default_factory=LastRun)

    def all_excludes(self) -> list[str]:
        out = list(self.excludes)
        if self.skip_temp:
            out += TEMP_PATTERNS
        if self.skip_system:
            out += SYSTEM_PATTERNS
        if self.skip_hidden:
            out += HIDDEN_PATTERNS
        return list(dict.fromkeys(out))

    def tag(self) -> str:
        return f"pr7bk:{self.id}"

    @staticmethod
    def from_dict(d: dict) -> "Job":
        d = dict(d)
        d["destination"] = Destination(**d.get("destination", {}))
        d["schedule"] = Schedule(**d.get("schedule", {}))
        d["keep"] = Keep(**d.get("keep", {}))
        d["last"] = LastRun(**d.get("last", {}))
        known = set(Job.__dataclass_fields__)
        return Job(**{k: v for k, v in d.items() if k in known})


def jobs_path() -> str:
    return os.path.join(data_folder(), "jobs.json")


def load() -> list[Job]:
    try:
        with open(jobs_path(), encoding="utf-8") as f:
            return [Job.from_dict(d) for d in json.load(f).get("jobs", [])]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def save(jobs: list[Job]):
    os.makedirs(data_folder(), exist_ok=True)
    tmp = jobs_path() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "jobs": [asdict(j) for j in jobs]}, f, indent=1)
    os.replace(tmp, jobs_path())


def update_last(job_id: str, last: LastRun):
    """A finished run's result, written back (the scheduled run is a separate process from the window)."""
    jobs = load()
    for j in jobs:
        if j.id == job_id:
            j.last = last
    save(jobs)


def size(n) -> str:
    n = float(n or 0)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{int(n)} bytes" if unit == "bytes" else (f"{n:.0f} {unit}" if n >= 100 else f"{n:.1f} {unit}")
        n /= 1000
    return ""


def duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min" if not s or m >= 10 else f"{m} min {s} s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min"


def when_text(iso: str, now: dt.datetime | None = None) -> str:
    """Duplicati's way: "Today 03:00", "Yesterday 03:00", "Sunday 10:00", else the date."""
    if not iso:
        return ""
    try:
        t = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    now = now or dt.datetime.now(t.tzinfo)
    days = (now.date() - t.date()).days
    hm = t.strftime("%H:%M")
    if days == 0:
        return f"Today {hm}"
    if days == 1:
        return f"Yesterday {hm}"
    if days == -1:
        return f"Tomorrow {hm}"
    if 1 < days < 7 or -7 < days < -1:
        return f"{t.strftime('%A')} {hm}"
    return f"{t.strftime('%a')} {t.day} {t.strftime('%b')} {hm}" if t.year == now.year else t.strftime("%Y-%m-%d %H:%M")
