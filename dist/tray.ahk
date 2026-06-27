#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Smiteless tray - the BUNDLED launcher (compiled to Smiteless.exe and shipped in the
; installer). Unlike the dev smiteless.ahk (which runs `python ui\*.py`), this drives the
; frozen app: app\SmitelessApp.exe <overlay|widget|settings|phase|update>. No Python or
; AutoHotkey needs to be installed on the user's machine.
;
; Install layout (A_ScriptDir = %LOCALAPPDATA%\Smiteless):
;   Smiteless.exe            <- this
;   VERSION
;   app\SmitelessApp.exe     <- the frozen Python app
;   assets\smiteless.ico
; ============================================================

APP := A_ScriptDir "\app\SmitelessApp.exe"
ICO := A_ScriptDir "\assets\smiteless.ico"
NOAUTO := EnvGet("USERPROFILE") "\.claude\smiteless_noautoopen"   ; present = auto-open OFF

if FileExist(ICO)
    TraySetIcon(ICO)
A_IconTip := "Smiteless"

tray := A_TrayMenu
tray.Delete()
tray.Add("Open overlay", (*) => Launch("overlay"))
tray.Add("Profile / home", (*) => Launch("profile"))
tray.Add("Item widget", (*) => Launch("widget"))
tray.Add("Settings", (*) => Launch("settings"))
tray.Add()
tray.Add("Auto-open at champ select", ToggleAuto)
tray.Add("Check for updates", (*) => Launch("update --force"))
tray.Add()
tray.Add("Reload", (*) => Reload())
tray.Add("Exit", (*) => ExitApp())
tray.Default := "Open overlay"
RefreshAutoCheck()

; Global hotkeys: Ctrl+Alt+X = overlay, Ctrl+Alt+B = item widget
^!x::Launch("overlay")
^!b::Launch("widget")

Launch(cmd) {
    global APP
    Run('"' APP '" ' cmd, , "Hide")
}

ToggleAuto(*) {
    global NOAUTO
    if FileExist(NOAUTO)
        FileDelete(NOAUTO)
    else
        FileAppend("off", NOAUTO)
    RefreshAutoCheck()
}

RefreshAutoCheck() {
    global NOAUTO
    if FileExist(NOAUTO)
        A_TrayMenu.Uncheck("Auto-open at champ select")
    else
        A_TrayMenu.Check("Auto-open at champ select")
}

; Update notification: poll GitHub in the BACKGROUND and pop a tray balloon when a newer
; version exists - on launch AND every few hours (so it notifies mid-session, not just at
; boot). It also renames the menu item to "Update to vX" and flags the icon tooltip. The
; menu item runs the one-click installer.
g_updateVer := ""
g_updLabel := "Check for updates"
CheckUpdate() {
    global APP, g_updateVer, g_updLabel
    out := A_Temp "\smiteless_updchk.txt"
    try FileDelete(out)
    RunWait('"' APP '" update --check "' out '"', , "Hide")
    ver := ""
    try ver := Trim(FileRead(out), " `t`r`n")
    if (ver != "" && ver != g_updateVer) {
        g_updateVer := ver
        newLabel := "Update to " ver
        try A_TrayMenu.Rename(g_updLabel, newLabel)
        g_updLabel := newLabel
        A_IconTip := "Smiteless  -  update " ver " available"
        TrayTip("Version " ver " is ready. Right-click the gold S in your tray, then '"
            . newLabel "'.", "Smiteless update available", 1)
    }
}
SetTimer(CheckUpdate, -12000)                  ; first check ~12s after launch
SetTimer(CheckUpdate, 4 * 60 * 60 * 1000)      ; then every 4 hours

; Auto-open watcher: overlay at champ select, item widget in-game (gated by auto-open).
g_overlayOpened := false
g_widgetOpened := false
SmiteWatch() {
    global g_overlayOpened, g_widgetOpened, APP, NOAUTO
    if FileExist(NOAUTO)
        return
    if (!ProcessExist("LeagueClient.exe") && !ProcessExist("LeagueClientUx.exe") && !ProcessExist("League of Legends.exe")) {
        g_overlayOpened := false
        g_widgetOpened := false
        return
    }
    out := A_Temp "\smiteless_phase.txt"
    ph := ""
    try ph := Trim(FileRead(out), " `t`r`n")
    Run('"' APP '" phase "' out '"', , "Hide")
    active := (ph = "ChampSelect" || ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    ingame := (ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    if (active) {
        if (!g_overlayOpened) {
            g_overlayOpened := true
            Launch("overlay --wait")
        }
    } else {
        g_overlayOpened := false
    }
    if (ingame) {
        if (!g_widgetOpened) {
            g_widgetOpened := true
            Launch("widget")
        }
    } else {
        g_widgetOpened := false
    }
}
SetTimer(SmiteWatch, 4000)
