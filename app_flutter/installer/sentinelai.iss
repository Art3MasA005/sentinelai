; Inno Setup script for the SentinelAI desktop console.
; Build with installer\build_installer.ps1 (it builds the Flutter release first and passes the defines below).

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef BackendDefault
  #define BackendDefault ""
#endif
#define ReleaseDir "..\build\windows\x64\runner\Release"

[Setup]
AppId={{6C1F3B7E-2E4A-4E37-9B7D-5E1A9C0F2D41}
AppName=SentinelAI
AppVersion={#AppVersion}
AppVerName=SentinelAI {#AppVersion}
AppPublisher=SentinelAI
DefaultDirName={autopf}\SentinelAI
DefaultGroupName=SentinelAI
DisableProgramGroupPage=yes
; Per-user install by default: no administrator prompt.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\windows\runner\resources\app_icon.ico
UninstallDisplayIcon={app}\sentinelai.exe
UninstallDisplayName=SentinelAI
OutputDir=..\..\dist
OutputBaseFilename=SentinelAI-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#ReleaseDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[INI]
; Read by the app (BackendLauncher) to start the local backend when none is running.
Filename: "{app}\sentinelai.ini"; Section: "SentinelAI"; Key: "BackendDir"; String: "{code:GetBackendDir}"

[Icons]
Name: "{autoprograms}\SentinelAI"; Filename: "{app}\sentinelai.exe"
Name: "{autodesktop}\SentinelAI"; Filename: "{app}\sentinelai.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\sentinelai.exe"; Description: "{cm:LaunchProgram,SentinelAI}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\sentinelai.ini"

[Code]
var
  BackendPage: TInputDirWizardPage;

procedure InitializeWizard;
begin
  BackendPage := CreateInputDirPage(wpSelectDir,
    'SentinelAI backend',
    'Where is the SentinelAI backend folder?',
    'The app starts the local Python backend from this folder when it is not already running. ' +
    'It is the "backend" folder of the SentinelAI repository and must contain .venv\Scripts\pythonw.exe.',
    False, '');
  BackendPage.Add('Backend folder:');
  BackendPage.Values[0] := '{#BackendDefault}';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = BackendPage.ID) and
     not FileExists(AddBackslash(BackendPage.Values[0]) + '.venv\Scripts\pythonw.exe') then
    Result := MsgBox('No .venv\Scripts\pythonw.exe was found in this folder, so the app will not be able to ' +
      'start the backend by itself (you can still start it by hand). Continue anyway?',
      mbConfirmation, MB_YESNO) = IDYES;
end;

function GetBackendDir(Param: String): String;
begin
  Result := BackendPage.Values[0];
end;
