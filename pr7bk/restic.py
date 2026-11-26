"""restic, the program that does the backing up (no Qt). PR7-BK has no backup code of its own (PR7-Z's rule with 7-Zip):
it runs the official restic, unmodified, and reads its JSON.

    find_restic       PR7BK_RESTIC, the bundled engine\\restic.exe, else PATH (tests on Linux: Ubuntu's restic)
    Restic(job, password, secret)   the environment restic wants: RESTIC_REPOSITORY / RESTIC_PASSWORD (never on the
                      command line, where other programs could read it), the destination's keys, a cache in <data>
    backup            restic backup --json: status lines -> Progress, error lines -> warnings, the summary -> LastRun;
                      exit 3 = a snapshot was made but some files couldn't be read (a warning, as Duplicati says)
    forget            the job's Keep rules (restic forget --prune, only this job's snapshots: its tag)
    snapshots / ls    the versions and a version's files (Windows paths are stored as /C/Users/...)
    restore           into a staging folder first, then each file moved into place by the "if it exists" choice
                      (overwrite / keep both with the version's date / skip): PR7-Z's way of extracting
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import ntpath
import os
import posixpath
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field

from .jobs import Job, LastRun, data_folder

EXIT_OK, EXIT_FATAL, EXIT_PARTIAL, EXIT_NO_REPO, EXIT_LOCKED, EXIT_PASSWORD, EXIT_INTERRUPTED = 0, 1, 3, 10, 11, 12, 130


class ResticError(Exception):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind                         # error / password / no_repo / locked / cancelled / missing


def find_restic() -> str | None:
    env = os.environ.get("PR7BK_RESTIC")
    if env:
        return env if os.path.exists(env) or shutil.which(env) else None
    exe = "restic.exe" if sys.platform == "win32" else "restic"
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (getattr(sys, "_MEIPASS", ""), os.path.join(os.path.dirname(sys.executable), "_internal"),
              os.path.dirname(here)):
        p = os.path.join(d, "engine", exe) if d else ""
        if p and os.path.isfile(p):
            return p
    return shutil.which(exe)


def version(exe: str | None = None) -> str:
    exe = exe or find_restic()
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=30,
                             creationflags=_no_window()).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    bits = out.split()
    return bits[1] if len(bits) > 1 else out.strip()


def _no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ---------------------------------------------------------------- paths inside snapshots
def snapshot_path(path: str, windows: bool | None = None) -> str:
    """C:\\Users\\Ari -> /C/Users/Ari (how restic stores Windows paths); POSIX paths stay."""
    windows = sys.platform == "win32" if windows is None else windows
    if windows:
        drive, rest = ntpath.splitdrive(path)
        return "/" + drive.rstrip(":") + rest.replace("\\", "/").rstrip("/") if drive else path.replace("\\", "/")
    return path.rstrip("/") or "/"


def local_path(snap: str, windows: bool | None = None) -> str:
    windows = sys.platform == "win32" if windows is None else windows
    if windows:
        parts = snap.strip("/").split("/")
        if parts and len(parts[0]) == 1:
            return parts[0] + ":\\" + "\\".join(parts[1:])
        return snap.replace("/", "\\")
    return snap


# ---------------------------------------------------------------- what restic reports
@dataclass
class Progress:
    percent: float = 0.0
    files_done: int = 0
    total_files: int = 0
    bytes_done: int = 0
    total_bytes: int = 0
    seconds_left: int | None = None
    current: str = ""
    phase: str = "Scanning"


@dataclass
class Snapshot:
    id: str
    short: str
    time: dt.datetime
    paths: list
    tags: list = field(default_factory=list)
    files: int | None = None                  # restic 0.17+ keeps a summary in the snapshot
    added: int | None = None

    def label(self) -> str:
        return self.time.astimezone().strftime("%Y-%m-%d %H%M")


@dataclass
class Node:
    path: str                                 # inside the snapshot (/C/Users/...)
    name: str
    is_dir: bool
    size: int = 0
    mtime: str = ""


def parse_time(s: str) -> dt.datetime:
    """restic's times have nanoseconds; Python takes microseconds."""
    s = s.replace("Z", "+00:00")
    if "." in s:
        head, rest = s.split(".", 1)
        digits = "".join(c for c in rest if c.isdigit())
        tz = rest[len(digits):]
        s = f"{head}.{digits[:6].ljust(6, '0')}{tz}"
    return dt.datetime.fromisoformat(s)


class Restic:
    def __init__(self, job: Job, password: str, secret: str = "", exe: str | None = None):
        self.job, self.password, self.secret = job, password, secret
        self.exe = exe or find_restic()
        self.process: subprocess.Popen | None = None
        self.cancelled = threading.Event()

    # ------------------------------------------------------------ the environment
    def repository(self) -> tuple[str, dict]:
        d = self.job.destination
        if d.kind == "local":
            return d.path, {}
        if d.kind == "sftp":
            host = d.host + (f":{d.port}" if d.port else "")
            user = f"{d.user}@" if d.user else ""
            if d.port:
                return f"sftp://{user}{host}/{d.path.lstrip('/')}" if not d.path.startswith("/") else \
                    f"sftp://{user}{host}/{d.path}", {}
            return f"sftp:{user}{d.host}:{d.path}", {}
        if d.kind == "rest":
            env = {"RESTIC_REST_USERNAME": d.user, "RESTIC_REST_PASSWORD": self.secret} if d.user else {}
            return "rest:" + d.host, env
        if d.kind == "s3":
            sub = d.path.strip("/")
            return f"s3:{d.host.rstrip('/')}/{d.bucket}" + (f"/{sub}" if sub else ""), \
                {"AWS_ACCESS_KEY_ID": d.user, "AWS_SECRET_ACCESS_KEY": self.secret}
        if d.kind == "b2":
            return f"b2:{d.bucket}:{d.path.strip('/') or '/'}", {"B2_ACCOUNT_ID": d.user, "B2_ACCOUNT_KEY": self.secret}
        raise ResticError(f"Unknown destination: {d.kind}")

    def env(self) -> dict:
        repo, extra = self.repository()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("RESTIC_", "AWS_", "B2_"))}
        env.update(extra)
        env.update({"RESTIC_REPOSITORY": repo, "RESTIC_PASSWORD": self.password,
                    "RESTIC_CACHE_DIR": os.path.join(data_folder(), "cache"), "RESTIC_PROGRESS_FPS": "2"})
        return env

    # ------------------------------------------------------------ running restic
    def run(self, args: list[str], on_line=None, timeout: float | None = None) -> tuple[int, list[str], str]:
        if not self.exe:
            raise ResticError("restic isn't there (it comes with PR7-BK; reinstall it)", "missing")
        if self.cancelled.is_set():
            raise ResticError("Stopped.", "cancelled")
        self.process = p = subprocess.Popen([self.exe, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            stdin=subprocess.DEVNULL, env=self.env(), creationflags=_no_window())
        err: list[bytes] = []
        t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
        t.start()
        lines = []
        start = time.monotonic()
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            lines.append(line)
            if on_line:
                on_line(line)
            if timeout and time.monotonic() - start > timeout:
                p.kill()
        code = p.wait()
        t.join(5)
        self.process = None
        stderr = b"".join(err).decode("utf-8", "replace")
        if self.cancelled.is_set():
            raise ResticError("Stopped.", "cancelled")
        return code, lines, stderr

    def stop(self):
        """Stop what's running (Stop / closing the window); the repository's stale lock is removed afterwards."""
        self.cancelled.set()
        p = self.process
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    def check_error(self, code: int, stderr: str):
        if code == 0:
            return
        low = stderr.lower()
        if code == EXIT_PASSWORD or "wrong password" in low:
            raise ResticError("The password doesn't open this backup.", "password")
        if code == EXIT_NO_REPO or "is there a repository" in low or "repository does not exist" in low:
            raise ResticError("There's no backup at the destination yet.", "no_repo")
        if code == EXIT_LOCKED or "repository is already locked" in low:
            raise ResticError("Another backup or restore is using this destination right now.", "locked")
        if code == EXIT_INTERRUPTED:
            raise ResticError("Stopped.", "cancelled")
        lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
        msg = next((ln for ln in lines if ln.lower().startswith(("fatal", "error"))), "")
        raise ResticError(msg or (lines[-1] if lines else f"restic stopped with exit code {code}"))

    # ------------------------------------------------------------ the repository
    def exists(self) -> bool:
        code, _lines, err = self.run(["cat", "config"])
        if code == 0:
            return True
        try:
            self.check_error(code, err)
        except ResticError as e:
            if e.kind == "no_repo":
                return False
            raise
        return False

    def init(self):
        code, _lines, err = self.run(["init"])
        self.check_error(code, err)

    def ensure(self) -> bool:
        """Create the repository the first time (Duplicati does it on the first run); True when it was created."""
        if self.job.destination.kind == "local":
            os.makedirs(self.job.destination.path, exist_ok=True)
        if self.exists():
            return False
        self.init()
        return True

    def unlock(self):
        try:
            self.run(["unlock"])
        except ResticError:
            pass

    # ------------------------------------------------------------ backing up
    def backup_args(self, windows: bool | None = None) -> list[str]:
        windows = sys.platform == "win32" if windows is None else windows
        j = self.job
        args = ["backup", "--json", "--tag", j.tag()]
        flag = "--iexclude" if windows else "--exclude"      # Windows names are case-insensitive
        for pat in j.all_excludes():
            args += [flag, pat]
        if j.larger_than_gb:
            args += ["--exclude-larger-than", f"{j.larger_than_gb}G"]
        if j.open_files and windows:
            args.append("--use-fs-snapshot")
        # a folder that isn't there is PR7-BK's own warning (restic 0.20 would warn again)
        return args + ["--", *[p for p in j.sources if os.path.exists(p)]]

    def backup(self, on_progress=None, on_warning=None) -> LastRun:
        start = time.monotonic()
        started = dt.datetime.now().astimezone()
        warnings: list[str] = []
        summary: dict = {}

        def line(text: str):
            try:
                msg = json.loads(text)
            except ValueError:
                return
            kind = msg.get("message_type")
            if kind == "status" and on_progress:
                cur = msg.get("current_files") or []
                on_progress(Progress(float(msg.get("percent_done") or 0) * 100, msg.get("files_done", 0),
                                     msg.get("total_files", 0), msg.get("bytes_done", 0), msg.get("total_bytes", 0),
                                     msg.get("seconds_remaining"), cur[0] if cur else "",
                                     "Backing up" if msg.get("total_files") else "Scanning"))
            elif kind == "error":
                e = msg.get("error") or {}
                text_ = f"{msg.get('item', '')}: {e.get('message', '') if isinstance(e, dict) else e}".strip(": ")
                warnings.append(text_)
                if on_warning:
                    on_warning(text_)
            elif kind == "summary":
                summary.update(msg)
        missing = [s for s in self.job.sources if not os.path.exists(s)]
        if missing and len(missing) == len(self.job.sources):
            raise ResticError("None of the folders to back up are there: " + ", ".join(missing))
        code, _lines, err = self.run(self.backup_args(), on_line=line)
        if code not in (EXIT_OK, EXIT_PARTIAL) or not summary:
            self.check_error(code or EXIT_FATAL, err)
        if code == EXIT_PARTIAL and not warnings:
            warnings.append("Some files couldn't be read.")
        for m in missing:
            warnings.append(f"{m}: not there (skipped)")
        if on_progress:
            on_progress(Progress(100.0, summary.get("total_files_processed", 0), summary.get("total_files_processed", 0),
                                 summary.get("total_bytes_processed", 0), summary.get("total_bytes_processed", 0), 0,
                                 "", "Removing old versions" if self.job.keep.args() else "Done"))
        if self.job.keep.args():
            self.forget()
        return LastRun(when=started.isoformat(timespec="seconds"), ok=True, warnings=len(warnings),
                       seconds=round(time.monotonic() - start, 1), files_new=summary.get("files_new", 0),
                       files_changed=summary.get("files_changed", 0), data_added=summary.get("data_added", 0),
                       total_files=summary.get("total_files_processed", 0),
                       total_bytes=summary.get("total_bytes_processed", 0), snapshot=summary.get("snapshot_id", ""),
                       message="; ".join(warnings[:5]) + (f" (and {len(warnings) - 5} more)" if len(warnings) > 5 else ""))

    def forget_args(self) -> list[str]:
        return ["forget", "--json", "--tag", self.job.tag(), "--group-by", "tags", *self.job.keep.args(), "--prune"]

    def forget(self):
        code, _lines, err = self.run(self.forget_args())
        self.check_error(code, err)

    # ------------------------------------------------------------ versions and files
    def snapshots(self) -> list[Snapshot]:
        code, lines, err = self.run(["snapshots", "--json", "--tag", self.job.tag()])
        self.check_error(code, err)
        try:
            data = json.loads("\n".join(lines) or "[]")
        except ValueError:
            data = []
        out = []
        for s in data or []:
            summ = s.get("summary") or {}
            out.append(Snapshot(s["id"], s.get("short_id", s["id"][:8]), parse_time(s["time"]), s.get("paths", []),
                                s.get("tags") or [], summ.get("total_files_processed"), summ.get("data_added")))
        return sorted(out, key=lambda s: s.time, reverse=True)

    def ls(self, snapshot: str) -> list[Node]:
        code, lines, err = self.run(["ls", "--json", snapshot])
        self.check_error(code, err)
        out = []
        for ln in lines:
            try:
                n = json.loads(ln)
            except ValueError:
                continue
            if n.get("struct_type") == "node" or ("path" in n and "type" in n and "tree" not in n):
                out.append(Node(n["path"], n.get("name", posixpath.basename(n["path"])), n.get("type") == "dir",
                                int(n.get("size") or 0), n.get("mtime", "")))
        return out

    def check(self) -> str:
        code, lines, err = self.run(["check"])
        self.check_error(code, err)
        return "\n".join(lines).strip()

    # ------------------------------------------------------------ restoring
    def restore(self, snap: Snapshot, items: list[str], target: str | None, exists: str = "keepboth",
                windows: bool | None = None, on_line=None) -> dict:
        """items: snapshot paths (files or folders). target None = where they were, else a folder (each item goes in
        by its own name). exists: overwrite / keepboth / skip. Returns {"restored", "skipped", "renamed", "files"}."""
        windows = sys.platform == "win32" if windows is None else windows
        if not items:
            return {"restored": 0, "skipped": 0, "renamed": 0, "files": []}
        if target:
            os.makedirs(target, exist_ok=True)
            stage_root = target
        else:
            # beside where the files go (same drive: the final moves are renames), at the nearest folder that exists;
            # never a drive's root, which ordinary users can't write to
            stage_root = os.path.dirname(local_path(items[0], windows))
            while stage_root and not os.path.isdir(stage_root) and os.path.dirname(stage_root) != stage_root:
                stage_root = os.path.dirname(stage_root)
        stage = os.path.join(stage_root, f".pr7bk-restore-{uuid.uuid4().hex[:8]}")
        try:
            os.makedirs(stage)
        except OSError:
            stage = os.path.join(data_folder(), f"restore-{uuid.uuid4().hex[:8]}")
            os.makedirs(stage)
        args = ["restore", snap.id, "--target", stage]
        for it in items:
            args += ["--include", it]
        try:
            code, _lines, err = self.run(args, on_line=on_line)
            self.check_error(code, err)
            result = {"restored": 0, "skipped": 0, "renamed": 0, "files": []}
            for it in items:
                staged = os.path.join(stage, *[p for p in it.strip("/").split("/") if p])
                if not os.path.exists(staged):
                    continue
                dest = os.path.join(target, posixpath.basename(it.rstrip("/"))) if target else local_path(it, windows)
                self._place(staged, dest, exists, snap, result)
            return result
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _place(self, src: str, dest: str, exists: str, snap: Snapshot, result: dict):
        if os.path.isdir(src) and not os.path.islink(src):
            if os.path.isfile(dest):
                dest = self._both(dest, snap)
            os.makedirs(dest, exist_ok=True)
            for name in os.listdir(src):
                self._place(os.path.join(src, name), os.path.join(dest, name), exists, snap, result)
            return
        if os.path.exists(dest):
            if exists == "skip":
                result["skipped"] += 1
                return
            if exists == "keepboth":
                dest = self._both(dest, snap)
                result["renamed"] += 1
            else:
                os.remove(dest) if os.path.isfile(dest) or os.path.islink(dest) else shutil.rmtree(dest)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        shutil.move(src, dest)
        result["restored"] += 1
        result["files"].append(dest)

    @staticmethod
    def _both(dest: str, snap: Snapshot) -> str:
        """"name (2026-11-24 0300).ext", numbered if that's taken too."""
        stem, ext = os.path.splitext(dest)
        cand = f"{stem} ({snap.label()}){ext}"
        n = 2
        while os.path.exists(cand):
            cand = f"{stem} ({snap.label()} {n}){ext}"
            n += 1
        return cand


def as_dict(last: LastRun) -> dict:
    return dataclasses.asdict(last)
