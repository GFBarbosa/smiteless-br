#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Smiteless - League of Legends champ-select & in-game companion.
;
; Win+B opens one always-on-top window with three sections that fill in
; progressively (window stays responsive; Esc or the X closes it):
;   1) build card   - runes/build for your champ, live from op.gg   (lolbuild.py)
;   2) coach guide   - VERIFIED op.gg lane winrates + a strong/weak-side call
;                      computed from those numbers; optional AI commentary (lolcoach.py)
;   3) player scout  - LIVE Riot match data per player: account WR over the last
;                      10 ranked + their current-champ WR (lolscout.py). In-game only.
;
; Works in champ select, on the loading screen, and in-game (each section uses
; whatever data the current phase exposes). For the overlay to render over the
; game, run League in Borderless (fullscreen-exclusive hides all overlays).
; ============================================================

; --- CONFIG -------------------------------------------------
; Path to a Python 3 interpreter. The scripts use only the standard library,
; so any python3 works. Use "python" if it's on PATH, or an absolute path.
PY := "python"
; The .py scripts live next to this file by default.
SCRIPTS := A_ScriptDir
; ------------------------------------------------------------

#b:: {
    static lastGui := 0
    if lastGui {
        try lastGui.Destroy()
        lastGui := 0
    }
    buildScript := SCRIPTS "\lolbuild.py"
    coachScript := SCRIPTS "\lolcoach.py"
    scoutScript := SCRIPTS "\lolscout.py"
    buildOut := A_Temp "\smiteless_build.txt"
    stamp := A_TickCount
    coachOut := A_Temp "\smiteless_coach_" stamp ".txt"
    coachDone := A_Temp "\smiteless_coach_" stamp ".done"
    scoutOut := A_Temp "\smiteless_scout_" stamp ".txt"
    scoutDone := A_Temp "\smiteless_scout_" stamp ".done"

    ; --- Phase 1: build card (fast, blocking ~1-2s) ---
    ToolTip("Smiteless: pulling build card...")
    RunWait(A_ComSpec ' /c ""' PY '" "' buildScript '" > "' buildOut '" 2>&1"', , "Hide")
    ToolTip()
    buildText := ""
    try buildText := FileRead(buildOut, "UTF-8")
    if (Trim(buildText) = "")
        buildText := "No build card. Is the League client in champ select / a game running?"

    sepC := "`r`n`r`n------------ matchup & macro guide ------------`r`n`r`n"
    sepS := "`r`n`r`n------------ player scout (live Riot data) ------------`r`n`r`n"
    coachWait := "Reading the game... quick read in a few seconds, AI commentary upgrades it (~30-90s)."
    scoutWait := "Scouting players (live, in-game only; ~2 min first run, instant once cached)..."

    g := Gui("+AlwaysOnTop +Resize", "Smiteless")
    g.SetFont("s10", "Consolas")
    ctrl := g.Add("Edit", "ReadOnly -Wrap +HScroll w900 r40", buildText sepC coachWait sepS scoutWait)
    g.OnEvent("Escape", (*) => g.Destroy())
    g.OnEvent("Close", (*) => g.Destroy())
    g.Show("AutoSize")
    lastGui := g

    ; --- Phases 2 & 3: coach + scout run async, each streaming to its own file.
    ;     The poller re-reads both every tick and concatenates. ---
    Run(A_ComSpec ' /c ""' PY '" "' coachScript '" --out "' coachOut '" --fm "' coachDone '" 2>nul"', , "Hide")
    Run(A_ComSpec ' /c ""' PY '" "' scoutScript '" --out "' scoutOut '" --fm "' scoutDone '" 2>nul"', , "Hide")
    startTick := A_TickCount
    lastShown := ""

    Poll() {
        hwnd := 0
        try hwnd := g.Hwnd
        if (!hwnd || !WinExist("ahk_id " hwnd))
            return
        coachTxt := coachWait
        if FileExist(coachOut) {
            t := ""
            try t := FileRead(coachOut, "UTF-8")
            if (Trim(t) != "")
                coachTxt := t
        }
        scoutTxt := scoutWait
        if FileExist(scoutOut) {
            t := ""
            try t := FileRead(scoutOut, "UTF-8")
            if (Trim(t) != "")
                scoutTxt := t
        }
        content := buildText sepC coachTxt sepS scoutTxt
        if (content != lastShown) {
            try ctrl.Value := content
            lastShown := content
        }
        if ((FileExist(coachDone) && FileExist(scoutDone)) || (A_TickCount - startTick > 190000))
            return
        SetTimer(Poll, -500)
    }
    SetTimer(Poll, -500)
}
