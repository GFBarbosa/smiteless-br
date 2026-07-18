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

_user32 = ctypes.windll.user32
_DMG_C = {"AD": C_WARN, "AP": C_ARC, "mixed": C_MUTED}
_TONE_C = {"good": C_GOOD, "bad": C_BAD, "neutral": C_MUTED}


def render_frame(dd, b, W, H):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (255, 0, 255))
    d = ImageDraw.Draw(img)
    s = max(0.6, min(1.4, H / 1080.0))
    def S(v): return int(v * s)
    M = S(40)
    colw = S(560)

    d.text((M, S(30)), "SMITELESS", font=_dfont(S(20)), fill=C_EMBER)
    d.text((M + S(148), S(30)), "MATCHUP", font=_dfont(S(20)), fill=C_MUTED)
    d.text((M, S(62)), "loading — here's the game before it starts", font=_wfont(S(13)), fill=C_FAINT)

    def _column(x, title, rows, title_col, detailed):
        _card(d, x, S(96), colw, H - S(96) - S(200), title_col)
        px = x + S(22)
        d.text((px, S(110)), title, font=_wfont(S(15), True), fill=title_col)
        yy = S(146)
        rowh = S(78) if detailed else S(66)
        for r in rows:
            d.text((px, yy + S(2)), r["role"], font=_wfont(S(11), True), fill=C_MUTED)
            nmcol = C_EMBER if r.get("me") else C_TXT
            d.text((px + S(44), yy), (r["champ"] or "?")[:15], font=_wfont(S(17), True), fill=nmcol)
            rx2 = x + colw - S(22)
            dchip = r["dmg"]
            d.text((rx2 - d.textlength(dchip, font=_wfont(S(11), True)), yy + S(3)), dchip,
                   font=_wfont(S(11), True), fill=_DMG_C.get(dchip, C_MUTED))
            if r.get("rank"):
                d.text((rx2 - S(46) - d.textlength(r["rank"], font=_wfont(S(12), True)), yy + S(2)),
                       r["rank"], font=_wfont(S(12), True), fill=C_ARC)
            # scout tags line (rank/tilt/OTP/off-champ), colored relative to YOU
            cxp = px + S(44)
            ptags = r.get("ptags") or []
            for txt, tone in ptags:
                f = _wfont(S(12), True)
                d.text((cxp, yy + S(23)), txt, font=f, fill=_TONE_C.get(tone, C_MUTED))
                cxp += d.textlength(txt, font=f) + S(14)
            if not ptags and r.get("rank") == "":       # not scouted -> at least the champ read
                if r.get("phrases"):
                    d.text((px + S(44), yy + S(23)), "· " + r["phrases"][0], font=_wfont(S(12)),
                           fill=C_FAINT)
            # champ good/bad phrase (enemies get one line even when scouted)
            if detailed and r.get("phrases"):
                d.text((px + S(44), yy + S(44)), "· " + r["phrases"][0], font=_wfont(S(12)),
                       fill=C_MUTED)
            yy += rowh

    _column(M, "YOUR TEAM", b.get("allies") or [], C_GOOD, detailed=False)
    _column(W - M - colw, "ENEMY", b.get("enemies") or [], C_BAD, detailed=True)

    # GAME PLAN — the synthesis, wide across the bottom
    plan = b.get("plan") or []
    ph = S(170)
    py = H - S(180)
    pw = W - 2 * M
    _card(d, M, py, pw, ph, C_EMBER)
    d.text((M + S(22), py + S(14)), "GAME PLAN", font=_wfont(S(15), True), fill=C_EMBER)
    yy = py + S(44)
    for line in plan:
        d.text((M + S(22), yy), "→ " + line, font=_wfont(S(16)), fill=C_TXT)
        yy += S(28)
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


def _live_up():
    """True once the live game (:2999) is serving — i.e. the game world has loaded and you're
    past the loading screen. The loading screen is exactly the window where this is FALSE."""
    try:
        lb.http("https://127.0.0.1:2999/liveclientdata/gamestats", timeout=1, insecure=True)
        return True
    except Exception:
        return False


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

    def _fetch():
        # ALL network work lives here, OFF the poll/render loop, so the overlay is never blocked.
        # Phase 1: champs + tags + plan (fast, no Riot API) -> the overlay appears immediately.
        # Phase 2: per-player rank/OTP scout (slow, rate-limited) -> fills in when ready.
        try:
            fast = ll.brief(dd, scout=False)
            if fast:
                state["brief"] = fast
                _log("fast brief READY (champs/tags/plan) -> showing")
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
        while state["run"]:
            live = _live_up()
            gf = _gameflow_phase()
            errs = (errs + 1) if gf == "" else 0           # "" = LCU hiccup; only real after a streak
            # LOADING = the game process is up (GameStart/InProgress/Reconnect) but the live
            # game isn't serving yet. That whole span is the loading screen.
            loading = (gf in ("GameStart", "InProgress", "Reconnect")) and not live
            n += 1
            if n <= 4 or loading or n % 10 == 0:           # log the interesting transitions
                _log(f"poll gf={gf!r} live={live} loading={loading} want={state['want']} shown={state['shown']} brief={state['brief'] is not None} fetching={state['fetching']}")
            if loading:
                state["want"] = True
                if not state["fetching"]:                  # kick the fetch ONCE, on a worker thread
                    state["fetching"] = True
                    threading.Thread(target=_fetch, daemon=True).start()
            elif live or errs >= 3 or gf in ("None", "Lobby", "Matchmaking", "ReadyCheck",
                                             "WaitingForStats", "PreEndOfGame", "EndOfGame"):
                # game started, dodge/requeue, or client gone -> this run is over
                _done(f"over (gf={gf!r} live={live} errs={errs})")
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
            if b is not state["rendered"]:              # (re)draw on first show AND on scout upgrade
                frame = render_frame(dd, b, W, H)
                ph = ImageTk.PhotoImage(frame)
                label.configure(image=ph)
                label.image = ph
                state["rendered"] = b
                if not state["shown"]:
                    root.deiconify()
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
