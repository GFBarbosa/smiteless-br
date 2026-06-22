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
; The image renders progressively (build/lanes first, player scout fills in over
; ~2 min in-game) and reloads as it updates.
;
;   - Auto-opens when a match starts (loading screen onward).
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

#b::OpenSmiteless()

OpenSmiteless() {
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

    ToolTip("Smiteless: reading game...")
    Run(A_ComSpec ' /c ""' PY '" "' cardScript '" --out "' img '" --fm "' done '" --count 10 2>nul"', , "Hide")
    startTick := A_TickCount
    g := 0
    pic := 0
    lastMod := ""

    Poll() {
        if (!g) {
            if (!FileExist(img)) {
                if (A_TickCount - startTick > 30000) {
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
            g.Show("AutoSize")
            SmitePlaceWindow(g)
            lastGui := g
            lastMod := FileGetTime(img, "M")
        } else {
            hwnd := 0
            try hwnd := g.Hwnd
            if (!hwnd || !WinExist("ahk_id " hwnd))
                return
            m := FileGetTime(img, "M")
            if (m != lastMod) {
                try pic.Value := img
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

; Auto-open once per game. The in-game client is "League of Legends.exe"
; (distinct from the launcher "LeagueClient.exe").
g_smiteGamePid := 0
SmiteWatch() {
    global g_smiteGamePid
    pid := ProcessExist("League of Legends.exe")
    if (pid && pid != g_smiteGamePid) {
        g_smiteGamePid := pid
        OpenSmiteless()
    } else if (!pid) {
        g_smiteGamePid := 0
    }
}
SetTimer(SmiteWatch, 4000)
