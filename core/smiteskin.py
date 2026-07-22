"""smiteskin.py - the Smiteless "Duskfall" design system (v1.0). See docs/UIDESIGN.md.

The ONE place colors, type, and spacing live. Every window (Tk chrome and PIL boards
alike) imports from here - never re-declare a hex or a font family in a surface file.

Duskfall in one line: League client at dusk, lit by an ember. Violet-ink ground, hot
amber (EMBER) for identity + actions, arcane cyan (ARC) for live telemetry, Bahnschrift
for headers and every numeral. The v0.9.1 skin only unified the old palette; this one
replaces it.
"""

# ---- ground ramp (violet-ink; hex for Tk, rgb() derives the PIL tuples) ----
VOID = "#0c0a13"        # window ground, board background
SURFACE = "#15121f"     # cards, strips, panels
RAISED = "#1e1930"      # buttons at rest, raised chips, expanded rows
HOVER = "#2a2342"       # button hover/active, selection fills
SUNKEN = "#07060b"      # entry wells, troughs, scrollbar channels
LINE = "#2b2444"        # strong hairlines, card outlines
LINE_SOFT = "#1c1730"   # subtle seams inside cards

# ---- ink ----
TXT = "#e8e3f4"         # body text (cool white-violet)
MUTED = "#9a92b4"       # secondary text
FAINT = "#5e5678"       # tertiary/disabled, labeled-rule lines

# ---- accent + status ----
EMBER = "#ffb454"       # THE accent: brand, section headers, primary action, "me"
EMBER_DEEP = "#c77f2e"  # ember pressed/dimmed, rails on identity cards
ARC = "#5ad1dc"         # live telemetry: timers, win-prob, sparklines, live dots
GOOD = "#5fe0a0"        # wins / TAKE / saved-ok
BAD = "#ff6478"         # losses / danger / GIVE / dodge flags
WARN = "#ffd166"        # caution / 50-50 / expiring key
INFO = "#8fa9ef"        # links, neutral highlights, bullet dots
MYSTIC = "#b98bf5"      # antiheal/utility tags, duo markers

# ---- shape & space tokens ----
R_CARD = 10             # card corner radius (PIL boards)
R_BTN = 8               # button radius (PIL boards)
RAIL = 3                # state-rail width on a card's left edge
PAD = 14                # card inner padding
GAP = 10                # gap between cards
PAD_WIN = 18            # window gutters

# ---- typography ----
# Bahnschrift (DIN-style, ships with Win10+) carries headers and ALL numerals; Segoe UI
# stays the body face. If Bahnschrift is missing, Segoe UI Semibold is the stand-in.
FONT_DISPLAY = "Bahnschrift"
FONT_DISPLAY_FALLBACK = "Segoe UI Semibold"
FONT_BODY = "Segoe UI"
FONT_BODY_BOLD = "Segoe UI Semibold"
FONT_MONO = "Consolas"
# PIL file paths (smitecard.font() owns the load-with-fallback logic)
FONT_DISPLAY_TTF = r"C:\Windows\Fonts\bahnschrift.ttf"
FONT_BODY_TTF = r"C:\Windows\Fonts\segoeui.ttf"
FONT_SYMBOL_TTF = r"C:\Windows\Fonts\seguisym.ttf"     # the tofu-rescue face: full symbol coverage


# ---- glyph coverage (the tofu killer) ----
# Segoe UI and Bahnschrift are missing MOST of the pictographs the surfaces draw (⚑ ⚠ ✚ ⇩
# ✓ ✦ ▸ ● …), so any string routed to them un-checked renders [] boxes. The old fix was a
# hand-typed allowlist of "symbol chars" in each surface — which rotted the moment a new
# glyph shipped (✚ and ⇩ were never added: v0.9.29's tofu). This probes the FONT ITSELF —
# render the char, compare against the font's .notdef box — so coverage can never rot.
_GLYPH_OK = {}          # (font_path, ch) -> bool, probed once per process
_NOTDEF = {}            # font_path -> the rendered tofu box, for comparison


def _pil_renders(path, ch, _size=24):
    key = (path, ch)
    if key in _GLYPH_OK:
        return _GLYPH_OK[key]
    try:
        from PIL import Image, ImageDraw, ImageFont
        f = ImageFont.truetype(path, _size)
        if path not in _NOTDEF:
            im = Image.new("L", (48, 48), 0)
            ImageDraw.Draw(im).text((4, 4), "", font=f, fill=255)   # unmapped -> .notdef
            _NOTDEF[path] = im.tobytes()
        im = Image.new("L", (48, 48), 0)
        ImageDraw.Draw(im).text((4, 4), ch, font=f, fill=255)
        _GLYPH_OK[key] = im.tobytes() != _NOTDEF[path]
    except Exception:
        _GLYPH_OK[key] = True       # can't probe -> don't second-guess the draw
    return _GLYPH_OK[key]


def needs_symbol(text, font_path=None):
    """True if `text` carries a glyph the given face (default: Segoe UI body) can't draw —
    the caller should switch the whole string to FONT_SYMBOL_TTF. ASCII never triggers."""
    if not text:
        return False
    path = font_path or FONT_BODY_TTF
    return any(ord(c) > 0x2000 and not _pil_renders(path, c) for c in text)

_HAS_DISPLAY = None     # cached "is Bahnschrift installed" probe (Tk only)


def _has_display_font():
    global _HAS_DISPLAY
    if _HAS_DISPLAY is None:
        try:
            import tkinter.font as tkfont
            _HAS_DISPLAY = FONT_DISPLAY in set(tkfont.families())
        except Exception:
            _HAS_DISPLAY = True     # no Tk yet / non-Windows dev box: let Tk substitute
    return _HAS_DISPLAY


def display(size, bold=False):
    """Tk font tuple for headers/numerals: Bahnschrift, Segoe UI Semibold fallback."""
    fam = FONT_DISPLAY if _has_display_font() else FONT_DISPLAY_FALLBACK
    return (fam, size, "bold") if bold else (fam, size)


def body(size=10, bold=False):
    """Tk font tuple for body text."""
    return (FONT_BODY, size, "bold") if bold else (FONT_BODY, size)


def mono(size=9, bold=False):
    return (FONT_MONO, size, "bold") if bold else (FONT_MONO, size)


# type scale (Tk pt) - keep surfaces on the same rungs
H1 = 16                 # window titles
H2 = 12                 # section headers (ALL-CAPS, EMBER)
BODY = 10               # standard text (bigger than the old 8-9)
SMALL = 9               # descriptions, MUTED

BRAND_MARK = "✦"   # the Duskfall spark: every brand row starts with it


def rgb(hx):
    """'#0c0a13' -> (12, 10, 19) so PIL renders from the same source of truth."""
    return tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))


def wr_color(wr):
    """Semantic win-rate ramp: <46 BAD, 46-52 MUTED, 52-56 GOOD, >56 ARC (exceptional)."""
    if wr is None:
        return MUTED
    if wr < 46:
        return BAD
    if wr < 52:
        return MUTED
    if wr <= 56:
        return GOOD
    return ARC


# ---- shared Tk widget factories (chrome consistency without a framework) ----

def brand_row(parent, suffix="", bg=None):
    """The '✦ SMITELESS <SUFFIX>' identity row every window opens with. Returns the Frame."""
    import tkinter as tk
    bg = bg or VOID
    fr = tk.Frame(parent, bg=bg)
    tk.Label(fr, text=BRAND_MARK, bg=bg, fg=EMBER, font=display(H1)).pack(side="left")
    tk.Label(fr, text=" SMITELESS", bg=bg, fg=TXT, font=display(H1)).pack(side="left")
    if suffix:
        tk.Label(fr, text=" " + suffix.upper(), bg=bg, fg=MUTED,
                 font=display(H1)).pack(side="left")
    return fr


def section_rule(parent, text, bg=None):
    """H2 labeled rule: EMBER header with a soft hairline running to the right edge."""
    import tkinter as tk
    bg = bg or VOID
    fr = tk.Frame(parent, bg=bg)
    tk.Label(fr, text=text.upper(), bg=bg, fg=EMBER, font=display(H2)).pack(side="left")
    tk.Frame(fr, bg=LINE_SOFT, height=1).pack(side="left", fill="x", expand=True,
                                              padx=(GAP, 0), pady=(2, 0))
    return fr


def card(parent, rail=None, bg=None):
    """A railed SURFACE card: 3px state rail on the left, body Frame returned as .body."""
    import tkinter as tk
    outer = tk.Frame(parent, bg=(bg or SURFACE))
    tk.Frame(outer, bg=(rail or LINE), width=RAIL).pack(side="left", fill="y")
    outer.body = tk.Frame(outer, bg=(bg or SURFACE))
    outer.body.pack(side="left", fill="both", expand=True)
    return outer


def button(parent, text, cmd, primary=False, size=SMALL):
    """Flat Duskfall button. Exactly ONE primary (EMBER fill, VOID ink) per window."""
    import tkinter as tk
    if primary:
        b = tk.Button(parent, text=text, command=cmd, bg=EMBER, fg=VOID,
                      activebackground=EMBER_DEEP, activeforeground=VOID)
    else:
        b = tk.Button(parent, text=text, command=cmd, bg=RAISED, fg=TXT,
                      activebackground=HOVER, activeforeground=TXT)
    b.config(relief="flat", bd=0, padx=12, pady=4, cursor="hand2",
             font=body(size, bold=True))
    if not primary:
        b.bind("<Enter>", lambda e: b.config(bg=HOVER))
        b.bind("<Leave>", lambda e: b.config(bg=RAISED))
    return b


# ---- legacy aliases (v0.9.1 names) - untouched call-sites keep working; new code
# uses the Duskfall names above. Remove once every surface has migrated. ----
BG = VOID
PANEL = SURFACE
SEP = LINE_SOFT
GOLD = EMBER
RED = BAD
GREEN = GOOD
TEAL = ARC
BLUE = INFO
PURPLE = MYSTIC
BTN = RAISED
BTN_HOVER = HOVER
ENTRY = SUNKEN


def _colorref(hx):
    """COLORREF is 0x00BBGGRR - DWM wants the bytes backwards."""
    r, g, b = rgb(hx)
    return (b << 16) | (g << 8) | r


def dark_titlebar(root):
    """Paint a native Tk window's Windows title bar in Duskfall ink so it stops fighting
    the app. attr 20 = immersive dark mode, 35 = caption color, 34 = border color. Needs
    Win11; on failure the window just keeps the stock bar - cosmetic, never fatal."""
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)   # GA_ROOT
        if not hwnd:
            return
        for attr, val in ((20, 1), (35, _colorref(VOID)), (34, _colorref(LINE_SOFT))):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(ctypes.c_int(val)), 4)
    except Exception:
        pass
