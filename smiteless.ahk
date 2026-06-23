#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Smiteless - League of Legends champ-select & in-game companion.
;
; A scoreboard-style overlay rendered as an image by smitecard.py:
;   - build/runes header for your champ (op.gg)
;   - both teams aligned by role, matchups paired by the REAL champ in each slot
;   - a data-only gank rating per enemy lane (your lane WR + enemy recent form)
;   - a last-10 W/L form bar per player (live Riot match history)
;   - a lane matchup + macro panel when you lock a lane (not jungle)
; The image renders progressively and reloads as it updates.
;
;   - Auto-opens when a match starts, holding until the loading screen has champs.
;   - Win+B reopens it after you close it.
;   - Opens on a second monitor if you have one.
;
; Player scouting is in-game only. Run League in Borderless so it shows over the
; game. Esc / X closes.
; ============================================================

; --- CONFIG -------------------------------------------------
; Python 3 with Pillow installed (pip install Pillow). "python" if on PATH.
PY := "python"
SCRIPTS := A_ScriptDir          ; the .py files live next to this script
; ------------------------------------------------------------

#b::OpenSmiteless(false)

OpenSmiteless(autoMode := false) {
    global PY, SCRIPTS
    static lastGui := 0
    if lastGui {
        try lastGui.Destroy()
        lastGui := 0
    }
    cardScript := SCRIPTS "\smitecard.py"
    stamp := A_TickCount
    img := A_Temp "\smitecard_" stamp ".png"
    done := A_Temp "\smitecard_" stamp ".done"
    waitFlag := autoMode ? " --wait" : ""       ; auto-open waits for the champs to load

    if (!autoMode)
        ToolTip("Smiteless: reading game...")
    Run(A_ComSpec ' /c ""' PY '" "' cardScript '" --out "' img '" --fm "' done '" --count 10' waitFlag ' 2>nul"', , "Hide")
    startTick := A_TickCount
    g := 0
    pic := 0
    lastMod := ""
    lastH := 0

    Poll() {
        if (!g) {
            if (!FileExist(img)) {
                if (A_TickCount - startTick > 90000) {
                    ToolTip()
                    return
                }
                SetTimer(Poll, -400)
                return
            }
            ToolTip()
            g := Gui("+AlwaysOnTop +Resize", "Smiteless")
            g.MarginX := 0, g.MarginY := 0
            pic := g.Add("Picture", "w920", img)
            g.OnEvent("Escape", (*) => g.Destroy())
            g.OnEvent("Close", (*) => g.Destroy())
            g.Show("AutoSize NoActivate")        ; show on top WITHOUT stealing focus from the game
            SmitePlaceWindow(g)
            lastGui := g
            lastMod := FileGetTime(img, "M")
            try lastH := Integer(Trim(FileRead(img ".dim")))
        } else {
            hwnd := 0
            try hwnd := g.Hwnd
            if (!hwnd || !WinExist("ahk_id " hwnd))
                return
            m := FileGetTime(img, "M")
            if (m != lastMod) {
                try pic.Value := img
                nh := 0
                try nh := Integer(Trim(FileRead(img ".dim")))
                if (nh > 0 && nh != lastH) {        ; height changed -> resize in place (keep position + focus)
                    WinGetPos(&wx, &wy, , , "ahk_id " g.Hwnd)
                    pic.Move(, , 920, nh)
                    g.Show("AutoSize NoActivate")
                    WinMove(wx, wy, , , "ahk_id " g.Hwnd)
                    lastH := nh
                }
                lastMod := m
            }
        }
        if (FileExist(done) || (A_TickCount - startTick > 420000))
            return
        SetTimer(Poll, -500)
    }
    SetTimer(Poll, -500)
}

SmitePlaceWindow(g) {
    if (MonitorGetCount() <= 1)
        return
    prim := MonitorGetPrimary()
    target := 0
    loop MonitorGetCount() {
        if (A_Index != prim) {
            target := A_Index
            break
        }
    }
    if (!target)
        return
    MonitorGetWorkArea(target, &L, &T, &R, &B)
    WinGetPos(, , &w, &h, "ahk_id " g.Hwnd)
    WinMove(L + ((R - L) - w) // 2, T + ((B - T) - h) // 2, , , "ahk_id " g.Hwnd)
}

; Auto-open at CHAMP SELECT (and in-game). Polls the LCU gameflow phase via
; phasecheck.py (async, non-blocking) only while the client/game is running, and
; opens once per session. Resets when you return to lobby / post-game.
g_smiteOpened := false
SmiteWatch() {
    global g_smiteOpened, PY, SCRIPTS
    if (!ProcessExist("LeagueClientUx.exe") && !ProcessExist("League of Legends.exe")) {
        g_smiteOpened := false
        return
    }
    out := A_Temp "\smiteless_phase.txt"
    ph := ""
    try ph := Trim(FileRead(out))
    Run(A_ComSpec ' /c ""' PY '" "' SCRIPTS '\phasecheck.py" > "' out '" 2>nul"', , "Hide")
    active := (ph = "ChampSelect" || ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    if (active && !g_smiteOpened) {
        g_smiteOpened := true
        OpenSmiteless(true)
    } else if (ph = "Lobby" || ph = "None" || ph = "Matchmaking" || ph = "EndOfGame" || ph = "PreEndOfGame" || ph = "WaitingForStats") {
        g_smiteOpened := false
    }
}
SetTimer(SmiteWatch, 4000)
