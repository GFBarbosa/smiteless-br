#!/usr/bin/env python3
"""smiteload.py - the LOADING-SCREEN matchup overlay.

While the game loads (you're staring at the loading screen anyway), this fills the screen
with a full ACCOUNT scoreboard: ten splash-art rows — riot id, rank + LP + season record,
last-10 form bars, KDA, mastery, this-champ record, an avg-performance grade pill, and the
profile-read tag pills (duo / smurf read / OTP / tilt / first-timer / autofill / …) that
lolload derives from each player's real match history. Unlike the death brief it CAN use
the center - there's no fight to watch yet. Fades out the moment the game actually starts.

Read-only off the local client + the user's own Riot key (loading exposes summonerIds the
LCU resolves to real riot ids, so the full scout works here).
"""
import sys, os, time, threading, ctypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass

import lolbuild as lb
import lolload as ll
import lolgame as lg
import smiteconfig as cfg
import smiteskin as skin
# reuse the death overlay's window plumbing + drawing helpers (one source of truth)
from smitedead import (_wfont, _dfont, _wrap, _card, _make_click_through, game_monitor,
                       CHROMA_HEX, C_TXT, C_MUTED, C_FAINT, C_EMBER, C_ARC, C_GOOD, C_BAD,
                       C_WARN, C_INFO, C_SURF)

import smitecard as sc                              # champion art loaders (get_icon / get_splash)
_user32 = ctypes.windll.user32
_DMG_C = {"AD": C_WARN, "AP": C_ARC, "mixed": C_MUTED}
C_MYSTIC = skin.rgb(skin.MYSTIC)
_TONE_C = {"good": C_GOOD, "bad": C_BAD, "neutral": C_MUTED, "info": C_MYSTIC}
C_VOID = skin.rgb(skin.VOID); C_RAISED = skin.rgb(skin.RAISED); C_SUNKEN = skin.rgb(skin.SUNKEN)
C_LINE = skin.rgb(skin.LINE); C_LINE_SOFT = skin.rgb(skin.LINE_SOFT)
_TIER_COL = {"iron": (150, 130, 120), "bronze": (176, 120, 84), "silver": (158, 170, 185),
             "gold": skin.rgb(skin.EMBER), "plat": (72, 200, 190), "platinum": (72, 200, 190),
             "emerald": (74, 200, 128), "diamond": (108, 168, 245), "master": (196, 112, 232),
             "gm": (232, 96, 96), "grandmaster": (232, 96, 96), "chall": (128, 205, 255),
             "challenger": (128, 205, 255)}


def _tier_color(rank):
    return _TIER_COL.get((rank or "").split()[0].lower(), C_MUTED) if rank else C_MUTED


def _cached_icon(dd, cid, size):
    """Champion square icon ONLY if already cached (memory/disk) — never downloads, so it can't
    block the render thread. The fetch worker warms the cache; misses just render a placeholder."""
    ck = (cid, size)
    if ck in sc._ICONS:
        return sc._ICONS[ck]
    key = dd.get("id2key", {}).get(cid)
    if not key:
        return None
    fp = os.path.join(sc.ICONCACHE, dd["ver"], key + ".png")
    if os.path.exists(fp):
        try:
            from PIL import Image
            im = Image.open(fp).convert("RGBA").resize((size, size))
            sc._ICONS[ck] = im
            return im
        except Exception:
            return None
    return None


def _geom(W, H):
    """Card-grid geometry for the loading board: five tall splash cards per team, two teams
    stacked (yours on top, theirs below). Returns a dict the renderer and the icon-warmer both
    read, so every splash banner is warmed at EXACTLY the size a card will crop it to (cache
    hit, never a stall on the render thread)."""
    s = max(0.70, min(1.75, H / 1080.0))
    def S(v): return int(v * s)
    cols = 5
    M = S(30)                                   # outer margin
    header_h, footer_h = S(50), S(58)
    col_gap, row_gap = S(14), S(16)
    grid_w = W - 2 * M
    card_w = (grid_w - (cols - 1) * col_gap) // cols
    avail_h = H - header_h - footer_h - 2 * M
    card_h = (avail_h - row_gap) // 2
    banner_h = int(card_h * 0.46)               # taller crop -> cinematic banner, not a thumbnail
    return {"s": s, "S": S, "cols": cols, "M": M, "header_h": header_h, "footer_h": footer_h,
            "col_gap": col_gap, "row_gap": row_gap, "card_w": card_w, "card_h": card_h,
            "banner_h": banner_h, "W": W, "H": H}


def _cached_splash(cid, size):
    """Face-cropped splash ONLY if already in smitecard's memory cache — never downloads,
    so the render thread can't stall. The fetch worker warms these."""
    return sc._SPLASH.get((cid, size))


def _grade_of(perf):
    """(letter, color) — same bands as the profile's game grades."""
    for lo, letter, col in ((115, "S+", C_ARC), (100, "S", C_ARC), (85, "A", C_ARC),
                            (70, "B", C_GOOD), (55, "C", C_MUTED)):
        if perf >= lo:
            return letter, col
    return "D", C_BAD


def _carry_score(r):
    """How likely this account is to decide the game on the champ they just locked: how they
    actually play (perf) sharpened by mastery on this pick, a live win streak, and comfort."""
    s = float(r.get("perf") or 50)
    if r.get("pts", 0) >= 250_000:
        s += 16                                  # true one-trick
    elif r.get("pts", 0) >= 100_000:
        s += 12
    form = r.get("form") or []
    if len(form) >= 3 and all(form[:3]):
        s += 8                                   # walking in hot
    if r.get("cg", 0) >= 5 and r.get("cw", 0) * 2 > r["cg"]:
        s += 6                                   # proven on this champ recently
    if (r.get("role") or "") in ("MID", "BOT", "TOP"):
        s += 4                                   # a damage seat converts a lead into a win
    return s


def _carry_call(allies):
    """WHO TO PLAY FOR on your own team — the header's one call. Enabling the teammate most
    likely to carry (or recognizing that it's YOU) is a decision you act on; a scary enemy
    name is only a warning. Returns (text, color) or None when nobody stands out."""
    best, bs = None, -1.0
    for r in allies or []:
        if not r.get("scouted"):
            continue
        s = _carry_score(r)
        if s > bs:
            bs, best = s, r
    if not best or bs < 74:
        return None
    ev = ""                                      # cite the evidence, same rule as the tags
    for txt, _tone in (best.get("tags") or []):
        if any(w in txt for w in ("OTP", "main", "carries", "heater", "comfort", "climbing")):
            ev = txt
            break
    if best.get("me"):
        return ("YOU'RE THE WIN CONDITION" + (f" — {ev}" if ev else " — play for your own tempo"),
                C_EMBER)
    nm = (best.get("player") or "").split("#")[0] or best.get("champ", "")
    return (f"PLAY FOR {best['champ'].upper()}" + (f" ({nm})" if nm else "")
            + (f" — {ev}" if ev else ""), C_GOOD)


def _rank_str(rk):
    if not rk or not rk.get("tier"):
        return "", None
    from lolload import _TIER
    t = _TIER.get(rk["tier"].upper(), rk["tier"].title())
    return f"{t} {rk.get('div', '')}".strip() + f" · {rk.get('lp', 0)} LP", t


_LANE_ORDER = ("TOP", "JG", "MID", "BOT", "SUP")


def _by_lane(rows):
    """The five cards in LANE order — TOP · JG · MID · BOT · SUP — so a column IS a lane and
    the ally card sits directly above the enemy it laned against. Riot's roster comes back in
    lobby order, which is why mid kept landing in a random column. Rows whose position the
    client didn't report (blind pick, autofill mid-swap) fill whatever slots are left, in
    their original order, so nobody is ever dropped from the board."""
    slots = {}
    spare = []
    for r in rows or []:
        k = (r.get("role") or "").upper()
        if k in _LANE_ORDER and k not in slots:
            slots[k] = r
        else:
            spare.append(r)
    out = []
    for k in _LANE_ORDER:
        if k in slots:
            out.append(slots[k])
        elif spare:
            out.append(spare.pop(0))
    return out + spare                      # anything left over (>5 rows) still renders


def _circle_icon(img, d, dd, cid, cx, cy, r, ring_col, S):
    """Champ portrait as a ringed circle, straddling the banner/body seam (the porofessor
    signature). Draws a filled disc first so a missing icon still reads as a portrait slot."""
    from PIL import Image, ImageDraw
    d.ellipse([cx - r - S(3), cy - r - S(3), cx + r + S(3), cy + r + S(3)], fill=C_VOID)
    ic = _cached_icon(dd, cid, r * 2)
    if ic:
        mask = Image.new("L", (r * 2, r * 2), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, r * 2, r * 2), fill=255)
        img.paste(ic, (cx - r, cy - r), mask)
    else:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=C_RAISED)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ring_col, width=max(2, S(2)))


def _dmg_split(dd, cid):
    """(ad_frac, ap_frac, label) — the champ's damage lean from Data Dragon's attack/magic
    info (0-10 each). Not a per-game stat; a stable profile read that's always available, so
    the bottom bar echoes the reference's damage strip without inventing precise numbers."""
    info = dd.get("id2info", {}).get(cid, {}) or {}
    atk, mag = float(info.get("attack", 0) or 0), float(info.get("magic", 0) or 0)
    tot = atk + mag
    if tot <= 0:
        return 0.5, 0.5, "MIXED"
    adf = atk / tot
    label = "AD" if adf >= 0.62 else ("AP" if adf <= 0.38 else "MIXED")
    return adf, 1 - adf, label


def _pill(d, x, y, txt, col, maxx, S, primary=False):
    """One tag chip. The first tag is the sharpest read -> filled; the rest sit quiet."""
    f = _wfont(S(11), True)
    txt = txt if len(txt) <= 30 else txt[:29] + "…"
    w = int(d.textlength(txt, font=f))
    if x + w + S(13) > maxx:
        return None
    if primary:
        d.rounded_rectangle([x, y, x + w + S(12), y + S(20)], S(9),
                            fill=tuple(int(c * 0.26) for c in col))
        d.text((x + S(6), y + S(3)), txt, font=f, fill=col)
    else:
        d.rounded_rectangle([x, y, x + w + S(12), y + S(20)], S(9), fill=C_SUNKEN,
                            outline=tuple(int(c * 0.42) for c in col), width=1)
        d.text((x + S(6), y + S(3)), txt, font=f, fill=tuple(int(c * 0.85) for c in col))
    return x + w + S(12) + S(5)


def _player_card(img, d, dd, r, x, y, cw, ch, g, side_col, scouted):
    """One player: a tall splash card in the profile's visual language — splash banner with
    champ + summoner name, a ringed portrait on the seam, rank badge, mastery, the recent-form
    read (win% · games · KDA + last-10 bars), the profile tag pills, and a damage-lean bar."""
    from PIL import Image, ImageDraw
    S = g["S"]
    banner_h = g["banner_h"]
    rad = S(12)
    is_me = bool(r.get("me"))
    cid = r.get("cid", 0)

    d.rounded_rectangle([x, y, x + cw, y + ch], rad, fill=C_SURF)

    # ---- splash banner ----
    # The art is a BANNER, not a pasted thumbnail: it fills the card's shoulders and then
    # dissolves into the body on every open edge (a long vertical ramp plus a soft vignette
    # down each side), so there's no hard rectangle boundary anywhere. The dissolve is
    # clipped by the card's own rounded silhouette so the corners stay round.
    from PIL import ImageChops
    shape = Image.new("L", (cw, banner_h), 0)            # the card's top silhouette
    sd = ImageDraw.Draw(shape)
    sd.rounded_rectangle((0, 0, cw - 1, banner_h - 1), radius=rad, fill=255)
    sd.rectangle((0, banner_h // 2, cw, banner_h), fill=255)
    art = _cached_splash(cid, (cw, banner_h))
    if art:
        img.paste(art, (x, y), shape)
        fade_h = max(2, int(banner_h * 0.72))            # long ramp: art -> card body
        vg = Image.new("L", (1, banner_h), 0)
        vg.putdata([0] * (banner_h - fade_h)
                   + [int((i / max(1, fade_h - 1)) ** 1.45 * 255) for i in range(fade_h)])
        veil = vg.resize((cw, banner_h))
        edge = max(3, int(cw * 0.11))                    # soft side vignette
        hg = Image.new("L", (cw, 1), 0)
        hg.putdata([int((1 - min(px, cw - 1 - px) / edge) ** 1.7 * 165)
                    if min(px, cw - 1 - px) < edge else 0 for px in range(cw)])
        veil = ImageChops.lighter(veil, hg.resize((cw, banner_h)))
        veil = ImageChops.darker(veil, shape)            # never bleed past the rounded edge
        img.paste(Image.new("RGB", (cw, banner_h), C_SURF), (x, y), veil)
    else:
        img.paste(Image.new("RGB", (cw, banner_h), C_RAISED), (x, y), shape)

    # side identity: a thin colored cap along the top edge
    d.rounded_rectangle([x + rad, y, x + cw - rad, y + S(4)], S(2), fill=side_col)

    # rank badge, top-right on the banner
    rk = r.get("rank_full")
    if rk and rk.get("tier"):
        rs, rcol = sc.rank_str(rk)
        rf = _dfont(S(13))
        rw = int(d.textlength(rs, font=rf))
        bx1 = x + cw - S(9)
        d.rounded_rectangle([bx1 - rw - S(12), y + S(9), bx1, y + S(9) + S(21)], S(6),
                            fill=tuple(int(c * 0.30) for c in rcol),
                            outline=tuple(int(c * 0.55) for c in rcol), width=1)
        d.text((bx1 - S(6), y + S(11)), rs, font=rf, fill=rcol, anchor="ra")

    # champ name, lifted clear of the portrait with a dark shadow so it reads over the splash
    cxc = x + cw // 2
    champ = (r.get("champ") or "?")
    nf = _dfont(S(19))
    d.text((cxc + S(1), y + banner_h - S(53) + S(1)), champ.upper(), font=nf, fill=C_VOID, anchor="mm")
    d.text((cxc, y + banner_h - S(53)), champ.upper(), font=nf,
           fill=(C_EMBER if is_me else C_TXT), anchor="mm")

    # ---- portrait on the seam ----
    pr = S(28)
    ring = C_EMBER if is_me else side_col
    _circle_icon(img, d, dd, cid, cxc, y + banner_h, pr, ring, S)

    # mastery pip on the portrait corner (a main/OTP earns the ember)
    pts = r.get("pts", 0)
    if pts:
        mcol = C_EMBER if pts >= 100_000 else C_MUTED
        mtxt = f"{pts // 1000}k"
        mf = _wfont(S(9), True)
        mw = int(d.textlength(mtxt, font=mf))
        mbx = cxc + pr - S(2)
        d.rounded_rectangle([mbx - mw - S(7), y + banner_h + pr - S(14),
                             mbx + S(1), y + banner_h + pr], S(7),
                            fill=C_VOID, outline=tuple(int(c * 0.6) for c in mcol), width=1)
        d.text((mbx - S(3), y + banner_h + pr - S(13)), mtxt, font=mf, fill=mcol, anchor="ra")

    cy = y + banner_h + pr + S(10)

    # ---- summoner name + role ----
    player = r.get("player") or ""
    nm = player.split("#")[0] if player else ("scouting…" if not scouted else "account hidden")
    d.text((cxc, cy), nm[:18], font=_wfont(S(13), True),
           fill=(C_TXT if player else C_FAINT), anchor="mm")
    meta = " · ".join(p for p in (r.get("role"), r.get("dmg")) if p)
    d.text((cxc, cy + S(17)), meta, font=_wfont(S(10)),
           fill=_DMG_C.get(r.get("dmg"), C_MUTED), anchor="mm")
    cy += S(34)

    # ---- recent form read: win% · games · KDA ----
    n, w = r.get("n", 0), r.get("w", 0)
    ix = x + S(13)
    if n:
        wr = round(w / n * 100)
        wcol = sc._wr_color(wr)
        d.text((ix, cy), f"{wr}%", font=_dfont(S(22)), fill=wcol)
        d.text((ix, cy + S(25)), f"{w}W {n - w}L · {n}g", font=_wfont(S(10)), fill=C_MUTED)
        if r.get("kdar") is not None:
            d.text((x + cw - S(13), cy + S(2)), f"{r['kdar']}", font=_dfont(S(20)),
                   fill=C_TXT, anchor="ra")
            d.text((x + cw - S(13), cy + S(24)), "KDA", font=_wfont(S(9), True),
                   fill=C_FAINT, anchor="ra")
            if r.get("kavg"):
                d.text((x + cw - S(40), cy + S(24)), r["kavg"], font=_wfont(S(9)),
                       fill=C_MUTED, anchor="ra")
        # last-10 form bars, centered under the numbers
        form = r.get("form") or []
        if form:
            bw, bg = S(11), S(3)
            tot = len(form[:10]) * (bw + bg) - bg
            bx = cxc - tot // 2
            for wn in reversed(form[:10]):
                d.rounded_rectangle([bx, cy + S(44), bx + bw, cy + S(50)], S(2),
                                    fill=(C_GOOD if wn else C_BAD))
                bx += bw + bg
        cy += S(58)
        # this-champ record
        if r.get("cg"):
            cwn = r["cw"]
            col = C_GOOD if cwn * 2 >= r["cg"] else C_BAD
            d.text((cxc, cy), f"{cwn}-{r['cg'] - cwn} on {champ}", font=_wfont(S(10), True),
                   fill=col, anchor="mm")
        elif scouted:
            d.text((cxc, cy), "champ not in recents", font=_wfont(S(9)), fill=C_FAINT, anchor="mm")
        cy += S(16)
    else:
        d.text((cxc, cy + S(6)), ("reading account…" if not scouted else "no recent ranked"),
               font=_wfont(S(11)), fill=C_FAINT, anchor="mm")
        cy += S(30)

    # ---- tag pills (up to 3 wrapping rows) ----
    tags = list(r.get("tags") or [])
    if not tags and r.get("phrases"):
        tags = [(p, "neutral") for p in r["phrases"][:3]]
    txmax = x + cw - S(10)
    dmg_bar_y = y + ch - S(26)
    ti = 0
    ry = cy
    while ry + S(20) <= dmg_bar_y - S(6) and ti < len(tags):
        px = x + S(10)
        placed = False
        while ti < len(tags):
            txt, tone = tags[ti]
            nx = _pill(d, px, ry, txt, _TONE_C.get(tone, C_MUTED), txmax, S, primary=(ti == 0))
            if nx is None:
                break
            px, placed = nx, True
            ti += 1
        if not placed:                                   # a pill too wide for a whole row
            ti += 1
        ry += S(25)

    # ---- damage-lean bar, pinned to the card bottom ----
    adf, apf, label = _dmg_split(dd, cid)
    bx0, bx1 = x + S(12), x + cw - S(12)
    bw = bx1 - bx0
    by = dmg_bar_y
    d.rounded_rectangle([bx0, by, bx1, by + S(14)], S(5), fill=C_SUNKEN)
    split = bx0 + int(bw * adf)
    if adf > 0.02:
        d.rounded_rectangle([bx0, by, max(bx0 + S(5), split), by + S(14)], S(5), fill=_dim(C_WARN, 0.75))
    if apf > 0.02:
        d.rounded_rectangle([min(bx1 - S(5), split), by, bx1, by + S(14)], S(5), fill=_dim(C_ARC, 0.75))
    d.text((bx0 + S(6), by + S(1)), f"{round(adf * 100)}% AD", font=_wfont(S(9), True), fill=C_VOID)
    d.text((bx1 - S(6), by + S(1)), f"{round(apf * 100)}% AP", font=_wfont(S(9), True),
           fill=C_VOID, anchor="ra")

    if is_me:                                        # find yourself instantly: an ember frame
        d.rounded_rectangle([x, y, x + cw, y + ch], rad, outline=C_EMBER, width=max(2, S(2)))


def _dim(c, f):
    return tuple(max(0, min(255, int(x * f))) for x in c)


def render_frame(dd, b, W, H):
    """The loading board: two teams of five tall splash cards (yours on top, theirs below) in
    the porofessor idiom — big face-cropped splash, ringed portrait, rank badge, mastery, the
    recent-form read (win% · games · KDA + last-10 bars), the profile tag pills, and a damage-
    lean bar — over a slim game-plan footer. Built to be read at a glance while the game loads."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (W, H), C_VOID)
    d = ImageDraw.Draw(img)
    g = _geom(W, H)
    S = g["S"]
    allies, enemies = _by_lane(b.get("allies")), _by_lane(b.get("enemies"))
    scouted = bool(b.get("scouted"))
    M, cols, cw, ch = g["M"], g["cols"], g["card_w"], g["card_h"]
    col_gap, row_gap = g["col_gap"], g["row_gap"]
    grid_w = cols * cw + (cols - 1) * col_gap
    gx0 = (W - grid_w) // 2

    # ---------- header ----------
    hy = g["M"]
    try:
        d.text((gx0, hy + S(2)), "✦", font=ImageFont.truetype("seguisym.ttf", S(18)), fill=C_EMBER)
    except Exception:
        pass
    d.text((gx0 + S(28), hy), "SMITELESS", font=_dfont(S(22)), fill=C_EMBER)
    d.text((gx0 + S(178), hy + S(5)), "LOADING SCOUT", font=_dfont(S(15)), fill=C_MUTED)
    call = _carry_call(allies) if scouted else None
    if call:
        sub, scol = call
    else:
        sub, scol = ("reading the ten accounts…" if not scouted
                     else "who they are, before minute one"), C_FAINT
    sf = _wfont(S(13), True)
    d.text((gx0 + grid_w, hy + S(4)), sub, font=sf, fill=scol, anchor="ra")

    # ---------- team labels + card rows ----------
    row_y = [hy + g["header_h"], hy + g["header_h"] + ch + row_gap]
    for row_i, (team, title, tcol, side_col) in enumerate((
            (allies, "YOUR TEAM", C_GOOD, C_GOOD), (enemies, "ENEMY TEAM", C_BAD, C_BAD))):
        ly = row_y[row_i]
        d.text((gx0, ly - S(18)), title, font=_wfont(S(12), True), fill=tcol)
        if row_i == 1 and scouted:
            note = "tags read from each account's real history"
            d.text((gx0 + grid_w, ly - S(17)), note, font=_wfont(S(10)), fill=C_FAINT, anchor="ra")
        for i, r in enumerate(team[:cols]):
            cx = gx0 + i * (cw + col_gap)
            _player_card(img, d, dd, r, cx, ly, cw, ch, g, side_col, scouted)

    # ---------- footer: game plan + win/lose ----------
    plan = b.get("plan") or []
    wc = b.get("wincons") or {}
    fy = row_y[1] + ch + S(12)
    fh = g["footer_h"] - S(2)
    if plan or wc:
        d.rounded_rectangle([gx0, fy, gx0 + grid_w, fy + fh], S(10), fill=C_SURF)
        d.rounded_rectangle([gx0, fy + S(6), gx0 + S(4), fy + fh - S(6)], S(2), fill=C_EMBER)
        px = gx0 + S(18)
        d.text((px, fy + S(9)), "GAME PLAN", font=_wfont(S(11), True), fill=C_EMBER)
        if plan:
            d.text((px + S(96), fy + S(9)), "→ " + plan[0], font=_wfont(S(12)), fill=C_TXT)
            if len(plan) > 1:
                d.text((px + S(96), fy + S(29)), "→ " + plan[1], font=_wfont(S(11)), fill=C_MUTED)
        if wc:
            wf = _wfont(S(11), True)
            wx = gx0 + grid_w - S(18)
            lose_t = wc.get("lose", "")
            win_t = wc.get("win", "")
            d.text((wx, fy + S(9)), win_t, font=_wfont(S(11)), fill=C_TXT, anchor="ra")
            d.text((wx - int(d.textlength(win_t, font=_wfont(S(11)))) - S(8), fy + S(9)),
                   "WIN", font=wf, fill=C_GOOD, anchor="ra")
            d.text((wx, fy + S(29)), lose_t, font=_wfont(S(11)), fill=C_MUTED, anchor="ra")
            d.text((wx - int(d.textlength(lose_t, font=_wfont(S(11)))) - S(8), fy + S(29)),
                   "LOSE", font=wf, fill=C_BAD, anchor="ra")
    return img


def _single_instance():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW(None, False, "Global\\SmitelessLoad")
    return ctypes.get_last_error() != 183


_LOG = os.path.expanduser("~/.claude/smiteless_load.log")


def _log(msg):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _game_time():
    """Live game clock (seconds) from :2999, or -1 if it's not serving. IMPORTANT: :2999 starts
    answering with gameTime~0 while you're STILL on the loading screen, so 'is it serving' is the
    wrong exit signal (it closed the overlay mid-load). The clock only advances once the game has
    actually started — so gameTime > ~1 is the real 'past the loading screen' signal."""
    try:
        d = lb.http("https://127.0.0.1:2999/liveclientdata/gamestats", timeout=1, insecure=True)
        return float(d.get("gameTime", 0.0)) if isinstance(d, dict) else 0.0
    except Exception:
        return -1.0


def _gameflow_phase():
    """RAW LCU gameflow phase (unlike phasecheck, which reports InProgress the moment :2999
    answers — useless for telling loading apart from the live game)."""
    lc = lg._lcu()
    if not lc:
        return ""
    port, hdr = lc
    try:
        r = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/gameflow-phase",
                    headers=hdr, timeout=3, insecure=True)
        return r if isinstance(r, str) else ""
    except Exception:
        return ""


def main():
    if not _single_instance():
        return
    # LOADING SCOUT: reborn as the ten-splash-card board (render_frame). The launcher spawns this
    # at champ select; it covers the load and fades the instant the game starts. Gated on a FRESH
    # key (`loading_scout`, default ON) — the retired native overlay's `loading_overlay:false`
    # lingers in old settings files and must NOT suppress the rebuilt board. Untick "Loading-screen
    # scout" in Settings to turn it off.
    if not cfg.load().get("loading_scout", True):
        return
    import tkinter as tk
    from PIL import ImageTk
    from smitedead import toplevel_hwnd

    dd = lb.ddragon()
    l, t, r, b = game_monitor()
    W, H = r - l, b - t
    try:
        open(_LOG, "w").close()                     # fresh log per launch
    except Exception:
        pass
    _log(f"LAUNCH monitor=({l},{t},{r},{b}) size={W}x{H} loading_scout={cfg.load().get('loading_scout', True)}")
    root = tk.Tk()
    cfg.watch_tray(root)                        # close with the tray (no orphan loading brief)
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=CHROMA_HEX)
    root.attributes("-transparentcolor", CHROMA_HEX)
    root.geometry(f"{W}x{H}+{l}+{t}")
    label = tk.Label(root, bd=0, bg=CHROMA_HEX)
    label.pack(fill="both", expand=True)
    root.update_idletasks()
    _make_click_through(toplevel_hwnd(root.winfo_id()))

    state = {"run": True, "brief": None, "shown": False, "want": False, "fetching": False,
             "deadline": time.monotonic() + 1200}         # spawned at champ select: cover it + load

    def _done(why):
        _log(f"EXIT {why}")
        state["run"] = False
        try:
            root.after(0, root.destroy)
        except Exception:
            pass

    def _warm_icons(bf):
        # icons (disk) + face-cropped splash banners at EXACTLY the card size the renderer
        # asks smitecard's memory cache for — a warmed card is a pure cache hit.
        gg = _geom(W, H)
        banner = (gg["card_w"], gg["banner_h"])
        for r in (bf.get("allies") or []) + (bf.get("enemies") or []):
            try:
                sc.get_icon(dd, r.get("cid", 0), 96)         # downloads the disk file (any size)
                sc.get_splash(dd, r.get("cid", 0), banner)
            except Exception:
                pass

    def _fetch():
        # ALL network work lives here, OFF the poll/render loop, so the overlay is never blocked.
        # Phase 1: champs + tags + plan (fast, no Riot API) -> the overlay appears immediately.
        # Phase 2: warm champion portraits, then force a redraw so the art pops in.
        # Phase 3: per-player rank/OTP scout (slow, rate-limited) -> fills in when ready.
        try:
            fast = ll.brief(dd, scout=False)
            if fast:
                state["brief"] = fast
                _log("fast brief READY (champs/tags/plan) -> showing")
                _warm_icons(fast)
                if state["run"]:
                    state["brief"] = dict(fast)              # new object -> tick re-renders w/ art
                    _log("icons warmed -> redraw")
        except Exception as e:
            _log(f"fast brief ERROR {type(e).__name__}: {e}")
        try:
            full = ll.brief_shared(dd)          # ONE scout per lobby, shared with the web board
            if full and state["run"]:
                state["brief"] = full
                _log("scout brief READY (ranks/tags) -> enriched")
        except Exception as e:
            _log(f"scout brief ERROR {type(e).__name__}: {e}")

    def poll():
        n = errs = 0
        seen_load = False
        while state["run"]:
            gt = _game_time()                              # >1 = game running; ~0 = still loading; -1 = down
            gf = _gameflow_phase()
            errs = (errs + 1) if gf == "" else 0           # "" = LCU hiccup; only real after a streak
            started = gt > 1.0                             # the game clock is running -> past the load screen
            # LOADING = game process up (GameStart/InProgress/Reconnect) AND not started yet.
            loading = (gf in ("GameStart", "InProgress", "Reconnect")) and not started
            if loading:
                seen_load = True
            n += 1
            if n <= 4 or loading or n % 12 == 0:
                _log(f"poll gf={gf!r} gt={gt:.1f} started={started} loading={loading} want={state['want']} shown={state['shown']} fetching={state['fetching']}")
            if started:                                    # game actually began -> we're done
                _done(f"game started (gt={gt:.1f})")
                return
            if loading:
                state["want"] = True
                if not state["fetching"]:                  # kick the fetch ONCE, on a worker thread
                    state["fetching"] = True
                    threading.Thread(target=_fetch, daemon=True).start()
            elif seen_load and (errs >= 4 or gf in ("None", "Lobby", "Matchmaking", "ReadyCheck",
                                                    "WaitingForStats", "PreEndOfGame", "EndOfGame")):
                _done(f"left after load (gf={gf!r})")       # dodge/crash after we'd been loading
                return
            elif not seen_load and gf in ("None", "Lobby", "Matchmaking", "EndOfGame") and errs == 0:
                _done(f"no game (gf={gf!r})")               # dropped back to lobby before ever loading
                return
            else:
                state["want"] = False                      # ChampSelect -> armed and waiting
            if time.monotonic() > state["deadline"]:
                _done("deadline")
                return
            time.sleep(0.5)

    threading.Thread(target=poll, daemon=True).start()

    state["rendered"] = None
    def tick():
        if not state["run"]:
            return
        b = state["brief"]
        if state["want"] and b:
            if b is not state["rendered"]:              # (re)draw on first show AND on any upgrade
                frame = render_frame(dd, b, W, H)
                ph = ImageTk.PhotoImage(frame)
                label.configure(image=ph)
                label.image = ph
                state["rendered"] = b
            if not state["shown"]:                      # show/hide is driven by want, INDEPENDENT
                root.deiconify()                        # of render — so a blip can't wedge it hidden
                _make_click_through(toplevel_hwnd(root.winfo_id()))
                state["shown"] = True
                _log("overlay SHOWN")
        elif state["shown"] and not state["want"]:
            root.withdraw()
            state["shown"] = False
        root.after(250, tick)

    root.withdraw()
    root.after(200, tick)
    root.mainloop()
    state["run"] = False


if __name__ == "__main__":
    main()
