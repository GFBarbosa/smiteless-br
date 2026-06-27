#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Smiteless - persistent tray app.
;
; Sits in the system tray with a right-click menu:
;   Open overlay | Item widget | Settings | Auto-open at champ select (toggle) | Reload | Exit
; It auto-opens the overlay at champ select and the floating item widget in-game (while
; auto-open is on and the client is up). Hotkeys: Ctrl+Alt+X = overlay, Ctrl+Alt+B = item
; widget (both global). The windows are Python (smiteoverlay.py / smitewidget.py /
; smitesettings.py); this script is just the persistent shell.
; ============================================================

; --- CONFIG -------------------------------------------------
PY := "python"                  ; Python 3 + Pillow. Set to your python.exe if not on PATH.
PYW := RegExReplace(PY, "i)python(\.exe)?$", "pythonw$1")   ; windowless python -> no console flash
if (InStr(PYW, "\") && !FileExist(PYW))                     ; full path that doesn't exist -> fall back
    PYW := PY
SCRIPTS := A_ScriptDir          ; the .py files live in core/ ui/ tools/ under this dir
; ------------------------------------------------------------

NOAUTO := EnvGet("USERPROFILE") "\.claude\smiteless_noautoopen"   ; present = auto-open OFF

if FileExist(SCRIPTS "\assets\smiteless.ico")
    TraySetIcon(SCRIPTS "\assets\smiteless.ico")
A_IconTip := "Smiteless"

tray := A_TrayMenu
tray.Delete()                                   ; replace the default AHK menu
tray.Add("Open overlay", (*) => OpenSmiteless(false))
tray.Add("Profile / home", (*) => OpenProfile())
tray.Add("Item widget", (*) => OpenWidget())
tray.Add("Settings", (*) => OpenSettings())
tray.Add()
tray.Add("Auto-open at champ select", ToggleAuto)
tray.Add()
tray.Add("Reload", (*) => Reload())
tray.Add("Exit", (*) => ExitApp())
tray.Default := "Open overlay"                  ; double-click the tray icon
RefreshAutoCheck()

; Ctrl+Alt+X opens the overlay; Ctrl+Alt+B opens the floating item widget - both global.
^!x::OpenSmiteless(false)
^!b::OpenWidget()

OpenSmiteless(autoMode := false) {
    global PYW, SCRIPTS
    waitFlag := autoMode ? " --wait" : ""       ; auto-open stays hidden until champs are present
    Run('"' PYW '" "' SCRIPTS '\ui\smiteoverlay.py"' waitFlag, , "Hide")
}

OpenWidget() {
    global PYW, SCRIPTS                           ; small floating in-game item helper (single-instance)
    Run('"' PYW '" "' SCRIPTS '\ui\smitewidget.py"', , "Hide")
}

OpenProfile() {
    global PYW, SCRIPTS                           ; the home / profile window
    Run('"' PYW '" "' SCRIPTS '\ui\smiteprofile.py"', , "Hide")
}

OpenSettings() {
    global PYW, SCRIPTS
    Run('"' PYW '" "' SCRIPTS '\ui\smitesettings.py"', , "Hide")
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
g_widgetOpened := false
SmiteWatch() {
    global g_smiteOpened, g_widgetOpened, PYW, SCRIPTS, NOAUTO
    if FileExist(NOAUTO)                         ; auto-open disabled
        return
    if (!ProcessExist("LeagueClient.exe") && !ProcessExist("LeagueClientUx.exe") && !ProcessExist("League of Legends.exe")) {
        g_smiteOpened := false
        g_widgetOpened := false
        return
    }
    out := A_Temp "\smiteless_phase.txt"
    ph := ""
    try ph := Trim(FileRead(out), " `t`r`n")     ; strip CR/LF (Trim's default omits them)
    Run('"' PYW '" "' SCRIPTS '\smiteless_main.py" phase "' out '"', , "Hide")   ; writes phase to file (no console)
    active := (ph = "ChampSelect" || ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    ingame := (ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    if (active) {
        if (!g_smiteOpened) {
            g_smiteOpened := true
            OpenSmiteless(true)
        }
    } else {
        g_smiteOpened := false                   ; any non-active phase re-arms for the next game
    }
    if (ingame) {                                ; the floating item helper is in-game only
        if (!g_widgetOpened) {
            g_widgetOpened := true
            OpenWidget()
        }
    } else {
        g_widgetOpened := false
    }
}
SetTimer(SmiteWatch, 4000)
