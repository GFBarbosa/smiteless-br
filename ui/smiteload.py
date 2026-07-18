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
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), C_VOID)         # full dark backdrop — loading is a takeover
    d = ImageDraw.Draw(img)
    s = max(0.72, min(1.5, H / 1080.0))
    def S(v): return int(v * s)
    M, gap = S(48), S(40)
    colw = (W - 2 * M - gap) // 2

    # subtle top hairline + brand
    d.rectangle([0, 0, W, S(2)], fill=skin.rgb(skin.EMBER))
    d.text((M, S(30)), "SMITELESS", font=_dfont(S(28)), fill=C_EMBER)
    d.text((M + S(210), S(34)), "MATCHUP", font=_dfont(S(24)), fill=C_MUTED)
    sub = "scouting the lobby…" if not b.get("scouted") else "know them before the first minion"
    d.text((M, S(72)), sub, font=_wfont(S(14)), fill=C_FAINT)

    top = S(112)
    pnl_h = H - top - S(178)

    def _pill(x, y, txt, col, f):
        w = d.textlength(txt, font=f)
        d.rounded_rectangle([x, y, x + w + S(16), y + S(22)], S(8), fill=C_SUNKEN)
        d.text((x + S(8), y + S(3)), txt, font=f, fill=col)
        return x + w + S(16) + S(8)

    def _panel(x, title, rows, rail):
        d.rounded_rectangle([x, top, x + colw, top + pnl_h], S(16), fill=C_SURF)
        d.rounded_rectangle([x, top + S(10), x + S(6), top + pnl_h - S(10)], S(3), fill=rail)
        d.text((x + S(28), top + S(16)), title, font=_wfont(S(17), True), fill=rail)
        rowh = (pnl_h - S(56)) / max(1, len(rows))
        for i, r in enumerate(rows):
            _player(x + S(16), top + S(52) + i * rowh, colw - S(32), rowh - S(10), r, rail)

    def _player(x, y, w, h, r, teamcol):
        x, y, h = int(x), int(y), int(h)
        d.rounded_rectangle([x, y, x + w, y + h], S(12), fill=C_RAISED)
        d.rectangle([x, y + S(6), x + S(4), y + h - S(6)], fill=teamcol)
        isz = h - S(20)
        ic = _cached_icon(dd, r.get("cid", 0), isz)
        ix, iy = x + S(12), y + S(10)
        if ic:
            img.paste(ic, (ix, iy), ic)
        else:
            d.rounded_rectangle([ix, iy, ix + isz, iy + isz], S(6), fill=C_SUNKEN)
        tx = ix + isz + S(16)
        d.text((tx, y + S(9)), (r["champ"] or "?")[:14], font=_wfont(S(20), True),
               fill=(C_EMBER if r.get("me") else C_TXT))
        d.text((tx, y + S(36)), f"{r.get('role','')}   {r.get('dmg','')}",
               font=_wfont(S(12), True), fill=_DMG_C.get(r.get("dmg"), C_MUTED))
        if r.get("rank"):
            rc = _tier_color(r["rank"])
            rw = d.textlength(r["rank"], font=_wfont(S(15), True))
            d.text((x + w - S(16) - rw, y + S(11)), r["rank"], font=_wfont(S(15), True), fill=rc)
        # tags as pills
        cy = y + S(58)
        cx = tx
        for txt, tone in (r.get("ptags") or [])[:3]:
            cx = _pill(cx, cy, txt, _TONE_C.get(tone, C_MUTED), _wfont(S(11), True))
        if not (r.get("ptags")) and r.get("phrases"):     # pre-scout: show the champ read instead
            d.text((tx, cy + S(2)), "· " + r["phrases"][0], font=_wfont(S(12)), fill=C_FAINT)
        elif r.get("phrases") and h > S(92):
            d.text((tx, y + S(84)), "· " + r["phrases"][0], font=_wfont(S(12)), fill=C_MUTED)

    _panel(M, "YOUR TEAM", b.get("allies") or [], C_GOOD)
    _panel(M + colw + gap, "ENEMY", b.get("enemies") or [], C_BAD)

    # GAME PLAN footer
    plan = b.get("plan") or []
    py, pw = H - S(158), W - 2 * M
    d.rounded_rectangle([M, py, M + pw, py + S(128)], S(16), fill=C_SURF)
    d.rounded_rectangle([M, py + S(10), M + S(6), py + S(118)], S(3), fill=C_EMBER)
    d.text((M + S(28), py + S(14)), "GAME PLAN", font=_wfont(S(17), True), fill=C_EMBER)
    yy = py + S(46)
    for line in plan[:3]:
        d.text((M + S(28), yy), "→ " + line, font=_wfont(S(16)), fill=C_TXT)
        yy += S(26)
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
