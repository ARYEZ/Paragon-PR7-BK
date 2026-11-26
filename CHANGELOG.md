# Changelog

## 0.1.0

- First release: backups, the way Duplicati makes them, with restic 0.20.0 doing the work.
- Add / Edit backup in five steps: password (in Windows' Credential Manager), destination (folder, SFTP, REST, S3,
  B2), folders and filters, schedule (Windows' Task Scheduler), versions to keep, open files.
- Runs with live progress, Stop, warnings for files that couldn't be read, a log per backup.
- Restore any version's files where they were or to another folder: keep both, replace or skip.
- Verify, Copy, Delete; OBSIDIAN and AURORA finishes; Check for Updates.
