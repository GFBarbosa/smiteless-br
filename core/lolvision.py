#!/usr/bin/env python3
"""lolvision.py - pure-PIL template matching over DOWNLOADED ART (no screen capture).

One job: find the champion's FACE inside their splash art, by locating the champ's square
icon (which IS Riot's hand-picked face crop) within the splash. smitecard uses the result
to center every banner crop on the face instead of a random slice of the art.
Operates exclusively on ddragon images already on disk/network - it never reads the screen.
"""


def _samples(img, n=6):
    """n x n grid of (dx, dy, value) samples from a grayscale PIL image."""
    w, h = img.size
    px = img.load()
    out = []
    for j in range(n):
        for i in range(n):
            x = min(w - 1, int((i + 0.5) * w / n))
            y = min(h - 1, int((j + 0.5) * h / n))
            out.append((x, y, px[x, y]))
    return out


def match_template(hay, tpl, step=3, n=6):
    """Best (score, x, y) placing grayscale `tpl` inside grayscale `hay`, comparing an
    n*n sample grid (mean abs diff, 0-255; lower = better). Coarse scan + local refine."""
    hw, hh = hay.size
    tw, th = tpl.size
    if tw >= hw or th >= hh:
        return 255.0, 0, 0
    hp = hay.load()
    pts = _samples(tpl, n)
    best, bx, by = 10 ** 9, 0, 0
    for y in range(0, hh - th, step):
        for x in range(0, hw - tw, step):
            s = 0
            for dx, dy, v in pts:
                s += abs(hp[x + dx, y + dy] - v)
            if s < best:
                best, bx, by = s, x, y
    # refine around the coarse hit at step 1 with a denser grid
    pts2 = _samples(tpl, min(10, max(6, n + 2)))
    cnt2 = len(pts2)
    best2, rx, ry = 10 ** 9, bx, by
    for y in range(max(0, by - step), min(hh - th, by + step + 1)):
        for x in range(max(0, bx - step), min(hw - tw, bx + step + 1)):
            s = 0
            for dx, dy, v in pts2:
                s += abs(hp[x + dx, y + dy] - v)
            if s < best2:
                best2, rx, ry = s, x, y
    return best2 / cnt2, rx, ry


def find_face(splash, icon):
    """(fx, fy) normalized face center inside a splash, by locating the champ's square
    ICON inside it. None if no confident match (caller falls back to a fixed bias)."""
    try:
        hay = splash.convert("L")
        hw, hh = hay.size
        scale = 256.0 / hw
        hay = hay.resize((256, max(1, int(hh * scale))))
        ic = icon.convert("L")
        best = None                                # (score, cx, cy)
        for s in (18, 24, 30, 38, 48):
            tpl = ic.resize((s, s))
            score, x, y = match_template(hay, tpl, step=3, n=6)
            if best is None or score < best[0]:
                best = (score, x + s / 2.0, y + s / 2.0)
        if best and best[0] < 34:                  # confident enough to trust
            return (best[1] / 256.0, best[2] / hay.size[1])
    except Exception:
        pass
    return None
