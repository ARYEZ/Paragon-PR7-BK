"""Start PR7-BK.

    PR7-BK.exe                    the window (one per user: a second start brings the first to the front)
    PR7-BK.exe --run ID           run one backup with no window (Windows' Task Scheduler starts this); exit 0 ok,
                                  1 finished with warnings, 2 failed
    PR7-BK.exe --new-home-backup  open the wizard with your home folder, every day (PR7-OS's Welcome: Back up to a drive)
    PR7-BK.exe --unregister       remove every backup's scheduled task (the uninstaller); backups themselves stay
    PR7-BK.exe --version
    PR7-BK.exe --selftest OUT.json   a real backup with the bundled restic offscreen: folders backed up through the
                                     real window, a change, a second version, a file restored and checked byte for
                                     byte, Keep rules applied (CI checks the installed exe)
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys

TIMEOUT_MS = 1500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "Paragon-PR7-BK-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def hand_over() -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(server_name())
    if not s.waitForConnected(TIMEOUT_MS):
        return False
    s.write(b'{"show": true}\n')
    s.flush()
    s.waitForBytesWritten(TIMEOUT_MS)
    if not s.waitForDisconnected(TIMEOUT_MS):
        s.disconnectFromServer()
    return True


def listen(window):
    """Later starts hand over to this window (PR7-R's hand-off, with its Windows fix: data may already be waiting)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()
        done = []

        def read():
            buf.extend(bytes(sock.readAll()))
            if buf.endswith(b"\n") and not done:
                done.append(True)
                window.showNormal()
                window.raise_()
                window.activateWindow()
                sock.disconnectFromServer()
        sock.readyRead.connect(read)
        sock.disconnected.connect(read)
        if sock.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def selftest(out: str) -> int:
    import tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    tmp = tempfile.mkdtemp()
    os.environ["PR7BK_DATA"] = os.path.join(tmp, "data")
    os.environ["PR7BK_MEMORY_KEYRING"] = "1"
    result = {}
    try:
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
        from . import __version__, restic, theme
        from .main_window import MainWindow
        app = QApplication.instance() or QApplication(sys.argv[:1])
        theme.load_fonts()
        src = os.path.join(tmp, "Studio", "Projects")
        os.makedirs(os.path.join(src, "titles"))
        notes = os.path.join(src, "titles", "notes.txt")
        with open(notes, "w") as f:
            f.write("version one\n")
        with open(os.path.join(src, "titles", "scene.blend"), "wb") as f:
            f.write(os.urandom(300_000))
        with open(os.path.join(src, "cache.tmp"), "wb") as f:
            f.write(b"temp")
        w = MainWindow(sync=True)
        w.answers.update({"say": lambda k, t: None, "confirm": False, "schtasks": lambda a: (0, "")})
        w.resize(1320, 860)
        w.show()
        w.add()
        w.w_name.setText("Self-test")
        w.w_pass.setText("self-test password")
        w.w_pass2.setText("self-test password")
        w.next_step()
        w.w_dest["path"].setText(os.path.join(tmp, "backups"))
        w.next_step()
        w.chosen = [src]
        w.next_step()
        w.w_sched_none.setChecked(True)
        w.next_step()
        w.w_keep_last.setChecked(True)
        w.w_last.setValue(2)
        w.next_step()                                           # saved
        job = w.jobs[0]
        w.run_now(job)
        first = job.last
        with open(notes, "w") as f:
            f.write("version two\n")
        w.run_now(job)
        w.run_now(job)
        w.show_restore(job)
        snaps = w.snapshots
        w.r_versions.setCurrentItem(w.r_versions.topLevelItem(len(snaps) - 1))      # the oldest kept
        names = sorted(n.name for n in w.nodes)
        target = os.path.join(tmp, "Restored")
        w.r_other.setChecked(True)
        w.r_folder.setText(target)
        from PySide6.QtCore import Qt
        item = next(iter(w.r_files.findItems("notes.txt", Qt.MatchFlag.MatchRecursive)))
        item.setCheckState(0, Qt.CheckState.Checked)
        w.restore()
        for p in ("home", "wizard", "restore"):
            w.show_page(p)
            app.processEvents()
            w.grab()
        restored = os.path.join(target, "notes.txt")
        result = {"version": __version__, "restic": restic.version(), "first_new": first.files_new,
                  "ok": job.last.ok, "versions": len(snaps), "names": names,
                  "restored": open(restored).read() if os.path.exists(restored) else None,
                  "temp_left_out": "cache.tmp" not in names, "fonts": "Inter" in QFontDatabase.families()}
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        result = {"error": f"{type(e).__name__}: {e}"}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0 if result.get("restored") else 1


def unregister() -> int:
    from . import jobs, schedule
    for j in jobs.load():
        schedule.remove(j)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ["--version"]:
            from . import __version__
            print(__version__)
            return 0
        if argv[:1] == ["--selftest"] and len(argv) == 2:
            return selftest(argv[1])
        if argv[:1] == ["--run"] and len(argv) == 2:
            from . import runs
            return runs.run_by_id(argv[1])
        if argv[:1] == ["--unregister"]:
            return unregister()
    except Exception:  # noqa: BLE001 - a command-line mode never waits on an error box (PR7-IS's lesson)
        return 2
    from PySide6.QtWidgets import QApplication

    from . import finish, settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-BK")
    if hand_over():
        return 0
    theme.set_finish(finish.start(settings.get("finish", "obsidian")))
    theme.load_fonts()
    from PySide6.QtGui import QFont, QIcon
    app.setFont(QFont("Inter", 10))
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    w = MainWindow()
    w.show()
    if "--new-home-backup" in argv:
        w.new_home_backup()
    from PySide6.QtCore import QTimer
    follow = QTimer(w)                            # one finish for the family: follow another app's switch
    follow.timeout.connect(lambda: finish.follow(theme.FINISH, w.set_finish))
    follow.start(2000)
    listen(w)
    from . import update_ui
    update_ui.start(w)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
