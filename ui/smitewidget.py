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
PANEL = "#151823"; SEP = "#232838"
KIND_COLOR = {"core": TXT, "insert": GOLD, "counter": RED, "antiheal": PURPLE, "build": GOLD, "boots": BLUE}
KIND_TAG = {"core": "", "insert": "⚑", "counter": "⚠", "antiheal": "✚", "build": "▸", "boots": "▸"}
POLL = 1                                                  # seconds between live reads (all local)
# objective-timer feature toggles read from settings (default on); a per-frame gate keeps the
# widget honest when the user turns them off.
# ---- dragon spawn chime: a soft Japanese-style pentatonic bell jingle, synthesized to a real
# WAV and played through the normal audio device (winsound.Beep / MessageBeep are silent on a
# lot of machines - which is why the old cue couldn't be heard). Notes rise/lengthen as the
# spawn nears. Generated once into %TEMP% and cached (bump _CHIME_VER to re-render).
import math, struct, wave, tempfile

_SR = 44100
_CHIME_VER = "v7"
_MAX_AMP = 0.55            # peak level at volume 100; the Settings slider scales this down
# G-major (the bright, triumphant Zelda-jingle key). Music-box / ocarina timbre, ascending
# arpeggios that resolve up to a held final note - that N64 "secret found / item get" feel.
_HZ = {"G4": 392.00, "A4": 440.00, "B4": 493.88, "C5": 523.25, "D5": 587.33, "E5": 659.25,
       "G5": 783.99, "A5": 880.00, "B5": 987.77, "D6": 1174.66}
# (onset_step, [(note, ring_seconds), ...]) - last note rings long and gets a soft sub-octave.
_CUE = {
    45: (0.22, [("D5", 0.18), ("G5", 0.44)]),
    30: (0.17, [("G4", 0.15), ("B4", 0.15), ("D5", 0.17), ("G5", 0.50)]),
    15: (0.12, [("D5", 0.12), ("E5", 0.12), ("G5", 0.12), ("A5", 0.12), ("B5", 0.55)]),
}


def _voice(f, t, dur, last=False):
    """Soft, rounded ocarina/music-box tone: mostly fundamental with a gentle octave and a
    faint third - the harsh upper partials are dropped so it's mellow, not pingy. A slow
    attack means it's breathed in rather than struck. The held final note adds a soft
    sub-octave for body, like the resolved chord under a Zelda fanfare."""
    env = math.exp(-t * (2.8 / dur))
    atk = min(1.0, t / 0.028)                            # ~28ms soft fade-in: barely-there onset
    s = (1.00 * math.sin(2 * math.pi * f * t)
         + 0.16 * math.sin(2 * math.pi * 2 * f * t) * math.exp(-t * 4))   # near-pure sine; faint octave only
    if last:
        s += 0.16 * math.sin(2 * math.pi * (f / 2) * t) * math.exp(-t * 2.5)
    return s * env * atk


def _render_cue(cue, vol=30):
    """Sequence a cue's notes (onset = i*step, each rings its own length) into one 16-bit
    mono PCM buffer, scaled to `vol` (0-100) of the max level."""
    step, seq = cue
    last_onset = (len(seq) - 1) * step
    total = last_onset + seq[-1][1] + 0.12
    n_total = int(_SR * (total + 0.05))
    buf = [0.0] * n_total
    for i, (nm, ring) in enumerate(seq):
        f = _HZ[nm]
        start = int(_SR * i * step)
        last = (i == len(seq) - 1)
        for k in range(int(_SR * ring)):
            idx = start + k
            if idx >= n_total:
                break
            buf[idx] += _voice(f, k / _SR, ring, last)
    peak = max(1e-6, max(abs(x) for x in buf))
    level = max(0.0, min(100.0, float(vol))) / 100.0 * _MAX_AMP
    amp = level / peak
    return b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x * amp)) * 32767)) for x in buf)


def _cue_path(thr, vol=30):
    vol = int(max(0, min(100, vol)))
    p = os.path.join(tempfile.gettempdir(), f"smiteless_drake_{_CHIME_VER}_{thr}_{vol}.wav")
    try:
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            return p
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(_SR)
            w.writeframes(_render_cue(_CUE[thr], vol))
    except Exception:
        return None
    return p


def _beep(thr, vol=30):
    """Play the drake chime through the default audio device (reliable everywhere)."""
    if vol <= 0:
        return
    try:
        import winsound
        p = _cue_path(thr, vol)
        if p:
            winsound.PlaySound(p, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            return
    except Exception:
        pass
    try:
        import winsound
        winsound.Beep(880, 200)                           # last-ditch fallback
    except Exception:
        pass


def _dragon_due(prev, secs, fired):
    """Which step (45/30/15) to beep right now as the dragon countdown CROSSES it, or None.
    Mutates `fired`. Crossing-based so a 5s poll or joining mid-window never double-beeps; a
    jump upward (a drake just died -> next spawn) resets the fired steps. When one poll gap
    crosses SEVERAL steps (opened the widget late, long lag spike), fire the MOST URGENT one
    and mark the rest as done - a 10s-out drake should get the 15s cue, not the calm 45s."""
    if prev is None or secs is None:
        return None
    if secs > prev + 20:
        fired.clear()
        return None
    crossed = [thr for thr in (45, 30, 15) if thr not in fired and prev > thr >= secs]
    if not crossed:
        return None
    fired.update(crossed)
    return min(crossed)
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
    st = {"alive": True, "muted": False}     # muted = temp-silence the drake chime for this game

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.96)
    root.configure(bg=SEP)                               # 1px edge via padding
    outer = tk.Frame(root, bg=BG)
    outer.pack(padx=1, pady=1, fill="both", expand=True)

    hdr = tk.Frame(outer, bg=PANEL)                      # header strip
    hdr.pack(fill="x")
    tk.Label(hdr, text=" ◆", font=("Segoe UI", 8), fg=GOLD, bg=PANEL).pack(side="left")
    tk.Label(hdr, text="SMITELESS", font=("Segoe UI Semibold", 8), fg=GOLD, bg=PANEL).pack(side="left", padx=(3, 0), pady=3)
    close = tk.Label(hdr, text="✕ ", font=("Segoe UI", 9, "bold"), fg=MUTED, bg=PANEL, cursor="hand2")
    close.pack(side="right")
    # Drake chime mute — click to silence the 45/30/15 drake cues for THIS game (resets next
    # game). Struck-through red note = muted; gold note = alerts on. (Settings has a permanent off.)
    mute = tk.Label(hdr, text="♪", font=("Segoe UI", 10, "bold"), fg=GOLD, bg=PANEL, cursor="hand2")
    mute.pack(side="right", padx=(0, 2))

    def _toggle_mute(*_):
        st["muted"] = not st.get("muted", False)
        if st["muted"]:
            mute.config(fg=RED, font=("Segoe UI", 10, "bold", "overstrike"))
        else:
            mute.config(fg=GOLD, font=("Segoe UI", 10, "bold"))
    mute.bind("<Button-1>", _toggle_mute)

    champrow = tk.Frame(outer, bg=BG)
    champrow.pack(fill="x", padx=10, pady=(6, 0))
    champ = tk.Label(champrow, text="waiting for a live game…", font=("Segoe UI Semibold", 12),
                     fg=MUTED, bg=BG, anchor="w")
    champ.pack(side="left")
    wpchip = tk.Label(champrow, text="", font=("Segoe UI Semibold", 9), bg=BG, fg=MUTED, padx=7)
    wpchip.pack(side="right")

    body = tk.Frame(outer, bg=BG)
    body.pack(fill="x", padx=10, pady=(3, 4))
    sep = tk.Frame(outer, bg=SEP, height=1)
    intel = tk.Frame(outer, bg=BG)                        # objectives / jungle map / gank / spike
    summ = tk.Label(outer, text="open in-game or a replay to see suggestions",
                    font=("Segoe UI", 8), fg=MUTED, bg=BG, anchor="w", justify="left")
    summ.pack(side="bottom", fill="x", padx=10, pady=(2, 7))

    def _fmt(secs):
        return "UP" if secs <= 0 else f"{secs // 60}:{secs % 60:02d}"

    def render_intel(pulse):
        for w in intel.winfo_children():
            w.destroy()
        if not pulse:
            sep.pack_forget()
            intel.pack_forget()
            wpchip.config(text="", bg=BG)
            return
        sep.pack(fill="x", padx=10, pady=(1, 0), before=summ)
        intel.pack(fill="x", padx=10, pady=(4, 1), before=summ)
        wp = pulse.get("winprob")
        if wp:
            wpchip.config(text=f"{'WIN' if wp['ahead'] else 'BEHIND'} {wp['pct']}%",
                          fg=(GREEN if wp["ahead"] else RED), bg=PANEL)
        else:
            wpchip.config(text="", bg=BG)
        objs = pulse.get("objectives") or []
        if objs:
            row = tk.Frame(intel, bg=BG)
            row.pack(fill="x")
            tk.Label(row, text="⟳", font=("Segoe UI", 9), fg=TEAL, bg=BG).pack(side="left")
            for o in objs[:3]:
                col = GOLD if o["urgent"] else (TEAL if o["up"] else (TXT if o.get("setup") else MUTED))
                txt = f" {o['label']} {_fmt(o['secs'])}"
                if o.get("setup"):
                    txt += " · set up"                    # ~75s out: shove + ward before it spawns
                tk.Label(row, text=txt + " ", font=("Segoe UI", 9,
                         "bold" if o["urgent"] else "normal"), fg=col, bg=BG).pack(side="left")
        jg, gk, sp = pulse.get("jungle"), pulse.get("gank"), pulse.get("spike")
        if jg:
            state = jg.get("state")
            jbold = False
            if state == "dead":
                r = jg.get("respawn") or 0
                jtxt = f"⌖ {jg['champ']} DEAD — back in {r}s · free map" if r else \
                       f"⌖ {jg['champ']} DEAD — free map"
                jcol, jbold = GREEN, True
            elif state == "seen":
                jtxt = f"⌖ {jg['champ']} SEEN {str(jg['side']).upper()} · {jg['what']} {jg['ago']}s ago"
                jcol, jbold = TEAL, True
            elif state == "nosign":
                tail = f" (last: {jg['last_side']})" if jg.get("last_side") else ""
                jtxt = f"⌖ {jg['champ']} NO SIGN {jg['idle']}s — respect the gank{tail}"
                jcol, jbold = RED, True
            elif state == "farming":
                tail = f" · last seen {jg['last_side']}" if jg.get("last_side") else ""
                jtxt = f"⌖ {jg['champ']} farm registered{tail}"
                jcol = MUTED
            elif state == "moving":
                jtxt = f"⌖ {jg['champ']} on the move ({jg.get('idle', 0)}s quiet)"
                jcol = GOLD
            elif jg.get("side"):                          # legacy one-shot read shape
                jtxt = f"⌖ {jg['champ']} last seen {str(jg['side']).upper()} · {jg['what']} {jg['ago']}s ago"
                jcol = TEAL
            else:
                jtxt = f"⌖ {jg['champ']}: {jg.get('what') or 'no read yet'}"
                jcol = MUTED
            tk.Label(intel, text=jtxt, font=("Segoe UI Semibold", 9) if jbold else ("Segoe UI", 9),
                     fg=jcol, bg=BG, anchor="w", justify="left").pack(fill="x")
        if gk:
            tk.Label(intel, text=f"◎ GANK: {gk['lane']} — {gk['champ']} lvl {gk['lvl']} vs {gk['vs_lvl']}",
                     font=("Segoe UI Semibold", 9), fg=GREEN, bg=BG, anchor="w").pack(fill="x")
        if sp:
            tk.Label(intel, text=f"⚠ {sp['name']} spiked · {sp['items']} items · {sp['k']}/{sp['d']}",
                     font=("Segoe UI", 9), fg=RED, bg=BG, anchor="w").pack(fill="x")

    def render(rec, pulse=None, recall=None):
        for w in body.winfo_children():
            w.destroy()
        if not rec:
            champ.config(text="waiting for a live game…", fg=MUTED)
            summ.config(text="open in-game or a replay to see suggestions")
            render_intel(None)
            return
        champ.config(text=rec["champ"], fg=TXT)
        if recall:                                        # power-spike / back-timing hint
            g = recall.get("gap", 0)
            rc = GOLD if g == 0 else (TEAL if g <= 350 else MUTED)
            tk.Label(body, text="⌂ " + recall["text"], font=("Segoe UI Semibold", 9),
                     fg=rc, bg=BG, anchor="w", justify="left", wraplength=300).pack(fill="x", pady=(0, 2))
        if not rec["lines"]:
            tk.Label(body, text="standard build — nothing to adjust",
                     font=("Segoe UI", 9), fg=MUTED, bg=BG, anchor="w").pack(fill="x")
        for kind, txt in rec["lines"]:
            tag = KIND_TAG.get(kind, "▸")
            label = f"{tag}  {txt}" if tag else txt
            fnt = ("Segoe UI Semibold", 10) if kind == "core" else ("Segoe UI", 9)
            tk.Label(body, text=label, font=fnt, fg=KIND_COLOR.get(kind, TXT), bg=BG,
                     anchor="w", justify="left", wraplength=300).pack(fill="x", pady=1)
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

    for w in (outer, hdr, champrow, champ, summ):
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
        _cfg = cfg.load()
        intel_on = _cfg.get("game_intel", True)
        audio_on = _cfg.get("dragon_audio", True)
        dvol = int(_cfg.get("dragon_volume", 30))        # Settings volume slider (0-100)
        dragon = {"prev": None, "fired": set(), "last_up_ping": 0.0}  # dragon-spawn/up audio state
        if audio_on and dvol > 0:                         # warm the chime cache so the first cue is instant
            threading.Thread(target=lambda: [_cue_path(t, dvol) for t in (45, 30, 15)], daemon=True).start()

        def dragon_audio(secs):
            if secs is None:
                dragon["prev"], dragon["fired"], dragon["last_up_ping"] = None, set(), 0.0
                return
            thr = _dragon_due(dragon["prev"], secs, dragon["fired"])   # advance state even if muted
            dragon["prev"] = secs
            muted = st.get("muted", False)                # temp mute for this game (header ♪ button)
            if thr is not None and not muted:
                threading.Thread(target=_beep, args=(thr, dvol), daemon=True).start()
            # Once drake is up, keep replaying the final cue every ~5s until it dies.
            if secs <= 0:
                t = time.monotonic()
                if (t - float(dragon.get("last_up_ping") or 0.0)) >= 4.8:
                    dragon["last_up_ping"] = t
                    if not muted:
                        threading.Thread(target=_beep, args=(15, dvol), daemon=True).start()
            else:
                dragon["last_up_ping"] = 0.0

        while st["alive"]:
            try:                                         # one :2999 read shared by build + intel
                raw = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata",
                              timeout=2, insecure=True)
            except Exception:
                raw = None
            try:
                rec = li.recommend(dd, data=raw)
            except Exception:
                rec = None
            recall = None                                # power-spike / back-timing hint
            if raw is not None:
                try:
                    recall = li.recall_advice(dd, data=raw)
                except Exception:
                    recall = None
            ph = phasecheck.phase()
            pulse = None
            if (intel_on or audio_on) and raw is not None:
                try:
                    pulse = ll.pulse(dd, data=raw)
                except Exception:
                    pulse = None
            if audio_on and raw is not None:             # dragon spawn reminder (45/30/15s)
                drake = next((o for o in (pulse.get("objectives") or [])
                              if o.get("label") == "Drake"), None) if pulse else None
                dragon_audio(drake["secs"] if drake else None)
            if raw is not None:                          # fresh game data -> paint + reset counters
                seen, ended, stale = True, 0, 0
                q.put({"rec": rec, "pulse": pulse if intel_on else None, "recall": recall})
            elif ph in INGAME_PHASES:
                # :2999 hiccup while the game is definitely alive (teamfight load, lag). HOLD
                # THE LAST FRAME - pushing an empty one here is what made the tracker/intel
                # "only work sometimes": every blip wiped the panel back to 'waiting...'.
                if not seen:
                    q.put({"rec": None, "pulse": None})   # never had data yet -> show waiting
                seen, ended, stale = True, 0, 0
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
                # a DEFINITE non-game phase (Lobby / WaitingForStats / EndOfGame / None ...).
                # BUT: LeagueClientUx restarting mid-game reports None/Lobby for a while, and a
                # :2999 hiccup at the same moment used to close the widget "randomly" mid-game.
                # So: more strikes, plus a FINAL direct live-client check with a generous
                # timeout - if the game answers, we were fooled; keep living.
                ended += 1
                if not seen:
                    q.put({"rec": rec, "pulse": None})
                if ended >= (4 if seen else 3):          # ~20s of confirmed non-game (seen)
                    if seen:
                        try:
                            lb.http("https://127.0.0.1:2999/liveclientdata/gamestats",
                                    timeout=6, insecure=True)
                            ended = 0                     # game's still alive -> false alarm
                            continue
                        except Exception:
                            pass
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
                try:                                     # a render bug must never kill the pump
                    if isinstance(msg, dict) and "rec" in msg:
                        render(msg["rec"], msg.get("pulse"), msg.get("recall"))
                    else:
                        render(msg)                      # backward-compatible: bare rec
                except Exception:
                    pass
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
