#!/usr/bin/env python3
"""claudecli.py - thin wrapper around the logged-in `claude` CLI (no API key needed).

Shared by lolmatchup.py (per-matchup lane tips, web search) and lolcoach.py (the
standalone text coach). Runs the CLI from a neutral temp cwd so it does NOT load the
heavy C:\\ project memory (that was adding 30-60s), and hard-kills the whole process
tree on timeout.
"""
import os, shutil, subprocess, tempfile

MODEL = "sonnet"      # quality model for the guide/tips
TIMEOUT = 120         # generous default; callers can override (e.g. web-search tips use 170)
# Never flash a console: from the windowed (frozen) app, spawning a console subprocess pops
# a blank "claude" terminal on the loading screen. CREATE_NO_WINDOW keeps it invisible.
_NO_WINDOW = 0x08000000


def find_claude():
    """Prefer the real claude.exe (lets us exec without a shell so the timeout can kill
    the process directly). Fall back to whatever `claude` resolves to on PATH."""
    exe = os.path.expanduser(
        r"~/AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe")
    if os.path.exists(exe):
        return exe
    return shutil.which("claude")


def call_claude(prompt, allow_tools=None, timeout=None, model=None):
    """Return (text, error). Uses the logged-in claude CLI; no API key needed.
    Pass allow_tools="WebSearch,WebFetch" to let it pull up-to-date info."""
    claude = find_claude()
    if not claude:
        return None, "claude CLI not found"
    args = [claude, "-p", "--model", model or MODEL, "--strict-mcp-config"]
    if allow_tools:
        args += ["--allowedTools", allow_tools]
    try:
        p = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", cwd=tempfile.gettempdir(),
            creationflags=_NO_WINDOW,
        )
    except (FileNotFoundError, OSError) as e:
        return None, f"couldn't launch claude ({e})"
    try:
        out, err = p.communicate(input=prompt, timeout=(timeout or TIMEOUT))
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True,
                       creationflags=_NO_WINDOW)
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        return None, "timed out"
    out = (out or "").strip()
    err = (err or "").strip()
    blob = (out + "\n" + err).lower()
    if "session limit" in blob or "usage limit" in blob:
        return None, "Claude usage/session limit reached"
    if p.returncode != 0 and not out:
        return None, (err[:200] or f"claude exited {p.returncode}")
    if not out:
        return None, "claude returned no text"
    return out, None
