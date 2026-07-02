#!/usr/bin/env python3
"""smiteprofile.py - the home / profile window (opened out of game, or from the tray/hotkey).

A normal, focusable, landscape, SCROLLABLE window: your rank, recent form, champ win rates,
and your games each scored against the lobby. Click a game to expand its 10-player breakdown
in place (click again to collapse); "Load more" pulls in older games.
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
import lolscout as ls
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
    """Center on the SECOND monitor if there is one (so it lands beside the game, like the
    overlay), else the primary."""
    try:
        from smiteoverlay import target_monitor
        l, t, r, b = target_monitor()
        x = l + ((r - l) - w) // 2
        y = t + max(0, ((b - t) - h) // 2 - 40)
        root.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        try:
            sw, sh = _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
            root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 40)}")
        except Exception:
            root.geometry(f"{w}x{h}")


def main():
    if not _single_instance():
        return
    import tkinter as tk
    from PIL import Image, ImageTk

    dd = lb.ddragon()
    key = ls.read_key()
    st = {"count": cfg.load().get("profile_games", 10), "busy": False, "photo_top": None, "photo_bottom": None,
          "split_y": 0, "prof": None, "expanded": set(), "details": {}, "hit": [], "hit_reviews": []}

    root = tk.Tk()
    root.title("Smiteless — Profile")
    root.configure(bg=BG)
    try:
        cand = []
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            cand.extend([
                os.path.join(exe_dir, "assets", "smiteless.ico"),
                os.path.join(exe_dir, "smiteless.ico"),
            ])
        cand.extend([
            os.path.join(_ROOT, "assets", "smiteless.ico"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "smiteless.ico"),
        ])
        ico = next((p for p in cand if os.path.exists(p)), "")
        if ico:
            # Use both APIs so Windows titlebar/taskbar consistently get the same "S" icon.
            root.iconbitmap(ico)
            root._app_icon = ImageTk.PhotoImage(Image.open(ico))
            root.iconphoto(True, root._app_icon)
    except Exception:
        pass
    _center(root, sc.W + 24, 780)              # default tall enough to show ~10 recent games before scrolling
    root.minsize(sc.W + 24, 520)

    header = tk.Label(root, bg=BG, bd=0, highlightthickness=0)
    header.pack(side="top", fill="x")

    body = tk.Frame(root, bg=BG)
    body.pack(side="top", fill="both", expand=True)
    vbar = tk.Scrollbar(body, orient="vertical", bg=BAR, troughcolor="#0b0e15",
                        activebackground=BTN_HOVER, relief="flat", bd=0,
                        highlightthickness=0, width=12)
    vbar.pack(side="right", fill="y")
    canvas = tk.Canvas(body, bg=BG, highlightthickness=0, yscrollcommand=vbar.set, width=sc.W)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.config(command=canvas.yview)
    canvas.create_text(sc.W // 2, 60, text="loading your match history…", fill=MUTED, font=("Segoe UI", 13))

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
    savebtn = tk.Button(bar, text="Save card", bg=BTN, fg=TXT, activebackground=BTN_HOVER,
                        activeforeground=TXT, relief="flat", font=("Segoe UI", 9),
                        padx=12, pady=4, cursor="hand2", state="disabled")
    savebtn.pack(side="right", padx=(0, 4), pady=7)
    savebtn.bind("<Enter>", lambda e: savebtn.config(bg=BTN_HOVER))
    savebtn.bind("<Leave>", lambda e: savebtn.config(bg=BTN))

    def _save_card():
        prof = st.get("prof")
        if not prof:
            return
        try:
            import time as _t
            pil = sc.render_profile(dd, prof)          # collapsed, shareable snapshot
            name = f"smiteless_{(prof.get('riot_id') or 'profile').split('#')[0]}_{_t.strftime('%Y%m%d')}.png"
            name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
            dest = os.path.join(os.path.expanduser("~"), "Desktop", name)
            pil.save(dest)
            status.config(text=f"saved → {dest}")
        except Exception as e:
            status.config(text=f"save failed: {e}")

    def _render(keep_scroll=True):
        prof = st["prof"]
        if not prof:
            return
        pil = sc.render_profile(dd, prof, st["expanded"], st["details"])
        split = int(getattr(pil, "profile_split_y", 240))
        split = max(120, min(pil.height - 1, split))
        top_img = pil.crop((0, 0, pil.width, split))
        bottom_img = pil.crop((0, split, pil.width, pil.height))
        ptop = ImageTk.PhotoImage(top_img)
        pbot = ImageTk.PhotoImage(bottom_img)
        st["photo_top"] = ptop                 # keep refs or Tk GC's them
        st["photo_bottom"] = pbot
        st["split_y"] = split
        top_pos = canvas.yview()[0] if keep_scroll else 0.0
        header.config(image=ptop)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=pbot)
        canvas.configure(scrollregion=(0, 0, bottom_img.width, bottom_img.height))
        canvas.yview_moveto(top_pos)
        st["hit"] = [(max(0, y0 - split), max(0, y1 - split), idx)
                     for y0, y1, idx in getattr(pil, "hit_games", []) if y1 > split]
        st["hit_reviews"] = [(x0, max(0, y0 - split), x1, max(0, y1 - split), idx)
                             for x0, y0, x1, y1, idx in getattr(pil, "hit_reviews", []) if y1 > split]

    def _apply(prof):
        st["busy"] = False
        if not prof or not prof.get("games"):
            header.config(image="")
            canvas.delete("all")
            msg = (prof.get("error") if prof else None) or \
                "couldn't read your profile — is the League client open, with a Riot key set?"
            canvas.create_text(sc.W // 2, 70, text=msg, fill=MUTED, font=("Segoe UI", 12), width=sc.W - 100)
            return
        st["prof"] = prof
        _render(keep_scroll=False)
        latest = (prof.get("games") or [{}])[0].get("review") or []
        if latest:
            status.config(text=f"{len(prof['games'])} games  ·  latest review: {latest[0]}")
        else:
            status.config(text=f"{len(prof['games'])} games  ·  click a game for the full breakdown")
        loadbtn.config(state="normal", text="Load more")
        savebtn.config(state="normal", command=_save_card)

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

    def _fetch_detail(mid):
        def work():
            try:
                det = lp.match_detail(mid, key)
            except Exception:
                det = None
            st["details"][mid] = det or {}
            root.after(0, _render)
        threading.Thread(target=work, daemon=True).start()

    def _show_review(game):
        import tkinter as tk
        tips = list(game.get("review") or [])
        kind = game.get("review_kind", "improve")
        head = "What you did well" if kind == "positive" else "3 things to improve"
        win = tk.Toplevel(root)
        win.title("Smiteless — Full review")
        win.configure(bg=BG)
        win.minsize(560, 360)
        tk.Label(win, text=f"{game.get('champ', '?')} ({game.get('pos', '?')})", bg=BG, fg=GOLD,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(win, text=head, bg=BG, fg=(TXT if kind == "positive" else MUTED),
                 font=("Segoe UI", 10)).pack(anchor="w", padx=14, pady=(0, 8))
        wrap = tk.Frame(win, bg=BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        sb = tk.Scrollbar(wrap, orient="vertical")
        sb.pack(side="right", fill="y")
        tx = tk.Text(wrap, bg="#131722", fg=TXT, relief="flat", wrap="word", yscrollcommand=sb.set,
                     font=("Segoe UI", 10), padx=12, pady=10)
        tx.pack(side="left", fill="both", expand=True)
        sb.config(command=tx.yview)
        if not tips:
            tips = ["No review available yet."]
        for i, t in enumerate(tips, 1):
            tx.insert("end", f"{i}. {t}\n\n")
        tx.config(state="disabled")

    def _on_click(event):
        x = canvas.canvasx(event.x)
        y = canvas.canvasy(event.y)
        for x0, y0, x1, y1, idx in st["hit_reviews"]:
            if x0 <= x <= x1 and y0 <= y <= y1:
                gm = st["prof"]["games"][idx]
                _show_review(gm)
                return
        for y0, y1, idx in st["hit"]:
            if y0 <= y <= y1:
                # in-canvas "Load more" region (special hit index)
                if idx == "__load_more__":
                    _load(True)
                    return
                if idx in st["expanded"]:
                    st["expanded"].discard(idx)
                else:
                    st["expanded"].add(idx)
                    mid = st["prof"]["games"][idx].get("mid")
                    if mid and mid not in st["details"]:
                        _fetch_detail(mid)       # loads, then re-renders
                _render()
                return

    loadbtn.config(command=lambda: _load(True))
    canvas.bind("<Button-1>", _on_click)
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
    root.bind("<Escape>", lambda e: root.destroy())
    root.after(60, lambda: _load(False))
    root.mainloop()


if __name__ == "__main__":
    main()
