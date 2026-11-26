"""Check a real install of PR7-BK-Setup.exe (CI, Windows): verify_install.py installed|uninstalled

`installed`: the files (restic included), the Start menu entry, the uninstall entry, and the installed exe's --selftest:
a real backup with the bundled restic, a second version, Keep rules, a file restored and checked.
`uninstalled`: all of it gone."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-BK"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-BK.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{9C8D5648-E4E9-4E7F-B684-DE9E5D1C1B23}_is1"


def value(root, path, name=""):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-BK.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7bk" / "fonts" / "Inter-Regular.ttf"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(HKCU, UNINSTALL, "DisplayName") == "Paragon PR7-BK", "Installed apps entry", p)
    check((APP / "_internal" / "engine" / "restic.exe").is_file(), "restic is bundled", p)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.json"
        try:
            subprocess.run([str(exe), "--selftest", str(out)], timeout=600, check=False)
        except subprocess.TimeoutExpired:
            pass
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        if "error" in got:
            print(got["error"])
        check(got.get("restored") == "version two\n" and got.get("versions") == 2 and got.get("temp_left_out"),
              f"the installed exe backs up, keeps two versions and restores a file ({got})", p)
        check(str(got.get("restic", "")).startswith("0.20"), f"with the bundled restic ({got.get('restic')})", p)
        r = subprocess.run([str(exe), "--run", "no-such-backup"], timeout=120, check=False)
        check(r.returncode == 2, f"--run of an unknown backup says so (exit {r.returncode})", p)
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-BK.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(HKCU, UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
