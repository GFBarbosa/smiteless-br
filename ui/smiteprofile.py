#!/usr/bin/env python3
"""smiteprofile.py - the home / profile window (shown when you open Smiteless out of a game).

A normal, focusable, SCROLLABLE window: your rank, recent form, champ win rates, and your
games each scored against the lobby - rendered by smitecard.render_profile and shown in a
scrolling canvas with a "Load more" button that pulls in more games.
"""
import sys, os, threading, ctypes
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):                # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass
import lolbuild as lb
import lolprofile as lp
import smitecard as sc
import smiteconfig as cfg

BG = "#0e1016"; BAR = "#171a24"; GOLD = "#c8aa6e"; TXT = "#d8d6cf"; MUTED = "#8b897f"
BTN = "#262b3b"; BTN_HOVER = "#333a52"
_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32


def _single_instance():
    _kernel32.CreateMutexW(None, False, "Global\\SmitelessProfile")
    return _kernel32.GetLastError() != 183     # ERROR_ALREADY_EXISTS


def _center(root, w, h):
    try:
        sw, sh = _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 30)}")
    except Exception:
        root.geometry(f"{w}x{h}")


def main():
    if not _single_instance():
        return
    import tkinter as tk
    from PIL import ImageTk

    dd = lb.ddragon()
    st = {"count": cfg.load().get("profile_games", 10), "busy": False, "photo": None}

    root = tk.Tk()
    root.title("Smiteless — Profile")
    root.configure(bg=BG)
    ico = os.path.join(_ROOT, "assets", "smiteless.ico")
    try:
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass
    _center(root, sc.W + 22, 720)
    root.minsize(sc.W + 22, 360)

    body = tk.Frame(root, bg=BG)
    body.pack(side="top", fill="both", expand=True)
    vbar = tk.Scrollbar(body, orient="vertical")
    vbar.pack(side="right", fill="y")
    canvas = tk.Canvas(body, bg=BG, highlightthickness=0, yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.config(command=canvas.yview)
    canvas.create_text(sc.W // 2, 60, text="loading your profile…", fill=MUTED,
                       font=("Segoe UI", 13), tags="msg")

    bar = tk.Frame(root, bg=BAR)
    bar.pack(side="bottom", fill="x")
    status = tk.Label(bar, text="", bg=BAR, fg=MUTED, font=("Segoe UI", 9))
    status.pack(side="left", padx=14, pady=8)
    loadbtn = tk.Button(bar, text="Load more", bg=BTN, fg=TXT, activebackground=BTN_HOVER,
                        activeforeground=TXT, relief="flat", font=("Segoe UI", 9, "bold"),
                        padx=16, pady=4, cursor="hand2", state="disabled")
    loadbtn.pack(side="right", padx=12, pady=7)
    loadbtn.bind("<Enter>", lambda e: loadbtn.config(bg=BTN_HOVER))
    loadbtn.bind("<Leave>", lambda e: loadbtn.config(bg=BTN))

    def _apply(prof):
        st["busy"] = False
        if not prof or not prof.get("games"):
            canvas.delete("all")
            msg = (prof.get("error") if prof else None) or "no ranked games found (need a Riot API key)"
            canvas.create_text(sc.W // 2, 60, text=msg, fill=MUTED, font=("Segoe UI", 12))
            return
        pil = sc.render_profile(dd, prof)
        photo = ImageTk.PhotoImage(pil)
        st["photo"] = photo                       # keep a ref or Tk GC's it (blank image)
        top = canvas.yview()[0]
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas.configure(scrollregion=(0, 0, pil.width, pil.height))
        canvas.yview_moveto(top)                  # keep scroll position across "load more"
        status.config(text=f"showing {len(prof['games'])} games")
        more = len(prof["games"]) >= st["count"]  # there were at least as many as we asked for
        loadbtn.config(state="normal" if more else "disabled",
                       text="Load more" if more else "no more games")

    def _load(more=False):
        if st["busy"]:
            return
        st["busy"] = True
        if more:
            st["count"] += 10
            loadbtn.config(text="loading…", state="disabled")
        def work():
            try:
                prof = lp.build_profile(dd, count=st["count"])
            except Exception:
                prof = None
            root.after(0, lambda: _apply(prof))
        threading.Thread(target=work, daemon=True).start()

    loadbtn.config(command=lambda: _load(True))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
    root.bind("<Escape>", lambda e: root.destroy())
    root.after(60, lambda: _load(False))
    root.mainloop()


if __name__ == "__main__":
    main()
