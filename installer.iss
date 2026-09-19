; Inno Setup script for HECTOR Desktop.

#define MyAppName "HECTOR Desktop"
#ifndef MyAppVersion
  #define VerFile "..\hector_package\pyproject.toml"
  #if !FileExists(VerFile)
    #define VerFile "pyproject.toml"
  #endif
  #define VerResult ""
  #define VerHandle FileOpen(VerFile)
  #sub ReadVerLine
    #define VerLine FileRead(VerHandle)
    #if (VerResult == "") && (Copy(VerLine, 1, 10) == "version = ")
      #define VerRest Copy(VerLine, Pos('"', VerLine) + 1, Len(VerLine))
      #expr VerResult = Copy(VerRest, 1, Pos('"', VerRest) - 1)
    #endif
  #endsub
  #for {0; VerHandle && !FileEof(VerHandle); 0} ReadVerLine
  #if VerHandle
    #expr FileClose(VerHandle)
  #endif
  #if VerResult == ""
    #error "Could not determine MyAppVersion. Build via .\windows_app.cmd, or pass /DMyAppVersion=X.Y.Z to ISCC."
  #endif
  #define MyAppVersion VerResult
#endif
#define MyAppPublisher "HECTOR"
#define MyAppExeName "HECTOR Desktop.exe"

[Setup]
AppId={{B6E2C9A4-7E1D-4C3A-9F2B-1A2B3C4D5E6F}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=release
OutputBaseFilename=HECTOR-Desktop-{#MyAppVersion}-Setup
SetupIconFile=hector_desktop\resources\hector.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\HECTOR Desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
