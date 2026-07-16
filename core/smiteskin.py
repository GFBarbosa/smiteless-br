"""smiteskin.py - the ONE place Smiteless colors live.

Every window (Tk chrome and PIL boards alike) had its own copy of the palette, and they
drifted: profile's BG was #0e1016 while everything else was #11131a, the widget's PANEL
was #151823 vs #171a24, two different REDs. That drift is what read as "questionable".
This module is the canonical source - import from here, never re-declare a hex.

Also home to dark_titlebar(): the desktop windows (profile/settings/notes) keep their
native Windows title bar (real drag/snap/minimize), but Windows 11's compositor paints
it our near-black instead of the stock white slab. One ctypes call, no custom chrome.
(Council v0.9.1: Naturalist's plan + the top-5 consensus header treatment.)
"""

# ---- canonical palette (hex for Tk; rgb() derives the PIL tuples from the SAME values)
BG = "#11131a"          # window ground - everywhere, including profile (was #0e1016)
PANEL = "#171a24"       # raised strips/cards (widget header was #151823 - unified)
SEP = "#232838"         # hairline seams / 1px edges
GOLD = "#c8aa6e"        # THE accent - identity + emphasis only
TXT = "#d8d6cf"         # body text
MUTED = "#9b988e"       # secondary text (board-legible grey; replaces darker variants)
RED = "#e0646c"         # losing / danger (settings had #d46d78 - unified)
GREEN = "#5fc47a"
TEAL = "#4cc0b0"
BLUE = "#7fa8e0"
PURPLE = "#c98bdb"
BTN = "#262b3b"         # flat button fill
BTN_HOVER = "#333a52"   # button active/hover
ENTRY = "#0d0f16"       # entry/trough wells (settings had #0f1219 - unified)


def rgb(hx):
    """'#11131a' -> (17, 19, 26) so PIL renders from the same source of truth."""
    return tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))


def _colorref(hx):
    """COLORREF is 0x00BBGGRR - DWM wants the bytes backwards."""
    r, g, b = rgb(hx)
    return (b << 16) | (g << 8) | r


def dark_titlebar(root):
    """Paint a native Tk window's Windows title bar dark so it stops fighting the app.
    attr 20 = immersive dark mode, 35 = caption color, 34 = border color. Needs Win11;
    on failure the window just keeps the stock bar - cosmetic, never fatal."""
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)   # GA_ROOT
        if not hwnd:
            return
        for attr, val in ((20, 1), (35, _colorref(BG)), (34, _colorref(SEP))):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(ctypes.c_int(val)), 4)
    except Exception:
        pass
