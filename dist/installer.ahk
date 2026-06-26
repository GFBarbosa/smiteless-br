#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; SmitelessSetup.exe - self-contained installer (compiled from this script with the whole
; app embedded as payload.zip). Needs nothing pre-installed: Python, Pillow and AutoHotkey
; are all inside the payload.
;
;   SmitelessSetup.exe              show the install window (normal use)
;   SmitelessSetup.exe /upgrade     silent reinstall over the existing copy (used by the updater)
;   SmitelessSetup.exe /uninstall   remove Smiteless
;
; Installs to %LOCALAPPDATA%\Smiteless and makes Desktop + Start Menu + Startup shortcuts.
; ============================================================

APPNAME := "Smiteless"
TARGET := EnvGet("LOCALAPPDATA") "\" APPNAME
REGKEY := "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\" APPNAME

mode := "gui"
for a in A_Args {
    if (a = "/upgrade" || a = "/S" || a = "/silent")
        mode := "silent"
    else if (a = "/uninstall")
        mode := "uninstall"
}

if (mode = "uninstall") {
    Uninstall()
    ExitApp()
} else if (mode = "silent") {
    DoInstall(true)            ; upgrade path: relaunch the tray after replacing files
    ExitApp()
}

; ---------- normal GUI install ----------
g := Gui("+AlwaysOnTop -MaximizeBox -MinimizeBox", APPNAME " Setup")
g.BackColor := "0x11131A"
g.SetFont("s10 cWhite", "Segoe UI")
g.MarginX := 22, g.MarginY := 18
g.SetFont("s15 bold c0xC8AA6E")
g.Add("Text", , "Smiteless")
g.SetFont("s10 cWhite")
g.Add("Text", "y+8 w430", "A League of Legends champ-select and in-game overlay.")
g.Add("Text", "y+12 w430 c0x9B988E",
    "This installs everything it needs (nothing else to download) into your account folder, "
    . "adds a desktop shortcut, and starts it with Windows. Run League in Borderless mode.")
g.SetFont("s9 c0x9B988E")
g.Add("Text", "y+12 w430", "Installs to:  " TARGET)
btn := g.Add("Button", "y+18 w120 h34 Default", "Install")
btn.SetFont("s10 bold")
cancel := g.Add("Button", "x+10 yp w90 h34", "Cancel")
status := g.Add("Text", "xm y+14 w430 c0x9B988E", "")
btn.OnEvent("Click", GuiInstall)
cancel.OnEvent("Click", (*) => ExitApp())
g.OnEvent("Close", (*) => ExitApp())
g.Show()

GuiInstall(*) {
    global g, btn, cancel, status, TARGET
    btn.Enabled := false, cancel.Enabled := false
    status.Value := "Installing..."
    DoInstall(true)
    status.Value := "Done!  Smiteless is starting and will run with Windows from now on."
    btn.Text := "Finish", btn.Enabled := true
    btn.OnEvent("Click", (*) => ExitApp())
    MsgBox("Smiteless is installed and running.`n`nLook for the gold 'S' icon near your clock "
        . "(click the ^ arrow if you don't see it). Press Ctrl+Alt+X any time to open it.",
        APPNAME, "Iconi")
    ExitApp()
}

DoInstall(launch) {
    global TARGET, REGKEY, APPNAME
    ; stop any running copy so files aren't locked
    RunWait(A_ComSpec ' /c taskkill /F /IM Smiteless.exe /IM SmitelessApp.exe >nul 2>nul', , "Hide")
    Sleep(400)
    DirCreate(TARGET)
    ; extract the embedded payload (Expand-Archive reads the Compress-Archive zip reliably)
    tmp := A_Temp "\smiteless_payload.zip"
    FileInstall("payload.zip", tmp, 1)
    psfile := A_Temp "\smiteless_extract.ps1"
    try FileDelete(psfile)
    FileAppend("Expand-Archive -LiteralPath '" tmp "' -DestinationPath '" TARGET "' -Force", psfile)
    RunWait('powershell -NoProfile -ExecutionPolicy Bypass -File "' psfile '"', , "Hide")
    try FileDelete(psfile)
    try FileDelete(tmp)
    ; keep a copy of this installer for clean uninstall
    try FileCopy(A_ScriptFullPath, TARGET "\Uninstall.exe", 1)
    ; shortcuts (Desktop, Startup, Start Menu)
    ico := TARGET "\assets\smiteless.ico"
    exe := TARGET "\Smiteless.exe"
    FileCreateShortcut(exe, A_Desktop "\Smiteless.lnk", TARGET, , APPNAME, ico)
    FileCreateShortcut(exe, A_Startup "\Smiteless.lnk", TARGET, , APPNAME, ico)
    DirCreate(A_Programs "\" APPNAME)
    FileCreateShortcut(exe, A_Programs "\" APPNAME "\Smiteless.lnk", TARGET, , APPNAME, ico)
    FileCreateShortcut(TARGET "\Uninstall.exe", A_Programs "\" APPNAME "\Uninstall Smiteless.lnk",
        TARGET, "/uninstall", "Uninstall " APPNAME, ico)
    ; Add/Remove Programs entry
    ver := "1.0.0"
    try ver := Trim(FileRead(TARGET "\VERSION"), " `t`r`n")
    RegWrite(APPNAME, "REG_SZ", REGKEY, "DisplayName")
    RegWrite('"' TARGET '\Uninstall.exe" /uninstall', "REG_SZ", REGKEY, "UninstallString")
    RegWrite(ico, "REG_SZ", REGKEY, "DisplayIcon")
    RegWrite(ver, "REG_SZ", REGKEY, "DisplayVersion")
    RegWrite("bobbyroylee", "REG_SZ", REGKEY, "Publisher")
    RegWrite(TARGET, "REG_SZ", REGKEY, "InstallLocation")
    RegWrite(1, "REG_DWORD", REGKEY, "NoModify")
    RegWrite(1, "REG_DWORD", REGKEY, "NoRepair")
    if (launch)
        Run('"' exe '"', TARGET)
}

Uninstall() {
    global TARGET, REGKEY, APPNAME
    RunWait(A_ComSpec ' /c taskkill /F /IM Smiteless.exe /IM SmitelessApp.exe >nul 2>nul', , "Hide")
    Sleep(400)
    try FileDelete(A_Desktop "\Smiteless.lnk")
    try FileDelete(A_Startup "\Smiteless.lnk")
    try DirDelete(A_Programs "\" APPNAME, true)
    try RegDeleteKey(REGKEY)
    ; remove the install folder. Uninstall.exe runs from INSIDE it, so a detached batch
    ; retries rmdir until the exe has exited and the folder unlocks, then deletes itself.
    bat := A_Temp "\smiteless_uninstall.bat"
    try FileDelete(bat)
    FileAppend('@echo off`r`n'
        . ':retry`r`n'
        . 'rmdir /s /q "' TARGET '" 2>nul`r`n'
        . 'if exist "' TARGET '" ( ping 127.0.0.1 -n 2 >nul & goto retry )`r`n'
        . 'del "%~f0"`r`n', bat)
    Run(A_ComSpec ' /c "' bat '"', , "Hide")
    MsgBox(APPNAME " has been removed.", APPNAME, "Iconi")
}
