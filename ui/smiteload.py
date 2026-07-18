#!/usr/bin/env python3
"""smiteload.py - the LOADING-SCREEN matchup overlay.

While the game loads (you're staring at the loading screen anyway), this fills the whole
screen with the pre-game read: every champ's good/bad tags, the damage split to itemize
against, and a plain game-plan for the comp. Unlike the death brief it CAN use the center -
there's no fight to watch yet. Fades out the moment the game actually starts.

Read-only off the local client. No live rank/form here (Riot only exposes placeholder ids
during loading); this is champion knowledge, not player scouting.
"""
import sys, os, time, threading, ctypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass

import lolbuild as lb
import lolload as ll
import lolgame as lg
import smiteconfig as cfg
import smiteskin as skin
# reuse the death overlay's window plumbing + drawing helpers (one source of truth)
from smitedead import (_wfont, _dfont, _wrap, _card, _make_click_through, game_monitor,
                       CHROMA_HEX, C_TXT, C_MUTED, C_FAINT, C_EMBER, C_ARC, C_GOOD, C_BAD,
                       C_WARN, C_INFO, C_SURF)

import smitecard as sc                              # champion art loaders (get_icon / get_splash)
_user32 = ctypes.windll.user32
_DMG_C = {"AD": C_WARN, "AP": C_ARC, "mixed": C_MUTED}
_TONE_C = {"good": C_GOOD, "bad": C_BAD, "neutral": C_MUTED}
C_VOID = skin.rgb(skin.VOID); C_RAISED = skin.rgb(skin.RAISED); C_SUNKEN = skin.rgb(skin.SUNKEN)
C_LINE = skin.rgb(skin.LINE)
_TIER_COL = {"iron": (150, 130, 120), "bronze": (176, 120, 84), "silver": (158, 170, 185),
             "gold": skin.rgb(skin.EMBER), "plat": (72, 200, 190), "platinum": (72, 200, 190),
             "emerald": (74, 200, 128), "diamond": (108, 168, 245), "master": (196, 112, 232),
             "gm": (232, 96, 96), "grandmaster": (232, 96, 96), "chall": (128, 205, 255),
             "challenger": (128, 205, 255)}


def _tier_color(rank):
    return _TIER_COL.get((rank or "").split()[0].lower(), C_MUTED) if rank else C_MUTED


def _cached_icon(dd, cid, size):
    """Champion square icon ONLY if already cached (memory/disk) — never downloads, so it can't
    block the render thread. The fetch worker warms the cache; misses just render a placeholder."""
    ck = (cid, size)
    if ck in sc._ICONS:
        return sc._ICONS[ck]
    key = dd.get("id2key", {}).get(cid)
    if not key:
        return None
    fp = os.path.join(sc.ICONCACHE, dd["ver"], key + ".png")
    if os.path.exists(fp):
        try:
            from PIL import Image
            im = Image.open(fp).convert("RGBA").resize((size, size))
            sc._ICONS[ck] = im
            return im
        except Exception:
            return None
    return None


def render_frame(dd, b, W, H):
    """Compact, dense scouting card, centered on a dark backdrop. Two lines per player:
    portrait + name + tags + rank, then a detail line (role · dmg · mastery · record · wr · kda)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), C_VOID)
    d = ImageDraw.Draw(img)
    s = max(0.75, min(1.35, H / 1080.0))
    def S(v): return int(v * s)

    content = min(W - S(160), S(1280))             # a centered block, not a full-width sprawl
    x0 = (W - content) // 2
    gap = S(30)
    colw = (content - gap) // 2
    rowh = S(52)
    allies, enemies = b.get("allies") or [], b.get("enemies") or []
    pnl_h = S(38) + rowh * max(len(allies), len(enemies), 1)
    plan = b.get("plan") or []
    plan_h = S(28) + S(20) * min(3, len(plan)) + S(14)
    block = pnl_h + S(22) + plan_h
    top = max(S(84), (H - block) // 2)

    # header just above the block
    d.text((x0, top - S(46)), "SMITELESS", font=_dfont(S(19)), fill=C_EMBER)
    d.text((x0 + S(140), top - S(43)), "MATCHUP", font=_dfont(S(16)), fill=C_MUTED)
    sub = "scouting the lobby…" if not b.get("scouted") else "know them before the game starts"
    d.text((x0 + content - S(2) - d.textlength(sub, font=_wfont(S(12))), top - S(40)),
           sub, font=_wfont(S(12)), fill=C_FAINT)

    def _pill(x, y, txt, col):
        f = _wfont(S(10), True)
        w = d.textlength(txt, font=f)
        d.rounded_rectangle([x, y, x + w + S(12), y + S(17)], S(6), fill=C_SUNKEN)
        d.text((x + S(6), y + S(2)), txt, font=f, fill=col)
        return x + w + S(12) + S(6)

    def _panel(x, title, rows, rail):
        d.rounded_rectangle([x, top, x + colw, top + pnl_h], S(12), fill=C_SURF)
        d.text((x + S(16), top + S(11)), title, font=_wfont(S(12), True), fill=rail)
        d.rectangle([x + S(16), top + S(31), x + colw - S(16), top + S(31) + 1], fill=C_LINE)
        for i, r in enumerate(rows):
            _row(x, top + S(36) + i * rowh, colw, r)

    def _row(x, y, w, r):
        y = int(y)
        pad, isz = S(16), S(38)
        ix, iy = x + pad, y + (rowh - isz) // 2
        ic = _cached_icon(dd, r.get("cid", 0), isz)
        if ic:
            img.paste(ic, (int(ix), int(iy)), ic)
        else:
            d.rounded_rectangle([ix, iy, ix + isz, iy + isz], S(5), fill=C_SUNKEN)
        tx = ix + isz + S(12)
        name = (r["champ"] or "?")[:14]
        nf = _wfont(S(15), True)
        d.text((tx, y + S(7)), name, font=nf, fill=(C_EMBER if r.get("me") else C_TXT))
        if r.get("rank"):                          # rank far right, tier-coloured
            rf = _wfont(S(13), True)
            d.text((x + w - pad - d.textlength(r["rank"], font=rf), y + S(8)), r["rank"],
                   font=rf, fill=_tier_color(r["rank"]))
        cx = tx + d.textlength(name, font=nf) + S(10)   # tags after the name
        for txt, tone in (r.get("ptags") or [])[:2]:
            cx = _pill(cx, y + S(8), txt, _TONE_C.get(tone, C_MUTED))
        parts = [p for p in (r.get("role"), r.get("dmg"), r.get("mastery"),
                             r.get("champ_rec"), r.get("wr"), r.get("kda")) if p]
        if not (r.get("rank") or r.get("mastery")) and r.get("phrases"):   # pre-scout fallback
            parts = [r.get("role"), r.get("dmg"), r["phrases"][0]]
            parts = [p for p in parts if p]
        d.text((tx, y + S(28)), "  ·  ".join(parts), font=_wfont(S(11)), fill=C_MUTED)

    _panel(x0, "YOUR TEAM", allies, C_GOOD)
    _panel(x0 + colw + gap, "ENEMY", enemies, C_BAD)

    # GAME PLAN
    py = top + pnl_h + S(22)
    d.rounded_rectangle([x0, py, x0 + content, py + plan_h], S(12), fill=C_SURF)
    d.rounded_rectangle([x0, py + S(8), x0 + S(5), py + plan_h - S(8)], S(2), fill=C_EMBER)
    d.text((x0 + S(16), py + S(9)), "GAME PLAN", font=_wfont(S(12), True), fill=C_EMBER)
    yy = py + S(30)
    for line in plan[:3]:
        d.text((x0 + S(16), yy), "→ " + line, font=_wfont(S(12)), fill=C_TXT)
        yy += S(20)
    return img


def _single_instance():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW(None, False, "Global\\SmitelessLoad")
    return ctypes.get_last_error() != 183


_LOG = os.path.expanduser("~/.claude/smiteless_load.log")


def _log(msg):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _game_time():
    """Live game clock (seconds) from :2999, or -1 if it's not serving. IMPORTANT: :2999 starts
    answering with gameTime~0 while you're STILL on the loading screen, so 'is it serving' is the
    wrong exit signal (it closed the overlay mid-load). The clock only advances once the game has
    actually started — so gameTime > ~1 is the real 'past the loading screen' signal."""
    try:
        d = lb.http("https://127.0.0.1:2999/liveclientdata/gamestats", timeout=1, insecure=True)
        return float(d.get("gameTime", 0.0)) if isinstance(d, dict) else 0.0
    except Exception:
        return -1.0


def _gameflow_phase():
    """RAW LCU gameflow phase (unlike phasecheck, which reports InProgress the moment :2999
    answers — useless for telling loading apart from the live game)."""
    lc = lg._lcu()
    if not lc:
        return ""
    port, hdr = lc
    try:
        r = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/gameflow-phase",
                    headers=hdr, timeout=3, insecure=True)
        return r if isinstance(r, str) else ""
    except Exception:
        return ""


def main():
    if not _single_instance():
        return
    if not cfg.load().get("loading_brief", True):
        return
    import tkinter as tk
    from PIL import ImageTk
    from smitedead import toplevel_hwnd

    dd = lb.ddragon()
    l, t, r, b = game_monitor()
    W, H = r - l, b - t
    try:
        open(_LOG, "w").close()                     # fresh log per launch
    except Exception:
        pass
    _log(f"LAUNCH monitor=({l},{t},{r},{b}) size={W}x{H} loading_brief={cfg.load().get('loading_brief', True)}")
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=CHROMA_HEX)
    root.attributes("-transparentcolor", CHROMA_HEX)
    root.geometry(f"{W}x{H}+{l}+{t}")
    label = tk.Label(root, bd=0, bg=CHROMA_HEX)
    label.pack(fill="both", expand=True)
    root.update_idletasks()
    _make_click_through(toplevel_hwnd(root.winfo_id()))

    state = {"run": True, "brief": None, "shown": False, "want": False, "fetching": False,
             "deadline": time.monotonic() + 1200}         # spawned at champ select: cover it + load

    def _done(why):
        _log(f"EXIT {why}")
        state["run"] = False
        try:
            root.after(0, root.destroy)
        except Exception:
            pass

    def _warm_icons(bf):
        for r in (bf.get("allies") or []) + (bf.get("enemies") or []):
            try:
                sc.get_icon(dd, r.get("cid", 0), 96)         # downloads the disk file (any size)
            except Exception:
                pass

    def _fetch():
        # ALL network work lives here, OFF the poll/render loop, so the overlay is never blocked.
        # Phase 1: champs + tags + plan (fast, no Riot API) -> the overlay appears immediately.
        # Phase 2: warm champion portraits, then force a redraw so the art pops in.
        # Phase 3: per-player rank/OTP scout (slow, rate-limited) -> fills in when ready.
        try:
            fast = ll.brief(dd, scout=False)
            if fast:
                state["brief"] = fast
                _log("fast brief READY (champs/tags/plan) -> showing")
                _warm_icons(fast)
                if state["run"]:
                    state["brief"] = dict(fast)              # new object -> tick re-renders w/ art
                    _log("icons warmed -> redraw")
        except Exception as e:
            _log(f"fast brief ERROR {type(e).__name__}: {e}")
        try:
            full = ll.brief(dd, scout=True)
            if full and state["run"]:
                state["brief"] = full
                _log("scout brief READY (ranks/tags) -> enriched")
        except Exception as e:
            _log(f"scout brief ERROR {type(e).__name__}: {e}")

    def poll():
        n = errs = 0
        seen_load = False
        while state["run"]:
            gt = _game_time()                              # >1 = game running; ~0 = still loading; -1 = down
            gf = _gameflow_phase()
            errs = (errs + 1) if gf == "" else 0           # "" = LCU hiccup; only real after a streak
            started = gt > 1.0                             # the game clock is running -> past the load screen
            # LOADING = game process up (GameStart/InProgress/Reconnect) AND not started yet.
            loading = (gf in ("GameStart", "InProgress", "Reconnect")) and not started
            if loading:
                seen_load = True
            n += 1
            if n <= 4 or loading or n % 12 == 0:
                _log(f"poll gf={gf!r} gt={gt:.1f} started={started} loading={loading} want={state['want']} shown={state['shown']} fetching={state['fetching']}")
            if started:                                    # game actually began -> we're done
                _done(f"game started (gt={gt:.1f})")
                return
            if loading:
                state["want"] = True
                if not state["fetching"]:                  # kick the fetch ONCE, on a worker thread
                    state["fetching"] = True
                    threading.Thread(target=_fetch, daemon=True).start()
            elif seen_load and (errs >= 4 or gf in ("None", "Lobby", "Matchmaking", "ReadyCheck",
                                                    "WaitingForStats", "PreEndOfGame", "EndOfGame")):
                _done(f"left after load (gf={gf!r})")       # dodge/crash after we'd been loading
                return
            elif not seen_load and gf in ("None", "Lobby", "Matchmaking", "EndOfGame") and errs == 0:
                _done(f"no game (gf={gf!r})")               # dropped back to lobby before ever loading
                return
            else:
                state["want"] = False                      # ChampSelect -> armed and waiting
            if time.monotonic() > state["deadline"]:
                _done("deadline")
                return
            time.sleep(0.5)

    threading.Thread(target=poll, daemon=True).start()

    state["rendered"] = None
    def tick():
        if not state["run"]:
            return
        b = state["brief"]
        if state["want"] and b:
            if b is not state["rendered"]:              # (re)draw on first show AND on any upgrade
                frame = render_frame(dd, b, W, H)
                ph = ImageTk.PhotoImage(frame)
                label.configure(image=ph)
                label.image = ph
                state["rendered"] = b
            if not state["shown"]:                      # show/hide is driven by want, INDEPENDENT
                root.deiconify()                        # of render — so a blip can't wedge it hidden
                _make_click_through(toplevel_hwnd(root.winfo_id()))
                state["shown"] = True
                _log("overlay SHOWN")
        elif state["shown"] and not state["want"]:
            root.withdraw()
            state["shown"] = False
        root.after(250, tick)

    root.withdraw()
    root.after(200, tick)
    root.mainloop()
    state["run"] = False


if __name__ == "__main__":
    main()
