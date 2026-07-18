#!/usr/bin/env python3
"""smitedead.py - the fullscreen DEATH BRIEF: a see-through overlay that owns the grey screen.

When you die, this fades in over the whole monitor with the dense read you can't afford to
process while alive: a giant respawn clock + the one tempo verdict, what to buy on respawn,
the win read, the scariest enemy spike, the next objectives, and a feed of what you missed.
Laid out AROUND the game's own death HUD (keep-out map in render_frame): team boards sit
top-center where TAB lives, the reactive read hangs under the death recap on the left, the
strategic read hangs under the stats bar on the right — nothing covers the recap, chat,
respawn portraits, minimap, BACK IN plate, or the TEMPO widget's bottom-left corner. The
CENTER stays clear (magenta chroma key -> fully transparent AND click-through), so you keep
watching the fight through it and keep full camera control while dead. It vanishes the
instant you respawn.

100% read-only off the live-client feed (:2999). It never moves your camera or sends a single
input to the game - that would be automation Riot bans for. It only shows you what's true.
"""
import sys, os, time, threading, ctypes, json, subprocess
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
from smiteoverlay import target_monitor, make_no_activate, toplevel_hwnd, monitors, monitor_of, client_rect

_user32 = ctypes.windll.user32
_CREATE_NO_WINDOW = 0x08000000
_MON_CACHE = os.path.expanduser("~/.claude/smiteless_gamemon.json")


def _game_process_monitor():
    """Monitor of the LARGEST visible window owned by the League GAME process. This is the
    loading screen AND the live game — the class-name lookup misses the loading screen on some
    setups, but a process-owned window is always there once the game launches."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq League of Legends.exe",
                              "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             creationflags=_CREATE_NO_WINDOW, timeout=10).stdout
    except Exception:
        return None
    pids = set()
    for ln in out.splitlines():
        parts = ln.split('","')
        if len(parts) >= 2 and parts[0].strip('"').lower() == "league of legends.exe":
            try:
                pids.add(int(parts[1].strip('"')))
            except Exception:
                pass
    if not pids:
        return None
    best = [None]
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _l):
        if not _user32.IsWindowVisible(h):
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids:
            r = wintypes.RECT()
            _user32.GetWindowRect(h, ctypes.byref(r))
            area = (r.right - r.left) * (r.bottom - r.top)
            if area > 10000 and (best[0] is None or area > best[0][0]):
                best[0] = (area, ((r.left + r.right) // 2, (r.top + r.bottom) // 2))
        return True
    _user32.EnumWindows(proc(cb), 0)
    return monitor_of(*best[0][1]) if best[0] else None


def game_monitor():
    """The monitor the GAME is actually on — where an in-game / loading overlay belongs. In
    priority: the game process's own window (works during loading), the RiotWindowClass window,
    a cached last-known game monitor, the League client's monitor, then the primary. NEVER the
    non-primary target_monitor default, which put overlays on the wrong screen."""
    mon = _game_process_monitor()
    if not mon:
        try:
            h = _user32.FindWindowW("RiotWindowClass", None)
            if h and _user32.IsWindowVisible(h):
                r = wintypes.RECT()
                _user32.GetWindowRect(h, ctypes.byref(r))
                mon = monitor_of((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        except Exception:
            pass
    if mon:
        try:
            json.dump(list(mon), open(_MON_CACHE, "w"))     # remember for next loading screen
        except Exception:
            pass
        return mon
    try:
        c = json.load(open(_MON_CACHE))                     # cached last game monitor
        if isinstance(c, list) and len(c) == 4:
            return tuple(c)
    except Exception:
        pass
    try:
        _h, rect = client_rect()                            # the League client's monitor
        if rect:
            return monitor_of((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
    except Exception:
        pass
    for m in monitors():
        if (m[0], m[1]) == (0, 0):                          # primary (last resort)
            return m
    return monitors()[0]
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
    # Resolution-adaptive, but sized to sit as a compact ~17%-per-column strip on ANY monitor
    # (the design is drawn against a 1400px-tall reference, so 1080p renders ~0.77x — smaller
    # than the old 1080-reference that filled ~22% of the width and felt oversized).
    s = max(0.62, min(1.55, H / 1400.0))
    def S(v): return int(v * s)
    M = S(30)
    colw = S(430)

    lx = M
    rx = W - M - colw
    # Keep-out map of the GAME's own death HUD, so the brief reads as part of it instead
    # of sitting on top of it: top-left death recap/gold/shop ends ~0.31H; the chat/kill
    # feed owns the left from ~0.57H; the all-10 respawn portrait strip sits ~0.49-0.62H
    # on the right; the minimap owns the bottom-right; BACK IN owns bottom-center; the
    # bottom-left corner belongs to the user's TEMPO widget. Every card fits its lane or
    # doesn't draw.
    LY0, LY1 = int(H * 0.325), int(H * 0.565)     # left lane: below recap, above chat
    RY0, RY1 = int(H * 0.070), int(H * 0.485)     # right lane: below stats bar, above portraits

    def _hdr(x, y, title, col):
        d.text((x + S(22), y + S(11)), title, font=_wfont(S(13), True), fill=col)

    def _block(x, y, title, title_col, line, sub, rail, big=False, ymax=None):
        """A coaching card: bold headline + wrapped takeaway. Returns the new y-cursor.
        With ymax set, a card that would cross its lane boundary is skipped whole."""
        subf = _wfont(S(13))
        sublines = _wrap(d, sub or "", subf, colw - S(44))[:2] if sub else []
        lf = _wfont(S(17 if big else 16), True)
        headlines = _wrap(d, line or "", lf, colw - S(44))[:2] if line else []
        h = S(34) + S(23) * len(headlines) + S(20) * len(sublines)
        if ymax is not None and y + h > ymax:
            return y
        _card(d, x, y, colw, h, rail)
        _hdr(x, y, title, title_col)
        yy = y + S(32)
        for ln in headlines:
            d.text((x + S(22), yy), ln, font=lf, fill=C_TXT)
            yy += S(23)
        for ln in sublines:
            d.text((x + S(22), yy), ln, font=subf, fill=C_MUTED)
            yy += S(20)
        return y + h + S(12)

    # ========== TOP-CENTER: the two team boards, tab-scoreboard position ==========
    # (the one big free band while dead — the game's own banner sits above, the fight
    # is usually below; matching the TAB scoreboard's home makes it feel native)
    board = b.get("board")
    if board and (board.get("allies") or board.get("enemies")):
        bw = colw
        bx = (W - (bw * 2 + S(20))) // 2
        ty = S(56)
        if board.get("allies"):
            _team_block(d, S, bx, ty, bw, board["allies"], "YOUR TEAM", C_GOOD,
                        lead=board.get("gold_lead"))
        if board.get("enemies"):
            _team_block(d, S, bx + bw + S(20), ty, bw, board["enemies"], "ENEMY", C_BAD)

    # ========== LEFT LANE: the reactive read (clock, why you died, respawn plan) ==========
    ly = LY0
    ch = S(100)
    _card(d, lx, ly, colw, ch, _TONE_C.get(b.get("tone"), C_EMBER))
    px = lx + S(22)
    d.text((px, ly + S(11)), "RESPAWN", font=_wfont(S(13), True), fill=C_MUTED)
    secs = max(0, int(round(b.get("secs") or 0)))
    clock = f"{secs}"
    d.text((px - S(3), ly + S(26)), clock, font=_dfont(S(58)), fill=C_TXT)
    cw = d.textlength(clock, font=_dfont(S(58)))
    d.text((px + cw + S(8), ly + S(56)), "sec", font=_wfont(S(15)), fill=C_MUTED)
    d.text((px + cw + S(8), ly + S(30)),
           f"back {_mmss((b.get('gametime') or 0) + secs)}", font=_wfont(S(13)), fill=C_FAINT)
    ly += ch + S(12)

    why = b.get("why")
    if why:
        ly = _block(lx, ly, "WHY YOU DIED", C_BAD, why.get("line"), why.get("sub"), C_BAD,
                    ymax=LY1)

    buy, verdict = b.get("buy"), b.get("verdict")
    if buy or verdict:
        lines = _wrap(d, "→ " + buy, _wfont(S(15), True), colw - S(44))[:1] if buy else []
        vlines = _wrap(d, "→ " + verdict, _wfont(S(15), True), colw - S(44))[:1] if verdict else []
        h = S(34) + S(24) * (len(lines) + len(vlines))
        if ly + h <= LY1:
            _card(d, lx, ly, colw, h, C_INFO)
            _hdr(lx, ly, "ON RESPAWN", C_MUTED)
            yy = ly + S(32)
            for ln in lines:
                d.text((lx + S(22), yy), ln, font=_wfont(S(15), True), fill=C_TXT)
                yy += S(24)
            for ln in vlines:
                d.text((lx + S(22), yy), ln, font=_wfont(S(15), True), fill=C_ARC)
                yy += S(24)
            ly += h + S(12)

    # what you missed, folded into whatever's left of the lane (the game's own chat and
    # the TEMPO widget live at the bottom-left — never park a card down there again)
    feed = b.get("feed") or []
    if feed:
        rows = min(len(feed), (LY1 - ly - S(40)) // S(22))
        if rows >= 2:
            fh = S(40) + S(22) * rows
            _card(d, lx, ly, colw, fh, C_LINE)
            d.text((lx + S(22), ly + S(12)), "WHILE YOU WERE DEAD", font=_wfont(S(13), True),
                   fill=C_MUTED)
            yy = ly + S(36)
            for r in feed[:rows]:
                col = C_GOOD if r.get("ally") else C_BAD
                d.text((lx + S(22), yy), f"{r.get('ago', 0):>2}s", font=_wfont(S(12)), fill=C_FAINT)
                d.text((lx + S(60), yy), r.get("text", ""), font=_wfont(S(13)), fill=col)
                yy += S(22)

    # ========== RIGHT LANE: the strategic read (win con, threat, win%, objectives) ==========
    ry = RY0
    if b.get("wincon"):
        ry = _block(rx, ry, "HOW YOU WIN", C_EMBER, b["wincon"], None, C_EMBER, big=True,
                    ymax=RY1)
    threat = b.get("threat")
    if threat:
        ry = _block(rx, ry, "THE THREAT", C_BAD, threat.get("line"), threat.get("sub"), C_BAD,
                    ymax=RY1)
    wp = b.get("winprob")
    if wp:
        wh = S(62)
        if ry + wh <= RY1:
            good = wp.get("ahead")
            _card(d, rx, ry, colw, wh, C_GOOD if good else C_BAD)
            _hdr(rx, ry, "WIN READ", C_MUTED)
            pct = f"{int(wp.get('pct') or 0)}%"
            d.text((rx + colw - S(22) - d.textlength(pct, font=_dfont(S(30))), ry + S(20)),
                   pct, font=_dfont(S(30)), fill=(C_GOOD if good else C_BAD))
            d.text((rx + S(22), ry + S(34)), wp.get("basis") or "", font=_wfont(S(13)), fill=C_MUTED)
            ry += wh + S(12)
    objs = b.get("objectives") or []
    if objs:
        rows = min(len(objs), (RY1 - ry - S(34)) // S(22))
        if rows >= 1:
            oh = S(34) + S(22) * rows
            _card(d, rx, ry, colw, oh, C_ARC)
            _hdr(rx, ry, "NEXT OBJECTIVES", C_MUTED)
            oy = ry + S(32)
            for o in objs[:rows]:
                secs_o = o.get("secs") or 0
                up = o.get("up") or secs_o <= 0
                tcol = C_EMBER if (up or o.get("urgent")) else C_TXT
                when = "UP" if up else _mmss(secs_o)
                d.text((rx + S(22), oy), o.get("label", "?"), font=_wfont(S(14)), fill=C_TXT)
                d.text((rx + colw - S(22) - d.textlength(when, font=_wfont(S(14), True)), oy),
                       when, font=_wfont(S(14), True), fill=tcol)
                oy += S(22)

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
    root.attributes("-transparentcolor", CHROMA_HEX)   # bg pixels fully invisible
    root.attributes("-alpha", 0.88)                    # panels/text ~88% — the game shows through
    root.geometry(f"{W}x{H}+{l}+{t}")
    label = tk.Label(root, bd=0, bg=CHROMA_HEX)
    label.pack(fill="both", expand=True)
    root.update_idletasks()
    hwnd = toplevel_hwnd(root.winfo_id())
    _make_click_through(hwnd)

    state = {"brief": None, "ts": 0.0, "fails": 0, "run": True, "shown": False, "hwnd": hwnd}

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
                _make_click_through(state["hwnd"])
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
