#!/usr/bin/env python3
"""smitecard.py - renders the Smiteless overlay as a scoreboard-style PNG.

One image: build/runes header, both teams aligned by role (matchups paired by the
REAL champ in each slot), a data-only gank rating per enemy lane, and a last-10 W/L
form bar per player. Renders progressively (build + lanes first, scout fills in).

Usage:
  python smitecard.py --out card.png [--fm done.flag] [--count 10]
"""
import sys, os, io, time, urllib.request
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lolbuild as lb
import lolgame as lg
import lolcoach as lc
import lolscout as ls

# ---- theme ----
BG = (17, 19, 26); TEXT = (232, 230, 223); MUTED = (155, 152, 142); GOLD = (200, 170, 110)
BLUE = (45, 108, 181); RED = (181, 64, 74)
ALLY_BG = (22, 29, 42); ENEMY_BG = (40, 24, 28)
GREEN = (95, 196, 122); REDWR = (224, 100, 108); TAN = (203, 196, 150)
WSQ = (86, 184, 112); LSQ = (201, 85, 96)
GANK = {"GANK": ((34, 74, 47), (122, 214, 146)),
        "EVEN": ((58, 52, 24), (214, 185, 74)),
        "TOUGH": ((78, 36, 41), (228, 130, 130))}
ROLES = [("top", "top"), ("jungle", "jg"), ("mid", "mid"), ("adc", "adc"), ("support", "sup")]
LANE_MACRO = {
    "top": "Lane: freeze when ahead, shove + TP/roam with prio.   After: splitpush a side lane, draw pressure, TP to fights.",
    "mid": "Lane: crash then roam/recall on prio; don't roam on a wave pushing to you.   After: roam for picks, set up objectives.",
    "adc": "Lane: farm safe, trade on cooldowns, ward for ganks.   After: take objectives, position back-line, scale to carry.",
    "support": "Lane: enable your ADC, ward river, track the enemy jungler.   After: roam for vision + picks, peel or engage by your kit.",
}

# Champion archetype from Riot's tags, with a small override where tags mislead
# (e.g. Yasuo is tagged Fighter/Assassin but plays as a skirmisher).
ARCH_OVERRIDE = {
    "Yasuo": "skirmisher", "Yone": "skirmisher", "Sylas": "skirmisher", "Akshan": "skirmisher",
    "Katarina": "assassin", "Akali": "assassin", "Fizz": "assassin", "Diana": "assassin",
    "Ekko": "assassin", "Qiyana": "assassin", "Pyke": "assassin",
    "Kassadin": "scaling", "Vladimir": "scaling", "Kayle": "scaling", "Veigar": "scaling",
    "Cassiopeia": "scaling", "AurelionSol": "scaling", "Azir": "scaling", "Ryze": "scaling",
    "Smolder": "scaling", "Nasus": "scaling",
}
ARCHETYPE_MACRO = {
    "mage": "Lane: shove for prio + poke, respect all-ins (you're squishy).   After: group, zone with range from the back, win the 5v5.",
    "assassin": "Lane: shove and roam for picks, get a lead before they scale.   After: hunt isolated carries/supports - don't 5v5 front-to-back.",
    "skirmisher": "Lane: shove for tempo, look for side-lane 1v1s.   After: take a side lane, flank fights, fight around a knockup/engage.",
    "scaling": "Lane: farm safe, survive your weak early.   After: hit your spikes then take over - group, zone, force objectives.",
    "marksman": "Lane: farm safe, trade on cooldowns, respect ganks.   After: stay back-line, take objectives, scale to carry the 5v5.",
    "bruiser": "Lane: trade with your sustain/durability, manage the wave.   After: front-line or splitpush a side lane, draw pressure.",
    "tank": "Lane: soak XP, set up your jungler's ganks, scale.   After: front-line, start fights with your CC, peel the carry.",
}
VS_NOTE = {
    "assassin": "vs an assassin: respect the lvl-6 all-in, ward your flanks.",
    "mage": "vs a mage: dodge poke, trade when their key spell is down.",
    "skirmisher": "vs a skirmisher: avoid extended 1v1s, play for picks/collapse.",
    "scaling": "vs a scaling pick: punish early - shove, roam, deny farm.",
    "marksman": "vs a marksman: all-in early before they get items online.",
    "bruiser": "vs a bruiser: kite, don't extended-trade into their sustain.",
    "tank": "vs a tank: they out-sustain - play for objectives/roams, not the 1v1.",
    "enchanter": "vs an enchanter: dive the carry they peel, or burst through them.",
}


def archetype(dd, cid):
    if not cid:
        return ""
    if dd.get("id2key", {}).get(cid, "") in ARCH_OVERRIDE:
        return ARCH_OVERRIDE[dd["id2key"][cid]]
    tags = dd.get("id2tags", {}).get(cid, [])
    for t, a in (("Assassin", "assassin"), ("Marksman", "marksman"), ("Mage", "mage"),
                 ("Support", "enchanter"), ("Tank", "tank"), ("Fighter", "bruiser")):
        if t in tags:
            return a
    return ""
W = 920; ROWH = 66; TOP = 96
ICONCACHE = os.path.expanduser("~/.claude/cache/icons")
_FONTS = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _FONTS:
        fp = r"C:\Windows\Fonts\seguisb.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"
        try:
            _FONTS[key] = ImageFont.truetype(fp, size)
        except Exception:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def get_icon(dd, cid, size):
    key = dd.get("id2key", {}).get(cid)
    if not key:
        return None
    d = os.path.join(ICONCACHE, dd["ver"])
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, key + ".png")
    if not os.path.exists(fp):
        url = f"https://ddragon.leagueoflegends.com/cdn/{dd['ver']}/img/champion/{key}.png"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": lb.UA})
            open(fp, "wb").write(urllib.request.urlopen(req, timeout=8).read())
        except Exception:
            return None
    try:
        return Image.open(fp).convert("RGBA").resize((size, size))
    except Exception:
        return None


def build_data(dd, cid, role):
    try:
        d = lb.opgg(cid, role or "jungle")
    except Exception:
        return None
    if not d or "summary" not in d:
        return None
    av = d["summary"]["average_stats"]
    rp = max(d["runes"], key=lambda r: r["play"])
    core = max(d["core_items"], key=lambda x: x["play"])
    ss = max(d["summoner_spells"], key=lambda x: x["play"])
    return dict(keystone=dd["runes"].get(rp["primary_rune_ids"][0], ""),
                core=[dd["items"].get(i, "") for i in core["ids"]],
                summs=[dd["spells"].get(i, "") for i in ss["ids"]],
                wr=av["win_rate"] * 100,
                tier={1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}.get(av.get("tier"), ""))


# Gank score = transparent weighted sum, all terms in win-rate points (no AI).
# Starts as pure lane matchup (loads first); the form/champ terms kick in when the
# enemy's last-10 scout arrives, so a tilted/off-role enemy gets more gankable.
GANK_W_LANE = 1.0      # your laner's matchup edge vs 50%
GANK_W_FORM = 0.5      # enemy laner's last-10 account WR vs 50% (10-loss streak = +25)
GANK_W_CHAMP = 0.3     # enemy's WR ON the champ they're playing vs 50%
GANK_OFFCHAMP = 5.0    # flat bonus when the enemy is off their champ (no recent games on it)
GANK_T = 6.0           # |score| threshold for GANK / TOUGH; between = EVEN


def gank_score(ally_wr, e_n, e_w, e_cg, e_cw):
    s = 0.0
    if ally_wr is not None:
        s += GANK_W_LANE * (ally_wr - 50.0)
    if e_n:  # enemy form is known (scout has loaded for them)
        s += GANK_W_FORM * (50.0 - e_w / e_n * 100.0)
        if e_cg >= 3:
            s += GANK_W_CHAMP * (50.0 - e_cw / e_cg * 100.0)
        elif e_cg == 0:
            s += GANK_OFFCHAMP
    return s


def gank_label(score):
    return "GANK" if score >= GANK_T else ("TOUGH" if score <= -GANK_T else "EVEN")


def _wr_color(wr):
    return GREEN if wr >= 55 else (REDWR if wr <= 42 else TAN)


def draw_form(d, x, y, form):
    sq, gap = 7, 2
    for i, win in enumerate(form[:10]):
        cx = x + i * (sq + gap)
        d.rectangle([cx, y, cx + sq, y + sq], fill=WSQ if win else LSQ)


def draw_player(d, img, dd, x, y, cid, sc, is_me, side, accent, accent_bg, live=True):
    if not cid:
        return
    name = dd["id2name"].get(cid, "?")
    icon = get_icon(dd, cid, 38)
    cw = 372
    if side == "L":
        d.rectangle([x, y + 9, x + cw, y + ROWH - 5], fill=accent_bg)
        d.rectangle([x, y + 9, x + 3, y + ROWH - 5], fill=accent)
        ix = x + 11
        if icon:
            img.paste(icon, (ix, y + 13), icon)
        tx = ix + 46
        d.text((tx, y + 13), name + ("  YOU" if is_me else ""), font=font(14, 1), fill=GOLD if is_me else TEXT)
        _wr_line(d, tx, y + 35, sc, "la", live)
        if sc and sc.get("form"):
            draw_form(d, x + cw - 88, y + 38, sc["form"])
    else:
        d.rectangle([x - cw, y + 9, x, y + ROWH - 5], fill=accent_bg)
        d.rectangle([x - 3, y + 9, x, y + ROWH - 5], fill=accent)
        ix = x - 11 - 38
        if icon:
            img.paste(icon, (ix, y + 13), icon)
        tx = ix - 8
        d.text((tx, y + 13), name, font=font(14, 1), fill=TEXT, anchor="ra")
        _wr_line(d, tx, y + 35, sc, "ra", live)
        if sc and sc.get("form"):
            draw_form(d, x - cw + 6, y + 38, sc["form"])


def _wr_line(d, x, y, sc, anchor, live=True):
    if sc is None:
        if live:
            d.text((x, y), "scouting...", font=font(11), fill=MUTED, anchor=anchor)
        return
    n, w, cg, cw = sc["n"], sc["w"], sc["cg"], sc["cw"]
    if n:
        wr = w / n * 100
        t = f"L10 {w}-{n - w} {wr:.0f}%"
        col = _wr_color(wr)
    else:
        t, col = "no recent ranked", MUTED
    t += f"  ·  {cw}/{cg} on" if cg else "  ·  off-champ"
    d.text((x, y), t, font=font(11), fill=col, anchor=anchor)


def draw_badge(d, cx, y, rating):
    bg, fg = GANK[rating]
    label = {"GANK": "gank", "EVEN": "even", "TOUGH": "tough"}[rating]
    f = font(11, 1)
    half = d.textlength(label, font=f) / 2 + 8
    d.rounded_rectangle([cx - half, y, cx + half, y + 17], radius=8, fill=bg)
    d.text((cx, y + 8), label, font=f, fill=fg, anchor="mm")


def draw_lane_panel(d, img, dd, x, y, w, my_cid, my_role, opp_cid, my_wr, opp_sc):
    PH = 100
    d.rectangle([x, y, x + w, y + PH], fill=(26, 28, 38))
    d.rectangle([x, y, x + 3, y + PH], fill=GOLD)
    myn = dd["id2name"].get(my_cid, "?")
    arch = archetype(dd, my_cid)
    d.text((x + 14, y + 8), "YOUR LANE" + (f"   ·   {arch}" if arch else ""), font=font(11, 1), fill=GOLD)
    if opp_cid:
        oppn = dd["id2name"].get(opp_cid, "?")
        head = f"{myn} vs {oppn}"
        d.text((x + 14, y + 25), head, font=font(15, 1), fill=TEXT)
        hx = x + 14 + d.textlength(head, font=font(15, 1)) + 12
        if my_wr is not None:
            d.text((hx, y + 27), f"{my_wr:.0f}%", font=font(14, 1), fill=_wr_color(my_wr))
        else:
            d.text((hx, y + 28), "no op.gg sample", font=font(12), fill=MUTED)
        if opp_sc and opp_sc["n"]:
            ofw = opp_sc["w"] / opp_sc["n"] * 100
            ct = (f"{opp_sc['cw']}/{opp_sc['cg']} on {oppn}" if opp_sc["cg"] else "off-champ")
            d.text((x + 14, y + 46),
                   f"{oppn} last 10: {opp_sc['w']}-{opp_sc['n'] - opp_sc['w']} ({ofw:.0f}%)   ·   {ct}",
                   font=font(11), fill=MUTED)
    else:
        d.text((x + 14, y + 26), f"{myn} — lane opponent fills in once the match starts", font=font(12), fill=MUTED)
    macro = (LANE_MACRO["support"] if my_role == "support"
             else (ARCHETYPE_MACRO.get(arch) or LANE_MACRO.get(my_role)))
    if macro:
        d.text((x + 14, y + 64), macro, font=font(11), fill=(168, 184, 206))
    vs = VS_NOTE.get(archetype(dd, opp_cid)) if opp_cid else None
    if vs:
        d.text((x + 14, y + 82), vs, font=font(11), fill=(205, 175, 120))


def render(path, dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map, source, note="", roles_known=True, live=True):
    panel = bool(roles_known and my_role and my_role != "jungle" and my_role in dict(ROLES))
    H = TOP + 5 * ROWH + 46 + (116 if panel else 0)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # header
    ic = get_icon(dd, my_cid, 48)
    if ic:
        img.paste(ic, (16, 9), ic)
    d.text((74, 12), f"{dd['id2name'].get(my_cid, '?')}   {(my_role or '?').upper()}", font=font(18, 1), fill=GOLD)
    if build:
        bl = f"{build['keystone']}   ·   " + " > ".join(x for x in build['core'] if x) + "   ·   " + " / ".join(build['summs'])
        d.text((74, 40), bl[:104], font=font(12), fill=MUTED)
        d.text((W - 16, 13), f"{build['wr']:.1f}%  {build['tier']}", font=font(15, 1), fill=TEXT, anchor="ra")
    d.text((W - 16, 40), "SMITELESS  ·  " + source, font=font(11), fill=(110, 108, 100), anchor="ra")
    d.line([16, 66, W - 16, 66], fill=(40, 42, 50), width=1)
    d.text((26, 74), "YOUR TEAM", font=font(11, 1), fill=(125, 166, 216))
    d.text((W - 26, 74), "ENEMY", font=font(11, 1), fill=(216, 130, 130), anchor="ra")
    cxc = W // 2
    for i, (role, lbl) in enumerate(ROLES):
        y = TOP + i * ROWH
        a_cid, e_cid = ally_role.get(role), enemy_role.get(role)
        draw_player(d, img, dd, 16, y, a_cid, scout_map.get((a_cid, True)), a_cid == my_cid, "L", BLUE, ALLY_BG, live)
        draw_player(d, img, dd, W - 16, y, e_cid, scout_map.get((e_cid, False)), False, "R", RED, ENEMY_BG, live)
        if roles_known:
            d.text((cxc, y + 11), lbl, font=font(10), fill=(120, 118, 110), anchor="ma")
            if role == my_role or not e_cid:
                d.text((cxc, y + 28), "vs", font=font(10), fill=(100, 98, 92), anchor="ma")
            else:
                es = scout_map.get((e_cid, False))
                a = (es["n"], es["w"], es["cg"], es["cw"]) if es else (0, 0, 0, 0)
                draw_badge(d, cxc, y + 25, gank_label(gank_score(lanes.get(role), *a)))
    ly = TOP + 5 * ROWH + 12
    if panel:
        opp = enemy_role.get(my_role)
        draw_lane_panel(d, img, dd, 16, ly, W - 32, my_cid, my_role, opp,
                        lanes.get(my_role), scout_map.get((opp, False)) if opp else None)
        ly += 108
    d.text((16, ly), "gank = your lane wins + enemy struggling   |   green/red = last-10 W/L   |   N/M on = win rate on this champ",
           font=font(11), fill=(120, 118, 110))
    if note:
        d.text((16, ly + 18), note, font=font(11), fill=(200, 150, 90))
    tmp = path + ".tmp"
    img.save(tmp, format="PNG")
    os.replace(tmp, path)


def _info_card(path, msg):
    img = Image.new("RGB", (W, 140), BG)
    d = ImageDraw.Draw(img)
    d.text((20, 20), "SMITELESS", font=font(18, 1), fill=GOLD)
    d.text((20, 58), msg, font=font(13), fill=TEXT)
    tmp = path + ".tmp"; img.save(tmp, format="PNG"); os.replace(tmp, path)


def _takeflag(argv, name, default=None):
    if name in argv:
        i = argv.index(name); v = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]; return v
    return default


def main():
    argv = sys.argv[1:]
    wait = "--wait" in argv          # auto-open: don't draw anything until champs are present
    if wait:
        argv.remove("--wait")
    outp = _takeflag(argv, "--out") or os.path.expanduser("~/.claude/cache/smitecard.png")
    fm = _takeflag(argv, "--fm")
    try:
        count = int(_takeflag(argv, "--count", "10"))
    except Exception:
        count = 10
    dd = lb.ddragon()
    deadline = time.time() + 420          # keep trying up to 7 min for the match to come up
    build = None
    try:
        while time.time() < deadline:
            info, err = lg.resolve(dd)
            if err:                        # not in champ select / a game yet
                if not wait:               # manual press shows status; auto-open stays hidden
                    _info_card(outp, err)
                time.sleep(3)
                continue
            my_cid, my_role = info["my"], info["pos"]
            allies, enemies = info["allies"], info["enemies"]
            ally_role = {r: c for c, r in allies if r and c}
            enemy_role = {r: c for c, r in enemies if r and c}
            if build is None and my_cid:
                build = build_data(dd, my_cid, my_role)
            src = info.get("source", "")
            if not enemy_role:             # champ select / loading: roles + scout not live yet
                champs_ready = bool(allies) and bool(enemies)
                if wait and not champs_ready:
                    time.sleep(3)          # auto-open: hold the window until the champs are there
                    continue
                # show the champs we have (loading screen has no roles yet -> positional)
                ar = ally_role or {ROLES[i][0]: c for i, (c, _r) in enumerate(allies[:5]) if c}
                er = {ROLES[i][0]: c for i, (c, _r) in enumerate(enemies[:5]) if c}
                render(outp, dd, my_cid, my_role, ar, er, build, {}, {}, src,
                       "roles + live player scout load once the match starts...",
                       roles_known=False, live=False)
                time.sleep(4)
                continue
            # in-game: full board, then progressive player scout
            lanes = {r: wr for a, r, e, wr, g in lc.gather_lane_matchups(dd, allies, enemies)}
            scout_map = {}
            render(outp, dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map, src, "")
            for r in ls.iter_scout_struct(dd, count):
                if "error" in r:
                    render(outp, dd, my_cid, my_role, ally_role, enemy_role, build, lanes,
                           scout_map, src, r["error"])
                    break
                scout_map[(r["cid"], r["is_ally"])] = r
                render(outp, dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map, src, "")
            break
    finally:
        if fm:
            try:
                open(fm, "w").close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
