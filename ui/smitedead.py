#!/usr/bin/env python3
"""smitedead.py - the fullscreen DEATH BRIEF: a see-through overlay that owns the grey screen.

When you die, this fades in over the whole monitor with the dense read you can't afford to
process while alive: a giant respawn clock + the one tempo verdict, what to buy on respawn,
the win read, the scariest enemy spike, the next objectives, and a feed of what you missed.
The CENTER stays clear (a magenta chroma key -> fully transparent AND click-through), so you
keep watching the fight through it and keep full camera control while dead. It vanishes the
instant you respawn.

100% read-only off the live-client feed (:2999). It never moves your camera or sends a single
input to the game - that would be automation Riot bans for. It only shows you what's true.
"""
import sys, os, time, threading, ctypes
from ctypes import wintypes

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
import loldead as ld
import phasecheck
import smiteconfig as cfg
import smiteskin as skin
from smiteoverlay import target_monitor, make_no_activate, toplevel_hwnd, monitors, monitor_of


def game_monitor():
    """The monitor the GAME is actually on — that's where an in-game overlay belongs. Finds
    the League game window (class RiotWindowClass); falls back to the PRIMARY monitor (origin
    0,0), never the non-primary target_monitor (the board's fallback, wrong for a fullscreen
    in-game HUD since you play on your main screen)."""
    try:
        h = _user32.FindWindowW("RiotWindowClass", None)
        if h and _user32.IsWindowVisible(h):
            r = wintypes.RECT()
            _user32.GetWindowRect(h, ctypes.byref(r))
            return monitor_of((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    except Exception:
        pass
    for m in monitors():
        if (m[0], m[1]) == (0, 0):      # primary
            return m
    return monitors()[0]

_user32 = ctypes.windll.user32
CHROMA_HEX = "#ff00ff"                 # chroma key -> transparent + (with WS_EX_TRANSPARENT) click-through

C_SURF = skin.rgb(skin.SURFACE); C_RAISED = skin.rgb(skin.RAISED); C_LINE = skin.rgb(skin.LINE)
C_TXT = skin.rgb(skin.TXT); C_MUTED = skin.rgb(skin.MUTED); C_FAINT = skin.rgb(skin.FAINT)
C_EMBER = skin.rgb(skin.EMBER); C_ARC = skin.rgb(skin.ARC)
C_GOOD = skin.rgb(skin.GOOD); C_BAD = skin.rgb(skin.BAD); C_WARN = skin.rgb(skin.WARN)
C_INFO = skin.rgb(skin.INFO)
_TONE_C = {"go": C_ARC, "hold": C_BAD, "plan": C_EMBER}

_F = {}


def _wfont(sz, bold=False):
    from PIL import ImageFont
    k = ("w", sz, bold)
    if k not in _F:
        try:
            _F[k] = ImageFont.truetype("seguisb.ttf" if bold else "segoeui.ttf", sz)
        except Exception:
            _F[k] = ImageFont.load_default()
    return _F[k]


def _dfont(sz):
    from PIL import ImageFont
    k = ("d", sz)
    if k not in _F:
        try:
            _F[k] = ImageFont.truetype(skin.FONT_DISPLAY_TTF, sz)
        except Exception:
            _F[k] = _wfont(sz, True)
    return _F[k]


def _wrap(d, text, font, maxw):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _card(d, x, y, w, h, rail):
    d.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=C_SURF)
    d.rounded_rectangle([x, y, x + 6, y + h], radius=3, fill=rail)
    d.rectangle([x + 3, y, x + 6, y + h], fill=rail)


def _mmss(gt):
    gt = max(0, int(gt))
    return f"{gt // 60}:{gt % 60:02d}"


def _team_block(d, S, x, y, w, rows, title, title_col, lead=None):
    """One team's rundown as an edge column (role, champ, KDA, gold, a good/bad tag). Lives
    on the LEFT/RIGHT edge so the middle of the screen stays clear to watch the fight."""
    rowh = S(23)
    h = S(34) + rowh * len(rows)
    _card(d, x, y, w, h, title_col)
    px = x + S(18)
    d.text((px, y + S(10)), title, font=_wfont(S(12), True), fill=title_col)
    if lead is not None:
        lt = f"{lead / 1000:+.1f}k"
        d.text((x + w - S(18) - d.textlength(lt, font=_wfont(S(12), True)), y + S(10)),
               lt, font=_wfont(S(12), True), fill=(C_GOOD if lead >= 0 else C_BAD))
    yy = y + S(30)
    for r in rows:
        fill = C_EMBER if r["me"] else (C_FAINT if r["dead"] else C_TXT)
        d.text((px, yy), r["role"], font=_wfont(S(10), True), fill=C_MUTED)
        d.text((px + S(30), yy), (r["champ"] or "?")[:9], font=_wfont(S(12), r["me"]), fill=fill)
        d.text((px + S(112), yy), f"{r['k']}/{r['d']}/{r['a']}", font=_wfont(S(11)), fill=fill)
        d.text((px + S(178), yy), f"{r['gold'] / 1000:.1f}k", font=_wfont(S(11), True), fill=C_WARN)
        tag = "dead" if r["dead"] else ("FED" if r.get("fed") else r.get("tag", ""))
        if tag:
            tcol = C_BAD if r.get("fed") else (C_FAINT if tag == "dead" else C_MUTED)
            d.text((x + w - S(16) - d.textlength(tag, font=_wfont(S(11), bool(r.get("fed")))), yy),
                   tag, font=_wfont(S(11), bool(r.get("fed"))), fill=tcol)
        yy += rowh
    return y + h


def render_frame(dd, b, W, H):
    """Draw the whole brief onto a monitor-sized image whose background is the chroma key
    (so everything not a panel is see-through + click-through). Returns a PIL RGB image."""
    from PIL import Image, ImageDraw
    CHROMA = (255, 0, 255)
    img = Image.new("RGB", (W, H), CHROMA)
    d = ImageDraw.Draw(img)
    s = max(0.6, min(1.4, H / 1080.0))            # scale fonts/panels to the monitor
    def S(v): return int(v * s)
    M = S(30)
    colw = S(430)

    # ---------- LEFT COLUMN: hero (respawn + verdict), then buy ----------
    lx = M
    hy = int(H * 0.24)
    hh = S(250)
    rail = _TONE_C.get(b.get("tone"), C_EMBER)
    _card(d, lx, hy, colw, hh, rail)
    px, py = lx + S(24), hy + S(16)
    d.text((px, py), "RESPAWN", font=_wfont(S(15), True), fill=C_MUTED)
    secs = max(0, int(round(b.get("secs") or 0)))
    clock = f"{secs}"
    d.text((px - S(4), py + S(18)), clock, font=_dfont(S(96)), fill=C_TXT)
    cw = d.textlength(clock, font=_dfont(S(96)))
    d.text((px + cw + S(6), py + S(78)), "sec", font=_wfont(S(20)), fill=C_MUTED)
    back_at = _mmss((b.get("gametime") or 0) + secs)
    d.text((px, py + S(128)), f"back at {back_at}", font=_wfont(S(15)), fill=C_FAINT)
    vy = py + S(158)
    for ln in _wrap(d, b.get("verdict") or "", _wfont(S(18), True), colw - S(48))[:2]:
        d.text((px, vy), ln, font=_wfont(S(18), True), fill=rail)
        vy += S(24)
    for ln in _wrap(d, b.get("verdict_sub") or "", _wfont(S(13)), colw - S(48))[:2]:
        d.text((px, vy), ln, font=_wfont(S(13)), fill=C_MUTED)
        vy += S(18)

    # buy card
    by = hy + hh + S(14)
    ly = by                                        # left-column cursor for the allies board
    if b.get("buy"):
        bh = S(72)
        _card(d, lx, by, colw, bh, C_INFO)
        d.text((lx + S(24), by + S(12)), "ON RESPAWN", font=_wfont(S(13), True), fill=C_MUTED)
        for ln in _wrap(d, b["buy"], _wfont(S(17), True), colw - S(48))[:1]:
            d.text((lx + S(24), by + S(34)), ln, font=_wfont(S(17), True), fill=C_TXT)
        ly = by + bh + S(14)

    # ---------- RIGHT COLUMN: win%, watch (spike), next objectives ----------
    rx = W - M - colw
    ry = int(H * 0.24)
    wp = b.get("winprob")
    if wp:
        wh = S(88)
        good = wp.get("ahead")
        _card(d, rx, ry, colw, wh, C_GOOD if good else C_BAD)
        d.text((rx + S(24), ry + S(14)), "WIN READ", font=_wfont(S(13), True), fill=C_MUTED)
        pct = f"{int(wp.get('pct') or 0)}%"
        d.text((rx + S(24), ry + S(30)), pct, font=_dfont(S(40)), fill=(C_GOOD if good else C_BAD))
        d.text((rx + S(24) + d.textlength(pct, font=_dfont(S(40))) + S(14), ry + S(46)),
               wp.get("basis") or "", font=_wfont(S(14)), fill=C_MUTED)
        ry += wh + S(12)
    sp = b.get("spike")
    if sp:
        sh = S(70)
        _card(d, rx, ry, colw, sh, C_BAD)
        d.text((rx + S(24), ry + S(12)), "WATCH — SPIKED & AHEAD", font=_wfont(S(13), True), fill=C_MUTED)
        d.text((rx + S(24), ry + S(30)), f"{sp.get('name')}  {sp.get('items')} items  "
               f"{sp.get('k')}/{sp.get('d')}", font=_wfont(S(18), True), fill=C_TXT)
        ry += sh + S(12)
    objs = b.get("objectives") or []
    if objs:
        oh = S(40) + S(24) * len(objs)
        _card(d, rx, ry, colw, oh, C_ARC)
        d.text((rx + S(24), ry + S(12)), "NEXT OBJECTIVES", font=_wfont(S(13), True), fill=C_MUTED)
        oy = ry + S(36)
        for o in objs:
            secs_o = o.get("secs") or 0
            up = o.get("up") or secs_o <= 0
            tcol = C_EMBER if (up or o.get("urgent")) else C_TXT
            when = "UP" if up else _mmss(secs_o)
            lab = o.get("label", "?")
            d.text((rx + S(24), oy), lab, font=_wfont(S(15)), fill=C_TXT)
            d.text((rx + colw - S(24) - d.textlength(when, font=_wfont(S(15), True)), oy),
                   when, font=_wfont(S(15), True), fill=tcol)
            oy += S(24)

    # ---------- EDGES: the 10-player board, split L/R so the MIDDLE stays clear ----------
    # (you keep watching the fight through the transparent center while dead)
    board = b.get("board")
    if board:
        if board.get("allies"):
            _team_block(d, S, lx, ly, colw, board["allies"], "YOUR TEAM", C_GOOD,
                        lead=board.get("gold_lead"))
        if board.get("enemies"):
            _team_block(d, S, rx, ry + S(2), colw, board["enemies"], "ENEMY", C_BAD)

    # ---------- BOTTOM: what you missed ----------
    feed = b.get("feed") or []
    if feed:
        fw = S(560)
        fh = S(40) + S(22) * len(feed)
        fx, fy = M, H - M - fh
        _card(d, fx, fy, fw, fh, C_LINE)
        d.text((fx + S(24), fy + S(12)), "WHILE YOU WERE DEAD", font=_wfont(S(13), True), fill=C_MUTED)
        yy = fy + S(36)
        for r in feed:
            col = C_GOOD if r.get("ally") else C_BAD
            d.text((fx + S(24), yy), f"{r.get('ago', 0):>2}s", font=_wfont(S(12)), fill=C_FAINT)
            d.text((fx + S(64), yy), r.get("text", ""), font=_wfont(S(14)), fill=col)
            yy += S(22)

    return img


# ---------- click-through / no-activate window styling ----------
def _make_click_through(hwnd):
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x00000020, 0x00080000
    try:
        make_no_activate(hwnd)                     # NOACTIVATE | TOOLWINDOW | TOPMOST
        ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT | WS_EX_LAYERED)
    except Exception:
        pass


def _single_instance():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW(None, False, "Global\\SmitelessDead")
    return ctypes.get_last_error() != 183          # ERROR_ALREADY_EXISTS


def main():
    if not _single_instance():
        return
    if not cfg.load().get("death_brief", True):     # feature gated off -> don't even show up
        return
    import tkinter as tk
    from PIL import ImageTk

    dd = lb.ddragon()
    mon = game_monitor()
    l, t, r, b = mon
    W, H = r - l, b - t

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

    state = {"brief": None, "ts": 0.0, "fails": 0, "run": True, "shown": False}

    def poll():
        while state["run"]:
            try:
                raw = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata",
                              timeout=2, insecure=True)
                state["fails"] = 0
            except Exception:
                raw = None
                state["fails"] += 1
            if raw is not None:
                try:
                    state["brief"], state["ts"] = ld.brief(dd, raw), time.monotonic()
                except Exception:
                    state["brief"] = None
            # game over / client gone -> exit (a long unreachable streak AND not in a game)
            if state["fails"] >= 12 and phasecheck.phase() not in ("InProgress", "GameStart", "Reconnect"):
                state["run"] = False
                try:
                    root.after(0, root.destroy)
                except Exception:
                    pass
                return
            time.sleep(0.6)

    threading.Thread(target=poll, daemon=True).start()

    def tick():
        if not state["run"]:
            return
        b = state["brief"]
        if b:
            live = dict(b)                          # smooth the clock between polls
            live["secs"] = max(0, (b.get("secs") or 0) - (time.monotonic() - state["ts"]))
            frame = render_frame(dd, live, W, H)
            ph = ImageTk.PhotoImage(frame)
            label.configure(image=ph)
            label.image = ph
            if not state["shown"]:
                root.deiconify()
                _make_click_through(toplevel_hwnd(root.winfo_id()))
                state["shown"] = True
        elif state["shown"]:
            root.withdraw()                         # respawned -> vanish
            state["shown"] = False
        root.after(250, tick)

    root.withdraw()
    state["shown"] = False
    root.after(200, tick)
    root.mainloop()
    state["run"] = False


if __name__ == "__main__":
    main()
