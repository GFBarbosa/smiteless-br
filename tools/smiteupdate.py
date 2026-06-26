#!/usr/bin/env python3
"""smiteupdate.py - notify + one-click updater.

On launch the tray runs `SmitelessApp.exe update`. This checks the GitHub Releases API for
a newer version than the local VERSION file; if there is one, it shows a small window with
an Update button. Clicking Update downloads that release's SmitelessSetup.exe and runs it
(the installer closes the running app, lays the new files down, and relaunches). If we're
up to date or offline, it exits silently.
"""
import os
import sys
import json
import ssl
import tempfile
import subprocess
import urllib.request

REPO = "bobbyroylee/smiteless"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = "Smiteless-Updater"


def install_root():
    """The folder that holds VERSION + Smiteless.exe. Frozen layout: <root>/app/SmitelessApp.exe."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ -> repo root


def local_version():
    try:
        with open(os.path.join(install_root(), "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"


def _vtuple(s):
    s = (s or "").lstrip("vV").strip()
    out = []
    for part in s.split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out or [0])


def latest_release():
    """(tag, setup_download_url) for the newest release, or None."""
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(API, headers={"User-Agent": UA,
                                                    "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            d = json.load(r)
    except Exception:
        return None
    tag = d.get("tag_name")
    url = None
    for a in d.get("assets", []):
        if a.get("name", "").lower() == "smitelesssetup.exe":
            url = a.get("browser_download_url")
            break
    return (tag, url) if tag and url else None


def _download(url, dest):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)


def _run_setup(cur, tag, url):
    setup = os.path.join(tempfile.gettempdir(), "SmitelessSetup.exe")
    try:
        _download(url, setup)
    except Exception:
        return False
    # /upgrade tells the installer to close the running app, overwrite, and relaunch silently
    subprocess.Popen([setup, "/upgrade"], close_fds=True)
    return True


def _dialog(cur, tag, url):
    import tkinter as tk
    root = tk.Tk()
    root.title("Smiteless update")
    root.configure(bg="#11131a")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    wrap = tk.Frame(root, bg="#11131a")
    wrap.pack(padx=18, pady=16)
    tk.Label(wrap, text="A new version of Smiteless is available",
             font=("Segoe UI", 11, "bold"), fg="#c8aa6e", bg="#11131a").pack(anchor="w")
    tk.Label(wrap, text=f"You have {cur}.  Latest is {tag}.",
             font=("Segoe UI", 9), fg="#d8d6cf", bg="#11131a").pack(anchor="w", pady=(4, 12))
    btns = tk.Frame(wrap, bg="#11131a")
    btns.pack(anchor="e")

    def do_update():
        for w in wrap.winfo_children():
            w.configure(state="disabled") if isinstance(w, tk.Button) else None
        ok = _run_setup(cur, tag, url)
        root.destroy()
        if not ok:
            try:
                import tkinter.messagebox as mb
                mb.showerror("Smiteless", "Couldn't download the update. Try again later.")
            except Exception:
                pass

    tk.Button(btns, text="Later", width=10, command=root.destroy,
              bg="#262b3b", fg="#d8d6cf", activebackground="#333a52",
              relief="flat", font=("Segoe UI", 9)).pack(side="right", padx=(8, 0))
    tk.Button(btns, text="Update now", width=12, command=do_update,
              bg="#c8aa6e", fg="#11131a", activebackground="#d8bd86",
              relief="flat", font=("Segoe UI", 9, "bold")).pack(side="right")
    root.update_idletasks()
    root.eval("tk::PlaceWindow . center")
    root.mainloop()


def _info(msg):
    try:
        import tkinter as tk
        import tkinter.messagebox as mb
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        mb.showinfo("Smiteless", msg)
        r.destroy()
    except Exception:
        pass


def main(args=None):
    args = args or []
    force = "--force" in args                     # manual "Check for updates" -> always give feedback
    cur = local_version()
    rel = latest_release()
    if not rel:
        if force:
            _info("Couldn't reach the update server. Check your internet and try again.")
        return                                    # offline / no release -> silent otherwise
    tag, url = rel
    if _vtuple(tag) <= _vtuple(cur):
        if force:
            _info(f"You're on the latest version ({cur}).")
        return                                     # up to date
    if "--apply" in args:                          # headless apply (no prompt)
        _run_setup(cur, tag, url)
    else:
        _dialog(cur, tag, url)


if __name__ == "__main__":
    main(sys.argv[1:])
