; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.1.0 installer\HealthCenterSetup.iss
; Needs dist\HealthCenterSystem.exe and installer\postgresql-installer.exe (see build steps).

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define PgInstaller "postgresql-installer.exe"

[Setup]
AppId={{6F1C2B7A-4D0E-4C55-9B1A-HCS000000001}
AppName=Health Center System
AppVersion={#AppVersion}
DefaultDirName={sd}\HealthCenter
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=HealthCenterSetup-{#AppVersion}
Compression=lzma2
SolidCompression=yes

[Dirs]
; Normal users must be able to write here so the self-update can replace the exe.
Name: "{app}"; Permissions: users-modify

[Files]
Source: "..\dist\HealthCenterSystem.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PgInstaller}"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\Health Center System"; Filename: "{app}\HealthCenterSystem.exe"
Name: "{autodesktop}\Health Center System"; Filename: "{app}\HealthCenterSystem.exe"
Name: "{autoprograms}\Set up backup drive"; Filename: "{app}\HealthCenterSystem.exe"; Parameters: "--mark-drive"

[UninstallRun]
Filename: "schtasks"; Parameters: "/Delete /TN HealthCenterBackup /F"; Flags: runhidden; RunOnceId: "RemoveBackupTask"

[Code]
var
  AdminPage: TInputQueryWizardPage;

function ExistingInstall: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonappdata}\HealthCenterSystem\setup_complete.txt'));
end;

procedure InitializeWizard;
begin
  AdminPage := CreateInputQueryPage(wpSelectDir,
    'First administrator account', 'Create the administrator login',
    'This account manages users, doctors and backups. Write the password down and keep it safe.');
  AdminPage.Add('Username:', False);
  AdminPage.Add('Password (at least 8 characters):', True);
  AdminPage.Add('Confirm password:', True);
  AdminPage.Values[0] := 'admin';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (AdminPage <> nil) and (PageID = AdminPage.ID) and ExistingInstall;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = AdminPage.ID then
  begin
    if Trim(AdminPage.Values[0]) = '' then
    begin
      MsgBox('Enter a username.', mbError, MB_OK);
      Result := False;
    end
    else if Length(AdminPage.Values[1]) < 8 then
    begin
      MsgBox('The password must be at least 8 characters.', mbError, MB_OK);
      Result := False;
    end
    else if AdminPage.Values[1] <> AdminPage.Values[2] then
    begin
      MsgBox('The passwords do not match.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Lines: TArrayOfString;
  CredsFile, Params: String;
begin
  if CurStep = ssPostInstall then
  begin
    CredsFile := ExpandConstant('{tmp}\hcs_creds.txt');
    Params := '--setup --pg-installer "' + ExpandConstant('{tmp}\{#PgInstaller}') + '"';
    if not ExistingInstall then
    begin
      SetArrayLength(Lines, 2);
      Lines[0] := Trim(AdminPage.Values[0]);
      Lines[1] := AdminPage.Values[1];
      SaveStringsToUTF8File(CredsFile, Lines, False);
      Params := Params + ' --creds "' + CredsFile + '"';
    end;
    WizardForm.StatusLabel.Caption := 'Setting up the database. This can take several minutes...';
    if (not Exec(ExpandConstant('{app}\HealthCenterSystem.exe'), Params, '', SW_HIDE,
                 ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
      MsgBox('The database setup did not finish. Please send this file to your support person:' + #13#10 +
             ExpandConstant('{commonappdata}\HealthCenterSystem\setup.log'), mbError, MB_OK);
  end;
end;