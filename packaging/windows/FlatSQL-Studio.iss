; Inno Setup script for FlatSQL Studio.
; Compiled by GitHub Actions; ISCC is pre-installed on windows-latest runners.

#define MyAppName "FlatSQL Studio"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "FlatSQL"
#define MyAppURL "https://github.com/NaceKapus/FlatSQL"
#define MyAppExeName "FlatSQL-Studio.exe"

[Setup]
; AppId uniquely identifies the application for upgrades/uninstalls — never change it.
AppId={{5D9A7E8F-3C2B-4A6F-B1D8-E9F0A1B2C3D4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=FlatSQL-Studio-Setup
SetupIconFile=..\..\src\flatsql\assets\img\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\FlatSQL-Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
