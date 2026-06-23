#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Smiteless - live League of Legends champ-select & in-game overlay.
;
; The overlay itself is a self-contained Python window (smiteoverlay.py): it polls the
; League client/API directly and updates IN PLACE as picks come in and the game
; progresses - no PNG file, no picture-reload. This script just LAUNCHES it (Win+B) and
; auto-launches it when a match starts. The window manages itself: opens on a second
; monitor, never steals focus from the game, Esc or click to close, and auto-closes at
; game end. It's single-instance, so re-launching while it's up is a harmless no-op.
;
; Run League in Borderless so the overlay shows over the game.
; ============================================================

; --- CONFIG -------------------------------------------------
; Python 3 with Pillow installed (pip install -r requirements.txt). "python" if on PATH.
PY := "python"
SCRIPTS := A_ScriptDir          ; the .py files live next to this script
; ------------------------------------------------------------

OpenSmiteless(autoMode := false) {
    global PY, SCRIPTS
    waitFlag := autoMode ? " --wait" : ""       ; auto-open stays hidden until champs are present
    Run(A_ComSpec ' /c ""' PY '" "' SCRIPTS '\smiteoverlay.py" --count 10' waitFlag ' 2>nul"', , "Hide")
}

#b::OpenSmiteless(false)

; Auto-open at CHAMP SELECT (and in-game). Polls the LCU gameflow phase via phasecheck.py
; (async, non-blocking) only while the client/game is running, and launches the overlay
; once per session. Resets when you return to lobby / post-game.
g_smiteOpened := false
SmiteWatch() {
    global g_smiteOpened, PY, SCRIPTS
    if (!ProcessExist("LeagueClient.exe") && !ProcessExist("LeagueClientUx.exe") && !ProcessExist("League of Legends.exe")) {
        g_smiteOpened := false                  ; LeagueClient.exe is the one present during champ select
        return
    }
    out := A_Temp "\smiteless_phase.txt"
    ph := ""
    try ph := Trim(FileRead(out), " `t`r`n")    ; strip CR/LF too - Trim's default omits only space/tab
    Run(A_ComSpec ' /c ""' PY '" "' SCRIPTS '\phasecheck.py" > "' out '" 2>nul"', , "Hide")
    active := (ph = "ChampSelect" || ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    if (active) {
        if (!g_smiteOpened) {
            g_smiteOpened := true
            OpenSmiteless(true)
        }
    } else {
        g_smiteOpened := false              ; any non-active phase re-arms
    }
}
SetTimer(SmiteWatch, 4000)
