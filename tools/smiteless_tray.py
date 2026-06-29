#!/usr/bin/env python3
"""smiteless_tray.py - the persistent Smiteless tray app, pure Python (replaces the AHK).

A system-tray icon + right-click menu (Open overlay / Settings / Auto-open / Start with
Windows / Quit), a global Ctrl+Alt+X hotkey (native Win32 RegisterHotKey), and the
champ-select auto-open watcher. The overlay and settings windows are launched as separate
single-instance Python processes.

Run with pythonw.exe so there's no console window. Needs: pip install pystray pillow.
"""
import sys, os, threading, subprocess, ctypes
from ctypes import wintypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import smiteconfig as cfg
import phasecheck

HERE = os.path.dirname(os.path.abspath(__file__))
_pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
PYW = _pyw if os.path.exists(_pyw) else sys.executable        # windowless launcher
OVERLAY = os.path.join(_ROOT, "ui", "smiteoverlay.py")
SETTINGS = os.path.join(_ROOT, "ui", "smitesettings.py")
ICON = os.path.join(_ROOT, "assets", "smiteless.ico")
CREATE_NO_WINDOW = 0x08000000

_k32 = ctypes.windll.kernel32
_u32 = ctypes.windll.user32
_stop = threading.Event()


def _single_instance():
    # use_last_error so GetLastError is read reliably (a plain ctypes call can clobber it,
    # which let duplicate instances start)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW(None, False, "Global\\SmitelessTray")
    return ctypes.get_last_error() != 183        # ERROR_ALREADY_EXISTS


def _launch(script, *args):
    try:
        subprocess.Popen([PYW, script, *args], creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def open_overlay(auto=False):
    _launch(OVERLAY, *(["--wait"] if auto else []))


def open_settings():
    _launch(SETTINGS)


# ---------- auto-open watcher (polls the phase in-process, adaptive interval) ----------
def _watcher():
    opened = False
    while not _stop.is_set():
        poll_interval = 4 if cfg.auto_open_enabled() else 30  # 30s when disabled to avoid constant polling
        if cfg.auto_open_enabled():
            active = phasecheck.phase() in ("ChampSelect", "GameStart", "InProgress", "Reconnect")
            if active and not opened:
                opened = True
                open_overlay(auto=True)
                poll_interval = 2  # speed up polling while in-game
            elif not active:
                opened = False                   # any non-active phase re-arms for next game
        else:
            opened = False
        _stop.wait(poll_interval)


# ---------- global hotkey: Ctrl+Alt+X (native, like AHK uses) ----------
def _hotkey():
    MOD_ALT, MOD_CONTROL, VK_X, WM_HOTKEY = 0x0001, 0x0002, 0x58, 0x0312
    if not _u32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL, VK_X):
        return                                   # another app owns it (e.g. an old AHK tray)
    try:
        msg = wintypes.MSG()
        while not _stop.is_set():
            r = _u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                open_overlay(False)
    finally:
        _u32.UnregisterHotKey(None, 1)


def main():
    if not _single_instance():
        return
    import pystray
    from PIL import Image

    threading.Thread(target=_watcher, daemon=True).start()
    threading.Thread(target=_hotkey, daemon=True).start()

    try:
        img = Image.open(ICON)
    except Exception:
        img = Image.new("RGB", (64, 64), (20, 23, 32))

    def toggle_autoopen(icon, item):
        cfg.set_auto_open(not cfg.auto_open_enabled())
        icon.update_menu()

    def toggle_autostart(icon, item):
        cfg.set_autostart(not cfg.autostart_enabled())
        icon.update_menu()

    def quit_app(icon, item):
        _stop.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open overlay", lambda icon, item: open_overlay(False), default=True),
        pystray.MenuItem("Settings…", lambda icon, item: open_settings()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Auto-open at champ select", toggle_autoopen,
                         checked=lambda item: cfg.auto_open_enabled()),
        pystray.MenuItem("Start with Windows", toggle_autostart,
                         checked=lambda item: cfg.autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("smiteless", img, "Smiteless", menu)
    icon.run()
    _stop.set()


if __name__ == "__main__":
    main()
