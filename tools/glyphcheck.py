#!/usr/bin/env python3
"""glyphcheck.py - tofu tripwire. Fails the build/selftest when a PIL-drawn string
literal carries a glyph Segoe UI can't render AND the draw on that line goes through a
text-blind font call (_wfont / _dfont / display_font / font(size) without text=).

Why this exists: the tofu bug has now shipped TWICE (fixed for smitecard in ee6eca3,
regressed on the widget by v0.9.29) because each surface kept its own hand-typed list of
"symbol characters". The render-time fix is skin.needs_symbol() probing the font itself;
this check catches the remaining failure mode — routing a symbol literal to a font
function that never looks at the text at all.

Tk draws (skin.body/display/mono font tuples) are exempt: Tk does its own font fallback.

  python tools/glyphcheck.py          # exit 1 + a report line per offending line
"""
import sys, os, re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_ROOT, _d))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import smiteskin as skin

SCAN = ["core/smitecard.py", "ui/smitewidget.py", "ui/smiteload.py", "ui/smitedead.py",
        "ui/smiteoverlay.py", "ui/smiteprofile.py"]

# a font= that DOES adapt to its text (or is the symbol face itself) is fine
_TEXT_AWARE = re.compile(r"font=\s*(?:_tfont\(|name_font\(|font\([^)]*text\s*=|"
                         r"font\(\s*[^,)]+,\s*(?:1|True)\s*,\s*[\"'f]|"
                         r"ImageFont\.truetype\([^)]*sym)")
_PIL_DRAW = re.compile(r"\bd\d?\.text\(|\.textlength\(")
_STR_LIT = re.compile(r"[\"']([^\"']*)[\"']")


def _logical_lines(path):
    """(first_lineno, joined_statement) with continuation lines merged until parens
    balance — a d.text((...) call regularly spans 2-3 source lines."""
    out, buf, start, depth = [], [], 0, 0
    for i, raw in enumerate(open(path, encoding="utf-8"), 1):
        ln = raw.split("#", 1)[0].rstrip("\n")     # strings in comments don't render
        if not buf:
            start = i
        buf.append(ln)
        depth += ln.count("(") - ln.count(")")
        if depth <= 0:
            out.append((start, " ".join(buf)))
            buf, depth = [], 0
    if buf:
        out.append((start, " ".join(buf)))
    return out


def check():
    bad = []
    for rel in SCAN:
        path = os.path.join(_ROOT, rel)
        if not os.path.exists(path):
            continue
        for i, ln in _logical_lines(path):
            if not _PIL_DRAW.search(ln):
                continue
            lits = " ".join(_STR_LIT.findall(ln))
            hard = [c for c in set(lits) if ord(c) > 0x2000 and not skin._pil_renders(skin.FONT_BODY_TTF, c)]
            if not hard:
                continue
            if _TEXT_AWARE.search(ln):
                continue
            # font=some_var: the font was chosen earlier (e.g. star_f = font(sz, 1, "✦"));
            # only a direct text-blind CALL at the draw site is a provable tofu path
            if not re.search(r"font=\s*(?:_wfont|_dfont|display_font|font)\s*\(", ln):
                continue
            bad.append(f"{rel}:{i}: glyph(s) {' '.join(sorted(hard))} drawn with a "
                       f"text-blind font -> tofu. Route through _tfont/font(text=...).")
    return bad


def main():
    bad = check()
    for b in bad:
        print("FAIL:", b)
    if not bad:
        print("glyphcheck: no tofu-able draw calls found "
              f"({len(SCAN)} surfaces scanned against {os.path.basename(skin.FONT_BODY_TTF)})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
