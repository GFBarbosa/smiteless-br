#!/usr/bin/env python3
"""smiteless_main.py - single entry point for the bundled app.

One frozen exe (SmitelessApp.exe) covers every window/tool; the first CLI arg picks which:

    SmitelessApp.exe overlay        the scoreboard overlay (default)
    SmitelessApp.exe widget         the floating item widget
    SmitelessApp.exe settings       the settings window
    SmitelessApp.exe phase <file>   write the LCU gameflow phase to <file> (for the tray watcher)
    SmitelessApp.exe autoaccept     auto-accept queue ready checks (when enabled)
    SmitelessApp.exe update [--apply]  check GitHub for a newer release (notify / one-click)
    SmitelessApp.exe selftest       dependency health check (dev)

Kept tiny on purpose so PyInstaller has a clean root to analyse.
"""
import os
import sys

# Dev (not frozen): make the flat imports resolve from the source folders. When frozen,
# every module is bundled into the exe, so these inserts are harmless no-ops.
if not getattr(sys, "frozen", False):
    _R = os.path.dirname(os.path.abspath(__file__))
    for _d in ("core", "ui", "tools"):
        sys.path.insert(0, os.path.join(_R, _d))


for _s in ("stdout", "stderr"):                # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass


def main():
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "overlay").lower()
    rest = sys.argv[2:]
    sys.argv = [sys.argv[0]] + rest                  # downstream sees only its own flags

    if cmd == "overlay":
        import smiteoverlay
        smiteoverlay.main()
    elif cmd == "widget":
        import smitewidget
        smitewidget.main()
    elif cmd == "settings":
        import smitesettings
        smitesettings.main()
    elif cmd == "profile":
        import smiteprofile
        smiteprofile.main()
    elif cmd == "phase":
        import tempfile
        import phasecheck
        out = rest[0] if rest else os.path.join(tempfile.gettempdir(), "smiteless_phase.txt")
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(phasecheck.phase() or "")
        except Exception:
            pass
    elif cmd == "autoaccept":
        import lolautoaccept
        lolautoaccept.main()
    elif cmd == "update":
        import smiteupdate
        smiteupdate.main(rest)
    elif cmd == "selftest":
        import selftest
        selftest.main()
    else:
        sys.stderr.write("usage: SmitelessApp.exe [overlay|widget|settings|phase|autoaccept|update|selftest]\n")


if __name__ == "__main__":
    main()
