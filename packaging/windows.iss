; Inno Setup script: wraps dist\ios-homescreen into an installer in out\.
; ISCC /DAppVersion=0.2.0 packaging\windows.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3E2B1A-8C4D-4E5F-9A7B-1C2D3E4F5A6B}
AppName=ios-homescreen
AppVersion={#AppVersion}
AppPublisher=Yakup Emre Yerli
AppPublisherURL=https://github.com/YakupEmreYerli/ios-homescreen
DefaultDirName={localappdata}\Programs\ios-homescreen
DefaultGroupName=ios-homescreen
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\out
OutputBaseFilename=ios-homescreen-{#AppVersion}-windows-x64-setup
SetupIconFile=..\build\icons\ios-homescreen.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ios-homescreen.exe

[Files]
Source: "..\dist\ios-homescreen\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\ios-homescreen"; Filename: "{app}\ios-homescreen.exe"
Name: "{autodesktop}\ios-homescreen"; Filename: "{app}\ios-homescreen.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\ios-homescreen.exe"; Description: "Open ios-homescreen"; Flags: nowait postinstall skipifsilent
