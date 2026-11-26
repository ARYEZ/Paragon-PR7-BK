; Paragon PR7-BK installer (Inno Setup 6): backups, the way Duplicati makes them (restic does the work).
;   iscc /DAppVersion=0.1.0 installer\pr7bk.iss      (after pyinstaller pr7bk.spec has made dist\PR7-BK)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-BK, with a Start menu entry. Scheduled backups are
; the user's own Task Scheduler tasks (made by PR7-BK); the uninstaller removes them (--unregister). The backups
; themselves, at their destinations, are never touched.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{9C8D5648-E4E9-4E7F-B684-DE9E5D1C1B23}
AppName=Paragon PR7-BK
AppVersion={#AppVersion}
AppVerName=Paragon PR7-BK {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-BK
DefaultGroupName=Paragon PR7-BK
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-BK-Setup-{#AppVersion}
SetupIconFile=..\pr7bk\icons\app.ico
UninstallDisplayIcon={app}\PR7-BK.exe
UninstallDisplayName=Paragon PR7-BK
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-BK\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-BK"; Filename: "{app}\PR7-BK.exe"; Comment: "Backups"
Name: "{autodesktop}\Paragon PR7-BK"; Filename: "{app}\PR7-BK.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-BK.exe"; Description: "{cm:LaunchProgram,Paragon PR7-BK}"; Flags: nowait postinstall skipifsilent
; Updates (Check for updates runs this installer with /SILENT /relaunch=1): start PR7-BK again when done.
Filename: "{app}\PR7-BK.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[UninstallRun]
Filename: "{app}\PR7-BK.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "Unregister"

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
