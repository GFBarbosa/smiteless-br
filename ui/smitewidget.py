#!/usr/bin/env python3
"""smitewidget.py - small floating in-game item helper.

A compact, always-on-top, draggable window that shows what to build NEXT from op.gg's
real per-champ pool, adapting live to the enemy's actual build + who's fed + what you
already own. Independent of the big scoreboard overlay - it's meant to sit in a corner
the whole game. Never steals focus; remembers where you drag it.

  python smitewidget.py
"""
import sys, os, json, threading, time, queue
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):                # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass
import lolbuild as lb
import lolitems as li
import lollive as ll
import phasecheck
import smiteconfig as cfg
from smiteoverlay import (make_no_activate, show_no_activate, toplevel_hwnd,
                          monitors, _kernel32)

INGAME_PHASES = ("GameStart", "InProgress", "Reconnect")   # widget belongs on screen only here

BG = "#11131a"; GOLD = "#c8aa6e"; TXT = "#d8d6cf"; MUTED = "#7f7d75"
RED = "#e0646c"; PURPLE = "#c98bdb"; BLUE = "#7fa8e0"; GREEN = "#5fc47a"; TEAL = "#4cc0b0"
KIND_COLOR = {"counter": RED, "antiheal": PURPLE, "build": GOLD, "boots": BLUE}
KIND_TAG = {"counter": "⚠", "antiheal": "✚", "build": "▸", "boots": "▸"}
POLL = 5                                                  # seconds between live reads
# objective-timer feature toggles read from settings (default on); a per-frame gate keeps the
# widget honest when the user turns them off.
POS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "smiteless_widget_pos.json")


def acquire_single_instance():
    _kernel32.CreateMutexW(None, False, "Global\\SmitelessWidget")
    return _kernel32.GetLastError() != 183                # ERROR_ALREADY_EXISTS


def _load_pos():
    try:
        p = json.load(open(POS_FILE))
        x, y = int(p["x"]), int(p["y"])
        for m in monitors():                             # only if still on a visible monitor
            if m[0] - 40 <= x <= m[2] and m[1] - 20 <= y <= m[3]:
                return x, y
    except Exception:
        pass
    return None


def _save_pos(x, y):
    try:
        os.makedirs(os.path.dirname(POS_FILE), exist_ok=True)
        json.dump({"x": x, "y": y}, open(POS_FILE, "w"))
    except Exception:
        pass


def main():
    if not cfg.load().get("item_widget", True):
        return                                           # item widget disabled in settings
    if not acquire_single_instance():
        return                                           # one widget already up
    import tkinter as tk
    dd = lb.ddragon()
    st = {"alive": True}

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.94)
    root.configure(bg=GOLD)                              # 1px gold edge via padding
    outer = tk.Frame(root, bg=BG)
    outer.pack(padx=1, pady=1, fill="both", expand=True)

    hdr = tk.Frame(outer, bg=BG)
    hdr.pack(fill="x", padx=9, pady=(6, 1))
    tk.Label(hdr, text="SMITELESS · build", font=("Segoe UI", 8, "bold"), fg=GOLD, bg=BG).pack(side="left")
    close = tk.Label(hdr, text="✕", font=("Segoe UI", 9, "bold"), fg=MUTED, bg=BG, cursor="hand2")
    close.pack(side="right")

    champ = tk.Label(outer, text="waiting for a live game…", font=("Segoe UI", 12, "bold"),
                     fg=MUTED, bg=BG, anchor="w")
    champ.pack(fill="x", padx=9)
    body = tk.Frame(outer, bg=BG)
    body.pack(fill="x", padx=9, pady=(3, 2))
    intel = tk.Frame(outer, bg=BG)                        # live win read + objective timers + spike
    intel.pack(fill="x", padx=9, pady=(0, 1))
    summ = tk.Label(outer, text="open in-game or a replay to see suggestions",
                    font=("Segoe UI", 8), fg=MUTED, bg=BG, anchor="w", justify="left")
    summ.pack(fill="x", padx=9, pady=(0, 7))

    def _fmt(secs):
        return "UP" if secs <= 0 else f"{secs // 60}:{secs % 60:02d}"

    def render_intel(pulse):
        for w in intel.winfo_children():
            w.destroy()
        if not pulse:
            return
        wp = pulse.get("winprob")
        if wp:
            lab = "WIN" if wp["ahead"] else "BEHIND"
            row = tk.Frame(intel, bg=BG)
            row.pack(fill="x")
            tk.Label(row, text=f"{lab} {wp['pct']}%", font=("Segoe UI", 9, "bold"),
                     fg=(GREEN if wp["ahead"] else RED), bg=BG, anchor="w").pack(side="left")
            tk.Label(row, text=f"  {wp['basis']}", font=("Segoe UI", 8), fg=MUTED, bg=BG,
                     anchor="w").pack(side="left")
        objs = pulse.get("objectives") or []
        if objs:
            row = tk.Frame(intel, bg=BG)
            row.pack(fill="x")
            tk.Label(row, text="⟳", font=("Segoe UI", 9), fg=TEAL, bg=BG).pack(side="left")
            for o in objs[:3]:
                col = GOLD if o["urgent"] else (TEAL if o["up"] else MUTED)
                tk.Label(row, text=f" {o['label']} {_fmt(o['secs'])} ", font=("Segoe UI", 9,
                         "bold" if o["urgent"] else "normal"), fg=col, bg=BG).pack(side="left")
        sp = pulse.get("spike")
        if sp:
            tk.Label(intel, text=f"⚠ {sp['name']} spiked — {sp['items']} items, {sp['k']}/{sp['d']}",
                     font=("Segoe UI", 9), fg=RED, bg=BG, anchor="w").pack(fill="x")

    def render(rec, pulse=None):
        for w in body.winfo_children():
            w.destroy()
        if not rec:
            champ.config(text="waiting for a live game…", fg=MUTED)
            summ.config(text="open in-game or a replay to see suggestions")
            render_intel(None)
            return
        champ.config(text=rec["champ"], fg=TXT)
        if not rec["lines"]:
            tk.Label(body, text="building standard — no defensive swap needed",
                     font=("Segoe UI", 9), fg=MUTED, bg=BG, anchor="w").pack(fill="x")
        for kind, txt in rec["lines"]:
            tk.Label(body, text=f"{KIND_TAG.get(kind, '▸')}  {txt}", font=("Segoe UI", 9),
                     fg=KIND_COLOR.get(kind, TXT), bg=BG, anchor="w", justify="left").pack(fill="x")
        if rec.get("no_pool"):
            tk.Label(body, text="(no op.gg pool for this champ/role yet)", font=("Segoe UI", 8),
                     fg=MUTED, bg=BG, anchor="w").pack(fill="x")
        render_intel(pulse)
        summ.config(text=rec["summary"])

    # --- drag anywhere on the chrome; persist where you drop it ---
    drag = {"x": 0, "y": 0}

    def press(e):
        drag["x"], drag["y"] = e.x_root, e.y_root

    def move(e):
        root.geometry(f"+{root.winfo_x() + e.x_root - drag['x']}+{root.winfo_y() + e.y_root - drag['y']}")
        drag["x"], drag["y"] = e.x_root, e.y_root

    def drop(_e):
        _save_pos(root.winfo_x(), root.winfo_y())

    for w in (outer, hdr, champ, summ):
        w.bind("<Button-1>", press)
        w.bind("<B1-Motion>", move)
        w.bind("<ButtonRelease-1>", drop)

    def quit_():
        st["alive"] = False
        _save_pos(root.winfo_x(), root.winfo_y())
        try:
            root.destroy()
        except Exception:
            pass

    close.bind("<Button-1>", lambda e: quit_())
    root.bind("<Escape>", lambda e: quit_())
    root.bind("<Button-3>", lambda e: quit_())

    # --- live polling off the UI thread ---
    q = queue.Queue()

    def worker():
        seen, ended, stale = False, 0, 0
        intel_on = cfg.load().get("game_intel", True)
        while st["alive"]:
            try:                                         # one :2999 read shared by build + intel
                raw = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata",
                              timeout=3, insecure=True)
            except Exception:
                raw = None
            try:
                rec = li.recommend(dd, data=raw)
            except Exception:
                rec = None
            ph = phasecheck.phase()
            pulse = None
            if intel_on and (rec is not None or ph in INGAME_PHASES):
                try:
                    pulse = ll.pulse(dd, data=raw)
                except Exception:
                    pulse = None
            if rec is not None or ph in INGAME_PHASES:   # in a live game -> show + reset
                seen, ended, stale = True, 0, 0
                q.put({"rec": rec, "pulse": pulse})      # build lines (+intel), or rec None while loading
            elif ph == "":
                # Client UNREACHABLE: during a teamfight/lag spike both :2999 and the LCU can
                # time out for a while even though the game is still going. Do NOT disappear -
                # hold the last frame. Only a very long dead stretch (client really gone) closes.
                stale += 1
                if not seen:
                    q.put({"rec": rec, "pulse": None})   # never saw a game -> show "waiting"
                if stale >= (36 if seen else 4):         # seen: ~3 min tolerance; not seen: ~20s
                    q.put("__quit__")
                    return
            else:
                # a DEFINITE non-game phase (Lobby / WaitingForStats / EndOfGame / None ...) ->
                # the game is actually over -> close so the next champ select opens fresh.
                ended += 1
                if not seen:
                    q.put({"rec": rec, "pulse": None})
                if ended >= (2 if seen else 3):          # ~10s confirmed over (seen) / ~15s otherwise
                    q.put("__quit__")
                    return
            for _ in range(POLL * 2):
                if not st["alive"]:
                    return
                time.sleep(0.5)

    threading.Thread(target=worker, daemon=True).start()

    def pump():
        if not st["alive"]:
            return
        try:
            while True:
                msg = q.get_nowait()
                if msg == "__quit__":
                    quit_()
                    return
                if isinstance(msg, dict) and "rec" in msg:
                    render(msg["rec"], msg.get("pulse"))
                else:
                    render(msg)                          # backward-compatible: bare rec
        except queue.Empty:
            pass
        make_no_activate(toplevel_hwnd(root.winfo_id()))
        root.after(400, pump)

    # place: remembered spot, else upper-left of the monitor you play on (primary)
    root.update_idletasks()
    pos = _load_pos()
    if not pos:
        prim = next((m for m in monitors() if (m[0], m[1]) == (0, 0)), monitors()[0])
        pos = (prim[0] + 24, prim[1] + 150)
    root.geometry(f"+{pos[0]}+{pos[1]}")
    hwnd = toplevel_hwnd(root.winfo_id())
    make_no_activate(hwnd)
    show_no_activate(hwnd)
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
