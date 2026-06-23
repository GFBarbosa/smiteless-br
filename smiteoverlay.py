#!/usr/bin/env python3
"""smiteoverlay.py - the live Smiteless overlay, all in Python.

A borderless, always-on-top window that polls the League client/API directly and
updates IN PLACE as champ-select picks come in and the game progresses - no PNG
round-trip, no AutoHotkey picture-reload. It reuses smitecard's renderer (the same
Pillow scoreboard) but displays each frame straight into a Tk window via PhotoImage.

Key behaviors:
  - Never steals focus from the game (WS_EX_NOACTIVATE) - stays on top, click/Esc closes.
  - Opens on the second monitor if you have one.
  - Auto-closes ~1.5 min after the match ends so the next game's auto-open is fresh.
  - Single-instance (a second launch no-ops while one is already up).

  python smiteoverlay.py            # manual: show status now, then the board
  python smiteoverlay.py --wait     # auto-open: stay hidden until champs are present
  python smiteoverlay.py --count 10
"""
import sys, os, threading, ctypes
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smitecard as sc

BG = "#11131a"   # matches smitecard's background so there's no border seam

# ---- win32 constants ----
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def acquire_single_instance():
    """True if we're the only overlay; False if one is already running."""
    _kernel32.CreateMutexW(None, False, "Global\\SmitelessOverlay")
    return _kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def monitors():
    """List of (left, top, right, bottom) for each display."""
    rects = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), ctypes.c_double)

    def cb(_h, _dc, prc, _d):
        r = prc.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return 1
    try:
        _user32.EnumDisplayMonitors(0, 0, proc(cb), 0)
    except Exception:
        pass
    if not rects:  # fallback: primary only
        rects = [(0, 0, _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1))]
    return rects


def target_monitor():
    """The non-primary monitor if there is one, else the primary. (left,top,right,bottom)"""
    mons = monitors()
    for m in mons:
        if (m[0], m[1]) != (0, 0):      # primary's origin is (0,0)
            return m
    return mons[0]


def make_no_activate(hwnd):
    try:
        ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                               ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
    except Exception:
        pass


def show_no_activate(hwnd):
    try:
        _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
    except Exception:
        pass


def main():
    if not acquire_single_instance():
        return  # another overlay is already up
    argv = sys.argv[1:]
    wait = "--wait" in argv
    if wait:
        argv.remove("--wait")
    count = 10
    if "--count" in argv:
        i = argv.index("--count")
        try:
            count = int(argv[i + 1])
        except Exception:
            pass

    import tkinter as tk
    from PIL import ImageTk

    root = tk.Tk()
    root.overrideredirect(True)                 # borderless, no taskbar button
    root.attributes("-topmost", True)
    root.configure(bg=BG)
    root.geometry("1x1+-4000+-4000")            # park off-screen until the first frame
    label = tk.Label(root, bd=0, bg=BG)
    label.pack()
    root.update_idletasks()
    hwnd = root.winfo_id()                       # overrideredirect -> this is the toplevel HWND
    make_no_activate(hwnd)

    st = {"img": None, "dirty": False, "ref": None, "size": None,
          "pos": None, "shown": False, "closing": False, "done": False}
    lock = threading.Lock()

    def emit(pil_img):                           # called from the worker thread (no Tk here!)
        with lock:
            st["img"] = pil_img
            st["dirty"] = True

    def close(*_):
        st["closing"] = True
        try:
            root.destroy()
        except Exception:
            pass

    # left-drag to move the window; Esc or right-click to close it
    def start_drag(e):
        st["drag"] = (e.x_root, e.y_root)

    def on_drag(e):
        if not st.get("drag") or not st["pos"] or not st["size"]:
            return
        dx, dy = e.x_root - st["drag"][0], e.y_root - st["drag"][1]
        st["pos"] = (st["pos"][0] + dx, st["pos"][1] + dy)
        st["drag"] = (e.x_root, e.y_root)
        w, h = st["size"]
        root.geometry(f"{w}x{h}+{st['pos'][0]}+{st['pos'][1]}")

    label.bind("<Button-1>", start_drag)
    label.bind("<B1-Motion>", on_drag)
    root.bind("<Escape>", close)
    root.bind("<Button-3>", close)               # right-click to close
    label.bind("<Button-3>", close)

    def worker():
        try:
            sc.run(emit, count=count, wait=wait, stop=lambda: st["closing"], monitor=True)
            st["done"] = True                    # normal return = match over -> overlay may close
        except Exception as e:
            # Unexpected crash: show it and KEEP the window up (don't auto-close) so it's visible.
            emit(sc.info_image(f"overlay error: {type(e).__name__}: {e}  -  Esc to close"))

    threading.Thread(target=worker, daemon=True).start()

    def place(size):
        w, h = size
        if st["pos"] is None:                    # center on the target monitor, once
            l, t, r, b = target_monitor()
            st["pos"] = (l + ((r - l) - w) // 2, t + ((b - t) - h) // 2)
        x, y = st["pos"]
        root.geometry(f"{w}x{h}+{x}+{y}")

    def pump():
        if st["closing"]:
            return
        with lock:
            dirty, pil = st["dirty"], st["img"]
            st["dirty"] = False
        if dirty and pil is not None:
            ref = ImageTk.PhotoImage(pil)        # build on the Tk (main) thread
            label.configure(image=ref)
            st["ref"] = ref                      # keep a reference or it gets GC'd (blank image)
            if st["size"] != pil.size:
                st["size"] = pil.size
                place(pil.size)
            if not st["shown"]:
                show_no_activate(hwnd)           # reveal without taking focus
                st["shown"] = True
        if st["done"] and not dirty:             # worker finished (match over) -> close out
            close()
            return
        root.after(120, pump)

    root.after(50, pump)
    root.mainloop()
    # Force-release the process (and thus the single-instance mutex) immediately, even if a
    # background tip-generation thread is mid-flight - otherwise a lingering thread could keep
    # the mutex held and block the next launch.
    os._exit(0)


if __name__ == "__main__":
    main()
