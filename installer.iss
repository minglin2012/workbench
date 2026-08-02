; Inno Setup 脚本 — 工作台 安装程序

#define MyAppName "工作台"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Workbench"
#define MyAppExeName "Workbench.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Workbench
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=.\dist
OutputBaseFilename=Workbench-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\Workbench.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "projects.yaml"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 工作台"; Filename: "{uninstallexe}"
Name: "{autostartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--no-browser"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动工作台"; Flags: nowait postinstall skipifsilent

[Code]
// 安装后首次启动时，复制默认配置到用户目录
procedure CurStepChanged(CurStep: TSetupStep);
var
  UserConfigDir: string;
  UserConfigFile: string;
  DefaultConfig: string;
begin
  if CurStep = ssPostInstall then
  begin
    UserConfigDir := ExpandConstant('{userappdata}\workbench');
    UserConfigFile := UserConfigDir + '\projects.yaml';
    DefaultConfig := ExpandConstant('{app}\projects.yaml');

    // 创建用户配置目录
    if not DirExists(UserConfigDir) then
      CreateDir(UserConfigDir);

    // 仅当用户还没有配置文件时才复制默认配置
    if not FileExists(UserConfigFile) then
      CopyFile(DefaultConfig, UserConfigFile, False);
  end;
end;
