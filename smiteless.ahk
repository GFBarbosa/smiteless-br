#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Smiteless - persistent tray app.
;
; Sits in the system tray with a right-click menu:
;   Open overlay | Settings | Auto-open at champ select (toggle) | Reload | Exit
; It auto-opens the overlay at champ select (while auto-open is on and the client is up)
; and binds Ctrl+Alt+X (global). The overlay/settings windows are Python
; (smiteoverlay.py / smitesettings.py); this script is just the persistent shell.
; ============================================================

; --- CONFIG -------------------------------------------------
PY := "python"                  ; Python 3 + Pillow. Set to your python.exe if not on PATH.
SCRIPTS := A_ScriptDir          ; the .py files live next to this script
; ------------------------------------------------------------

NOAUTO := EnvGet("USERPROFILE") "\.claude\smiteless_noautoopen"   ; present = auto-open OFF

if FileExist(SCRIPTS "\smiteless.ico")
    TraySetIcon(SCRIPTS "\smiteless.ico")
A_IconTip := "Smiteless"

tray := A_TrayMenu
tray.Delete()                                   ; replace the default AHK menu
tray.Add("Open overlay", (*) => OpenSmiteless(false))
tray.Add("Settings", (*) => OpenSettings())
tray.Add()
tray.Add("Auto-open at champ select", ToggleAuto)
tray.Add()
tray.Add("Reload", (*) => Reload())
tray.Add("Exit", (*) => ExitApp())
tray.Default := "Open overlay"                  ; double-click the tray icon
RefreshAutoCheck()

; Ctrl+Alt+X opens the overlay - global (works anywhere, anytime).
^!x::OpenSmiteless(false)

OpenSmiteless(autoMode := false) {
    global PY, SCRIPTS
    waitFlag := autoMode ? " --wait" : ""       ; auto-open stays hidden until champs are present
    Run(A_ComSpec ' /c ""' PY '" "' SCRIPTS '\smiteoverlay.py"' waitFlag ' 2>nul"', , "Hide")
}

OpenSettings() {
    global PY, SCRIPTS
    Run(A_ComSpec ' /c ""' PY '" "' SCRIPTS '\smitesettings.py" 2>nul"', , "Hide")
}

ToggleAuto(ItemName, *) {
    global NOAUTO
    if FileExist(NOAUTO)
        FileDelete(NOAUTO)                       ; enable auto-open
    else
        FileAppend("off", NOAUTO)                ; disable auto-open
    RefreshAutoCheck()
}

RefreshAutoCheck() {
    global NOAUTO
    if FileExist(NOAUTO)
        A_TrayMenu.Uncheck("Auto-open at champ select")
    else
        A_TrayMenu.Check("Auto-open at champ select")
}

; Auto-open watcher: only while auto-open is on AND the client/game is up. Polls the LCU
; gameflow phase via phasecheck.py (async) and opens the overlay once per active session.
g_smiteOpened := false
SmiteWatch() {
    global g_smiteOpened, PY, SCRIPTS, NOAUTO
    if FileExist(NOAUTO)                         ; auto-open disabled
        return
    if (!ProcessExist("LeagueClient.exe") && !ProcessExist("LeagueClientUx.exe") && !ProcessExist("League of Legends.exe")) {
        g_smiteOpened := false
        return
    }
    out := A_Temp "\smiteless_phase.txt"
    ph := ""
    try ph := Trim(FileRead(out), " `t`r`n")     ; strip CR/LF (Trim's default omits them)
    Run(A_ComSpec ' /c ""' PY '" "' SCRIPTS '\phasecheck.py" > "' out '" 2>nul"', , "Hide")
    active := (ph = "ChampSelect" || ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    if (active) {
        if (!g_smiteOpened) {
            g_smiteOpened := true
            OpenSmiteless(true)
        }
    } else {
        g_smiteOpened := false                   ; any non-active phase re-arms for the next game
    }
}
SetTimer(SmiteWatch, 4000)
