; Installateur ALICIA (Inno Setup 6) — construit par GitHub Actions : installer/build.ps1
;
; Installe ALICIA pour l'utilisateur courant (sans droits administrateur) dans
; %LOCALAPPDATA%\Programs\ALICIA, demande quelle IA utiliser (avec un bouton vers la page
; de clé Gemini), puis installe Python et les composants avec uv (fourni, bin\uv.exe).
; Les clés et réglages restent dans %APPDATA%\Alicia : une désinstallation ne les efface pas.

#ifndef AppVersion
  #define AppVersion "0.3.0"
#endif

[Setup]
AppId={{DAEFB63B-3EA5-4F22-A7FB-873735B9FC22}
AppName=ALICIA
AppVersion={#AppVersion}
AppVerName=ALICIA {#AppVersion}
AppPublisher=byRedemptiion
AppComments=Copilote de jeu : elle regarde ton écran, t'écoute et te conseille, sans jamais jouer à ta place.
DefaultDirName={localappdata}\Programs\ALICIA
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ALICIA-Setup
SetupIconFile=..\src\alicia\assets\alicia.ico
UninstallDisplayIcon={app}\src\alicia\assets\alicia.ico
UninstallDisplayName=ALICIA
WizardStyle=modern
WizardImageFile=wizard.bmp
WizardSmallImageFile=wizard-small.bmp
Compression=lzma2/max
SolidCompression=yes
ShowLanguageDialog=no
CloseApplications=no

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Messages]
fr.WelcomeLabel2=Tu vas installer ALICIA, ta copilote de jeu : elle regarde ton écran, t'écoute (F10 ou « Alicia… ») et te conseille, sans jamais jouer à ta place.%n%nIl faut une connexion Internet : l'installation télécharge Python et les voix (environ 2 Go la première fois).

[Files]
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Lancer_Alicia.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Mes_Jeux_Alicia.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Tester_IA.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\setup.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "build\uv.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "build\.alicia-version"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\ALICIA"; Filename: "{app}\.venv\Scripts\alicia-gui.exe"; WorkingDir: "{app}"; IconFilename: "{app}\src\alicia\assets\alicia.ico"; Comment: "ALICIA, copilote de jeu"
Name: "{autoprograms}\ALICIA"; Filename: "{app}\.venv\Scripts\alicia-gui.exe"; WorkingDir: "{app}"; IconFilename: "{app}\src\alicia\assets\alicia.ico"; Comment: "ALICIA, copilote de jeu"
Name: "{autoprograms}\ALICIA (diagnostic, avec terminal)"; Filename: "{app}\Lancer_Alicia.bat"; Parameters: "--console"; WorkingDir: "{app}"; IconFilename: "{app}\src\alicia\assets\alicia.ico"

[Run]
Filename: "{app}\.venv\Scripts\alicia-gui.exe"; WorkingDir: "{app}"; Description: "Lancer ALICIA maintenant"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Tout le dossier du programme (Python, composants, fichiers mis à jour par le bouton MAJ).
; Les clés et réglages (%APPDATA%\Alicia) et les modèles vocaux sont conservés.
Type: filesandordirs; Name: "{app}"

[Code]
var
  AiPage: TInputOptionWizardPage;
  KeyPage: TInputQueryWizardPage;
  KeyButton: TNewButton;
  SetupFailed: Boolean;

function SetEnvironmentVariable(lpName: String; lpValue: String): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure OpenKeyPage(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', 'https://aistudio.google.com/apikey', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

function ExistingKey(): Boolean;
var
  Text: AnsiString;
begin
  Result := LoadStringFromFile(ExpandConstant('{userappdata}\Alicia\.env'), Text)
    and (Pos('GEMINI_API_KEY=', String(Text)) > 0);
end;

procedure InitializeWizard;
begin
  AiPage := CreateInputOptionPage(wpWelcome,
    'Choisis l''IA d''ALICIA',
    'Le « cerveau » qui comprend ton écran et te répond.',
    'Tu pourras changer d''avis plus tard (bouton IA dans ALICIA).',
    True, False);
  AiPage.Add('Gemini (Google) — recommandé, gratuit pour commencer');
  AiPage.Add('Ollama — IA locale sur ton PC (avancé, demande une bonne carte graphique)');
  AiPage.Add('Je choisirai plus tard, au premier lancement d''ALICIA');
  AiPage.SelectedValueIndex := 0;

  KeyPage := CreateInputQueryPage(AiPage.ID,
    'Ta clé Gemini',
    'Gratuite, 1 minute avec ton compte Google.',
    '1. Clique sur le bouton : la page Gemini s''ouvre dans ton navigateur.' + #13#10 +
    '2. Clique sur « Create API key », puis copie la clé.' + #13#10 +
    '3. Colle-la ci-dessous. Elle reste sur ce PC, jamais partagée.');
  KeyButton := TNewButton.Create(KeyPage);
  KeyButton.Parent := KeyPage.Surface;
  KeyButton.Caption := 'Ouvrir la page Gemini pour créer ma clé';
  KeyButton.Left := 0;
  KeyButton.Top := KeyPage.SubCaptionLabel.Top + KeyPage.SubCaptionLabel.Height + ScaleY(12);
  KeyButton.Width := ScaleX(320);
  KeyButton.Height := ScaleY(30);
  KeyButton.OnClick := @OpenKeyPage;
  KeyPage.Add('Clé Gemini :', True);
  KeyPage.PromptLabels[0].Top := KeyButton.Top + KeyButton.Height + ScaleY(18);
  KeyPage.Edits[0].Top := KeyPage.PromptLabels[0].Top + KeyPage.PromptLabels[0].Height + ScaleY(4);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = KeyPage.ID) and (AiPage.SelectedValueIndex <> 0);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = KeyPage.ID) and (Trim(KeyPage.Values[0]) = '') then
  begin
    if ExistingKey() then
      Exit; { réinstallation : la clé déjà enregistrée est gardée }
    Result := MsgBox('Aucune clé collée. Continuer quand même ?' + #13#10 +
      'Tu pourras la coller au premier lancement d''ALICIA.', mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

function Provider(): String;
begin
  case AiPage.SelectedValueIndex of
    0: Result := 'gemini';
    1: Result := 'ollama';
  else
    Result := 'later';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Params: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  { La clé passe par une variable d'environnement (jamais sur la ligne de commande). }
  SetEnvironmentVariable('ALICIA_SETUP_PROVIDER', Provider());
  if Provider() = 'gemini' then
    SetEnvironmentVariable('ALICIA_SETUP_KEY', Trim(KeyPage.Values[0]))
  else
    SetEnvironmentVariable('ALICIA_SETUP_KEY', '');
  WizardForm.StatusLabel.Caption :=
    'Installation de Python, des composants et des voix (quelques minutes, fenêtre de progression)…';
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\setup.ps1') + '" -Installer';
  if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode)
     or (ResultCode <> 0) then
  begin
    SetupFailed := True;
    MsgBox('L''installation des composants a échoué (code ' + IntToStr(ResultCode) + ').' + #13#10 +
      'Vérifie ta connexion Internet puis relance l''installateur.' + #13#10 +
      'Journal : ' + ExpandConstant('{app}\install.log'), mbError, MB_OK);
  end;
  SetEnvironmentVariable('ALICIA_SETUP_KEY', '');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and SetupFailed then
    WizardForm.FinishedLabel.Caption :=
      'Les fichiers sont installés, mais pas tous les composants. Relance l''installateur une fois connecté à Internet.';
end;
