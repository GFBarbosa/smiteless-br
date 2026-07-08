#!/usr/bin/env python3
"""smitenotes.py - the Patch Notes / What's New window.

Renders CHANGELOG.md in a scrollable, read-only window. It reads the copy bundled with the
install (staged next to VERSION, so it matches the version you're running) and, in the
background, tries to pull the latest CHANGELOG.md from GitHub so you can see notes for a
release you haven't installed yet. Opened from the tray ("Patch notes") or:

    SmitelessApp.exe notes      (frozen)   /   python ui/smitenotes.py   (dev)
"""
import sys
import os
import ssl
import threading
import urllib.request
import ctypes

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_R, _d))
for _s in ("stdout", "stderr"):                 # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass

BG = "#11131a"; PANEL = "#171a24"; GOLD = "#c8aa6e"; TXT = "#d8d6cf"
MUTED = "#9b988e"; BULLET = "#8fb4e0"; BOLD = "#efe9dc"
RAW_URL = "https://raw.githubusercontent.com/bobbyroylee/smiteless/main/CHANGELOG.md"
_k32 = ctypes.windll.kernel32


def _single_instance():
    _k32.CreateMutexW(None, False, "Global\\SmitelessNotes")
    return _k32.GetLastError() != 183           # ERROR_ALREADY_EXISTS


def _install_root():
    try:
        import smiteupdate
        return smiteupdate.install_root()
    except Exception:
        return _R


def _local_changelog():
    for p in (os.path.join(_install_root(), "CHANGELOG.md"), os.path.join(_R, "CHANGELOG.md")):
        try:
            with open(p, encoding="utf-8") as f:
                t = f.read().strip()
                if t:
                    return t
        except Exception:
            continue
    return "# Smiteless — Patch Notes\n\n(no patch notes found)"


def _fetch_remote():
    try:
        req = urllib.request.Request(RAW_URL, headers={"User-Agent": "Smiteless-Notes"})
        with urllib.request.urlopen(req, timeout=6, context=ssl.create_default_context()) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None


def main():
    if not _single_instance():
        return
    import tkinter as tk

    root = tk.Tk()
    root.title("Smiteless — Patch Notes")
    root.configure(bg=BG)
    root.geometry("560x680")
    try:
        for ico in (os.path.join(_R, "assets", "smiteless.ico"),
                    os.path.join(_install_root(), "assets", "smiteless.ico")):
            if os.path.exists(ico):
                root.iconbitmap(ico)
                break
    except Exception:
        pass

    tk.Label(root, text="SMITELESS — PATCH NOTES", bg=BG, fg=GOLD,
             font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16, pady=(14, 6))
    frame = tk.Frame(root, bg=BG)
    frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    vbar = tk.Scrollbar(frame)
    vbar.pack(side="right", fill="y")
    txt = tk.Text(frame, bg=PANEL, fg=TXT, relief="flat", bd=0, wrap="word", padx=14, pady=10,
                  yscrollcommand=vbar.set, font=("Segoe UI", 10), highlightthickness=0,
                  spacing1=1, spacing3=3, cursor="arrow")
    txt.pack(side="left", fill="both", expand=True)
    vbar.config(command=txt.yview)
    txt.tag_config("h1", foreground=GOLD, font=("Segoe UI", 14, "bold"), spacing3=8)
    txt.tag_config("ver", foreground=GOLD, font=("Segoe UI", 12, "bold"), spacing1=14, spacing3=4)
    txt.tag_config("bul", lmargin1=14, lmargin2=28, spacing3=5)
    txt.tag_config("b", font=("Segoe UI", 10, "bold"), foreground=BOLD)
    txt.tag_config("dot", foreground=BULLET, font=("Segoe UI", 10, "bold"))

    def _inline(s, base):
        """Insert a line, honoring **bold** segments; `base` is an extra tag on every run."""
        for i, seg in enumerate(s.split("**")):
            if not seg:
                continue
            tags = ([base] if base else [])
            if i % 2 == 1:                          # odd segments are between ** ** -> bold
                tags.append("b")
            txt.insert("end", seg, tuple(tags))

    def render(md):
        txt.config(state="normal")
        txt.delete("1.0", "end")
        for line in md.splitlines():
            s = line.rstrip()
            if s.startswith("## "):
                txt.insert("end", s[3:] + "\n", "ver")
            elif s.startswith("# "):
                txt.insert("end", s[2:] + "\n", "h1")
            elif s.startswith("- "):
                txt.insert("end", "•  ", ("dot", "bul"))
                _inline(s[2:], "bul")
                txt.insert("end", "\n")
            elif not s:
                txt.insert("end", "\n")
            else:
                _inline(s, None)
                txt.insert("end", "\n")
        txt.config(state="disabled")

    render(_local_changelog())

    def _remote():
        md = _fetch_remote()
        if md and md.strip():
            root.after(0, lambda: render(md))       # GitHub copy may be newer than the bundled one
    threading.Thread(target=_remote, daemon=True).start()

    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
