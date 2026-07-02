#!/usr/bin/env python3
"""smitesettings.py - Smiteless settings window (Tk). Launched from the tray menu.

A normal (focusable) window - unlike the overlay - so you can tweak it like any dialog.
Everything it saves is read live by the overlay (smitecard.apply_settings each frame).
"""
import sys, os, ctypes, webbrowser
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):                # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass
import smiteconfig as cfg
import lolscout as ls

BG = "#11131a"; PANEL = "#171a24"; GOLD = "#c8aa6e"; TXT = "#d8d6cf"; MUTED = "#9b988e"
GREEN = "#5fc47a"; RED = "#d46d78"; TROUGH = "#0d0f16"; BTN = "#262b3b"; BTN_A = "#333a52"
ENTRY_BG = "#0f1219"
HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILES = [os.path.expanduser("~/.riot_api_key"), os.path.expanduser("~/.riot_api_key.txt")]


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
    root.resizable(True, True)
    try:
        root.iconbitmap(os.path.join(HERE, "smiteless.ico"))
    except Exception:
        pass

    shell = tk.Frame(root, bg=BG)
    shell.pack(fill="both", expand=True)
    vbar = tk.Scrollbar(shell, orient="vertical")
    vbar.pack(side="right", fill="y")
    canvas = tk.Canvas(shell, bg=BG, highlightthickness=0, yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.config(command=canvas.yview)
    body = tk.Frame(canvas, bg=BG)
    body_id = canvas.create_window((0, 0), window=body, anchor="nw")

    def _sync_scroll(_=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(body_id, width=canvas.winfo_width())
    body.bind("<Configure>", _sync_scroll)
    canvas.bind("<Configure>", _sync_scroll)
    root.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

    tk.Label(body, text="SMITELESS  SETTINGS", bg=BG, fg=GOLD,
             font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=18, pady=(16, 1))
    tk.Label(body, text="Changes apply live - the overlay's gank tags update within a few seconds.",
             bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(0, 8))

    def scale_row(title, desc, lo, hi, res, val, fmt):
        fr = tk.Frame(body, bg=PANEL)
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
    pgames = scale_row("Profile: games to load",
                       "how many recent games the home/profile page loads (and per 'Load more')",
                       5, 60, 1, s["profile_games"], lambda v: f"{int(v)}")
    dvol = scale_row("Dragon spawn volume",
                     "how loud the 45/30/15s drake chime is (0 = silent). Applies next game.",
                     0, 100, 5, s.get("dragon_volume", 30), lambda v: f"{int(v)}")

    auto = tk.BooleanVar(value=cfg.auto_open_enabled())
    homeonstart = tk.BooleanVar(value=cfg.home_on_start_enabled())
    startwin = tk.BooleanVar(value=cfg.autostart_enabled())

    def _chk(parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=BG, fg=TXT, selectcolor=TROUGH,
                              activebackground=BG, activeforeground=TXT, font=("Segoe UI", 9),
                              bd=0, highlightthickness=0)

    tips = tk.BooleanVar(value=s["matchup_tips"])
    kit = tk.BooleanVar(value=s["gank_kit"])
    duo = tk.BooleanVar(value=s["duo_detection"])
    widget = tk.BooleanVar(value=s["item_widget"])
    autoq = tk.BooleanVar(value=s.get("auto_accept", False))
    intel = tk.BooleanVar(value=s.get("game_intel", True))
    dragon = tk.BooleanVar(value=s.get("dragon_audio", True))
    dodge = tk.BooleanVar(value=s.get("dodge_alerts", True))
    flash_side = tk.IntVar(value=(0 if s.get("flash_on_d", True) else 1))  # 0=D, 1=F

    tk.Label(body, text="FEATURES", bg=BG, fg=GOLD, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(10, 2))
    ffr = tk.Frame(body, bg=BG)
    ffr.pack(fill="x", padx=16)
    col1 = tk.Frame(ffr, bg=BG); col1.pack(side="left", fill="x", expand=True, anchor="n")
    col2 = tk.Frame(ffr, bg=BG); col2.pack(side="left", fill="x", expand=True, anchor="n")
    _chk(col1, "In-game item widget", widget).pack(anchor="w")
    _chk(col1, "Live game intel (timers + win read)", intel).pack(anchor="w")
    _chk(col1, "Dragon spawn audio (45/30/15s)", dragon).pack(anchor="w")
    _chk(col1, "Matchup lane tips (AI)", tips).pack(anchor="w")
    _chk(col1, "Auto-accept queue", autoq).pack(anchor="w")
    _chk(col2, "Your champ's kit in gank rating", kit).pack(anchor="w")
    _chk(col2, "Duo / premade detection", duo).pack(anchor="w")
    _chk(col2, "Dodge alerts (champ select)", dodge).pack(anchor="w")

    fkey = tk.Frame(body, bg=PANEL)
    fkey.pack(fill="x", padx=14, pady=(6, 2))
    tk.Label(fkey, text="FLASH KEY", bg=PANEL, fg=TXT, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
    row = tk.Frame(fkey, bg=PANEL)
    row.pack(fill="x", padx=12, pady=(2, 8))
    tk.Label(row, text="D", bg=PANEL, fg=GOLD, font=("Segoe UI", 9, "bold")).pack(side="left")
    fscale = tk.Scale(row, from_=0, to=1, resolution=1, orient="horizontal", showvalue=0,
                      variable=flash_side, bg=PANEL, fg=TXT, troughcolor=TROUGH, highlightthickness=0,
                      bd=0, activebackground=GOLD, sliderrelief="flat", length=180)
    fscale.pack(side="left", padx=8)
    tk.Label(row, text="F", bg=PANEL, fg=GOLD, font=("Segoe UI", 9, "bold")).pack(side="left")
    fstat = tk.StringVar()
    tk.Label(row, textvariable=fstat, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(10, 0))

    def _upd_flash(_=None):
        fstat.set("Flash on D" if flash_side.get() == 0 else "Flash on F")
    fscale.config(command=_upd_flash)
    _upd_flash()

    tk.Label(body, text="STARTUP", bg=BG, fg=GOLD, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(10, 2))
    afr = tk.Frame(body, bg=BG)
    afr.pack(fill="x", padx=16, pady=(0, 0))
    _chk(afr, "Auto-open at champ select", auto).pack(side="left")
    _chk(afr, "Open profile/home on startup", homeonstart).pack(side="left", padx=(18, 0))
    _chk(afr, "Start with Windows", startwin).pack(side="left", padx=(18, 0))

    tk.Label(body, text="RIOT API KEY", bg=BG, fg=GOLD, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(12, 2))
    keyfr = tk.Frame(body, bg=PANEL)
    keyfr.pack(fill="x", padx=14, pady=(0, 5))
    top = tk.Frame(keyfr, bg=PANEL)
    top.pack(fill="x", padx=12, pady=(8, 0))
    tk.Label(top, text="Current key:", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")
    keylbl = tk.Label(top, text="", bg=PANEL, fg=MUTED, font=("Consolas", 9, "bold"))
    keylbl.pack(side="left", padx=(6, 0))

    row = tk.Frame(keyfr, bg=PANEL)
    row.pack(fill="x", padx=10, pady=(6, 2))
    key_entry = tk.Entry(row, bg=ENTRY_BG, fg=TXT, insertbackground=TXT, relief="flat",
                         font=("Consolas", 9), width=44)
    key_entry.pack(side="left", fill="x", expand=True, ipady=3)

    key_status = tk.Label(keyfr, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 8),
                          anchor="w", justify="left")
    key_status.pack(fill="x", padx=12, pady=(2, 8))
    tk.Label(keyfr, text="Saved to ~/.riot_api_key and ~/.riot_api_key.txt", bg=PANEL,
             fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=12, pady=(0, 8))

    def refresh_key_label():
        k = ls.read_key()
        if k and k.startswith("RGAPI-"):
            keylbl.config(text=f"...{k[-4:]} set", fg=GREEN)
        else:
            keylbl.config(text="not set", fg=RED)

    def open_dev_site():
        webbrowser.open("https://developer.riotgames.com/")
        key_status.config(text="log in, copy your key, then Paste + Save", fg=MUTED)

    def paste_key():
        try:
            c = root.clipboard_get().strip()
        except Exception:
            key_status.config(text="clipboard is empty", fg=RED)
            return
        key_entry.delete(0, "end")
        key_entry.insert(0, c)
        key_status.config(text="pasted - review it, then Save", fg=MUTED)

    def save_key():
        k = key_entry.get().strip()
        if not (k.startswith("RGAPI-") and len(k) >= 24):
            key_status.config(text="that doesn't look like an RGAPI-... key", fg=RED)
            return
        for p in KEY_FILES:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(k)
            except Exception as e:
                key_status.config(text=f"save failed: {e}", fg=RED)
                return
        key_entry.delete(0, "end")
        refresh_key_label()
        key_status.config(text=f"saved ...{k[-4:]} - applies next game", fg=GREEN)

    bfr = tk.Frame(keyfr, bg=PANEL)
    bfr.pack(fill="x", padx=10, pady=(0, 8))

    def _mkbtn(parent, text, cmd, accent=False):
        return tk.Button(parent, text=text, command=cmd, bg=(GOLD if accent else BTN),
                         fg=(BG if accent else TXT), activebackground=(GOLD if accent else BTN_A),
                         activeforeground=(BG if accent else TXT), relief="flat", bd=0, padx=12, pady=4,
                         font=("Segoe UI", 8, "bold"), cursor="hand2")

    _mkbtn(bfr, "Get key ↗", open_dev_site).pack(side="left", padx=(0, 4))
    _mkbtn(bfr, "Paste", paste_key).pack(side="left", padx=4)
    _mkbtn(bfr, "Save key", save_key, accent=True).pack(side="left", padx=4)
    key_entry.bind("<Return>", lambda e: save_key())
    refresh_key_label()

    status = tk.Label(body, text="", bg=BG, fg=GREEN, font=("Segoe UI", 8))
    status.pack(anchor="w", padx=18, pady=(6, 0))

    def save():
        cfg.save({"streak_influence": int(infl.get()), "gank_threshold": float(thr.get()),
                  "scout_games": int(scout.get()), "profile_games": int(pgames.get()),
                  "dragon_volume": int(dvol.get()),
                  "matchup_tips": tips.get(), "gank_kit": kit.get(),
                  "duo_detection": duo.get(), "item_widget": widget.get(),
                  "game_intel": intel.get(), "dragon_audio": dragon.get(),
                  "dodge_alerts": dodge.get(),
                  "auto_accept": autoq.get(), "flash_on_d": (flash_side.get() == 0)})
        cfg.set_auto_open(auto.get())
        cfg.set_home_on_start(homeonstart.get())
        cfg.set_autostart(startwin.get())
        status.config(text="saved ✓  (overlay updates live; widget toggle applies next game)", fg=GREEN)

    def reset():
        infl.set(cfg.DEFAULTS["streak_influence"])
        thr.set(cfg.DEFAULTS["gank_threshold"])
        scout.set(cfg.DEFAULTS["scout_games"])
        pgames.set(cfg.DEFAULTS["profile_games"])
        dvol.set(cfg.DEFAULTS["dragon_volume"])
        for v in (tips, kit, duo, widget, intel, dragon, dodge, autoq, auto, homeonstart):
            v.set(True)
        flash_side.set(0)
        _upd_flash()
        autoq.set(False)
        status.config(text="reset to defaults - click Save to apply", fg=MUTED)

    def mkbtn(parent, text, cmd, accent=False):
        return tk.Button(parent, text=text, command=cmd, bg=(GOLD if accent else BTN),
                         fg=(BG if accent else TXT), activebackground=(GOLD if accent else BTN_A),
                         activeforeground=(BG if accent else TXT), relief="flat", bd=0, padx=16, pady=5,
                         font=("Segoe UI", 9, "bold"), cursor="hand2")

    btns = tk.Frame(body, bg=BG)
    btns.pack(fill="x", padx=14, pady=(10, 16))
    mkbtn(btns, "Save", save, accent=True).pack(side="left", padx=4)
    mkbtn(btns, "Reset", reset).pack(side="left", padx=4)
    mkbtn(btns, "Close", root.destroy).pack(side="right", padx=4)

    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w = max(560, root.winfo_reqwidth())
    h = min(max(620, root.winfo_reqheight()), int(sh * 0.90))
    root.minsize(560, 520)
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
