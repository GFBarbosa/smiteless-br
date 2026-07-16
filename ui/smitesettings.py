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

import smiteskin as skin
BG = skin.BG; PANEL = skin.PANEL; GOLD = skin.GOLD; TXT = skin.TXT; MUTED = skin.MUTED
GREEN = skin.GREEN; RED = skin.RED; TROUGH = skin.ENTRY; BTN = skin.BTN; BTN_A = skin.BTN_HOVER
ENTRY_BG = skin.ENTRY   # (RED was a drifted #d46d78, ENTRY a drifted #0f1219 - unified)
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
    skin.dark_titlebar(root)
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

    try:
        import smiteupdate as _su
        _ver = _su.local_version()
    except Exception:
        _ver = ""
    _hdr = tk.Frame(body, bg=BG)
    _hdr.pack(fill="x", padx=18, pady=(16, 1))
    tk.Label(_hdr, text="SMITELESS  SETTINGS", bg=BG, fg=GOLD,
             font=("Segoe UI", 13, "bold")).pack(side="left")
    if _ver:
        tk.Label(_hdr, text=f"v{_ver}", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(8, 0), pady=(6, 0))
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

    # Gank-tuning dials (streak influence / gank threshold / champ-kit) were removed — they
    # confused more than they helped; the gank rating now always uses the tuned defaults.
    scout = scale_row("Scout depth (games / player)",
                      "more games = steadier form read, but a slower first scout",
                      5, 20, 1, s["scout_games"], lambda v: f"{int(v)}")
    pgames = scale_row("Profile: games to load",
                       "how many recent games the home/profile page loads (and per 'Load more')",
                       5, 60, 1, s["profile_games"], lambda v: f"{int(v)}")
    dvol = scale_row("Audio volume (chime + voice)",
                     "drake chime, voice callouts and the ghost fanfare (0 = silent). Applies next game.",
                     0, 100, 5, s.get("dragon_volume", 30), lambda v: f"{int(v)}")

    auto = tk.BooleanVar(value=cfg.auto_open_enabled())
    homeonstart = tk.BooleanVar(value=cfg.home_on_start_enabled())
    startwin = tk.BooleanVar(value=cfg.autostart_enabled())

    def _chk(parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=BG, fg=TXT, selectcolor=TROUGH,
                              activebackground=BG, activeforeground=TXT, font=("Segoe UI", 9),
                              bd=0, highlightthickness=0)

    tips = tk.BooleanVar(value=s["matchup_tips"])
    duo = tk.BooleanVar(value=s["duo_detection"])
    widget = tk.BooleanVar(value=s["item_widget"])
    autoq = tk.BooleanVar(value=s.get("auto_accept", False))
    intel = tk.BooleanVar(value=s.get("game_intel", True))
    tempo = tk.BooleanVar(value=s.get("tempo_coach", True))
    freev = tk.BooleanVar(value=s.get("free_alarm", True))
    tempov = tk.BooleanVar(value=s.get("tempo_voice", True))
    dragon = tk.BooleanVar(value=s.get("dragon_audio", True))
    ghostv = tk.BooleanVar(value=s.get("ghost_race", True))
    respawnv = tk.BooleanVar(value=s.get("respawn_plan", True))
    dodge = tk.BooleanVar(value=s.get("dodge_alerts", True))
    dock = tk.BooleanVar(value=s.get("dock_champ_select", True))
    autoimp = tk.BooleanVar(value=s.get("auto_import", False))
    autoban = tk.BooleanVar(value=s.get("auto_ban", False))
    flash_side = tk.IntVar(value=(0 if s.get("flash_on_d", True) else 1))  # 0=D, 1=F

    tk.Label(body, text="FEATURES", bg=BG, fg=GOLD, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(10, 2))
    ffr = tk.Frame(body, bg=BG)
    ffr.pack(fill="x", padx=16)
    col1 = tk.Frame(ffr, bg=BG); col1.pack(side="left", fill="x", expand=True, anchor="n")
    col2 = tk.Frame(ffr, bg=BG); col2.pack(side="left", fill="x", expand=True, anchor="n")
    _chk(col1, "In-game item widget", widget).pack(anchor="w")
    _chk(col1, "Live game intel (timers + win read)", intel).pack(anchor="w")
    _chk(col1, "Tempo coach (objective setup windows)", tempo).pack(anchor="w")
    _chk(col1, "Free-objective alarm (enemy jg can't contest)", freev).pack(anchor="w")
    _chk(col1, "Tempo voice callouts (base / rotate / take)", tempov).pack(anchor="w")
    _chk(col1, "Dragon spawn audio (45/30/15s)", dragon).pack(anchor="w")
    _chk(col1, "Ghost race (chase your best game)", ghostv).pack(anchor="w")
    _chk(col1, "Respawn plan (death-screen card)", respawnv).pack(anchor="w")
    _chk(col1, "Matchup lane tips (written guides)", tips).pack(anchor="w")
    _chk(col1, "Auto-accept queue", autoq).pack(anchor="w")
    _chk(col1, "Auto-import runes + summs on lock", autoimp).pack(anchor="w")
    _chk(col1, "Auto-ban top recommended (champ select)", autoban).pack(anchor="w")
    _chk(col2, "Duo / premade detection", duo).pack(anchor="w")
    _chk(col2, "Dodge alerts (champ select)", dodge).pack(anchor="w")
    _chk(col2, "Dock champ-select panel by client", dock).pack(anchor="w")

    # Auto-accept ROLE (position) swaps — pick which roles you'll swap INTO.
    _SWAP_LBL = {"top": "Top", "jungle": "Jungle", "mid": "Mid", "adc": "ADC", "support": "Support"}
    _swap_cur = set(s.get("auto_swap_roles") or [])
    swapvars = {r: tk.BooleanVar(value=(r in _swap_cur)) for r in cfg.SWAP_ROLES}
    tk.Label(body, text="AUTO ROLE SWAP (autofill escape)", bg=BG, fg=GOLD,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(10, 2))
    tk.Label(body, text="Check the roles you actually play. If you get autofilled off them, Smiteless "
             "automatically REQUESTS a swap from a teammate who has one — and accepts any offer that "
             "lands you on one. It only ever moves you ONTO a checked role, never off one. None "
             "checked = off.",
             bg=BG, fg=MUTED, font=("Segoe UI", 8), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 2))
    swaprow = tk.Frame(body, bg=BG)
    swaprow.pack(anchor="w", padx=16, pady=(0, 2))
    for r in cfg.SWAP_ROLES:
        _chk(swaprow, _SWAP_LBL[r], swapvars[r]).pack(side="left", padx=(0, 8))

    # Auto PICK-ORDER swap — trade your spot in the pick order toward first / last pick.
    _pk = s.get("auto_pick_swap")
    pickswap = tk.StringVar(value=(_pk if _pk in ("first", "last") else "off"))
    tk.Label(body, text="AUTO PICK-ORDER SWAP", bg=BG, fg=GOLD,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(10, 2))
    tk.Label(body, text="Auto-handle pick-order swaps. \"Accept any\" just accepts every incoming "
             "swap request. \"Last pick\" works you as late as possible so you can counter-pick; "
             "\"First pick\" swaps you early to lock a contested champ (these accept an offer that "
             "moves you the right way, and ask for one otherwise).",
             bg=BG, fg=MUTED, font=("Segoe UI", 8), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 2))
    pkrow = tk.Frame(body, bg=BG)
    pkrow.pack(anchor="w", padx=16, pady=(0, 2))
    for _lbl, _val in (("Off", "off"), ("Accept any", "any"), ("First pick", "first"), ("Last pick", "last")):
        tk.Radiobutton(pkrow, text=_lbl, variable=pickswap, value=_val, bg=BG, fg=TXT,
                       selectcolor=TROUGH, activebackground=BG, activeforeground=TXT,
                       font=("Segoe UI", 9), bd=0, highlightthickness=0).pack(side="left", padx=(0, 10))

    from tkinter import ttk
    import lolbuild as _lb
    try:
        _dd = _lb.ddragon()
        _champ_names = sorted(_dd["id2name"].values())
        _norm, _name2id, _id2name = _dd["norm"], _dd["name2id"], _dd["id2name"]
    except Exception:
        _champ_names, _name2id, _id2name = [], {}, {}
        _norm = lambda x: "".join(c for c in (x or "").lower() if c.isalnum())

    # dark-ish theming for the ttk combobox (field + its dropdown list)
    try:
        _st = ttk.Style()
        _st.theme_use("clam")
        _st.configure("Fav.TCombobox", fieldbackground=ENTRY_BG, background=BTN, foreground=TXT,
                      arrowcolor=TXT, bordercolor=BTN, lightcolor=BTN, darkcolor=BTN)
        root.option_add("*TCombobox*Listbox.background", ENTRY_BG)
        root.option_add("*TCombobox*Listbox.foreground", TXT)
        root.option_add("*TCombobox*Listbox.selectBackground", BTN_A)
        root.option_add("*TCombobox*Listbox.selectForeground", TXT)
    except Exception:
        pass

    tk.Label(body, text="FAVOURITE PICKS", bg=BG, fg=GOLD,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(12, 2))
    tk.Label(body, text="Pick a champ from the dropdown and Add it — order is priority (use ↑/↓). "
             "A role limits it to that role. In champ select the panel lists your top still-open "
             "picks (recommend-only — it never hovers or locks).",
             bg=BG, fg=MUTED, font=("Segoe UI", 8), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 4))
    favfr = tk.Frame(body, bg=PANEL)
    favfr.pack(fill="x", padx=14, pady=(0, 6))

    addrow = tk.Frame(favfr, bg=PANEL)
    addrow.pack(fill="x", padx=8, pady=(8, 4))
    champ_var = tk.StringVar()
    champ_cb = ttk.Combobox(addrow, textvariable=champ_var, values=_champ_names, width=18,
                            style="Fav.TCombobox", font=("Segoe UI", 9))
    champ_cb.pack(side="left")
    role_var = tk.StringVar(value="any role")
    role_om = tk.OptionMenu(addrow, role_var, "any role", "top", "jungle", "mid", "adc", "support")
    role_om.config(bg=BTN, fg=TXT, activebackground=BTN_A, activeforeground=TXT, relief="flat",
                   highlightthickness=0, font=("Segoe UI", 8), width=8, cursor="hand2")
    role_om["menu"].config(bg=PANEL, fg=TXT, activebackground=BTN_A)
    role_om.pack(side="left", padx=6)

    listfr = tk.Frame(favfr, bg=PANEL)
    listfr.pack(fill="x", padx=8, pady=(0, 8))
    fav_list = tk.Listbox(listfr, height=5, bg=ENTRY_BG, fg=TXT, selectbackground=BTN_A,
                          selectforeground=TXT, relief="flat", highlightthickness=0, bd=0,
                          font=("Consolas", 9), activestyle="none")
    fav_list.pack(side="left", fill="x", expand=True)
    for _entry in (s.get("fav_champs") or []):
        fav_list.insert("end", _entry)

    def _canon(nm):
        nm = (nm or "").strip()
        if not nm:
            return None
        if not _name2id:                       # ddragon unavailable -> accept the raw name
            return nm
        cid = _name2id.get(_norm(nm))
        return _id2name.get(cid) if cid else None

    def _filter_champs(_e=None):
        t = champ_var.get().strip().lower()
        champ_cb["values"] = [n for n in _champ_names if t in n.lower()] if t else _champ_names

    def _add_fav(_e=None):
        nm = _canon(champ_var.get())
        if not nm:
            return
        role = role_var.get()
        entry = nm if role == "any role" else f"{nm}, {role}"
        if entry.lower() not in [fav_list.get(i).lower() for i in range(fav_list.size())]:
            fav_list.insert("end", entry)
        champ_var.set("")
        champ_cb["values"] = _champ_names

    def _rm_fav():
        sel = fav_list.curselection()
        if sel:
            fav_list.delete(sel[0])

    def _move(delta):
        sel = fav_list.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if 0 <= j < fav_list.size():
            v = fav_list.get(i)
            fav_list.delete(i)
            fav_list.insert(j, v)
            fav_list.selection_set(j)

    def _favbtn(parent, txt, cmd):
        return tk.Button(parent, text=txt, command=cmd, bg=BTN, fg=TXT, activebackground=BTN_A,
                         activeforeground=TXT, relief="flat", bd=0, padx=8, pady=2,
                         font=("Segoe UI", 8, "bold"), cursor="hand2")
    _favbtn(addrow, "+ Add", _add_fav).pack(side="left", padx=(6, 0))
    champ_cb.bind("<KeyRelease>", _filter_champs)
    champ_cb.bind("<Return>", _add_fav)
    favbtns = tk.Frame(listfr, bg=PANEL)
    favbtns.pack(side="left", fill="y", padx=(6, 0))
    _favbtn(favbtns, "Remove", _rm_fav).pack(fill="x", pady=1)
    _favbtn(favbtns, "↑", lambda: _move(-1)).pack(fill="x", pady=1)
    _favbtn(favbtns, "↓", lambda: _move(1)).pack(fill="x", pady=1)

    tk.Label(body, text="YOUR ACCOUNTS", bg=BG, fg=GOLD,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(12, 2))
    tk.Label(body, text="One Riot ID per line (Name#TAG). Accounts you log into are remembered "
             "automatically; add smurfs here too. 'Good this game' pools your champion mastery "
             "across all of them, so it recommends champs you know on ANY account.",
             bg=BG, fg=MUTED, font=("Segoe UI", 8), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 4))
    accfr = tk.Frame(body, bg=PANEL)
    accfr.pack(fill="x", padx=14, pady=(0, 6))
    acc_text = tk.Text(accfr, height=4, bg=ENTRY_BG, fg=TXT, insertbackground=TXT, relief="flat",
                       font=("Consolas", 9), wrap="none", highlightthickness=0, bd=0)
    acc_text.pack(fill="x", padx=8, pady=8)
    try:
        acc_text.insert("1.0", "\n".join(a["riot_id"] for a in ls.load_accounts()))
    except Exception:
        pass

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
        favs = [fav_list.get(i) for i in range(fav_list.size())]
        try:
            ls.save_accounts([ln.strip() for ln in acc_text.get("1.0", "end").splitlines() if ln.strip()])
        except Exception:
            pass
        cfg.save({  # gank dials removed from the UI -> always write the tuned defaults
                  "streak_influence": cfg.DEFAULTS["streak_influence"],
                  "gank_threshold": cfg.DEFAULTS["gank_threshold"],
                  "gank_kit": cfg.BOOLS["gank_kit"],
                  "scout_games": int(scout.get()), "profile_games": int(pgames.get()),
                  "dragon_volume": int(dvol.get()),
                  "matchup_tips": tips.get(),
                  "duo_detection": duo.get(), "item_widget": widget.get(),
                  "game_intel": intel.get(), "tempo_coach": tempo.get(), "free_alarm": freev.get(),
                  "tempo_voice": tempov.get(),
                  "dragon_audio": dragon.get(), "ghost_race": ghostv.get(),
                  "respawn_plan": respawnv.get(),
                  "dodge_alerts": dodge.get(), "dock_champ_select": dock.get(),
                  "auto_import": autoimp.get(), "auto_ban": autoban.get(), "fav_champs": favs,
                  "auto_accept": autoq.get(), "flash_on_d": (flash_side.get() == 0),
                  "auto_swap_roles": [r for r in cfg.SWAP_ROLES if swapvars[r].get()],
                  "auto_pick_swap": ("" if pickswap.get() == "off" else pickswap.get())})
        cfg.set_auto_open(auto.get())
        cfg.set_home_on_start(homeonstart.get())
        cfg.set_autostart(startwin.get())
        status.config(text="saved ✓  (overlay updates live; widget toggle applies next game)", fg=GREEN)

    def reset():
        scout.set(cfg.DEFAULTS["scout_games"])
        pgames.set(cfg.DEFAULTS["profile_games"])
        dvol.set(cfg.DEFAULTS["dragon_volume"])
        for v in (tips, duo, widget, intel, dragon, ghostv, respawnv, dodge, dock, autoq, auto, homeonstart):
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
