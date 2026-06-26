#!/usr/bin/env python3
"""smitesettings.py - Smiteless settings window (Tk). Launched from the tray menu.

A normal (focusable) window - unlike the overlay - so you can tweak it like any dialog.
Everything it saves is read live by the overlay (smitecard.apply_settings each frame).
"""
import sys, os, ctypes
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import smiteconfig as cfg

BG = "#11131a"; PANEL = "#171a24"; GOLD = "#c8aa6e"; TXT = "#d8d6cf"; MUTED = "#9b988e"
GREEN = "#5fc47a"; TROUGH = "#0d0f16"; BTN = "#262b3b"; BTN_A = "#333a52"
HERE = os.path.dirname(os.path.abspath(__file__))


def _single_instance():
    k = ctypes.windll.kernel32
    k.CreateMutexW(None, False, "Global\\SmitelessSettings")
    return k.GetLastError() != 183   # ERROR_ALREADY_EXISTS


def main():
    if not _single_instance():
        return
    import tkinter as tk
    s = cfg.load()
    root = tk.Tk()
    root.title("Smiteless Settings")
    root.configure(bg=BG)
    root.resizable(False, False)
    try:
        root.iconbitmap(os.path.join(HERE, "smiteless.ico"))
    except Exception:
        pass

    tk.Label(root, text="SMITELESS  SETTINGS", bg=BG, fg=GOLD,
             font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=18, pady=(16, 1))
    tk.Label(root, text="Changes apply live - the overlay's gank tags update within a few seconds.",
             bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(0, 8))

    def scale_row(title, desc, lo, hi, res, val, fmt):
        fr = tk.Frame(root, bg=PANEL)
        fr.pack(fill="x", padx=14, pady=5)
        top = tk.Frame(fr, bg=PANEL)
        top.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(top, text=title, bg=PANEL, fg=TXT, font=("Segoe UI", 10, "bold")).pack(side="left")
        valv = tk.StringVar()
        tk.Label(top, textvariable=valv, bg=PANEL, fg=GOLD, font=("Consolas", 10, "bold")).pack(side="right")
        sc = tk.Scale(fr, from_=lo, to=hi, resolution=res, orient="horizontal", showvalue=0,
                      bg=PANEL, fg=TXT, troughcolor=TROUGH, highlightthickness=0, bd=0,
                      activebackground=GOLD, sliderrelief="flat", length=440)
        sc.set(val)
        sc.pack(fill="x", padx=10)
        descv = tk.StringVar()
        tk.Label(fr, textvariable=descv, bg=PANEL, fg=MUTED, font=("Segoe UI", 8),
                 anchor="w", justify="left").pack(fill="x", padx=12, pady=(0, 8))

        def upd(_=None):
            v = sc.get()
            valv.set(fmt(v))
            descv.set(desc(v) if callable(desc) else desc)
        sc.config(command=upd)
        upd()
        return sc

    def infl_desc(v):
        if v < 5:
            return "0 = ignore how they're doing; pure champ-vs-champ matchup"
        if v > 80:
            return "win/loss streak & form dominate the gank rating"
        if 45 <= v <= 55:
            return "50 = balanced (default): matchup is the base, form nudges it"
        return "champ matchup weighs more" if v < 50 else "form / streak weighs more"

    infl = scale_row("Win / loss streak influence", infl_desc,
                     0, 100, 1, s["streak_influence"], lambda v: f"{int(v)}")
    thr = scale_row("Gank decisiveness (threshold)",
                    "lower = more lanes tagged GANK / TOUGH; higher = only the clear ones",
                    3, 12, 0.5, s["gank_threshold"], lambda v: f"{float(v):.1f}")
    scout = scale_row("Scout depth (games / player)",
                      "more games = steadier form read, but a slower first scout",
                      5, 20, 1, s["scout_games"], lambda v: f"{int(v)}")

    auto = tk.BooleanVar(value=cfg.auto_open_enabled())
    startwin = tk.BooleanVar(value=cfg.autostart_enabled())

    def _chk(parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=BG, fg=TXT, selectcolor=TROUGH,
                              activebackground=BG, activeforeground=TXT, font=("Segoe UI", 9),
                              bd=0, highlightthickness=0)

    afr = tk.Frame(root, bg=BG)
    afr.pack(fill="x", padx=16, pady=(8, 0))
    _chk(afr, "Auto-open at champ select", auto).pack(side="left")
    _chk(afr, "Start with Windows", startwin).pack(side="left", padx=(18, 0))

    status = tk.Label(root, text="", bg=BG, fg=GREEN, font=("Segoe UI", 8))
    status.pack(anchor="w", padx=18, pady=(6, 0))

    def save():
        cfg.save({"streak_influence": int(infl.get()),
                  "gank_threshold": float(thr.get()),
                  "scout_games": int(scout.get())})
        cfg.set_auto_open(auto.get())
        cfg.set_autostart(startwin.get())
        status.config(text="saved ✓  (overlay updates live; auto-open next game)", fg=GREEN)

    def reset():
        infl.set(cfg.DEFAULTS["streak_influence"])
        thr.set(cfg.DEFAULTS["gank_threshold"])
        scout.set(cfg.DEFAULTS["scout_games"])
        auto.set(True)
        status.config(text="reset to defaults - click Save to apply", fg=MUTED)

    def mkbtn(parent, text, cmd, accent=False):
        return tk.Button(parent, text=text, command=cmd, bg=(GOLD if accent else BTN),
                         fg=(BG if accent else TXT), activebackground=(GOLD if accent else BTN_A),
                         activeforeground=(BG if accent else TXT), relief="flat", bd=0, padx=16, pady=5,
                         font=("Segoe UI", 9, "bold"), cursor="hand2")

    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=14, pady=(10, 16))
    mkbtn(btns, "Save", save, accent=True).pack(side="left", padx=4)
    mkbtn(btns, "Reset", reset).pack(side="left", padx=4)
    mkbtn(btns, "Close", root.destroy).pack(side="right", padx=4)

    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
