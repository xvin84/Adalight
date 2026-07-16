; Установщик Adalight для Windows (Inno Setup 6).
; Сборка: ISCC.exe /DAppVersion=x.y.z installer.iss
; Ставится в профиль пользователя (без прав администратора) — поэтому
; автообновление программы может заменять exe самостоятельно.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{9C4C1B6E-5B32-4E86-9D31-ADA119117001}
AppName=Adalight
AppVersion={#AppVersion}
AppPublisher=xvin84
AppPublisherURL=https://github.com/xvin84/Adalight
DefaultDirName={autopf}\Adalight
DefaultGroupName=Adalight
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=Adalight-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\Adalight.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked
Name: "autostart"; Description: "Запускать при входе в систему (свёрнуто в трей)"; Flags: unchecked

[Files]
Source: "dist\Adalight.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Adalight"; Filename: "{app}\Adalight.exe"
Name: "{autodesktop}\Adalight"; Filename: "{app}\Adalight.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "Adalight"; \
  ValueData: """{app}\Adalight.exe"" --minimized"; \
  Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Adalight.exe"; Description: "Запустить Adalight"; \
  Flags: nowait postinstall skipifsilent
