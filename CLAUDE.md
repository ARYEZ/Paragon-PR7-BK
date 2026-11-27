# Paragon PR7-BK: notes for Claude

**Paragon PR7-BK** is the owner's personal backup program: Python (**PySide6** + keyring) that **works the way Duplicati
works**, in the Paragon family look (PR7-Z ... PR7-LN, PR7-HW `ARYEZ/Paragon-PR7-HW`). Windows 10/11 x64 is the target;
it runs on Linux for tests. The owner writes Python; explain the why.

## How it's built

- **No backup code of our own** (PR7-Z's rule): every backup / restore runs the official restic, unmodified. CI downloads
  the pinned Windows release (0.20.0, SHA-256 in build.yml) into `engine/` (git-ignored); the spec bundles it.
  `restic.find_restic`: PR7BK_RESTIC, bundled, PATH (tests on Linux: Ubuntu's restic 0.16; the code works with both:
  0.17+ exit codes 10 / 12 and snapshot summaries, 0.16's stderr wording). To update: version + SHA-256 in build.yml,
  NOTICE, CHANGELOG.
- `pr7bk/jobs.py` (no Qt): `Job` (Destination, Schedule, Keep, LastRun) in <data>/jobs.json (**PR7BK_DATA** in tests);
  never a secret in it. `all_excludes` adds the temp / system / hidden patterns; `tag` = pr7bk:<id> (several jobs can
  share a repository). `when_text` = Duplicati's "Today 03:00".
- `pr7bk/restic.py` (no Qt): `Restic(job, password, secret)`: env (RESTIC_REPOSITORY / RESTIC_PASSWORD, never the command
  line; AWS_ / B2_ / RESTIC_REST_ keys; cache in <data>), `backup` (--json lines -> Progress / warnings / summary; exit 3
  = a warning), `forget` (--tag, --group-by tags, Keep rules, --prune), `snapshots`, `ls`, `restore` (into a staging
  folder in the target, then `_place` by overwrite / keepboth / skip), `stop` (terminate; `runs.Run` unlocks after).
  Windows paths in snapshots are /C/Users/... (`snapshot_path` / `local_path`).
- `pr7bk/secrets.py`: keyring "Paragon PR7-BK" (password, secret per job); **PR7BK_MEMORY_KEYRING** in tests.
- `pr7bk/schedule.py`: Task Scheduler task \Paragon\PR7-BK\<id> running `PR7-BK.exe --run <id>` (schtasks; `run=` for
  tests). `pr7bk/runs.py`: one run (window and --run): password, ensure the repository, backup, log in <data>/logs,
  LastRun written back to jobs.json (the window re-reads it every 15 s).
- **Linux (PR7-OS)**: `schedule.py` writes systemd user units (~/.config/systemd/user/pr7bk-<id>.timer/.service,
  OnCalendar from the Schedule, Persistent=true) and runs `systemctl --user`; `schedule.LINUX` (the shared tests set it
  False through conftest: they check Windows' schtasks commands). `MainWindow.new_home_backup` / `--new-home-backup`:
  the wizard with home, daily 03:00, caches and Trash left out. tests/test_linux.py.
- `pr7bk/main_window.py`: home cards (`JobCard`), the five-step wizard (`step_problem` checks each step; the source tree
  ticks folders, unticking inside a chosen one adds an exclude), Restore (versions, a checkable file tree from the
  backed-up folders down, search), log dialog; restic on threads through `_Bridge` (`sync = True` inline); `_ask` /
  `answers` / `_say`; `answers["schtasks"]` stands in for Task Scheduler.
- `pr7bk/app.py`: one window per user (QLocalSocket, PR7-R's Windows fix); command-line modes never let an error escape;
  `--run ID` (exit 0 / 1 / 2), `--unregister` (the uninstaller: every task), `--selftest OUT.json` (a real backup,
  versions, Keep, a restore through the real window; CI on the installed exe).
- Installer `installer/pr7bk.iss` (per user, AppId {9C8D5648-E4E9-4E7F-B684-DE9E5D1C1B23} permanent; desktopicon;
  `--unregister` on uninstall); CI installs it, `tools/verify_install.py installed|uninstalled`. Spec: file details, no
  UPX, PyInstaller's bootloader built in CI, Defender scan.
- Updates: `pr7bk/updates.py` / `update_ui.py` (the family's files, keep them in step); `family.py`: the family's AppIds
  (PR7-BK included; tests/test_window.py checks every name and AppId is there once). `pr7bk/finish.py`: the family's
  finish, the same file in every app.

## The look (family rules)

- Theme is PR7-HW's (OBSIDIAN + AURORA). Colours: the family's only (running orange, warnings orange, steps and the
  primary button the family gradient; tree tick boxes styled in `restyle`); Inter; labels UPPER CASE; paths keep case.
- The PR7-BK mark: PR7 `Logo.cpp` geometry plus B (PR7-HB's) and K (new, `widgets.K_OUTER`); icon "7BK" by
  `tools/make_icon.py`, wizard art by `tools/make_installer_art.py`. Mock-up: `tools/mockup.py`. Check visuals with
  `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT` (real backups made by restic).

## Rules

- Behaviour questions: do what Duplicati does (the five steps, the home page, restore choices).
- Never log, print or send a backup's password or a destination key.
- Tests: `python -m pytest` (offscreen) with the real restic on real folders; every restore is checked on disk. Never the
  real settings, data folder or Credential Manager (conftest), or, outside CI, Task Scheduler.
- Releases: bump `__version__` in `pr7bk/__init__.py` and add a `## x.y.z` section to CHANGELOG.md, then push: CI
  publishes that version by itself once every check has passed.
