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
import phasecheck
import smiteconfig as cfg
import smiteskin as skin
# reuse the death overlay's window plumbing + drawing helpers (one source of truth)
from smitedead import (_wfont, _dfont, _wrap, _card, _make_click_through, game_monitor,
                       CHROMA_HEX, C_TXT, C_MUTED, C_FAINT, C_EMBER, C_ARC, C_GOOD, C_BAD,
                       C_WARN, C_INFO, C_SURF)

_user32 = ctypes.windll.user32
_DMG_C = {"AD": C_WARN, "AP": C_ARC, "mixed": C_MUTED}


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
        yy = S(142)
        rowh = S(78) if detailed else S(58)
        for r in rows:
            d.text((px, yy + S(2)), r["role"], font=_wfont(S(11), True), fill=C_MUTED)
            d.text((px + S(44), yy), (r["champ"] or "?")[:16], font=_wfont(S(17), True), fill=C_TXT)
            dchip = r["dmg"]
            cw = d.textlength(dchip, font=_wfont(S(11), True))
            d.text((x + colw - S(22) - cw, yy + S(3)), dchip, font=_wfont(S(11), True),
                   fill=_DMG_C.get(dchip, C_MUTED))
            ph = r.get("phrases") or []
            if detailed:
                for i, line in enumerate(ph[:2]):
                    d.text((px + S(44), yy + S(24) + i * S(18)), "· " + line,
                           font=_wfont(S(13)), fill=C_MUTED)
            elif ph:
                d.text((px + S(44), yy + S(24)), "· " + ph[0], font=_wfont(S(12)), fill=C_FAINT)
            yy += rowh

    _column(M, "YOUR TEAM", b.get("allies") or [], C_GOOD, detailed=False)
    _column(W - M - colw, "ENEMY — WHAT THEY DO", b.get("enemies") or [], C_BAD, detailed=True)

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

    state = {"run": True, "brief": None, "shown": False, "deadline": time.monotonic() + 120}

    def poll():
        while state["run"]:
            ph = phasecheck.phase()
            if ph == "GameStart":                      # the loading screen
                if state["brief"] is None:
                    try:
                        state["brief"] = ll.brief(dd)
                    except Exception:
                        state["brief"] = None
            elif ph in ("InProgress", "Reconnect", "") and ph != "GameStart":
                # game started (or client gone) -> loading is over
                if ph != "GameStart":
                    state["run"] = False
                    try:
                        root.after(0, root.destroy)
                    except Exception:
                        pass
                    return
            if time.monotonic() > state["deadline"]:
                state["run"] = False
                try:
                    root.after(0, root.destroy)
                except Exception:
                    pass
                return
            time.sleep(1.0)

    threading.Thread(target=poll, daemon=True).start()

    def tick():
        if not state["run"]:
            return
        if state["brief"]:
            if not state["shown"]:
                frame = render_frame(dd, state["brief"], W, H)
                ph = ImageTk.PhotoImage(frame)
                label.configure(image=ph)
                label.image = ph
                root.deiconify()
                _make_click_through(toplevel_hwnd(root.winfo_id()))
                state["shown"] = True
        root.after(300, tick)

    root.withdraw()
    root.after(200, tick)
    root.mainloop()
    state["run"] = False


if __name__ == "__main__":
    main()
