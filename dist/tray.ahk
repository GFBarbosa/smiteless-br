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
NOHOME := EnvGet("USERPROFILE") "\.claude\smiteless_nohomeonstart" ; present = open profile/home at startup OFF
UPDATED_MARK := A_ScriptDir "\.updated_version"
SETTINGS := EnvGet("USERPROFILE") "\.claude\smiteless_settings.json"   ; read to gate auto-accept

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
ShowPostUpdate()

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

ShowPostUpdate() {
    global UPDATED_MARK
    if !FileExist(UPDATED_MARK)
        return
    ver := ""
    try ver := Trim(FileRead(UPDATED_MARK), " `t`r`n")
    try FileDelete(UPDATED_MARK)
    if (ver != "") {
        TrayTip("Updated to " ver, "Smiteless updated", 1)
    }
}

OpenHomeOnStartup() {
    global NOHOME
    if FileExist(NOHOME)
        return
    Launch("profile")
}

AutoUpdateOnLaunch() {
    global APP
    ; Always attempt background update apply on startup. If already current/offline, it exits quietly.
    Run('"' APP '" update --apply', , "Hide")
}

; Update notification: poll GitHub in the BACKGROUND and pop a tray balloon when a newer
; version exists - on launch AND every few minutes (so it notifies mid-session, not just at
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
SetTimer(CheckUpdate, 5 * 60 * 1000)           ; then every 5 minutes
SetTimer(AutoUpdateOnLaunch, -7000)            ; auto-apply update attempt on launch
SetTimer(OpenHomeOnStartup, -9000)             ; open profile/home shortly after startup
SetTimer(AutoAcceptTick, 1200)                 ; poll ready-check and auto-accept if enabled

AutoAcceptTick() {
    ; Auto-accept entirely IN-PROCESS via the League client's local API - no app launch, so
    ; there's no busy-cursor flash (spawning the windowed app every poll was the flicker).
    if (!AutoAcceptOn())
        return
    if (!ProcessExist("LeagueClientUx.exe") && !ProcessExist("LeagueClient.exe"))
        return
    r := LcuReq("GET", "/lol-matchmaking/v1/ready-check")
    if (InStr(r, '"state":"InProgress"') && InStr(r, '"playerResponse":"None"'))
        LcuReq("POST", "/lol-matchmaking/v1/ready-check/accept")
}

AutoAcceptOn() {
    global SETTINGS
    try {
        return RegExMatch(FileRead(SETTINGS), '"auto_accept"\s*:\s*true') > 0
    }
    return false                                   ; no settings file / never enabled -> off
}

; ---- talk to the League client's local API (LCU) directly, so the tray never has to spawn
;      the app just to poll. Reads the lockfile for the port+password, ignores the client's
;      self-signed cert, and uses HTTP Basic auth. ----
LcuLockfile() {
    for d in StrSplit("FCDEGH", "") {
        p := d ":\Riot Games\League of Legends\lockfile"
        if FileExist(p)
            return p
    }
    return ""
}

LcuReq(method, path) {
    lf := LcuLockfile()
    if (lf = "")
        return ""
    try {
        parts := StrSplit(FileRead(lf), ":")
        port := parts[3], pw := parts[4]
    } catch
        return ""
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open(method, "https://127.0.0.1:" port path, false)
        req.Option[4] := 0x3300                    ; SslErrorIgnoreFlags - accept the self-signed cert
        req.SetRequestHeader("Authorization", "Basic " LcuB64("riot:" pw))
        req.SetRequestHeader("Accept", "application/json")
        if (method = "POST")
            req.SetRequestHeader("Content-Type", "application/json")
        req.SetTimeouts(1000, 1000, 1000, 1000)
        req.Send()
        return req.Status "`n" req.ResponseText
    } catch
        return ""
}

LcuB64(s) {
    n := StrPut(s, "UTF-8") - 1
    buf := Buffer(n)
    StrPut(s, buf, "UTF-8")
    flags := 0x40000001                            ; CRYPT_STRING_BASE64 | CRYPT_STRING_NOCRLF
    sz := 0
    DllCall("crypt32\CryptBinaryToStringW", "Ptr", buf, "UInt", n, "UInt", flags, "Ptr", 0, "UInt*", &sz)
    out := Buffer(sz * 2)
    DllCall("crypt32\CryptBinaryToStringW", "Ptr", buf, "UInt", n, "UInt", flags, "Ptr", out, "UInt*", &sz)
    return RTrim(StrGet(out, "UTF-16"), "`r`n")
}

; Auto-open watcher: overlay at champ select, item widget in-game (gated by auto-open).
g_overlayOpened := false
g_widgetOpened := false
g_wasInGame := false
SmiteWatch() {
    global g_overlayOpened, g_widgetOpened, g_wasInGame, APP, NOAUTO
    autoOpen := !FileExist(NOAUTO)
    if (!ProcessExist("LeagueClient.exe") && !ProcessExist("LeagueClientUx.exe") && !ProcessExist("League of Legends.exe")) {
        g_overlayOpened := false
        g_widgetOpened := false
        g_wasInGame := false
        SetTimer(SmiteWatch, -9000)                 ; client closed -> no spawn; just check back later
        return
    }
    out := A_Temp "\smiteless_phase.txt"
    ph := ""
    try ph := Trim(FileRead(out), " `t`r`n")
    Run('"' APP '" phase "' out '"', , "Hide")
    active := (ph = "ChampSelect" || ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    ingame := (ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    if (active && autoOpen) {
        if (!g_overlayOpened) {
            g_overlayOpened := true
            Launch("overlay --wait")
        }
    } else {
        g_overlayOpened := false
    }
    if (ingame && autoOpen) {
        if (!g_widgetOpened) {
            g_widgetOpened := true
            Launch("widget")
        }
    } else {
        g_widgetOpened := false
        if (g_wasInGame) {
            Launch("profile")
        }
    }
    g_wasInGame := ingame
    ; adaptive cadence: brisk while a session is live, slow while idle in the client - so the
    ; phase poll (which spawns the app) isn't flashing the cursor every few seconds when idle.
    SetTimer(SmiteWatch, active ? -3000 : -7000)
}
SetTimer(SmiteWatch, -3000)
