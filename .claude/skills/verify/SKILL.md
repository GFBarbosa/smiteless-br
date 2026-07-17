---
name: verify
description: How to build, run, and visually verify Smiteless changes on this machine.
---

# Verifying Smiteless

Dev-run any window directly (imports resolve via the path inserts in each entry file):

    cd C:\Users\bobby\smiteless
    python ui\smitesettings.py          # settings (single-instance mutex "Global\SmitelessSettings")
    python ui\smiteprofile.py           # profile/home
    python smiteless_main.py <cmd>      # overlay|widget|settings|profile|phase|login <name>|accounts|...

Health check: `python tools\selftest.py` (needs network + the League client for the LCU line).

AHK syntax check (must use PowerShell — Git Bash mangles the /switches into paths):

    $ahk = "$env:LOCALAPPDATA\Programs\AutoHotkey\v2\AutoHotkey64.exe"
    Start-Process $ahk -ArgumentList '/ErrorStdOut','/Validate','<script>.ahk' -Wait -PassThru -NoNewWindow
    # exit 0 = clean; the plain `& $ahk` form does not surface the exit code

GUI evidence: windows are Tk. Find by title (`FindWindowW(None, "Smiteless Settings")`),
scroll with WM_MOUSEWHEEL SendMessage, capture with PrintWindow(PW_RENDERFULLCONTENT) +
GetDIBits so it works while occluded. **Never SetForegroundWindow / SetCursorPos clicks —
the user is often mid-game fullscreen.** Synthetic WM_LBUTTONDOWN/UP PostMessage at client
coords works on Tk without stealing focus.

Frozen build: `dist\build.ps1` → run `build\pyi\SmitelessApp\SmitelessApp.exe <cmd>` to
verify the shipped artifact. Full release: `dist\make-release.ps1 -Version X.Y.Z`
(+0.0.1 bumps, CHANGELOG entry first — it feeds the in-app Patch Notes).

Destructive paths: anything that kills the Riot/League clients (`lolaccounts.switch`)
or fires LCU POSTs mid-queue — don't drive live; test the engine functions and refusal
paths instead.
