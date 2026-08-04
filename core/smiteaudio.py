#!/usr/bin/env python3
"""Locale-aware speech, chimes, cache isolation, and one-process audio arbitration."""

import base64
import hashlib
import json
import math
import os
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass, field
from enum import IntEnum

import llmprocess


RENDERER_VERSION = "v2"
CHIME_VERSION = "v8"
LOCALE_VOICES = {"en": ("en-US", "Salli"), "pt_BR": ("pt-BR", "Camila")}
TTS_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://ttsmp3.com/"}
CACHE_DIR = os.path.join(tempfile.gettempdir(), "smiteless_audio")
MAX_RESPONSE_FILES = 64
MAX_RESPONSE_AGE = 7 * 24 * 60 * 60


class Priority(IntEnum):
    PROACTIVE_RESPONSE = 10
    DETERMINISTIC_ALERT = 20
    MANUAL_RESPONSE = 30
    LISTENING = 40


def normalize_locale(locale):
    value = str(locale or "").strip().replace("-", "_")
    if value.lower() == "pt_br":
        return "pt_BR"
    return "en" if value.lower() == "en" else "en"


def voice_for_locale(locale):
    return LOCALE_VOICES[normalize_locale(locale)][1]


def culture_for_locale(locale):
    return LOCALE_VOICES[normalize_locale(locale)][0]


def cache_identity(text, locale="en", voice=None, volume=30, renderer=RENDERER_VERSION):
    locale = normalize_locale(locale)
    voice = voice or voice_for_locale(locale)
    digest = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
    return f"{renderer}_{locale}_{voice}_{max(0, min(100, int(volume)))}_{digest}"


def cache_path(kind, name, text, locale="en", voice=None, volume=30, extension="mp3"):
    safe_kind = "".join(c for c in str(kind) if c.isalnum() or c in "_-")[:24] or "speech"
    safe_name = "".join(c for c in str(name) if c.isalnum() or c in "_-")[:32] or "line"
    ident = cache_identity(text, locale, voice, volume)
    return os.path.join(CACHE_DIR, f"{safe_kind}_{safe_name}_{ident}.{extension}")


def _atomic_bytes(path, blob):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(blob)
    os.replace(tmp, path)


def cleanup_cache(now=None):
    """Expire arbitrary response files while leaving the small deterministic cue set alone."""
    now = time.time() if now is None else float(now)
    try:
        rows = []
        for name in os.listdir(CACHE_DIR):
            if not name.startswith(("manual_", "proactive_", "test_")):
                continue
            path = os.path.join(CACHE_DIR, name)
            try:
                rows.append((os.path.getmtime(path), path))
            except OSError:
                pass
        rows.sort(reverse=True)
        for index, (mtime, path) in enumerate(rows):
            if index >= MAX_RESPONSE_FILES or now - mtime > MAX_RESPONSE_AGE:
                try:
                    os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


def render_online(name, text, locale="en", volume=30, kind="cue", urlopen=None):
    """Render with ttsMP3's locale-specific Polly voice and atomically cache the MP3."""
    locale = normalize_locale(locale)
    voice = voice_for_locale(locale)
    path = cache_path(kind, name, text, locale, voice, volume, "mp3")
    try:
        if os.path.getsize(path) > 800:
            return path
    except OSError:
        pass
    opener = urlopen or urllib.request.urlopen
    data = urllib.parse.urlencode({"msg": str(text), "lang": voice, "source": "ttsmp3"}).encode()
    try:
        request = urllib.request.Request("https://ttsmp3.com/makemp3_new.php", data=data,
                                         headers=TTS_HEADERS)
        with opener(request, timeout=15) as response:
            value = json.load(response)
        url = value.get("URL") if isinstance(value, dict) and not value.get("Error") else None
        if not url:
            return None
        with opener(urllib.request.Request(url, headers=TTS_HEADERS), timeout=15) as response:
            blob = response.read()
        if len(blob) <= 800:
            return None
        _atomic_bytes(path, blob)
        return path
    except Exception:
        return None


_SAPI_PS = r'''
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$cfg = $env:SMITELESS_SPEECH_CONFIG | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$s = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
  $voice = $s.GetInstalledVoices() | Where-Object {
    $_.Enabled -and $_.VoiceInfo.Culture.Name -eq [string]$cfg.culture
  } | Select-Object -First 1
  if ($null -eq $voice) { [Console]::Out.Write('{"ok":false,"error":"missing_voice"}'); exit 0 }
  $s.SelectVoice($voice.VoiceInfo.Name)
  $s.Volume = [int]$cfg.volume
  $s.Rate = 2
  $s.SetOutputToWaveFile([string]$cfg.path)
  $s.Speak([string]$cfg.text)
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  [Console]::Out.Write(([ordered]@{ok=$true; renderer="sapi"; voice=$voice.VoiceInfo.Name;
    culture=$voice.VoiceInfo.Culture.Name} | ConvertTo-Json -Compress))
} catch {
  [Console]::Out.Write(([ordered]@{ok=$false; error="sapi_error"; message=[string]$_.Exception.Message} |
    ConvertTo-Json -Compress))
} finally { $s.Dispose() }
'''


def render_sapi(name, text, locale="en", volume=30, kind="cue", popen_factory=None):
    """Render with an installed SAPI voice of the exact culture; never cross languages."""
    locale = normalize_locale(locale)
    culture = culture_for_locale(locale)
    path = cache_path(kind, name, text, locale, f"SAPI-{culture}", volume, "wav")
    try:
        if os.path.getsize(path) > 1000:
            return {"ok": True, "path": path, "renderer": "sapi", "culture": culture}
    except OSError:
        pass
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp.wav"
    config = {"culture": culture, "volume": max(0, min(100, int(volume))),
              "text": str(text), "path": tmp}
    env = os.environ.copy()
    env["SMITELESS_SPEECH_CONFIG"] = json.dumps(config, ensure_ascii=False,
                                                   separators=(",", ":"))
    encoded = base64.b64encode(_SAPI_PS.encode("utf-16-le")).decode("ascii")
    factory = popen_factory or subprocess.Popen
    process = None
    try:
        process = factory(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                           "-EncodedCommand", encoded], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", errors="replace", creationflags=llmprocess.NO_WINDOW,
                          env=env)
        stdout, _stderr = process.communicate(timeout=25)
        value = json.loads(str(stdout or "").strip())
        if process.returncode or not value.get("ok"):
            return value if isinstance(value, dict) else {"ok": False, "error": "sapi_error"}
        if not os.path.exists(tmp) or os.path.getsize(tmp) <= 1000:
            return {"ok": False, "error": "sapi_error"}
        os.replace(tmp, path)
        value["path"] = path
        return value
    except subprocess.TimeoutExpired:
        if process is not None:
            llmprocess.terminate_tree(process)
        return {"ok": False, "error": "timeout"}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": "sapi_error", "message": str(exc)[:200]}
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


_mci_lock = threading.RLock()
_active_aliases = set()


def _mci(command):
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(255)
        return ctypes.windll.winmm.mciSendStringW(command, buf, 254, 0)
    except Exception:
        return -1


def stop_playback():
    try:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
    with _mci_lock:
        aliases = list(_active_aliases)
    for alias in aliases:
        _mci(f"stop {alias}")
        _mci(f"close {alias}")


def play_file(path, volume=30):
    if not path or volume <= 0:
        return False
    if str(path).lower().endswith(".mp3"):
        alias = f"smiteaudio{os.getpid()}x{threading.get_ident()}"
        with _mci_lock:
            _active_aliases.add(alias)
        try:
            if _mci(f'open "{path}" type mpegvideo alias {alias}') != 0:
                return False
            _mci(f"setaudio {alias} volume to {max(0, min(1000, int(volume) * 10))}")
            return _mci(f"play {alias} wait") == 0
        finally:
            _mci(f"close {alias}")
            with _mci_lock:
                _active_aliases.discard(alias)
    try:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_SYNC |
                           winsound.SND_NODEFAULT)
        return True
    except Exception:
        return False


def speak(name, text, volume=30, locale="en", kind="cue"):
    """Render and synchronously play one line, reporting the renderer actually used."""
    if not str(text or "").strip() or volume <= 0:
        return {"ok": False, "error": "silent"}
    cleanup_cache()
    online = render_online(name, text, locale, volume, kind)
    if online and play_file(online, volume):
        return {"ok": True, "renderer": "ttsmp3", "voice": voice_for_locale(locale),
                "culture": culture_for_locale(locale)}
    sapi = render_sapi(name, text, locale, volume, kind)
    if sapi.get("ok") and play_file(sapi.get("path"), volume):
        return sapi
    return sapi if not sapi.get("ok") else {"ok": False, "error": "playback_error"}


_SR = 44100
_MAX_AMP = 0.55
_HZ = {"G4": 392.00, "B4": 493.88, "D5": 587.33, "E5": 659.25,
       "G5": 783.99, "A5": 880.00, "B5": 987.77}
_CUES = {45: (0.22, [("D5", 0.18), ("G5", 0.44)]),
         30: (0.17, [("G4", 0.15), ("B4", 0.15), ("D5", 0.17), ("G5", 0.50)]),
         15: (0.12, [("D5", 0.12), ("E5", 0.12), ("G5", 0.12), ("A5", 0.12),
                      ("B5", 0.55)])}


def _tone(freq, at, duration, last=False):
    env = math.exp(-at * (2.8 / duration))
    attack = min(1.0, at / 0.028)
    sample = math.sin(2 * math.pi * freq * at)
    sample += 0.16 * math.sin(2 * math.pi * 2 * freq * at) * math.exp(-at * 4)
    if last:
        sample += 0.16 * math.sin(2 * math.pi * (freq / 2) * at) * math.exp(-at * 2.5)
    return sample * env * attack


def _render_chime(cue, volume):
    step, sequence = cue
    total = (len(sequence) - 1) * step + sequence[-1][1] + 0.17
    samples = [0.0] * int(_SR * total)
    for index, (note, ring) in enumerate(sequence):
        start = int(_SR * index * step)
        for offset in range(int(_SR * ring)):
            samples[start + offset] += _tone(_HZ[note], offset / _SR, ring,
                                               index == len(sequence) - 1)
    peak = max(1e-6, max(abs(value) for value in samples))
    amp = (max(0, min(100, int(volume))) / 100.0 * _MAX_AMP) / peak
    return b"".join(struct.pack("<h", int(max(-1, min(1, value * amp)) * 32767))
                    for value in samples)


def chime_path(threshold, volume=30):
    threshold = int(threshold)
    volume = max(0, min(100, int(volume)))
    path = os.path.join(CACHE_DIR, f"chime_{CHIME_VERSION}_{threshold}_{volume}.wav")
    try:
        if os.path.getsize(path) > 1000:
            return path
    except OSError:
        pass
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with wave.open(tmp, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(_SR)
            handle.writeframes(_render_chime(_CUES[threshold], volume))
        os.replace(tmp, path)
        return path
    except Exception:
        return None


def play_chime(threshold, volume=30):
    path = chime_path(threshold, volume)
    return {"ok": bool(path and play_file(path, volume)), "renderer": "chime"}


@dataclass
class AudioJob:
    priority: Priority
    name: str = "line"
    text: str = ""
    locale: str = "en"
    volume: int = 30
    chime: int = 0
    created_at: float = field(default_factory=time.monotonic)
    callback: object = None


class AudioScheduler:
    """One-worker scheduler implementing listening/manual/deterministic/proactive priority."""

    def __init__(self, speaker=speak, chime_player=play_chime, stopper=stop_playback):
        self.speaker = speaker
        self.chime_player = chime_player
        self.stopper = stopper
        self.condition = threading.Condition()
        self.pending = []
        self.current = None
        self.listening = False
        self.generation = 0
        self.closed = False
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def submit(self, job):
        if not isinstance(job.priority, Priority):
            job.priority = Priority(int(job.priority))
        with self.condition:
            if self.closed:
                return False
            if job.priority == Priority.LISTENING:
                self.pending.clear()
                self.listening = True
                self.generation += 1
                self.stopper()
                self.condition.notify_all()
                return True
            if self.listening and job.priority == Priority.PROACTIVE_RESPONSE:
                return False
            if job.priority == Priority.MANUAL_RESPONSE:
                self.pending = [item for item in self.pending
                                if item.priority != Priority.PROACTIVE_RESPONSE]
                if self.current and self.current.priority == Priority.PROACTIVE_RESPONSE:
                    self.generation += 1
                    self.stopper()
            elif job.priority == Priority.DETERMINISTIC_ALERT:
                self.pending = [item for item in self.pending
                                if item.priority != Priority.PROACTIVE_RESPONSE]
                if self.current and self.current.priority == Priority.PROACTIVE_RESPONSE:
                    self.generation += 1
                    self.stopper()
            else:
                self.pending = [item for item in self.pending
                                if item.priority != Priority.PROACTIVE_RESPONSE]
            self.pending.append(job)
            self.pending.sort(key=lambda item: (-int(item.priority), item.created_at))
            self.condition.notify()
            return True

    def _worker(self):
        while True:
            with self.condition:
                while (not self.pending or self.listening) and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                job = self.pending.pop(0)
                self.current = job
                generation = self.generation
            result = (self.chime_player(job.chime, job.volume) if job.chime else
                      self.speaker(job.name, job.text, job.volume, job.locale,
                                   "manual" if job.priority == Priority.MANUAL_RESPONSE else
                                   ("proactive" if job.priority == Priority.PROACTIVE_RESPONSE else "cue")))
            with self.condition:
                if self.current is job:
                    self.current = None
            if generation == self.generation and callable(job.callback):
                try:
                    job.callback(result)
                except Exception:
                    pass

    def stop_listening(self):
        return self.submit(AudioJob(Priority.LISTENING))

    def finish_listening(self):
        """Release queued higher-priority audio after microphone capture has ended."""
        with self.condition:
            if self.closed:
                return False
            self.listening = False
            self.condition.notify_all()
            return True

    def cancel_proactive(self):
        """Drop queued proactive speech and stop it when it is currently playing."""
        with self.condition:
            pending_before = len(self.pending)
            self.pending = [item for item in self.pending
                            if item.priority != Priority.PROACTIVE_RESPONSE]
            current = bool(self.current and
                           self.current.priority == Priority.PROACTIVE_RESPONSE)
            if current:
                self.generation += 1
                self.stopper()
            if pending_before != len(self.pending):
                self.condition.notify_all()
            return current or pending_before != len(self.pending)

    def close(self):
        with self.condition:
            self.closed = True
            self.listening = False
            self.pending.clear()
            self.stopper()
            self.condition.notify_all()
        self.thread.join(timeout=2)


def coordinator_request(payload, timeout=0.45):
    try:
        import lolcoachipc
        return lolcoachipc.request({"type": "audio", **payload}, timeout=timeout)
    except Exception:
        return None


def deterministic_speech(name, text, volume=30, locale="en"):
    response = coordinator_request({"audio_kind": "deterministic", "name": name,
                                    "text": text, "volume": int(volume), "locale": locale})
    if response and response.get("ok"):
        return response
    return speak(name, text, volume, locale, "cue")


def deterministic_chime(threshold, volume=30):
    response = coordinator_request({"audio_kind": "deterministic", "chime": int(threshold),
                                    "volume": int(volume)})
    if response and response.get("ok"):
        return response
    return play_chime(threshold, volume)
