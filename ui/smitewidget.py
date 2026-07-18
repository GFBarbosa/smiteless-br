#!/usr/bin/env python3
"""smitewidget.py - small floating in-game item helper.

A compact, always-on-top, draggable window that shows what to build NEXT from op.gg's
real per-champ pool, adapting live to the enemy's actual build + who's fed + what you
already own. Independent of the big scoreboard overlay - it's meant to sit in a corner
the whole game. Never steals focus; remembers where you drag it.

  python smitewidget.py
"""
import sys, os, json, threading, time, queue, ctypes
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
import loltempo as lt
import lolrecords as lrec
import phasecheck
import smiteconfig as cfg
from smiteoverlay import (make_no_activate, show_no_activate, toplevel_hwnd,
                          monitors, _kernel32)

INGAME_PHASES = ("GameStart", "InProgress", "Reconnect")   # widget belongs on screen only here

import smiteskin as skin
VOID = skin.VOID; SURFACE = skin.SURFACE; LINE_SOFT = skin.LINE_SOFT
TXT = skin.TXT; MUTED = skin.MUTED; FAINT = skin.FAINT
EMBER = skin.EMBER; ARC = skin.ARC; GOOD = skin.GOOD; BAD = skin.BAD; WARN = skin.WARN
INFO = skin.INFO; MYSTIC = skin.MYSTIC   # Duskfall tokens (docs/UIDESIGN.md); no more v0.9.1 aliases
KIND_COLOR = {"core": TXT, "insert": EMBER, "counter": BAD, "antiheal": MYSTIC, "build": EMBER, "boots": INFO}
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


# ---- TEMPO voice callouts: short spoken cues ("Base now", "Rotate to dragon", "Take it").
# PRIMARY voice: AWS Polly "Salli" (US English) via ttsmp3.com's free endpoint — rendered
# ONCE per phrase to a cached MP3 and played through Windows MCI (winmm, built-in, decodes
# mp3, async, volume control). FALLBACK when offline: the built-in SAPI voice -> WAV ->
# winsound, same as before. Either way it's a one-time render per phrase, then local files.
import ctypes as _ct

_VOICE_VER = "v1"
_SALLI_VER = "v1"
_TTS_HDRS = {"User-Agent": "Mozilla/5.0", "Referer": "https://ttsmp3.com/"}


def _tts_salli(name, text):
    """Render `text` with the Salli voice (ttsmp3.com) to a cached MP3. None on any failure
    (offline / rate-limited) — callers fall back to the local Windows voice."""
    p = os.path.join(tempfile.gettempdir(), f"smiteless_salli_{_SALLI_VER}_{name}.mp3")
    try:
        if os.path.exists(p) and os.path.getsize(p) > 800:
            return p
        import urllib.request
        import urllib.parse
        import json as _json
        data = urllib.parse.urlencode({"msg": text, "lang": "Salli", "source": "ttsmp3"}).encode()
        req = urllib.request.Request("https://ttsmp3.com/makemp3_new.php", data=data, headers=_TTS_HDRS)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = _json.load(r)
        url = d.get("URL")
        if url and not d.get("Error"):
            req2 = urllib.request.Request(url, headers=_TTS_HDRS)
            with urllib.request.urlopen(req2, timeout=15) as r:
                blob = r.read()
            if len(blob) > 800:
                with open(p, "wb") as f:
                    f.write(blob)
                return p
    except Exception:
        pass
    return None


def _mci(cmd):
    """winmm mciSendString — 0 = success. Playback is process-global (survives the thread)."""
    try:
        buf = _ct.create_unicode_buffer(255)
        return _ct.windll.winmm.mciSendStringW(cmd, buf, 254, 0)
    except Exception:
        return -1


def _tts_path(name, text, vol=30):
    """Render `text` to a cached WAV via the built-in Windows speech synth. None on failure."""
    vol = int(max(0, min(100, vol)))
    p = os.path.join(tempfile.gettempdir(), f"smiteless_voice_{_VOICE_VER}_{name}_{vol}.wav")
    try:
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            return p
        import subprocess
        ps = ("Add-Type -AssemblyName System.Speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.Volume = {vol}; $s.Rate = 2; "
              f"$s.SetOutputToWaveFile('{p}'); $s.Speak('{text}'); $s.Dispose()")
        # stdin MUST be redirected: in the frozen (windowed, no-console) app the child
        # inherits an invalid stdin handle and dies with WinError 6 before PowerShell even
        # runs - which made the voice silently never render in the shipped build.
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       creationflags=0x08000000,          # CREATE_NO_WINDOW: never flash a console
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=25)
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            return p
    except Exception:
        pass
    return None


def _say(name, text, vol=30):
    """Speak a cue: Salli MP3 through MCI (preferred), else the local Windows voice through
    winsound. Renders + caches on first use; async; a new cue replaces the playing one."""
    if vol <= 0:
        return
    mp3 = _tts_salli(name, text)
    if mp3:
        _mci("close smitevoice")
        if _mci(f'open "{mp3}" type mpegvideo alias smitevoice') == 0:
            _mci(f"setaudio smitevoice volume to {max(0, min(1000, int(vol) * 10))}")
            if _mci("play smitevoice") == 0:
                return
            _mci("close smitevoice")
    try:
        import winsound
        p = _tts_path(name, text, vol)
        if p:
            winsound.PlaySound(p, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


# phase -> (cache name, spoken line). MOVE gets a per-objective callout.
_TEMPO_SPEECH = {
    "FREE": ("free", "Free objective. Their jungler's out. Take it now."),
    "BASE": ("base", "Base now."),
    "TAKE": ("take", "Take it. You win this fight."),
    "GIVE": ("give", "Give it. Trade elsewhere."),
    "EVEN": ("even", "Fifty fifty. Only with vision."),
    "FORCE": ("force", "Force now. Numbers advantage."),
    "PUSH": ("push", "Too far. Push your lane. Trade it."),
}
_TEMPO_ROTATE = {
    "Drake": ("rot_drake", "Rotate to dragon."),
    "Elder": ("rot_elder", "Rotate. Elder dragon."),
    "Baron": ("rot_baron", "Rotate to baron."),
    "Herald": ("rot_herald", "Rotate to herald."),
    "Grubs": ("rot_grubs", "Rotate to grubs."),
}


def _tempo_phrase(phase, obj):
    if phase == "MOVE":
        return _TEMPO_ROTATE.get(obj, ("rotate", "Rotate now."))
    return _TEMPO_SPEECH.get(phase)


class _TempoVoice:
    """Decides WHEN to speak: only on a phase/objective TRANSITION into an actionable
    phase, with a global cooldown and a per-cue repeat guard so threshold flapping
    (EVEN<->TAKE on the edge) can't chatter. Pure logic - testable without audio."""
    COOLDOWN = 6.0             # min seconds between any two spoken cues
    RESAY = 45.0               # min seconds before the SAME cue may repeat

    def __init__(self):
        self.key, self.last, self.spoken = None, -1e9, {}

    def cue(self, tempo, now):
        """(name, text) to speak right now, or None."""
        if not tempo or tempo.get("phase") in (None, "FARM"):
            self.key = (tempo or {}).get("phase")
            return None
        key = (tempo["phase"], tempo.get("obj"))
        if key == self.key:
            return None
        self.key = key
        if now - self.last < self.COOLDOWN or now - self.spoken.get(key, -1e9) < self.RESAY:
            return None
        self.last = now
        self.spoken[key] = now
        return _tempo_phrase(*key)


_QLOG = os.path.expanduser("~/.claude/cache/smiteless_widget.log")


def _qlog(reason):
    """Append a quit decision to a small forensics log — every close now has a paper trail,
    so 'it randomly disappeared' is answerable with facts instead of another guess."""
    try:
        os.makedirs(os.path.dirname(_QLOG), exist_ok=True)
        with open(_QLOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} quit: {reason}\n")
        if os.path.getsize(_QLOG) > 200_000:      # keep it small
            os.replace(_QLOG, _QLOG + ".old")
    except Exception:
        pass


_GAME_PROC = {"ts": 0.0, "alive": False}


def _game_running():
    """GROUND TRUTH for 'a game is happening': is the actual game client process
    (League of Legends.exe) running? The LCU phase API and :2999 both flake under load —
    this doesn't. Checked via tasklist (hidden, stdin redirected), cached 5s; on any
    error errs toward True (never kill the widget on a failed check)."""
    now = time.monotonic()
    if now - _GAME_PROC["ts"] < 5.0:
        return _GAME_PROC["alive"]
    alive = True
    try:
        import subprocess
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq League of Legends.exe",
                            "/FO", "CSV", "/NH"],
                           creationflags=0x08000000, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=8, text=True)
        alive = "League of Legends.exe" in (r.stdout or "")
    except Exception:
        alive = True
    _GAME_PROC["ts"], _GAME_PROC["alive"] = now, alive
    return alive


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


# ---- in-game click-through ----
# A HUD must NEVER eat a mouse click meant for the game — a click that lands on the
# widget mid-fight is a dropped move/attack command. While a live game is being read the
# window carries WS_EX_TRANSPARENT (every click falls straight through to the game);
# holding CTRL+ALT lifts it so the widget can still be dragged/muted/closed mid-game.
# Outside a live game it stays a normal, fully interactive window. Ctrl+Alt because the
# game binds Alt (pings) and Ctrl (self-cast) individually — but never both together.
_u32 = ctypes.windll.user32
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT, _WS_EX_LAYERED = 0x00000020, 0x00080000


def _interact_keys_down():
    return bool(_u32.GetAsyncKeyState(0x11) & 0x8000) and bool(_u32.GetAsyncKeyState(0x12) & 0x8000)


def _set_click_through(hwnd, on):
    """Add/remove WS_EX_TRANSPARENT on a toplevel. No-ops when the style already matches,
    so it's safe (and cheap) to assert every guard tick."""
    try:
        ex = _u32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        want = (ex | _WS_EX_TRANSPARENT | _WS_EX_LAYERED) if on else (ex & ~_WS_EX_TRANSPARENT)
        if want != ex:
            _u32.SetWindowLongW(hwnd, _GWL_EXSTYLE, want)
    except Exception:
        pass


# ---- PIL-rendered body: the widget's content is DRAWN (cards, chips, aligned rows) like
# the main board, instead of stacked Tk text labels — that's the difference between a HUD
# and a log file. One image per tick, swapped into a single Label.
_WFONTS = {}


def _wfont(sz, bold=False):
    from PIL import ImageFont
    key = (sz, bold)
    if key not in _WFONTS:
        try:
            _WFONTS[key] = ImageFont.truetype("seguisb.ttf" if bold else "segoeui.ttf", sz)
        except Exception:
            _WFONTS[key] = ImageFont.load_default()
    return _WFONTS[key]


def _dfont(sz, bold=False):
    """Bahnschrift - the Duskfall display face, drawn straight from skin.FONT_DISPLAY_TTF for
    every number/verdict the widget's whole job is to show. Falls back to the same Segoe UI
    Semibold substitution smiteskin.display() makes for Tk if the font file isn't installed."""
    from PIL import ImageFont
    key = (sz, "display")
    if key not in _WFONTS:
        try:
            _WFONTS[key] = ImageFont.truetype(skin.FONT_DISPLAY_TTF, sz)
        except Exception:
            _WFONTS[key] = _wfont(sz, True)
    return _WFONTS[key]


_SYM_CHARS = set("⌖◎⚠⌂⚑✓✗⟳✦◆★●▸")


def _tfont(text, sz, bold=False):
    """Font for a line: Segoe UI Symbol when it carries glyphs segoeui can't draw (they
    render as tofu boxes otherwise), plain/semibold Segoe UI everywhere else."""
    from PIL import ImageFont
    if any(c in _SYM_CHARS for c in (text or "")):
        key = (sz, "sym")
        if key not in _WFONTS:
            try:
                _WFONTS[key] = ImageFont.truetype("seguisym.ttf", sz)
            except Exception:
                return _wfont(sz, bold)
        return _WFONTS[key]
    return _wfont(sz, bold)


# Duskfall tokens rendered to PIL RGB via skin.rgb() - the drawn body used to carry its own
# frozen v0.9.1 palette here; now it's derived from the same source of truth as the Tk chrome.
C_VOID = skin.rgb(skin.VOID); C_SURFACE = skin.rgb(skin.SURFACE); C_LINE = skin.rgb(skin.LINE_SOFT)
C_EMBER = skin.rgb(skin.EMBER)
C_TXT = skin.rgb(skin.TXT); C_MUTED = skin.rgb(skin.MUTED); C_BAD = skin.rgb(skin.BAD)
C_GOOD = skin.rgb(skin.GOOD); C_ARC = skin.rgb(skin.ARC); C_INFO = skin.rgb(skin.INFO)
C_MYSTIC = skin.rgb(skin.MYSTIC); C_WARN = skin.rgb(skin.WARN); C_FAINT = skin.rgb(skin.FAINT)
# Verdict/phase colors: TAKE/FORCE win a fight -> GOOD, GIVE lose it -> BAD, EVEN is the
# 50-50 verdict -> WARN (was gold before Duskfall gave 50-50 its own status color); BASE/PUSH
# stay the action color (EMBER); FREE/MOVE are live reads (ARC); FARM is quiet (MUTED).
_PHASE_C = {"FREE": C_ARC, "TAKE": C_GOOD, "FORCE": C_GOOD, "GIVE": C_BAD, "EVEN": C_WARN,
            "BASE": C_EMBER, "MOVE": C_ARC, "PUSH": C_EMBER, "FARM": C_MUTED}
_KIND_C = {"core": C_TXT, "insert": C_EMBER, "counter": C_BAD, "antiheal": C_MYSTIC,
           "build": C_EMBER, "boots": C_INFO}


def _wwrap(d, text, f, maxw):
    lines, cur = [], ""
    for w in (text or "").split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _chip(d, x, y, text, fg, bg, f):
    w = int(d.textlength(text, font=f)) + 14
    d.rounded_rectangle([x, y, x + w, y + 17], radius=8, fill=bg)
    d.text((x + 7, y + 8), text, font=f, fill=fg, anchor="lm")
    return w


_TONE_C = {"go": C_ARC, "hold": C_BAD, "plan": C_EMBER}


def _render_dead(d, img, dead, rec, x, y, wrapw, W):
    """RESPAWN: the death-screen card. The grey screen is the only zero-cost reading
    window in a live game, so the ENTIRE widget collapses to one card: countdown, one
    directive for when you're back, and the buy (you're in the shop right now)."""
    tone = _TONE_C.get(dead.get("tone"), C_EMBER)
    secs = max(0, int(dead.get("secs") or 0))
    d.text((x + 2, y), "RESPAWN", font=_wfont(12, 1), fill=C_MUTED)
    t = f"back {secs // 60}:{secs % 60:02d}"
    f = _dfont(17, bold=True)                    # a number - display face, +2pt over the old 15
    # neutral white, never a tone color: an ember countdown next to an ember 'plan' directive
    # made the one card that must be unambiguous carry two identical ember clocks
    d.text((W - x - 2 - d.textlength(t, font=f), y - 2), t, font=f, fill=C_TXT)
    y += 24
    d.line([x, y, W - x, y], fill=C_LINE, width=1)
    y += 8
    lf = _wfont(12, 1)
    for ln in _wwrap(d, dead.get("line") or "", lf, wrapw - 4):
        d.text((x + 2, y), ln, font=lf, fill=tone)
        y += 17
    for ln in _wwrap(d, dead.get("sub") or "", _wfont(10), wrapw - 4):
        d.text((x + 2, y), ln, font=_wfont(10), fill=C_MUTED)
        y += 14
    buy = next((t_ for k, t_ in (rec.get("lines") or []) if k in ("core", "build")), None) if rec else None
    if buy:
        y += 4
        t = f"▸  {buy}"
        for ln in _wwrap(d, t, _tfont(t, 10, 1), wrapw - 4):
            d.text((x + 2, y), ln, font=_tfont(ln, 10, 1), fill=C_TXT)
            y += 15
    return img.crop((0, 0, W, y + 8))


def _render_body(dd, rec, pulse, recall, ghost=None, dead=None, W=318, ref=False):
    """Draw the widget body as one image. NOW / NEXT / REFERENCE hierarchy: by default the
    body is ONE directive (the tempo card), ONE next deadline line, and at most one urgent
    safety line — decision pressure, minimized. Hovering the widget (ref=True) expands the
    full reference view: ghost pace, objective chips, all intel rows, recall + items. While
    the player is DEAD the whole body is the single RESPAWN card."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, 720), C_VOID)
    d = ImageDraw.Draw(img)
    y, x = 6, 10
    wrapw = W - 2 * x
    pulse = pulse or {}
    if dead:
        return _render_dead(d, img, dead, rec, x, y, wrapw, W)

    # ---- champ + win chip ----
    name = (rec.get("champ") or "?").split("·")[0].strip()
    d.text((x, y + 2), name, font=_wfont(15, 1), fill=C_TXT)
    wp = pulse.get("winprob")
    if wp:
        t = f"{'WIN' if wp['ahead'] else 'BEHIND'} ~{wp['pct']}%"   # estimated, and it says so
        f = _dfont(12, bold=True)                 # a number (win%) - display face, +1pt
        cw = int(d.textlength(t, font=f)) + 14
        _chip(d, W - x - cw, y + 2, t, C_GOOD if wp["ahead"] else C_BAD, C_SURFACE, f)
    y += 26

    # ---- tempo directive card ----
    tempo = pulse.get("tempo")
    if tempo and tempo["phase"] == "FARM":
        # routine farm reminder: a plain quiet row - the bordered card is reserved for
        # phases that are actually a decision (v0.2.93: farm lines stand alone)
        for ln in _wwrap(d, tempo["line"], _wfont(11), wrapw - 4):
            d.text((x + 2, y), ln, font=_wfont(11), fill=C_MUTED)
            y += 15
        y += 5
    elif tempo:
        pc = _PHASE_C.get(tempo["phase"], C_TXT)
        tint = tuple(int(b + (c - b) * 0.16) for b, c in zip(C_VOID, pc))
        lf = _dfont(12, bold=True)                # verdict text: bold display face (TAKE/GIVE/50-50 etc.)
        lines = _wwrap(d, tempo["line"], lf, wrapw - 20)
        subs = []
        if tempo.get("sub") and tempo["phase"] in ("FREE", "TAKE", "GIVE", "EVEN", "FORCE", "PUSH"):
            subs = _wwrap(d, tempo["sub"], _wfont(10), wrapw - 20)
        ch = 12 + len(lines) * 17 + (len(subs) * 14 + 3 if subs else 0)
        d.rounded_rectangle([x, y, W - x, y + ch], radius=9, fill=tint, outline=pc, width=1)
        yy = y + 7
        for ln in lines:
            d.text((x + 10, yy), ln, font=lf, fill=pc)
            yy += 17
        yy += 3
        for ln in subs:
            d.text((x + 10, yy), ln, font=_wfont(10), fill=C_MUTED)
            yy += 14
        y += ch + 7

    # ---- collapsed (NOW / NEXT) view: everything below the directive is REFERENCE and
    # appears only while the cursor is over the widget ----
    if not ref:
        objs2 = pulse.get("objectives") or []
        nxt = objs2[0] if objs2 else None
        parts = []
        if nxt:
            parts.append(f"{nxt['label']} " + ("UP" if nxt["secs"] <= 0
                                               else f"{nxt['secs'] // 60}:{nxt['secs'] % 60:02d}"))
        if recall and recall.get("gap", 1) == 0 and not parts:
            parts.append(recall["text"])
        if parts:
            f2 = _dfont(11, bold=True)
            d.text((x + 2, y), "NEXT", font=_wfont(9, 1), fill=C_MUTED)
            d.text((x + 40, y - 1), "  ·  ".join(parts), font=f2,
                   fill=(C_EMBER if (nxt and (nxt["secs"] <= 0 or nxt.get("urgent"))) else C_ARC))
            y += 18
        # one urgent safety line, most pressing first (everything else waits in reference)
        jg2, gk2 = pulse.get("jungle"), pulse.get("gank")
        urgent = None
        if gk2:
            urgent = (f"◎ gank {gk2['lane'].lower()} — {gk2['champ']} {gk2['lvl']} vs {gk2['vs_lvl']}", C_GOOD)
        elif jg2 and jg2.get("state") == "nosign":
            urgent = (f"⌖ {jg2['champ']} NO SIGN {jg2['idle']}s — respect the gank", C_BAD)
        elif jg2 and jg2.get("state") == "dead":
            r2 = jg2.get("respawn") or 0
            urgent = (f"⌖ {jg2['champ']} DEAD{f' — back {r2}s' if r2 else ''} · free map", C_GOOD)
        if urgent:
            txt2, col2 = urgent
            for ln in _wwrap(d, txt2, _tfont(txt2, 10, 1), wrapw - 4):
                d.text((x + 2, y), ln, font=_tfont(ln, 10, 1), fill=col2)
                y += 15
        d.text((x + 2, y + 2), "hover = full detail", font=_wfont(8), fill=C_FAINT)
        return img.crop((0, 0, W, y + 16))

    # ---- GHOST pace row: you vs your best game on this champ (speedrun-timer style).
    # One ambient line: glows ember while ahead, dims to a whisper when behind (a timer,
    # not a nag); a crossed split briefly replaces it with the split result.
    if ghost:
        if ghost.get("split"):
            txt, ok = ghost["split"]
            gcol, gtxt = (C_GOOD if ok else C_BAD), f"★ {txt}"
        elif ghost["status"] == "first":
            gcol, gtxt = C_MUTED, "★ " + ghost["line"].replace("GHOST ▸ ", "GHOST · ")
        else:
            gcol = C_EMBER if ghost["status"] == "ahead" else C_MUTED
            gtxt = "★ " + ghost["line"].replace("GHOST ▸ ", "GHOST · ")
        d.text((x + 2, y), gtxt, font=_tfont(gtxt, 10, ghost["status"] == "ahead"), fill=gcol)
        y += 17

    # ---- objective timer chips ----
    objs = pulse.get("objectives") or []
    if tempo and tempo.get("phase") in ("FREE", "TAKE", "GIVE", "EVEN") and tempo.get("obj"):
        # the verdict card already names this objective and its clock - don't repeat it
        objs = [o for o in objs if o.get("label") != tempo["obj"]]
    if objs:
        cx = x
        f = _dfont(11, bold=True)                  # timers - display face, +1pt over the old 10
        for o in objs[:3]:
            up = o["secs"] <= 0
            t = f"{o['label']} UP" if up else f"{o['label']} {o['secs'] // 60}:{o['secs'] % 60:02d}"
            fg = C_EMBER if up or o.get("urgent") else (C_ARC if o.get("setup") else C_MUTED)
            cx += _chip(d, cx, y, t, fg, C_SURFACE, f) + 6
        y += 24

    # ---- intel rows (one font, one glyph column) ----
    sp = pulse.get("spike")
    rec_lines = list((rec.get("lines") or [])[:2] if pulse else (rec.get("lines") or []))
    if sp:                                        # dedupe: spiked enemy already named below?
        for i, (k, t) in enumerate(rec_lines):
            if sp["name"] in t:
                rec_lines[i] = (k, t.split(" — ")[0])
    rows = []
    jg = pulse.get("jungle")
    if jg:
        s = jg.get("state")
        if s == "dead":
            r = jg.get("respawn") or 0
            rows.append(("⌖", f"{jg['champ']} DEAD{f' — back {r}s' if r else ''} · free map", C_GOOD, 1))
        elif s == "seen":
            rows.append(("⌖", f"{jg['champ']} seen {str(jg['side']).upper()} · {jg['what']} {jg['ago']}s ago", C_ARC, 1))
        elif s == "nosign":
            rows.append(("⌖", f"{jg['champ']} NO SIGN {jg['idle']}s — respect the gank", C_BAD, 1))
        elif s == "moving":
            rows.append(("⌖", f"{jg['champ']} on the move ({jg.get('idle', 0)}s quiet)", C_EMBER, 0))
        elif s == "farming":
            rows.append(("⌖", f"{jg['champ']} farm registered", C_MUTED, 0))
    gk = pulse.get("gank")
    if gk:
        rows.append(("◎", f"gank {gk['lane'].lower()} — {gk['champ']} {gk['lvl']} vs {gk['vs_lvl']}", C_GOOD, 1))
    if sp:
        rows.append(("⚠", f"{sp['name']} spiked · {sp['items']} items · {sp['k']}/{sp['d']}", C_BAD, 0))
    for glyph, text, col, bold in rows:
        d.text((x + 2, y), glyph, font=_tfont(glyph, 10), fill=col)
        for ln in _wwrap(d, text, _wfont(10, bold), wrapw - 20):
            d.text((x + 20, y), ln, font=_wfont(10, bold), fill=col)
            y += 15
    if rows:
        y += 4

    # ---- items (reference block, visually quieter) ----
    if recall or rec_lines:
        d.line([x, y, W - x, y], fill=C_LINE, width=1)
        y += 7
    if recall:
        g = recall.get("gap", 0)
        rc = C_EMBER if g == 0 else (C_ARC if g <= 350 else C_MUTED)
        t = "⌂ " + recall["text"]
        for ln in _wwrap(d, t, _tfont(t, 10, 1), wrapw):
            d.text((x, y), ln, font=_tfont(ln, 10, 1), fill=rc)
            y += 15
        y += 1
    for kind, txt in rec_lines:
        tag = KIND_TAG.get(kind, "▸")
        t = f"{tag}  {txt}" if tag else txt
        for ln in _wwrap(d, t, _tfont(t, 10, kind == "core"), wrapw):
            d.text((x, y), ln, font=_tfont(ln, 10, kind == "core"), fill=_KIND_C.get(kind, C_TXT))
            y += 15
    return img.crop((0, 0, W, y + 8))


# ---- LEGEND: the decoder card behind the header's "?" — every phase color, glyph, chip
# and item tag the widget can show, drawn in the widget's own visual language so "teal =
# FREE" is learned from the exact swatch that appears live. Meanings are one-liners of what
# the engine actually computes (loltempo verdicts, lollive intel, lolrecords GHOST) — if a
# phase or tag is added there, add its row here.
_LEGEND_PHASES = (
    ("FREE",  "their jungler provably can't contest — take it"),
    ("TAKE",  "you win this fight — commit with vision"),
    ("FORCE", "numbers up — force a play while they're down"),
    ("EVEN",  "50/50 — only with a vision or smite edge"),
    ("GIVE",  "you lose this fight — concede, trade elsewhere"),
    ("MOVE",  "crash your wave, then rotate + ward early"),
    ("BASE",  "recall window — buy now to arrive early"),
    ("PUSH",  "you can't reach it — shove for the cross-trade"),
    ("FARM",  "nothing live yet — farm to the deadline"),
)
_LEGEND_GLYPHS = (
    ("⌖", C_ARC, "enemy jungler tracker — seen / no sign / dead"),
    ("◎", C_GOOD,  "gank window — a lane is killable right now"),
    ("⚠", C_BAD,  "power spike — an enemy just completed items"),
    ("⌂", C_EMBER, "recall read — your next buy is ready"),
    ("★", C_EMBER, "GHOST — pace vs your best game on this champ (amber = ahead)"),
)
_LEGEND_ITEMS = (
    ("core",     "core — your main build path"),
    ("insert",   "insert — buy this next, a timed power spike"),
    ("counter",  "counter — answers their biggest threat"),
    ("antiheal", "antiheal — their healing crossed the line, cut it"),
    ("boots",    "build / boots — the standard next step"),
)


def _render_legend(W=330):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, 1200), C_VOID)
    d = ImageDraw.Draw(img)
    x, y = 10, 8
    wrapw = W - 2 * x

    def section(title):
        nonlocal y
        if y > 12:
            y += 5
            d.line([x, y, W - x, y], fill=C_LINE, width=1)
            y += 8
        d.text((x, y), title, font=_wfont(9, 1), fill=C_EMBER)
        y += 17

    def row(tag, tagcol, text, tagw, bold=True, dfont=False):
        nonlocal y
        tf = _dfont(11, bold=True) if dfont else _tfont(tag, 10, bold)   # verdicts: display face
        d.text((x + 2, y), tag, font=tf, fill=tagcol)
        for ln in _wwrap(d, text, _wfont(10), wrapw - tagw - 4):
            d.text((x + 2 + tagw, y), ln, font=_wfont(10), fill=C_MUTED)
            y += 14
        y += 3

    section("TEMPO — THE CARD'S COLOR IS THE CALL")
    for ph, txt in _LEGEND_PHASES:
        row(ph, _PHASE_C.get(ph, C_TXT), txt, 46, dfont=True)

    section("INTEL")
    for g, col, txt in _LEGEND_GLYPHS:
        row(g, col, txt, 20)

    section("CHIPS")
    f = _dfont(11, bold=True)
    cx = x
    cx += _chip(d, cx, y, "WIN 61%", C_GOOD, C_SURFACE, f) + 6
    cx += _chip(d, cx, y, "Drake 1:20", C_MUTED, C_SURFACE, f) + 6
    _chip(d, cx, y, "Drake UP", C_EMBER, C_SURFACE, f)
    y += 25
    for txt in ("WIN / BEHIND — live power read from gold + XP + drakes; never rank or winrate.",
                "objective timers — amber = UP or urgent · cyan = your setup window."):
        for ln in _wwrap(d, txt, _wfont(10), wrapw - 4):
            d.text((x + 2, y), ln, font=_wfont(10), fill=C_MUTED)
            y += 14
        y += 3

    section("ITEM LINES")
    for kind, txt in _LEGEND_ITEMS:
        tag = KIND_TAG.get(kind) or "·"
        row(tag, _KIND_C.get(kind, C_TXT), txt, 20)

    section("RESPAWN")
    for ln in _wwrap(d, "while dead, everything collapses to one card: your respawn countdown, "
                        "the play for when you're back, and the buy.", _wfont(10), wrapw - 4):
        d.text((x + 2, y), ln, font=_wfont(10), fill=C_MUTED)
        y += 14
    return img.crop((0, 0, W, y + 10))


def acquire_single_instance():
    _kernel32.CreateMutexW(None, False, "Global\\SmitelessWidget")
    return _kernel32.GetLastError() != 183                # ERROR_ALREADY_EXISTS


def _wscale(root):
    """Resolution-adaptive widget scale: the body is drawn for a 1080p-tall screen and
    shrinks in step when the screen it sits on is shorter (e.g. the game switched the
    display to a lower resolution). Never upscales — text stays crisp on big monitors."""
    try:
        x, y = root.winfo_x(), root.winfo_y()
        mons = monitors()
        m = next((mm for mm in mons if mm[0] <= x < mm[2] and mm[1] <= y < mm[3]), mons[0])
        return max(0.6, min(1.0, (m[3] - m[1]) / 1080.0))
    except Exception:
        return 1.0


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
    st["vol"] = int(cfg.load().get("dragon_volume", 30))   # live audio volume (slider + Settings)

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.96)
    root.configure(bg=LINE_SOFT)                         # 1px edge via padding
    outer = tk.Frame(root, bg=VOID)
    outer.pack(padx=1, pady=1, fill="both", expand=True)

    hdr = tk.Frame(outer, bg=SURFACE)                     # header strip
    hdr.pack(fill="x")
    # Header (Duskfall, docs/UIDESIGN.md §5.3): the strip stays — it's the drag handle plus
    # live controls — but now carries the '✦ SMITELESS TEMPO' brand row instead of a bare
    # glyph. Every control still rests at MUTED and only brightens under the cursor.
    tk.Label(hdr, text=" " + skin.BRAND_MARK, font=skin.display(skin.SMALL, bold=True),
             fg=EMBER, bg=SURFACE).pack(side="left")
    tk.Label(hdr, text=" SMITELESS", font=skin.display(skin.SMALL, bold=True), fg=TXT,
             bg=SURFACE).pack(side="left")
    tk.Label(hdr, text=" TEMPO", font=skin.display(skin.SMALL), fg=MUTED,
             bg=SURFACE).pack(side="left")
    # Live dot: ARC while a live game is actually being polled, FAINT the rest of the time
    # (waiting for a live game). Wired in render() below - that's the one place the widget
    # already knows which state it's in.
    live_dot = tk.Label(hdr, text="●", font=skin.body(8), fg=FAINT, bg=SURFACE)
    live_dot.pack(side="left", padx=(4, 0))
    close = tk.Label(hdr, text="✕ ", font=skin.body(9, bold=True), fg=MUTED, bg=SURFACE, cursor="hand2")
    close.pack(side="right")
    close.bind("<Enter>", lambda e: close.config(fg=TXT))
    close.bind("<Leave>", lambda e: close.config(fg=MUTED))
    # LEGEND — the one "?" this HUD is allowed. Click: a reference card opens beside the
    # widget decoding every phase color, glyph, chip and item tag; click again to dismiss.
    # Auto-opens ONCE on first run (see render's waiting branch), then it's pull-only.
    helpb = tk.Label(hdr, text="?", font=skin.body(9, bold=True), fg=MUTED, bg=SURFACE, cursor="hand2")
    helpb.pack(side="right", padx=(0, 4))
    # Drake chime mute — click to silence the 45/30/15 drake cues for THIS game (resets next
    # game). Struck-through red note = muted; ember note = alerts on. (Settings has a permanent off.)
    mute = tk.Label(hdr, text="♪", font=skin.body(10, bold=True), fg=MUTED, bg=SURFACE, cursor="hand2")
    mute.pack(side="right", padx=(0, 2))

    def _toggle_mute(*_):
        st["muted"] = not st.get("muted", False)
        if st["muted"]:
            mute.config(fg=BAD, font=(skin.FONT_BODY, 10, "bold", "overstrike"))
        else:
            mute.config(fg=MUTED, font=skin.body(10, bold=True))
    mute.bind("<Button-1>", _toggle_mute)
    mute.bind("<Enter>", lambda e: st.get("muted") or mute.config(fg=EMBER))
    mute.bind("<Leave>", lambda e: st.get("muted") or mute.config(fg=MUTED))

    # Volume slider — live control for the voice callouts + drake chime (0 = silent).
    # Applies instantly, persists to Settings on release, and plays a short preview so
    # you can set it by ear mid-game.
    def _on_vol(v):
        st["vol"] = int(float(v))

    vol = tk.Scale(hdr, from_=0, to=100, orient="horizontal", showvalue=0, length=62,
                   width=7, sliderlength=12, bd=0, highlightthickness=0, bg=SURFACE,
                   troughcolor=LINE_SOFT, activebackground=EMBER, cursor="hand2", command=_on_vol)
    vol.set(st["vol"])
    # the slider is the noisiest header element — it appears only while the cursor is
    # over the widget (the pump's pointer check below packs/unpacks it)

    # shown instead of the slider when the cursor is over a CLICK-THROUGH widget (in a
    # live game): the one place the ctrl+alt affordance is taught, exactly when needed
    hint = tk.Label(hdr, text="ctrl+alt to touch", font=skin.body(8), fg=FAINT, bg=SURFACE)

    def _vol_done(_e):
        try:
            cfg.save({"dragon_volume": int(st["vol"])})
        except Exception:
            pass
        if st["vol"] > 0 and not st.get("muted", False):   # hear the new level immediately
            threading.Thread(target=_say, args=("hello", "Tempo online.", st["vol"]),
                             daemon=True).start()
    vol.bind("<ButtonRelease-1>", _vol_done)

    # the body is ONE drawn image (see _render_body) — a HUD, not a stack of text labels.
    from PIL import Image, ImageTk
    champ = tk.Label(outer, text="waiting for a live game…", font=skin.body(11, bold=True),
                     fg=MUTED, bg=VOID, anchor="w")
    champ.pack(fill="x", padx=10, pady=(6, 7))
    shot = tk.Label(outer, bg=VOID, bd=0)

    def render(rec, pulse=None, recall=None, ghost=None, dead=None, ref=False):
        st["ingame"] = bool(rec)                         # drives the click-through guard
        live_dot.config(fg=ARC if rec else FAINT)        # §5.3: ARC while a live game is read
        if not rec:
            shot.pack_forget()
            champ.config(text="waiting for a live game…", fg=MUTED)
            champ.pack(fill="x", padx=10, pady=(6, 7))
            st["hot"] = False
            # very first run ever: open the LEGEND once beside "waiting…" so the vocabulary
            # is learned before the first live game — push once, then pull-only via the ?.
            if not st.get("legend_intro"):
                st["legend_intro"] = True
                if not cfg.load().get("legend_seen"):
                    try:
                        cfg.save({"legend_seen": True})
                    except Exception:
                        pass
                    root.after(600, lambda: None if st.get("legend") else toggle_legend())
            return
        champ.pack_forget()
        tempo = (pulse or {}).get("tempo")
        st["hot"] = bool(dead                     # dead = solid: you're reading the plan
                         or (tempo and (tempo.get("urgent") or tempo.get("phase")
                                        in ("FREE", "TAKE", "GIVE", "EVEN", "FORCE", "PUSH")))
                         or (pulse or {}).get("gank") or (pulse or {}).get("spike"))
        try:
            im = _render_body(dd, rec, pulse, recall, ghost, dead, ref=ref)
        except Exception:
            return                                       # keep the last good frame
        s = _wscale(root)                                # adapt to the screen's live resolution
        if s < 0.999:
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))),
                           Image.LANCZOS)
        ph = ImageTk.PhotoImage(im)
        shot.configure(image=ph)
        shot.image = ph                                  # keep a reference or Tk drops it
        shot.pack(fill="x", padx=1, pady=(0, 1))

    # --- drag anywhere on the chrome; persist where you drop it ---
    drag = {"x": 0, "y": 0}

    def press(e):
        drag["x"], drag["y"] = e.x_root, e.y_root

    def move(e):
        root.geometry(f"+{root.winfo_x() + e.x_root - drag['x']}+{root.winfo_y() + e.y_root - drag['y']}")
        drag["x"], drag["y"] = e.x_root, e.y_root

    def drop(_e):
        _save_pos(root.winfo_x(), root.winfo_y())

    for w in (outer, hdr, champ, shot):
        w.bind("<Button-1>", press)
        w.bind("<B1-Motion>", move)
        w.bind("<ButtonRelease-1>", drop)

    def quit_(why="game over"):
        st["alive"] = False
        _qlog(why)
        _save_pos(root.winfo_x(), root.winfo_y())
        try:
            root.destroy()
        except Exception:
            pass

    # ONLY the ✕ button closes the widget. Escape and right-click used to be bound to
    # close too - in a game where right-click IS the move command, a click that drifted
    # onto the widget silently killed it. That was the original "it randomly disappears".
    close.bind("<Button-1>", lambda e: quit_("user closed (x button)"))

    # --- LEGEND card: a separate no-activate Toplevel beside the widget. Its own window so
    # the live body stays visible for side-by-side reading, and so it's untouched by the
    # per-tick body re-render. Draggable; closed by its ✕ or the ? again; dies with root.
    def _legend_open():
        lg = st.get("legend")
        try:
            return bool(lg and lg.winfo_exists())
        except Exception:
            return False

    def toggle_legend(*_):
        if _legend_open():
            try:
                st["legend"].destroy()
            except Exception:
                pass
            st["legend"] = None
            helpb.config(fg=MUTED)
            return
        lg = tk.Toplevel(root)
        lg.overrideredirect(True)
        lg.attributes("-topmost", True)
        lg.attributes("-alpha", 0.96)
        lg.configure(bg=LINE_SOFT)
        lo = tk.Frame(lg, bg=VOID)
        lo.pack(padx=1, pady=1, fill="both", expand=True)
        lh = tk.Frame(lo, bg=SURFACE)
        lh.pack(fill="x")
        # same '✦ SMITELESS <SUFFIX>' brand treatment as the main header (§4/§5.3), suffix LEGEND
        tk.Label(lh, text=" " + skin.BRAND_MARK, font=skin.display(skin.SMALL, bold=True),
                 fg=EMBER, bg=SURFACE).pack(side="left")
        tk.Label(lh, text=" LEGEND", font=skin.display(skin.SMALL, bold=True), fg=EMBER,
                 bg=SURFACE).pack(side="left", padx=(0, 3), pady=3)
        lx = tk.Label(lh, text="✕ ", font=skin.body(9, bold=True), fg=MUTED, bg=SURFACE, cursor="hand2")
        lx.pack(side="right")
        lx.bind("<Button-1>", toggle_legend)
        body = tk.Label(lo, bg=VOID, bd=0)
        lim = _render_legend()
        ls = _wscale(root)                               # legend follows the widget's scale
        if ls < 0.999:
            lim = lim.resize((max(1, round(lim.width * ls)), max(1, round(lim.height * ls))),
                             Image.LANCZOS)
        ph = ImageTk.PhotoImage(lim)
        body.configure(image=ph)
        body.image = ph                                  # keep a reference or Tk drops it
        body.pack(padx=1, pady=(0, 1))
        ldrag = {"x": 0, "y": 0}

        def lpress(e):
            ldrag["x"], ldrag["y"] = e.x_root, e.y_root

        def lmove(e):
            lg.geometry(f"+{lg.winfo_x() + e.x_root - ldrag['x']}+{lg.winfo_y() + e.y_root - ldrag['y']}")
            ldrag["x"], ldrag["y"] = e.x_root, e.y_root
        for w in (lo, lh, body):
            w.bind("<Button-1>", lpress)
            w.bind("<B1-Motion>", lmove)
        st["legend"] = lg
        helpb.config(fg=EMBER)
        # place beside the widget: right of it, flipping left / clamping on-screen
        lg.update_idletasks()
        lw, lht = lg.winfo_reqwidth(), lg.winfo_reqheight()
        rx, ry = root.winfo_rootx(), root.winfo_rooty()
        mons = monitors()
        mon = next((m for m in mons if m[0] <= rx <= m[2] and m[1] <= ry <= m[3]), mons[0])
        px = rx + root.winfo_width() + 10
        if px + lw > mon[2]:
            px = max(mon[0], rx - lw - 10)
        py = min(max(mon[1], ry), max(mon[1], mon[3] - lht))
        lg.geometry(f"+{px}+{py}")
        hw = toplevel_hwnd(lg.winfo_id())
        make_no_activate(hw)
        show_no_activate(hw)

    helpb.bind("<Button-1>", toggle_legend)
    helpb.bind("<Enter>", lambda e: helpb.config(fg=EMBER))
    helpb.bind("<Leave>", lambda e: helpb.config(fg=EMBER if _legend_open() else MUTED))

    # --- live polling off the UI thread ---
    q = queue.Queue()

    def worker():
        seen, last_ok = False, time.monotonic()
        _cfg = cfg.load()
        intel_on = _cfg.get("game_intel", True)
        tempo_on = _cfg.get("tempo_coach", True)
        free_on = _cfg.get("free_alarm", True)
        voice_on = _cfg.get("tempo_voice", True)
        audio_on = _cfg.get("dragon_audio", True)
        ghost_on = _cfg.get("ghost_race", True)
        respawn_on = _cfg.get("respawn_plan", True)
        dvol = int(st.get("vol", 30))                    # startup volume (live value = st["vol"])
        dragon = {"prev": None, "fired": set(), "last_up_ping": 0.0}  # dragon-spawn/up audio state
        tvoice = _TempoVoice()                            # tempo callout announce state
        ghostrace = lrec.GhostRace()   # GHOST: live race vs your PB game. NOT named 'grace' -
                                       # the quit logic below reuses that name for a float,
                                       # which silently killed the race after any :2999 blip.
        if audio_on and dvol > 0:                         # warm the chime cache so the first cue is instant
            threading.Thread(target=lambda: [_cue_path(t, dvol) for t in (45, 30, 15)], daemon=True).start()
        if tempo_on and voice_on and dvol > 0:            # pre-render the voice lines (one-time)
            threading.Thread(target=lambda: [_tts_salli(nm, tx) for nm, tx in
                                             list(_TEMPO_SPEECH.values()) + list(_TEMPO_ROTATE.values())
                                             + [("rotate", "Rotate now."), ("hello", "Tempo online.")]],
                             daemon=True).start()

        def dragon_audio(secs):
            if secs is None:
                dragon["prev"], dragon["fired"], dragon["last_up_ping"] = None, set(), 0.0
                return
            thr = _dragon_due(dragon["prev"], secs, dragon["fired"])   # advance state even if muted
            dragon["prev"] = secs
            muted = st.get("muted", False)                # temp mute for this game (header ♪ button)
            if thr is not None and not muted:
                threading.Thread(target=_beep, args=(thr, st["vol"]), daemon=True).start()
            # Once drake is up, remind SPARSELY: the full jingle fires exactly once at the
            # crossing above; the reminder is the short calm two-note cue every ~15s. (It
            # used to replay the full 5-note fanfare every ~5s — a 40s contested drake
            # meant 8 fanfares. That was the naggiest sound in the app.)
            if secs <= 0:
                t = time.monotonic()
                if (t - float(dragon.get("last_up_ping") or 0.0)) >= 15.0:
                    first = not dragon.get("last_up_ping")
                    dragon["last_up_ping"] = t
                    if not muted:
                        threading.Thread(target=_beep, args=((15 if first else 45), st["vol"]),
                                         daemon=True).start()
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
                if pulse is not None and tempo_on:       # TEMPO directive rides the same fetch
                    try:
                        pulse["tempo"] = lt.tempo_read(dd, raw, free_alarm=free_on)
                    except Exception:
                        pulse["tempo"] = None
                    if voice_on and st["vol"] > 0:       # spoken callout on phase transitions
                        try:
                            cue = tvoice.cue(pulse.get("tempo"), time.monotonic())
                            if cue and not st.get("muted", False):   # ♪ button mutes voice too
                                threading.Thread(target=_say, args=(cue[0], cue[1], st["vol"]),
                                                 daemon=True).start()
                        except Exception:
                            pass
            dead = None
            if respawn_on and raw is not None:           # RESPAWN: the death-screen plan card
                try:
                    dead = lt.respawn_plan(dd, raw)
                except Exception:
                    dead = None
            # "you're up" chime: one soft two-note cue as the respawn timer crosses ~1.5s,
            # so eyes-off-screen death time ends with a nudge instead of lost seconds.
            rs = (dead or {}).get("secs")
            prev_rs = st.get("respawn_prev")
            if (audio_on and rs is not None and prev_rs is not None
                    and prev_rs > 1.5 >= rs and not st.get("muted", False)):
                threading.Thread(target=_beep, args=(45, st["vol"]), daemon=True).start()
            st["respawn_prev"] = rs
            ghost = None
            if ghost_on and raw is not None:             # GHOST pace race vs your own best game
                try:
                    ghost = ghostrace.update(dd, raw)
                except Exception:
                    ghost = None
                if ghost and ghost.get("new_record_event") and not st.get("muted", False):
                    # beat your ghost: the triumphant "item get" jingle + a spoken stamp,
                    # then the record itself is rewritten from Riot data on the next
                    # profile load - so the fanfare is provisional, the ghost is exact.
                    threading.Thread(target=_beep, args=(15, st["vol"]), daemon=True).start()
                    if voice_on and st["vol"] > 0:
                        threading.Thread(target=_say, args=("record", "New record.", st["vol"]),
                                         daemon=True).start()
            if audio_on and raw is not None:             # dragon spawn reminder (45/30/15s)
                drake = next((o for o in (pulse.get("objectives") or [])
                              if o.get("label") == "Drake"), None) if pulse else None
                dragon_audio(drake["secs"] if drake else None)
            now = time.monotonic()
            if raw is not None:                          # fresh game data -> paint + reset the clock
                if not seen and voice_on and st["vol"] > 0 and not st.get("muted", False):
                    # first live data of the game: a short hello — confirms the whole audio
                    # pipeline (render + playback) is working instead of failing silently.
                    threading.Thread(target=_say, args=("hello", "Tempo online.", st["vol"]),
                                     daemon=True).start()
                seen, last_ok = True, now
                q.put({"rec": rec, "pulse": pulse if intel_on else None, "recall": recall,
                       "ghost": ghost, "dead": dead})
            elif ph in INGAME_PHASES:
                # :2999 hiccup while the game is definitely alive (teamfight load, lag). HOLD
                # THE LAST FRAME - pushing an empty one here is what made the tracker/intel
                # "only work sometimes": every blip wiped the panel back to 'waiting...'.
                if not seen:
                    q.put({"rec": None, "pulse": None})   # never had data yet -> show waiting
                seen, last_ok = True, now
            else:
                # No game data AND the phase says unreachable ("") or non-game (Lobby/None/...).
                # Both happen TRANSIENTLY mid-game (client restart, teamfight lag hitting the
                # LCU and :2999 at once) - which is why phase/:2999-based closing kept killing
                # the widget "randomly" no matter how the thresholds were tuned. The GROUND
                # TRUTH is the game process itself: while League of Legends.exe is RUNNING,
                # this widget is IMMORTAL. Only when the process is actually gone does a
                # wall-clock grace + one last direct live-client check allow a close - and
                # every close writes its reason to the forensics log.
                if not seen:
                    q.put({"rec": rec, "pulse": None})   # never saw a game -> show "waiting"
                if seen and _game_running():
                    last_ok = now                        # game process alive -> hold, forever
                else:
                    grace = 20.0 if seen else 15.0
                    if now - last_ok >= grace:
                        try:
                            lb.http("https://127.0.0.1:2999/liveclientdata/gamestats",
                                    timeout=6, insecure=True)
                            seen, last_ok = True, now     # game answered -> false alarm
                            continue
                        except Exception:
                            pass
                        _qlog(f"seen={seen} ph={ph!r} game_proc={_GAME_PROC['alive']} "
                              f"quiet={now - last_ok:.0f}s gamestats=dead")
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
                        st["last_msg"] = msg             # kept so hover can re-render in place
                        render(msg["rec"], msg.get("pulse"), msg.get("recall"), msg.get("ghost"),
                               msg.get("dead"), ref=st.get("ref_view", False))
                    else:
                        render(msg)                      # backward-compatible: bare rec
                except Exception:
                    pass
        except queue.Empty:
            pass
        make_no_activate(toplevel_hwnd(root.winfo_id()))
        # Re-assert TOPMOST every ~4s: the game (or another overlay) claiming topmost can
        # push the widget behind it - alive but invisible, the OTHER "it disappeared".
        st["zorder"] = st.get("zorder", 0) + 1
        if st["zorder"] % 10 == 0:
            try:
                show_no_activate(toplevel_hwnd(root.winfo_id()))
            except Exception:
                pass
        # Adaptive transparency: ghost-quiet while nothing needs you (0.84), solid when a
        # call-to-action is up (0.97), fully opaque under your cursor. Keeps the info on
        # screen without sitting ON the game.
        try:
            px, py = root.winfo_pointerxy()
            rx, ry = root.winfo_rootx(), root.winfo_rooty()
            inside = rx <= px <= rx + root.winfo_width() and ry <= py <= ry + root.winfo_height()
            a = 1.0 if inside else (0.97 if st.get("hot") else 0.84)
            if a != st.get("alpha"):
                st["alpha"] = a
                root.attributes("-alpha", a)
            # hover-reveal: the volume slider when the widget is touchable, the ctrl+alt
            # hint when it's click-through (nothing while the cursor is elsewhere)
            # hover = REFERENCE view: the widget expands to full detail under the cursor
            # and collapses back to NOW/NEXT when you leave
            if inside != st.get("ref_view"):
                st["ref_view"] = inside
                m = st.get("last_msg")
                if m:
                    try:
                        render(m["rec"], m.get("pulse"), m.get("recall"), m.get("ghost"),
                               m.get("dead"), ref=inside)
                    except Exception:
                        pass
            mode = ("hint" if st.get("ct") else "vol") if inside else None
            if mode != st.get("hdr_mode"):
                st["hdr_mode"] = mode
                vol.pack_forget()
                hint.pack_forget()
                if mode == "vol":
                    vol.pack(side="right", padx=(0, 7), pady=3)
                elif mode == "hint":
                    hint.pack(side="right", padx=(0, 7))
        except Exception:
            pass
        root.after(400, pump)

    def guard():
        """Fast loop owning the click-through state: transparent while a live game is being
        read, lifted the instant Ctrl+Alt are held (120ms feels immediate on a key-hold).
        The legend rides the same state so an open decoder card can't eat clicks either."""
        if not st["alive"]:
            return
        ct = bool(st.get("ingame")) and not _interact_keys_down()
        st["ct"] = ct
        _set_click_through(toplevel_hwnd(root.winfo_id()), ct)
        lg = st.get("legend")
        try:
            if lg and lg.winfo_exists():
                _set_click_through(toplevel_hwnd(lg.winfo_id()), ct)
        except Exception:
            pass
        root.after(120, guard)

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
    guard()
    root.mainloop()


if __name__ == "__main__":
    main()
