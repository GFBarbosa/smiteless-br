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

; Check GitHub for a newer release ~6s after startup (silent unless an update exists).
SetTimer(() => Launch("update"), -6000)

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
