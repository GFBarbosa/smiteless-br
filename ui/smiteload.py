#!/usr/bin/env python3
"""smiteload.py - the LOADING-SCREEN matchup overlay.

While the game loads (you're staring at the loading screen anyway), this fills the screen
with a full ACCOUNT scoreboard: ten splash-art rows — riot id, rank + LP + season record,
last-10 form bars, KDA, mastery, this-champ record, an avg-performance grade pill, and the
profile-read tag pills (duo / smurf read / OTP / tilt / first-timer / autofill / …) that
lolload derives from each player's real match history. Unlike the death brief it CAN use
the center - there's no fight to watch yet. Fades out the moment the game actually starts.

Read-only off the local client + the user's own Riot key (loading exposes summonerIds the
LCU resolves to real riot ids, so the full scout works here).
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
C_MYSTIC = skin.rgb(skin.MYSTIC)
_TONE_C = {"good": C_GOOD, "bad": C_BAD, "neutral": C_MUTED, "info": C_MYSTIC}
C_VOID = skin.rgb(skin.VOID); C_RAISED = skin.rgb(skin.RAISED); C_SUNKEN = skin.rgb(skin.SUNKEN)
C_LINE = skin.rgb(skin.LINE); C_LINE_SOFT = skin.rgb(skin.LINE_SOFT)
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


def _geom(W, H):
    """Shared geometry for the scoreboard: (s, S, CW, x0, RH, AW). The fetch worker warms
    splash crops at EXACTLY the size the renderer will ask for, so rows are cache hits."""
    s = max(0.70, min(1.60, H / 1080.0))
    def S(v): return int(v * s)
    CW = min(W - S(120), S(1580))
    return s, S, CW, (W - CW) // 2, S(72), S(148)


def _cached_splash(cid, size):
    """Face-cropped splash ONLY if already in smitecard's memory cache — never downloads,
    so the render thread can't stall. The fetch worker warms these."""
    return sc._SPLASH.get((cid, size))


def _grade_of(perf):
    """(letter, color) — same bands as the profile's game grades."""
    for lo, letter, col in ((115, "S+", C_ARC), (100, "S", C_ARC), (85, "A", C_ARC),
                            (70, "B", C_GOOD), (55, "C", C_MUTED)):
        if perf >= lo:
            return letter, col
    return "D", C_BAD


def _top_threat(enemies):
    """The single enemy account most likely to decide the game — perf-driven, sharpened
    by OTP mastery, a live win streak, and champ comfort. None unless someone actually
    stands out (a quiet lobby gets no scare line)."""
    best, bs = None, -1.0
    for r in enemies or []:
        if not r.get("scouted"):
            continue
        s = float(r.get("perf") or 50)
        if r.get("pts", 0) >= 100_000:
            s += 12
        form = r.get("form") or []
        if len(form) >= 3 and all(form[:3]):
            s += 8
        if r.get("cg", 0) >= 5 and r.get("cw", 0) * 2 > r["cg"]:
            s += 6
        if s > bs:
            bs, best = s, r
    return best if bs >= 78 else None


def _rank_str(rk):
    if not rk or not rk.get("tier"):
        return "", None
    from lolload import _TIER
    t = _TIER.get(rk["tier"].upper(), rk["tier"].title())
    return f"{t} {rk.get('div', '')}".strip() + f" · {rk.get('lp', 0)} LP", t


def render_frame(dd, b, W, H):
    """The loading scoreboard: ten FULL-WIDTH account rows in the profile's own visual
    language — a face-cropped splash slab, champ + mastery, the account (riot id, rank,
    LP, season record), last-10 form bars + KDA + this-champ record, the avg-performance
    grade pill, and the profile-read tag pills (duo/smurf/OTP/tilt/…). Nothing else on
    screen looks like this because nothing else HAS this much per-account detail."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), C_VOID)
    d = ImageDraw.Draw(img)
    s, S, CW, x0, RH, AW = _geom(W, H)
    allies, enemies = b.get("allies") or [], b.get("enemies") or []
    plan = b.get("plan") or []

    hdr_h, sect_h, gap = S(46), S(26), S(6)
    plan_h = S(30) + S(19) * min(3, len(plan)) + S(8) if plan else 0
    block = hdr_h + 2 * sect_h + (RH + gap) * (len(allies) + len(enemies)) + S(14) + plan_h
    top = max(S(28), (H - block) // 2)

    # ---------- header ----------
    try:                                            # the ✦ spark needs the symbol face
        from PIL import ImageFont
        d.text((x0, top + S(2)), "✦", font=ImageFont.truetype("seguisym.ttf", S(17)), fill=C_EMBER)
    except Exception:
        pass
    d.text((x0 + S(26), top), "SMITELESS", font=_dfont(S(20)), fill=C_EMBER)
    d.text((x0 + S(158), top + S(3)), "LOADING SCOUT", font=_dfont(S(16)), fill=C_MUTED)
    thr = _top_threat(enemies) if b.get("scouted") else None
    if thr:                                        # the one enemy who decides the game
        tags = " · ".join(t for t, _ in (thr.get("tags") or [])[:2])
        sub, scol = f"WATCH {thr['champ'].upper()}" + (f" — {tags}" if tags else ""), C_WARN
    else:
        sub, scol = ("reading the ten accounts…" if not b.get("scouted")
                     else "who they are, before minute one"), C_FAINT
    d.text((x0 + CW - d.textlength(sub, font=_wfont(S(12), True)), top + S(6)),
           sub, font=_wfont(S(12), True), fill=scol)
    yy = top + hdr_h

    def _pill(x, y, txt, col, maxx, primary=False):
        """Tag chip. The FIRST tag is the sharpest read (spec orders them), so it gets a
        filled chip; the rest sit quiet (dim ink, faint outline) — one loud thing per row
        instead of a string of equally-screaming outlines."""
        f = _wfont(S(11), True)
        w = int(d.textlength(txt, font=f))
        if x + w + S(16) > maxx:
            return None
        if primary:
            d.rounded_rectangle([x, y, x + w + S(14), y + S(19)], S(9),
                                fill=tuple(int(c * 0.24) for c in col))
            d.text((x + S(7), y + S(3)), txt, font=f, fill=col)
        else:
            d.rounded_rectangle([x, y, x + w + S(14), y + S(19)], S(9), fill=C_SUNKEN,
                                outline=tuple(int(c * 0.35) for c in col), width=1)
            d.text((x + S(7), y + S(3)), txt, font=f, fill=tuple(int(c * 0.82) for c in col))
        return x + w + S(14) + S(7)

    def _row(y, r):
        rail = C_EMBER if r.get("me") else (C_GOOD if r.get("_ally") else C_BAD)
        d.rounded_rectangle([x0, y, x0 + CW, y + RH], S(10), fill=C_SURF)
        # art slab, faded into the card so text never fights it
        art = _cached_splash(r.get("cid", 0), (AW, RH))
        if art:
            mask = Image.new("L", (AW, RH), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, AW, RH), radius=S(10), fill=255)
            ImageDraw.Draw(mask).rectangle((AW // 2, 0, AW, RH), fill=255)
            img.paste(art, (x0, y), mask)
            grad = Image.new("L", (AW, 1))
            grad.putdata([int(max(0, (i - AW * 0.45) / (AW * 0.55)) * 255) for i in range(AW)])
            img.paste(Image.new("RGB", (AW, RH), C_SURF), (x0, y), grad.resize((AW, RH)))
        else:
            ic = _cached_icon(dd, r.get("cid", 0), S(48))
            if ic:
                img.paste(ic, (x0 + S(14), y + (RH - S(48)) // 2), ic)
        d.rounded_rectangle([x0, y + S(6), x0 + S(4), y + RH - S(6)], S(2), fill=rail)

        # ---- champ block ----
        cx = x0 + int(AW * 0.72)
        d.text((cx, y + S(9)), (r.get("champ") or "?")[:14], font=_dfont(S(17)),
               fill=(C_EMBER if r.get("me") else C_TXT))
        meta = " · ".join(p for p in (r.get("role"), r.get("dmg")) if p)
        d.text((cx, y + S(33)), meta, font=_wfont(S(11)),
               fill=_DMG_C.get(r.get("dmg"), C_MUTED))
        if r.get("pts"):
            mst = f"M{r.get('mlevel', 0)} · {r['pts'] // 1000}k pts"
            d.text((cx, y + S(50)), mst, font=_wfont(S(10)),
                   fill=(C_EMBER if r["pts"] >= 100_000 else C_MUTED))

        # ---- account block ----
        ax = x0 + S(330)
        player = r.get("player") or ""
        if player:
            nm, _, tg = player.partition("#")
            nf = _wfont(S(14), True)
            d.text((ax, y + S(9)), nm[:16], font=nf, fill=C_TXT)
            if tg:
                d.text((ax + d.textlength(nm[:16], font=nf) + S(5), y + S(12)), f"#{tg}",
                       font=_wfont(S(10)), fill=C_FAINT)
            rs, _tier = _rank_str(r.get("rank_full"))
            if rs:
                d.text((ax, y + S(30)), rs, font=_wfont(S(12), True), fill=_tier_color(rs))
            else:
                d.text((ax, y + S(30)), "unranked", font=_wfont(S(12)), fill=C_FAINT)
            rk = r.get("rank_full") or {}
            sg = int(rk.get("w", 0) or 0) + int(rk.get("l", 0) or 0)
            if sg:
                d.text((ax, y + S(49)), f"{rk['w']}W {rk['l']}L · {round(rk['w'] / sg * 100)}% season",
                       font=_wfont(S(10)), fill=C_MUTED)
        elif b.get("scouted"):
            d.text((ax, y + S(26)), "account hidden", font=_wfont(S(11)), fill=C_FAINT)
        else:
            d.text((ax, y + S(26)), "scouting…", font=_wfont(S(11)), fill=C_FAINT)

        # ---- last-10 block: form bars + kda + this-champ ----
        fx = x0 + S(560)
        form = r.get("form") or []
        if form:
            d.text((fx, y + S(8)), "LAST 10", font=_wfont(S(8), True), fill=C_FAINT)
            bx = fx
            for wn in reversed(form[:10]):          # oldest -> newest, like the profile
                d.rounded_rectangle([bx, y + S(20), bx + S(9), y + S(30)], S(2),
                                    fill=(C_GOOD if wn else C_BAD))
                bx += S(12)
            bits = [f"{r['w']}-{r['n'] - r['w']}"]
            if r.get("kdar") is not None:
                bits.append(f"{r['kdar']} KDA" + (f"  ({r['kavg']})" if r.get("kavg") else ""))
            d.text((fx, y + S(35)), " · ".join(bits), font=_wfont(S(11)), fill=C_TXT)
            if r.get("cg"):
                cwn = r["cw"]
                col = C_GOOD if cwn * 2 >= r["cg"] else C_BAD
                d.text((fx, y + S(52)), f"{cwn}-{r['cg'] - cwn} on this champ",
                       font=_wfont(S(10), True), fill=col)
            elif r.get("scouted"):
                d.text((fx, y + S(52)), "champ not in recents", font=_wfont(S(10)), fill=C_FAINT)

        # ---- grade pill (far right): evidence-labelled, and only with a real sample ----
        gx = x0 + CW - S(64)
        if r.get("perf") is not None and r.get("n", 0) >= 4:
            letter, col = _grade_of(r["perf"])
            d.rounded_rectangle([gx, y + S(12), gx + S(48), y + RH - S(12)], S(8),
                                fill=tuple(int(c * 0.18) for c in col),
                                outline=tuple(int(c * 0.5) for c in col), width=1)
            d.text((gx + S(24), y + RH // 2 - S(7)), letter, font=_dfont(S(19)), fill=col, anchor="mm")
            d.text((gx + S(24), y + RH // 2 + S(12)), f"{int(r['perf'])} · {r['n']}g",
                   font=_dfont(S(10)), fill=tuple(int(c * 0.8) for c in col), anchor="mm")

        # ---- profile tags (two rows of pills) ----
        tx0, txmax = x0 + S(818), gx - S(14)
        tags = list((r.get("tags") or []))
        if not tags and r.get("phrases"):            # pre-scout: champion knowledge instead
            tags = [(p, "neutral") for p in r["phrases"][:3]]
        rows_y = (y + S(9), y + S(38))
        ti = 0
        for ry in rows_y:
            cx2 = tx0
            while ti < len(tags):
                txt, tone = tags[ti]
                nx = _pill(cx2, ry, txt, _TONE_C.get(tone, C_MUTED), txmax, primary=(ti == 0))
                if nx is None:
                    break
                cx2 = nx
                ti += 1

    def _section(y, title, col, note=""):
        f = _wfont(S(12), True)
        d.text((x0 + S(2), y + S(2)), title, font=f, fill=col)
        lx = x0 + S(10) + d.textlength(title, font=f)
        d.line([lx, y + S(10), x0 + CW, y + S(10)], fill=C_LINE_SOFT, width=1)
        if note:
            d.text((x0 + CW - d.textlength(note, font=_wfont(S(10))), y + S(1)),
                   note, font=_wfont(S(10)), fill=C_FAINT)
        return y + sect_h

    yy = _section(yy, "YOUR TEAM", C_GOOD)
    for r in allies:
        r["_ally"] = True
        _row(yy, r)
        yy += RH + gap
    yy += S(8)
    yy = _section(yy, "ENEMY TEAM", C_BAD, "tags read from each account's real history")
    for r in enemies:
        r["_ally"] = False
        _row(yy, r)
        yy += RH + gap

    # ---------- game plan ----------
    if plan:
        yy += S(6)
        d.rounded_rectangle([x0, yy, x0 + CW, yy + plan_h], S(10), fill=C_SURF)
        d.rounded_rectangle([x0, yy + S(6), x0 + S(4), yy + plan_h - S(6)], S(2), fill=C_EMBER)
        d.text((x0 + S(16), yy + S(8)), "GAME PLAN", font=_wfont(S(12), True), fill=C_EMBER)
        py = yy + S(28)
        for line in plan[:3]:
            d.text((x0 + S(16), py), "→ " + line, font=_wfont(S(12)), fill=C_TXT)
            py += S(19)
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
        # icons (disk) + face-cropped splash slabs at EXACTLY the row size the renderer
        # asks smitecard's memory cache for — a warmed row is a pure cache hit.
        _s, _S, _CW, _x0, RH, AW = _geom(W, H)
        for r in (bf.get("allies") or []) + (bf.get("enemies") or []):
            try:
                sc.get_icon(dd, r.get("cid", 0), 96)         # downloads the disk file (any size)
                sc.get_splash(dd, r.get("cid", 0), (AW, RH))
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
