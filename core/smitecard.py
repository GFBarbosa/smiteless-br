#!/usr/bin/env python3
"""smitecard.py - renders the Smiteless overlay as a scoreboard-style PNG.

One image: build/runes header, both teams aligned by role (matchups paired by the
REAL champ in each slot), a data-only gank rating per enemy lane, and a last-10 W/L
form bar per player. Renders progressively (build + lanes first, scout fills in).

Usage:
  python smitecard.py --out card.png [--fm done.flag] [--count 10]
"""
import sys, os, time, threading, urllib.request, urllib.parse
from PIL import Image, ImageDraw, ImageFont

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import lolgame as lg
import lolscout as ls
import lolmatchup as lm
import lolprofile as lp
import phasecheck
import smiteconfig as cfg

# Phases where the overlay's session is still alive. Anything else (Lobby, None, EndOfGame…)
# means the champ select was dodged/left or the game is over -> the overlay should close so a
# fresh one opens for the next game (avoids showing a stale board from the prior session).
ACTIVE_PHASES = ("ChampSelect", "GameStart", "InProgress", "Reconnect")

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
_ICONS = {}   # (cid, size) -> resized RGBA Image; avoids re-reading/resizing every repaint


def font(size, bold=False):
    key = (size, bold)
    if key not in _FONTS:
        fp = r"C:\Windows\Fonts\seguisb.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"
        try:
            _FONTS[key] = ImageFont.truetype(fp, size)
        except Exception:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def name_font(size, text):
    """Bold Segoe UI for Latin names; a CJK-capable font for names with CJK chars (so a
    Chinese/Japanese/Korean summoner name renders instead of tofu boxes)."""
    if all(ord(ch) < 0x2E00 for ch in text):
        return font(size, True)
    key = ("cjk", size)
    if key not in _FONTS:
        for fp in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
                   r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\YuGothB.ttc"):
            try:
                _FONTS[key] = ImageFont.truetype(fp, size)
                break
            except Exception:
                continue
        else:
            _FONTS[key] = font(size, True)
    return _FONTS[key]


def get_icon(dd, cid, size):
    ck = (cid, size)
    if ck in _ICONS:
        return _ICONS[ck]
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
            data = urllib.request.urlopen(req, timeout=8).read()
            tmp = f"{fp}.{os.getpid()}.tmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, fp)                       # atomic: never a half-written icon
        except Exception:
            return None
    try:
        im = Image.open(fp).convert("RGBA").resize((size, size))
        _ICONS[ck] = im
        return im
    except Exception:
        try:
            os.remove(fp)                             # corrupt cached icon -> re-download next time
        except Exception:
            pass
        return None


def build_data(dd, cid, role):
    """op.gg build/runes for a champ+role, or None on any missing/odd data (never crashes)."""
    try:
        d = lb.opgg(cid, role or "jungle")
        if not d or "summary" not in d or not d.get("runes"):
            return None
        av = d["summary"]["average_stats"]
        rp = max(d["runes"], key=lambda r: r["play"])
        core = max(d["core_items"], key=lambda x: x["play"])
        ss = max(d["summoner_spells"], key=lambda x: x["play"])
        shard = {5008: "Adaptive", 5005: "AtkSpd", 5007: "Haste", 5011: "Health",
                 5001: "HP-scale", 5010: "MoveSpd", 5013: "Tenacity"}
        pr = rp.get("primary_rune_ids", [])
        sr = rp.get("secondary_rune_ids", [])
        sm = max(d["skill_masteries"], key=lambda x: x["play"]) if d.get("skill_masteries") else None
        return dict(keystone=dd["runes"].get(pr[0], "") if pr else "",
                    primary=[dd["runes"].get(i, "") for i in pr],
                    secondary=[dd["runes"].get(i, "") for i in sr],
                    primary_tree=dd["trees"].get(rp.get("primary_page_id"), ""),
                    secondary_tree=dd["trees"].get(rp.get("secondary_page_id"), ""),
                    primary_ids=pr,
                    secondary_ids=sr,
                    primary_page_id=rp.get("primary_page_id"),
                    secondary_page_id=rp.get("secondary_page_id"),
                    stat_mod_ids=rp.get("stat_mod_ids", []),
                    shards=[shard.get(i, "") for i in rp.get("stat_mod_ids", [])],
                    core=[dd["items"].get(i, "") for i in core["ids"]],
                    summoner_ids=ss["ids"],
                    summs=[dd["spells"].get(i, "") for i in ss["ids"]],
                    skills=(sm["ids"] if sm else []),
                    wr=av.get("win_rate", 0) * 100,
                    tier={1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}.get(av.get("tier"), ""))
    except Exception:
        return None


# Gank score = transparent weighted math (no AI). The champ-vs-champ matchup is the
# BASE (dominant); the enemy laner's recent form is ~a 30% modifier that COMPOUNDS
# with the length of their win/loss streak; and an extreme (near-0%/100% winrate or
# a long streak) OVERRIDES the matchup entirely - amazing/avoid no matter what.
GANK_W_LANE = 1.0       # champ-vs-champ matchup edge vs 50% (the base; e.g. 55% -> +5)
GANK_W_FORM = 0.15      # enemy recent-form weight before streak compounding (~30% influence)
GANK_W_CHAMP = 0.10     # enemy's winrate ON the champ they're playing vs 50%
GANK_OFFCHAMP = 4.0     # enemy is off their champ (no recent games on it)
GANK_STREAK_COMP = 0.18 # each game in a streak BEYOND 2 amplifies the form term (compounding)
GANK_EXTREME = 16.0     # near-total streak/winrate decides regardless of matchup
GANK_T = 6.0            # |score| threshold for GANK / TOUGH; between = EVEN

# YOUR champ's gank/roam potential (added to every lane's score): hard reliable CC + engage
# makes any lane gankable; no CC means you need the enemy to be already losing. Keyed by
# Data Dragon champ key. Curated by kit (jungle + common mid roamers); default = neutral.
GANK_KIT = {
    # +6 elite lockdown / unmissable CC engage
    "Maokai": 6, "Nautilus": 6, "Sejuani": 6, "Amumu": 6, "Zac": 6, "Rammus": 6,
    "Skarner": 6, "Warwick": 6, "Volibear": 6, "Nunu": 6, "Leona": 6, "Galio": 6,
    "Lissandra": 6, "Annie": 6, "Malphite": 6, "Ornn": 6,
    # +4 strong engage / reliable CC
    "JarvanIV": 5, "Vi": 5, "Nocturne": 5, "RekSai": 5, "Elise": 5, "Trundle": 5,
    "Poppy": 5, "Evelynn": 5, "Pantheon": 5, "Sett": 5, "Hecarim": 4, "XinZhao": 4,
    "MonkeyKing": 4, "Gragas": 4, "Camille": 4, "Diana": 4, "Jax": 4, "Viego": 4,
    "Lillia": 4, "Fiddlesticks": 4, "Rengar": 4, "TwistedFate": 4, "Neeko": 4,
    "Veigar": 4, "Morgana": 4, "LeeSin": 4, "Udyr": 4, "Shaco": 4,
    # +2 gap-close / skillshot or single-target CC
    "Graves": 2, "KhaZix": 3, "Kayn": 3, "Ekko": 3, "Belveth": 2, "Taliyah": 3,
    "Kindred": 2, "Zed": 3, "Talon": 3, "Qiyana": 4, "Briar": 4, "Naafiri": 3,
    "Ahri": 3, "Sylas": 3, "Vex": 4, "Zoe": 3, "Akali": 2, "Fizz": 3, "Lux": 3,
    "Yone": 2, "Katarina": 2, "Gwen": 2,
    # 0/-1 little reliable CC -> weak ganks
    "Nidalee": -1, "Karthus": -1, "MasterYi": 0, "Shyvana": 0, "Teemo": 0,
    "Cassiopeia": 1, "Yasuo": 1,
}
GANK_KIT_DEFAULT = 1    # neutral (some CC / standard)


def gank_kit(dd, my_cid):
    """Your champ's flat gank/roam bonus (CC + engage). 0 if unknown champ."""
    if not my_cid:
        return 0.0
    return float(GANK_KIT.get(dd.get("id2key", {}).get(my_cid, ""), GANK_KIT_DEFAULT))


DUO_COLORS = [(232, 190, 90), (110, 205, 140), (150, 165, 235), (224, 130, 205), (110, 210, 210)]
DUO_SHARED = 3          # shared recent ranked games to call two teammates a duo


def detect_duos(scout_map):
    """{(cid, is_ally): duo_index} for players who share >= DUO_SHARED recent ranked games
    with a teammate (very likely a premade). Same index = same duo group."""
    out, nxt = {}, [0]
    for team in (True, False):
        players = [(k, set(sc.get("mids") or [])) for k, sc in scout_map.items()
                   if k[1] is team and sc.get("mids")]
        for i in range(len(players)):
            for j in range(i + 1, len(players)):
                if len(players[i][1] & players[j][1]) >= DUO_SHARED:
                    ki, kj = players[i][0], players[j][0]
                    idx = out.get(ki, out.get(kj))
                    if idx is None:
                        idx = nxt[0]
                        nxt[0] += 1
                    out[ki] = out[kj] = idx
    return out


def _duo_marker(d, cx, y, idx, side):
    col = DUO_COLORS[idx % len(DUO_COLORS)]
    d.ellipse([cx - 5, y - 5, cx + 5, y + 5], fill=col)
    if side == "L":
        d.text((cx + 9, y), "duo", font=font(10, 1), fill=col, anchor="lm")
    else:
        d.text((cx - 9, y), "duo", font=font(10, 1), fill=col, anchor="rm")


def apply_settings():
    """Pull the user's tuning (smitesettings.py) into the gank weights. The single
    'streak influence' dial scales the form weight, streak compounding, and the extreme
    override together (50 = the defaults above). Called each render so changes apply live."""
    global GANK_W_FORM, GANK_STREAK_COMP, GANK_EXTREME, GANK_W_CHAMP, GANK_OFFCHAMP, GANK_T
    global GANK_KIT_ON, DUO_ON
    s = cfg.load()
    m = s["streak_influence"] / 50.0          # 0..2, default 1.0; scales all "enemy state" terms
    GANK_W_FORM = 0.15 * m
    GANK_STREAK_COMP = 0.18 * m
    GANK_W_CHAMP = 0.10 * m
    GANK_OFFCHAMP = 4.0 * m
    GANK_EXTREME = min(32.0, 16.0 * m)        # at m=0 -> 0: pure champ matchup, ignore how they're doing
    GANK_T = float(s["gank_threshold"])
    GANK_KIT_ON = s.get("gank_kit", True)     # feature toggles
    DUO_ON = s.get("duo_detection", True)
    return s


GANK_KIT_ON = True
DUO_ON = True


def _streak(form):
    """Signed consecutive results from the MOST RECENT game: +k win streak, -k loss streak."""
    if not form:
        return 0
    first, k = form[0], 0
    for w in form:
        if w == first:
            k += 1
        else:
            break
    return k if first else -k


def gank_score(ally_wr, e_n, e_w, e_cg, e_cw, e_form=None, self_kit=0.0):
    s = float(self_kit)                                   # YOUR champ's CC/engage (gank/roam kit)
    if ally_wr is not None:
        s += GANK_W_LANE * (ally_wr - 50.0)               # BASE: champ vs champ
    if e_n:  # enemy scout loaded
        f = e_w / e_n * 100.0                              # enemy recent winrate %
        k = _streak(e_form or [])                          # signed streak (compounding)
        comp = 1.0 + GANK_STREAK_COMP * max(0, abs(k) - 2)
        s += GANK_W_FORM * (50.0 - f) * comp               # losing/loss-streak -> easier gank
        if e_n >= 8:                                        # extreme OVERRIDES the matchup
            if f <= 15.0 or k <= -7:
                s += GANK_EXTREME                           # tilted/inting -> amazing no matter what
            elif f >= 85.0 or k >= 7:
                s -= GANK_EXTREME                           # smurfing/heater -> avoid no matter what
        if e_cg >= 3:
            s += GANK_W_CHAMP * (50.0 - e_cw / e_cg * 100.0)
        elif e_cg == 0:
            s += GANK_OFFCHAMP
    return s


def gank_label(score):
    return "GANK" if score >= GANK_T else ("TOUGH" if score <= -GANK_T else "EVEN")


def _wr_color(wr):
    return GREEN if wr >= 55 else (REDWR if wr <= 42 else TAN)


TIER_ABBR = {"IRON": "I", "BRONZE": "B", "SILVER": "S", "GOLD": "G", "PLATINUM": "P",
             "EMERALD": "E", "DIAMOND": "D", "MASTER": "M", "GRANDMASTER": "GM", "CHALLENGER": "C"}
_DIVNUM = {"I": "1", "II": "2", "III": "3", "IV": "4"}
TIER_COLOR = {"IRON": (124, 114, 104), "BRONZE": (160, 114, 80), "SILVER": (156, 166, 176),
              "GOLD": (210, 170, 90), "PLATINUM": (76, 184, 176), "EMERALD": (72, 192, 120),
              "DIAMOND": (120, 166, 232), "MASTER": (186, 114, 206), "GRANDMASTER": (222, 96, 96),
              "CHALLENGER": (232, 202, 124)}


def rank_str(r):
    """('D2 45LP', tier-color) for a rank dict; ('Unranked', muted) if none."""
    if not r or not r.get("tier"):
        return "Unranked", MUTED
    t = r["tier"].upper()
    col = TIER_COLOR.get(t, TAN)
    ab = TIER_ABBR.get(t, t[:1])
    if t in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return f"{ab} {r.get('lp', 0)}LP", col
    return f"{ab}{_DIVNUM.get(r.get('div', ''), '')} {r.get('lp', 0)}LP", col


GRADE_COLOR = {"S+": (236, 206, 128), "S": (236, 206, 128), "A": (95, 200, 126),
               "B": (120, 166, 232), "C": (214, 156, 92), "D": (206, 86, 94)}
PCARD = (25, 28, 38); PCARD2 = (31, 35, 47); PEDGE = (46, 50, 64)
LABEL_COL = {"hard carry": (236, 206, 128), "carried": (95, 200, 126),
             "carried, team lost": (120, 166, 232), "rough one": (206, 86, 94),
             "could've done better": (214, 156, 92)}


def _dim(c, f):
    return tuple(max(0, min(255, int(x * f))) for x in c)


def _rrect(d, box, r, fill=None, outline=None, width=1):
    try:
        d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)
    except Exception:
        d.rectangle(box, fill=fill, outline=outline)


def _profile_headline(p):
    """One friendly line about how you've been doing."""
    best = p["champs"][0] if p["champs"] else None
    if p["n"] < 3:
        return "Play a few ranked games and your form, scores and best champs show up here."
    if p["wr"] >= 60:
        tail = f"  {best['champ']} is your best at {best['wr']}%." if best and best["g"] >= 2 else ""
        return f"You're on a {p['wr']}% run over your last {p['n']} — keep riding it.{tail}"
    if p["wr"] <= 40:
        tail = f"  Lean on {best['champ']} ({best['wr']}%)." if best and best["wr"] >= 55 else ""
        return f"Rough stretch ({p['wr']}% of {p['n']}). Tighten up — avg game score {p['avg_score']}/100.{tail}"
    if p["avg_score"] >= 62:
        return f"You've been playing well (avg score {p['avg_score']}/100) — the wins will follow."
    return f"{p['wr']}% over your last {p['n']}. Avg game score {p['avg_score']}/100; the score grades each game vs the whole lobby."


DETAIL_H = 170          # height of an expanded game's 10-player breakdown


def _draw_match_detail(d, img, dd, parts, my_puuid, x0, y0, w):
    """The 10-player breakdown for an expanded game (KDA + damage bars, both teams)."""
    _rrect(d, (x0, y0, x0 + w, y0 + DETAIL_H), 9, fill=(19, 22, 30), outline=PEDGE, width=1)
    me = next((pl for pl in parts if pl["puuid"] == my_puuid), None)
    myteam = me["team"] if me else 100
    maxd = max((pl["dmg"] for pl in parts), default=1) or 1
    pad, colw = 16, (w - 48) // 2
    teams = [[pl for pl in parts if pl["team"] == myteam],
             [pl for pl in parts if pl["team"] != myteam]]
    for ci, team in enumerate(teams):
        cx = x0 + pad + ci * (colw + 16)
        d.text((cx, y0 + 9), "YOUR TEAM" if ci == 0 else "ENEMY", font=font(10, 1),
               fill=(125, 166, 216) if ci == 0 else (216, 130, 130))
        ry = y0 + 30
        for pl in team[:5]:
            cid = dd["name2id"].get(dd["norm"](pl["champ"]))
            ic = get_icon(dd, cid, 22)
            if ic:
                img.paste(ic, (cx, ry), ic)
            mine = pl["puuid"] == my_puuid
            d.text((cx + 28, ry + 3), f"{pl['k']}/{pl['d']}/{pl['a']}",
                   font=font(11, 1 if mine else 0), fill=GOLD if mine else TEXT)
            bx, bw = cx + 96, colw - 138
            _rrect(d, (bx, ry + 7, bx + bw, ry + 13), 3, fill=(40, 44, 56))
            _rrect(d, (bx, ry + 7, bx + max(2, int(bw * pl["dmg"] / maxd)), ry + 13), 3, fill=(214, 130, 96))
            d.text((cx + colw - 4, ry + 2), f"{pl['dmg'] // 1000}k", font=font(10), fill=MUTED, anchor="ra")
            ry += 26


def render_profile(dd, p, expanded=None, details=None):
    """The home page: rank, recent form, champ win rates, and per-game scores graded vs the
    lobby. Carded; games in `expanded` (indices) show the 10-player breakdown from `details`
    (mid -> parts). Sets img.hit_games = [(y0, y1, index)] for click-to-expand."""
    expanded = expanded or set()
    details = details or {}
    games = p.get("games", [])
    HEAD, CHAMPS = 132, 96
    games_top = HEAD + CHAMPS + 34
    H = games_top + 16
    for i in range(len(games)):
        H += 50 + (DETAIL_H + 8 if i in expanded else 0)
    H = max(H, games_top + 60)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ---- header card ----
    _rrect(d, (14, 12, W - 14, 122), 14, fill=PCARD, outline=PEDGE, width=1)
    name = p.get("riot_id", "?").split("#")[0]
    d.text((30, 22), name, font=name_font(25, name), fill=TEXT)
    rs, rc = rank_str(p.get("rank"))
    d.text((30, 58), rs, font=font(14, 1), fill=rc)
    # win bar + record
    bx, by, bw2 = 30, 82, 230
    _rrect(d, (bx, by, bx + bw2, by + 8), 4, fill=(46, 50, 64))
    if p["wr"] > 0:
        _rrect(d, (bx, by, bx + int(bw2 * min(1.0, p["wr"] / 100.0)), by + 8), 4,
               fill=GREEN if p["wr"] >= 50 else REDWR)
    d.text((bx + bw2 + 14, by - 4), f"{p['wins']}W {p['losses']}L  ·  {p['wr']}%  ·  last {p['n']}",
           font=font(12, 1), fill=TEXT)
    # rank badge (top-right) + avg score
    sc_col = GRADE_COLOR["A"] if p["avg_score"] >= 58 else (REDWR if p["avg_score"] < 45 else TAN)
    d.text((W - 30, 30), str(p["avg_score"]), font=font(34, 1), fill=sc_col, anchor="ra")
    d.text((W - 30, 74), "AVG GAME SCORE", font=font(9, 1), fill=MUTED, anchor="ra")
    # headline
    for ln in _wrap(_profile_headline(p), font(12), W - 60)[:1]:
        d.text((30, 98), ln, font=font(12), fill=TAN)

    # ---- top champions ----
    cy = HEAD + 6
    d.text((20, cy), "TOP CHAMPIONS", font=font(11, 1), fill=GOLD)
    nch = max(1, min(6, len(p.get("champs", [])) or 1))
    cw = min(150, (W - 28) // nch)
    x = 14
    for c in p.get("champs", [])[:6]:
        cid = dd["name2id"].get(dd["norm"](c["champ"]))
        _rrect(d, (x, cy + 18, x + cw - 8, cy + 66), 10, fill=PCARD, outline=PEDGE, width=1)
        ic = get_icon(dd, cid, 36)
        if ic:
            img.paste(ic, (x + 10, cy + 24), ic)
        d.text((x + 54, cy + 24), dd["id2name"].get(cid, c["champ"])[:8], font=font(12, 1), fill=TEXT)
        wcol = GREEN if c["wr"] >= 55 else (REDWR if c["wr"] < 45 else TAN)
        d.text((x + 54, cy + 44), f"{c['wr']}%", font=font(13, 1), fill=wcol)
        d.text((x + 92, cy + 46), f"{c['g']}g", font=font(10), fill=MUTED)
        x += cw

    # ---- recent games ----
    d.text((20, games_top - 22), "RECENT GAMES", font=font(11, 1), fill=GOLD)
    d.text((W - 20, games_top - 21), "click a game to expand  ·  score = graded vs all 10",
           font=font(10), fill=(118, 116, 108), anchor="ra")
    hit_games, yy = [], games_top
    for i, g in enumerate(games):
        acc = GREEN if g["win"] else REDWR
        _rrect(d, (14, yy, W - 14, yy + 44), 9, fill=_dim(acc, 0.9))
        _rrect(d, (21, yy, W - 14, yy + 44), 9, fill=PCARD2)
        cid = dd["name2id"].get(dd["norm"](g["champ"]))
        ic = get_icon(dd, cid, 32)
        if ic:
            img.paste(ic, (30, yy + 6), ic)
        d.text((70, yy + 13), "W" if g["win"] else "L", font=font(15, 1), fill=acc)
        d.text((92, yy + 6), dd["id2name"].get(cid, g["champ"])[:12], font=font(13, 1), fill=TEXT)
        d.text((92, yy + 25), f"{g['k']}/{g['d']}/{g['a']}", font=font(11), fill=MUTED)
        gc = GRADE_COLOR.get(g["letter"], TAN)
        _rrect(d, (300, yy + 9, 362, yy + 35), 7, fill=_dim(gc, 0.20), outline=_dim(gc, 0.5), width=1)
        d.text((312, yy + 14), g["letter"], font=font(14, 1), fill=gc)
        d.text((340, yy + 16), str(g["score"]), font=font(12, 1), fill=gc)
        d.text((384, yy + 16), f"#{g['rank']}/10", font=font(11), fill=MUTED)
        d.text((456, yy + 15), g["label"], font=font(12, 1), fill=LABEL_COL.get(g["label"], MUTED))
        d.text((W - 26, yy + 15), "▾" if i in expanded else "▸", font=font(13), fill=MUTED, anchor="ra")
        hit_games.append((yy, yy + 44, i))
        yy += 50
        if i in expanded:
            parts = (details.get(g.get("mid")) or {}).get("parts")
            if parts:
                _draw_match_detail(d, img, dd, parts, p.get("puuid"), 14, yy, W - 28)
            else:
                _rrect(d, (14, yy, W - 14, yy + DETAIL_H), 9, fill=(19, 22, 30), outline=PEDGE, width=1)
                d.text((W // 2, yy + DETAIL_H // 2), "loading game detail…", font=font(11),
                       fill=MUTED, anchor="mm")
            yy += DETAIL_H + 8
    # append an in-image "Load more" button (clickable area) so users can load older games
    btn_h = 36
    btn_y = yy + 8
    try:
        _rrect(d, (14, btn_y, W - 14, btn_y + btn_h), 9, fill=PCARD2, outline=PEDGE, width=1)
        d.text((W // 2, btn_y + btn_h // 2), "Load more", font=font(12, 1), fill=GOLD, anchor="mm")
        hit_games.append((btn_y, btn_y + btn_h, "__load_more__"))
    except Exception:
        # drawing shouldn't crash rendering; if it does, silently skip the button
        pass

    img.hit_games = hit_games
    img.hitmap = []
    img.profile_split_y = max(120, games_top - 30)   # top card stays fixed; games section scrolls
    return img


def _abbr_pts(p):
    if p >= 1_000_000:
        return f"{p / 1e6:.1f}M"
    if p >= 1000:
        return f"{p // 1000}k"
    return str(p)


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
    rtext, rcol = rank_str(sc.get("rank"))
    n, w, cg, cw = sc["n"], sc["w"], sc["cg"], sc["cw"]
    if n:
        wr = w / n * 100
        t = f"L10 {w}-{n - w} {wr:.0f}%"
        col = _wr_color(wr)
    else:
        t, col = "no recent", MUTED
    m = sc.get("mastery")                        # champ comfort: lifetime mastery > recent record
    if m and m.get("points"):
        t += f"  ·  M{m['level']} {_abbr_pts(m['points'])}"
    elif cg == 0:
        t += "  ·  off-champ"                     # no mastery + none recent = first-timing it
    else:
        t += f"  ·  {cw}/{cg} on"
    rf, ff = font(11, 1), font(11)               # rank (bold, tier-colored) then form (by WR)
    if anchor == "ra":                           # right rows: form ... rank, mirrored
        d.text((x, y), t, font=ff, fill=col, anchor="ra")
        d.text((x - d.textlength(t, font=ff) - 10, y), rtext, font=rf, fill=rcol, anchor="ra")
    else:
        d.text((x, y), rtext, font=rf, fill=rcol, anchor="la")
        d.text((x + d.textlength(rtext, font=rf) + 10, y), t, font=ff, fill=col, anchor="la")


def draw_badge(d, cx, y, rating):
    bg, fg = GANK[rating]
    label = {"GANK": "gank", "EVEN": "even", "TOUGH": "tough"}[rating]
    f = font(11, 1)
    half = d.textlength(label, font=f) / 2 + 8
    d.rounded_rectangle([cx - half, y, cx + half, y + 17], radius=8, fill=bg)
    d.text((cx, y + 8), label, font=f, fill=fg, anchor="mm")


def _wrap(text, fnt, max_w):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if fnt.getlength(t) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_lane_panel(d, img, dd, x, y, w, my_cid, my_role, opp_cid, my_wr, opp_sc, tip_lines, ph):
    d.rectangle([x, y, x + w, y + ph], fill=(26, 28, 38))
    d.rectangle([x, y, x + 3, y + ph], fill=GOLD)
    myn = dd["id2name"].get(my_cid, "?")
    arch = archetype(dd, my_cid)
    label = "YOUR LANE" + (f"   ·   {arch}" if arch else "") + ("   ·   live tip" if tip_lines else "")
    d.text((x + 14, y + 8), label, font=font(11, 1), fill=GOLD)
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
            orank = rank_str(opp_sc.get("rank"))[0]
            d.text((x + 14, y + 46),
                   f"{oppn} {orank}   ·   last 10: {opp_sc['w']}-{opp_sc['n'] - opp_sc['w']} ({ofw:.0f}%)   ·   {ct}",
                   font=font(11), fill=MUTED)
    else:
        d.text((x + 14, y + 26), f"{myn} — lane opponent fills in once the match starts", font=font(12), fill=MUTED)
    if tip_lines:
        ty = y + 65
        for ln in tip_lines:
            d.text((x + 14, ty), ln, font=font(12), fill=(216, 202, 168))
            ty += 18
    else:
        macro = (LANE_MACRO["support"] if my_role == "support"
                 else (ARCHETYPE_MACRO.get(arch) or LANE_MACRO.get(my_role)))
        if macro:
            d.text((x + 14, y + 64), macro, font=font(11), fill=(168, 184, 206))
        vs = VS_NOTE.get(archetype(dd, opp_cid)) if opp_cid else None
        if vs:
            d.text((x + 14, y + 82), vs, font=font(11), fill=(205, 175, 120))


def draw_build_block(d, dd, x, y, build):
    d.text((x, y), "RUNES", font=font(11, 1), fill=GOLD)
    d.text((x, y + 18), build.get("keystone", ""), font=font(14, 1), fill=TEXT)
    minor = "  ·  ".join(r for r in build.get("primary", [])[1:] if r)
    if minor:
        d.text((x, y + 40), minor, font=font(11), fill=MUTED)
    sec = [r for r in build.get("secondary", []) if r]
    if sec:
        d.text((x, y + 58), f"{build.get('secondary_tree', '')}:  " + "  ·  ".join(sec),
               font=font(11), fill=(150, 170, 200))
    shards = [s for s in build.get("shards", []) if s]
    if shards:
        d.text((x, y + 76), "Shards:  " + "  /  ".join(shards), font=font(11), fill=MUTED)
    d.text((x, y + 104), "BUILD", font=font(11, 1), fill=GOLD)
    d.text((x, y + 122), " > ".join(c for c in build.get("core", []) if c), font=font(12), fill=TEXT)
    d.text((x, y + 142), "Summoners:  " + " / ".join(build.get("summs", [])), font=font(11), fill=MUTED)
    skills = [s for s in build.get("skills", []) if s]
    if skills:
        d.text((x, y + 160), "Skill max:  " + " > ".join(skills), font=font(11), fill=MUTED)


def _profile_url(riot_id):
    """u.gg profile URL for a 'Name#TAG' riot id, or None. (u.gg plays nicer than op.gg
    behind Cloudflare WARP.) u.gg uses the platform code directly, e.g. na1."""
    if not riot_id or "#" not in riot_id:
        return None
    region = getattr(ls, "PLATFORM", "na1")
    name, tag = riot_id.rsplit("#", 1)
    return f"https://u.gg/lol/profile/{region}/{urllib.parse.quote(name)}-{urllib.parse.quote(tag)}/overview"


_PICK_CACHE = {}
_ROLE_FALLBACK = {
    "top": ("Garen", "Darius", "Renekton", "Ornn"),
    "jungle": ("Vi", "JarvanIV", "Sejuani", "Nocturne"),
    "mid": ("Ahri", "Orianna", "Syndra", "Vex"),
    "adc": ("Jinx", "Caitlyn", "KaiSa", "Ashe"),
    "support": ("Leona", "Nautilus", "Lulu", "Rell"),
}


def _ally_comp_bonus(dd, cid, ally_ids):
    """Small draft-fit bonus based on what your team currently lacks."""
    tags_by_id = dd.get("id2tags", {})
    ally_tags = [set(tags_by_id.get(i, [])) for i in ally_ids if i]
    have_tank = any("Tank" in t for t in ally_tags)
    have_ap = any("Mage" in t for t in ally_tags)
    have_ad = any(("Marksman" in t) or ("Assassin" in t) or ("Fighter" in t) for t in ally_tags)
    have_engage = any(("Tank" in t) or ("Fighter" in t) for t in ally_tags)
    ctags = set(tags_by_id.get(cid, []))
    b = 0.0
    if not have_tank and ("Tank" in ctags):
        b += 7.0
    if not have_ap and ("Mage" in ctags):
        b += 4.0
    if not have_ad and (("Marksman" in ctags) or ("Assassin" in ctags) or ("Fighter" in ctags)):
        b += 4.0
    if not have_engage and (("Tank" in ctags) or ("Fighter" in ctags)):
        b += 3.0
    return b


def suggest_champs(dd, role, ally_ids, enemy_ids, topn=4):
    """A few role-appropriate champ suggestions for champ select.
    Scored by enemy counters (op.gg) + ally comp fit (frontline/AP-AD/engage needs)."""
    role = lb.ROLE.get((role or "").lower(), (role or "").lower())
    if role not in _ROLE_FALLBACK:
        return []
    ally_ids = tuple(sorted(i for i in ally_ids if i))
    enemy_ids = tuple(sorted(i for i in enemy_ids if i))
    ck = (role, ally_ids, enemy_ids)
    if ck in _PICK_CACHE:
        return _PICK_CACHE[ck]
    banned = set(ally_ids) | set(enemy_ids)
    scores = {}
    # Enemy-adaptive score: champs that op.gg lists as strong into the locked enemy picks.
    for eid in enemy_ids:
        try:
            d = lb.opgg(eid, role)
        except Exception:
            continue
        for c in d.get("counters", []):
            cid = c.get("champion_id")
            play = c.get("play", 0) or 0
            if not cid or cid in banned or play < 40:
                continue
            enemy_wr = (c.get("win", 0) / play) * 100.0
            ctr_wr = max(0.0, min(100.0, 100.0 - enemy_wr))
            sc = scores.setdefault(cid, {"sum": 0.0, "n": 0, "play": 0, "comp": 0.0})
            sc["sum"] += ctr_wr
            sc["n"] += 1
            sc["play"] += play
    # Ally-adaptive score: prefer candidates that patch missing comp pieces.
    for cid, sc in list(scores.items()):
        sc["comp"] = _ally_comp_bonus(dd, cid, ally_ids)
    for nm in _ROLE_FALLBACK[role]:
        cid = dd["name2id"].get(dd["norm"](nm))
        if not cid or cid in banned:
            continue
        sc = scores.setdefault(cid, {"sum": 50.0, "n": 1, "play": 0, "comp": 0.0})
        sc["comp"] = max(sc.get("comp", 0.0), _ally_comp_bonus(dd, cid, ally_ids))
    picked = []
    if scores:
        ranked = sorted(scores.items(),
                        key=lambda kv: ((kv[1]["sum"] / max(1, kv[1]["n"])) + kv[1].get("comp", 0.0), kv[1]["play"]),
                        reverse=True)
        picked = [cid for cid, _ in ranked if cid not in banned][:topn]
    if len(picked) < topn:
        for nm in _ROLE_FALLBACK[role]:
            cid = dd["name2id"].get(dd["norm"](nm))
            if cid and cid not in banned and cid not in picked:
                picked.append(cid)
            if len(picked) >= topn:
                break
    _PICK_CACHE[ck] = picked
    return picked


def render_image(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map, source, note="", roles_known=True, live=True, lane_tip=None, champ_select=False, suggestions=None):
    panel = bool(roles_known and not champ_select and my_role and my_role != "jungle" and my_role in dict(ROLES))
    tip_lines = _wrap(lane_tip, font(12), (W - 32) - 28) if (panel and lane_tip) else []
    panel_h = (77 + len(tip_lines) * 18) if tip_lines else (108 if panel else 0)
    H = (TOP + 5 * ROWH + 12 + panel_h + 48) if panel else (TOP + 5 * ROWH + 46)
    rail_w = 96 if (champ_select and suggestions) else 0
    W2 = W + rail_w
    xoff = rail_w
    img = Image.new("RGB", (W2, H), BG)
    d = ImageDraw.Draw(img)
    hits = []                                    # clickable icon rects -> op.gg URL
    # header
    ic = get_icon(dd, my_cid, 48)
    if ic:
        img.paste(ic, (16 + xoff, 9), ic)
        msc = scout_map.get((my_cid, True))
        murl = _profile_url(msc.get("riot_id")) if msc else None
        if murl:
            hits.append((16 + xoff, 9, 64 + xoff, 57, murl))
    if my_cid:
        d.text((74 + xoff, 12), f"{dd['id2name'].get(my_cid, '?')}   {(my_role or '?').upper()}", font=font(18, 1), fill=GOLD)
    else:                                        # spectator / replay: no "you"
        d.text((16 + xoff, 12), "SPECTATING", font=font(18, 1), fill=GOLD)
        d.text((16 + xoff, 42), "both teams scouted — no personal build (replay/spectator mode)", font=font(11), fill=MUTED)
    if build:
        bl = f"{build['keystone']}   ·   " + " > ".join(x for x in build['core'] if x) + "   ·   " + " / ".join(build['summs'])
        d.text((74 + xoff, 40), bl[:104], font=font(12), fill=MUTED)
        d.text((W2 - 16, 13), f"{build['wr']:.1f}%  {build['tier']}", font=font(15, 1), fill=TEXT, anchor="ra")
    d.text((W2 - 16, 40), "SMITELESS  ·  " + source, font=font(11), fill=(110, 108, 100), anchor="ra")
    d.line([16 + xoff, 66, W2 - 16, 66], fill=(40, 42, 50), width=1)
    d.text((26 + xoff, 74), "YOUR TEAM", font=font(11, 1), fill=(125, 166, 216))
    if champ_select:
        d.text((W2 - 26, 74), "YOUR RUNES + BUILD", font=font(11, 1), fill=GOLD, anchor="ra")
    else:
        d.text((W2 - 26, 74), "ENEMY", font=font(11, 1), fill=(216, 130, 130), anchor="ra")
    cxc = W2 // 2
    my_kit = gank_kit(dd, my_cid) if GANK_KIT_ON else 0.0           # toggleable
    duo_of = detect_duos(scout_map) if (DUO_ON and roles_known and not champ_select) else {}
    if champ_select and build:
        draw_build_block(d, dd, cxc + 34, TOP + 6, build)
    for i, (role, lbl) in enumerate(ROLES):
        y = TOP + i * ROWH
        a_cid, e_cid = ally_role.get(role), enemy_role.get(role)
        draw_player(d, img, dd, 16 + xoff, y, a_cid, scout_map.get((a_cid, True)), a_cid == my_cid, "L", BLUE, ALLY_BG, live)
        draw_player(d, img, dd, W2 - 16, y, e_cid, scout_map.get((e_cid, False)), False, "R", RED, ENEMY_BG, live)
        asc, esc = scout_map.get((a_cid, True)), scout_map.get((e_cid, False))
        aurl = _profile_url(asc.get("riot_id")) if (a_cid and asc) else None
        eurl = _profile_url(esc.get("riot_id")) if (e_cid and esc) else None
        if aurl:
            hits.append((27 + xoff, y + 13, 65 + xoff, y + 51, aurl))     # ally icon (left)
        if eurl:
            hits.append((W2 - 65, y + 13, W2 - 27, y + 51, eurl))   # enemy icon (right)
        if a_cid and (a_cid, True) in duo_of:               # premade markers (shared color = same duo)
            _duo_marker(d, 350 + xoff, y + 18, duo_of[(a_cid, True)], "L")
        if e_cid and (e_cid, False) in duo_of:
            _duo_marker(d, W2 - 350, y + 18, duo_of[(e_cid, False)], "R")
        if roles_known and not champ_select:
            d.text((cxc, y + 11), lbl, font=font(10), fill=(120, 118, 110), anchor="ma")
            if role == my_role or not e_cid:
                d.text((cxc, y + 28), "vs", font=font(10), fill=(100, 98, 92), anchor="ma")
            else:
                es = scout_map.get((e_cid, False))
                a = (es["n"], es["w"], es["cg"], es["cw"], es.get("form")) if es else (0, 0, 0, 0, None)
                draw_badge(d, cxc, y + 25, gank_label(gank_score(lanes.get(role), *a, self_kit=my_kit)))
        elif champ_select:
            d.text((388, y + 24), lbl, font=font(10), fill=(120, 118, 110), anchor="la")
    if champ_select and suggestions:
        # Draw this AFTER the team rows so it can't be covered by row backgrounds.
        sx, sy = 6, TOP + 2
        _rrect(d, (sx, sy, sx + 82, sy + 312), 10, fill=(20, 24, 34), outline=PEDGE, width=1)
        d.text((sx + 41, sy + 12), "PICKS", font=font(10, 1), fill=GOLD, anchor="ma")
        yy = sy + 28
        for cid in suggestions[:4]:
            ic = get_icon(dd, cid, 34)
            if ic:
                img.paste(ic, (sx + 8, yy), ic)
            name = dd["id2name"].get(cid, "")[:8]
            d.text((sx + 49, yy + 7), name, font=font(10, 1), fill=TEXT)
            yy += 70
    ly = TOP + 5 * ROWH + 12
    if panel:
        opp = enemy_role.get(my_role)
        draw_lane_panel(d, img, dd, 16 + xoff, ly, W2 - xoff - 32, my_cid, my_role, opp,
                        lanes.get(my_role), scout_map.get((opp, False)) if opp else None,
                        tip_lines, panel_h)
        ly += panel_h + 14
    d.text((16 + xoff, ly), "rank · L10 W/L · mastery · ● duo = premade   |   gank = matchup + enemy form/streak + YOUR champ's kit   |   click → u.gg",
           font=font(11), fill=(120, 118, 110))
    if note:
        d.text((16 + xoff, ly + 18), note, font=font(11), fill=(200, 150, 90))
    img.hitmap = hits
    return img


def render(path, dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map, source,
           note="", roles_known=True, live=True, lane_tip=None, champ_select=False):
    """Render the board to a PIL Image and write it to a PNG (CLI / debug / fallback)."""
    img = render_image(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map,
                       source, note, roles_known, live, lane_tip, champ_select)
    _save_png(img, path)
    return img


def _save_png(img, path):
    tmp = path + ".tmp"
    img.save(tmp, format="PNG")
    os.replace(tmp, path)
    try:                                   # sidecar so the AHK overlay can resize to match
        open(path + ".dim", "w").write(str(img.height))
    except Exception:
        pass


def info_image(msg):
    """A small status/error card (no live game yet, key stale, etc.)."""
    img = Image.new("RGB", (W, 140), BG)
    d = ImageDraw.Draw(img)
    d.text((20, 20), "SMITELESS", font=font(18, 1), fill=GOLD)
    d.text((20, 58), msg, font=font(13), fill=TEXT)
    return img


def _info_card(path, msg):
    _save_png(info_image(msg), path)


def _takeflag(argv, name, default=None):
    if name in argv:
        i = argv.index(name); v = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]; return v
    return default


def run(emit, count=None, wait=False, stop=None, monitor=False):
    """Core loop: resolve the live game, render each frame, and hand the finished PIL
    Image to emit(img). Shared by the PNG CLI (main) and the live Tk overlay.

      emit(img) - called with every rendered frame (a PIL Image).
      count     - scout games per player; None -> use the user's setting (live).
      wait      - auto-open mode: stay blank until champs are actually present.
      stop()    - return True to break out early (overlay was closed).
      monitor   - in-game, after the board is complete, keep watching for the match to
                  end (the overlay stays open through the game) instead of returning.

    Returns when the game/session ends, the deadline passes, or stop() is True."""
    stop = stop or (lambda: False)
    dd = lb.ddragon()
    deadline = time.time() + 420          # cap the pre-game wait (champ select + loading)
    build = None
    build_cid = 0
    last_cs_sig = None                    # champ-select frame signature (skip identical re-renders)
    shown = False                         # have we rendered a real session (champ select / game)?
    inactive = 0                          # consecutive reads with the client out of an active phase
    profile_img, profile_tried = None, False   # the home/profile page (manual open, out of game)
    while not stop() and time.time() < deadline:
        settings = apply_settings()       # live tuning: gank weights + scout depth
        n_scout = count if count is not None else settings["scout_games"]
        # The PHASE is authoritative for "are we in a session". lg.resolve keeps returning a
        # STALE board after a game ends, so we gate on phasecheck, not resolve - otherwise
        # opening the overlay out of game shows the PREVIOUS game instead of the home page.
        ph = phasecheck.phase()
        if ph not in ACTIVE_PHASES:
            if ph == "":                   # client unreachable (closed, or a mid-game lag blip) -> wait
                time.sleep(3)
                continue
            if monitor and shown:          # we were in champ select / a game and it's over -> close
                inactive += 1
                if inactive >= 2:
                    return
            elif not wait:                 # opened out of a game -> the Profile WINDOW handles this
                return
            time.sleep(3)
            continue
        inactive = 0
        info, err = lg.resolve(dd)
        if err:                            # in an active phase but nothing resolvable yet (loading)
            time.sleep(3)
            continue
        shown = True                       # resolve succeeded -> we're in a session
        my_cid, my_role = info["my"], info["pos"]
        allies, enemies = info["allies"], info["enemies"]
        ally_role = {r: c for c, r in allies if r and c}
        enemy_role = {r: c for c, r in enemies if r and c}
        if my_cid and my_cid != build_cid:        # (re)fetch on champ change (champ-select hover/lock)
            build = build_data(dd, my_cid, my_role)
            build_cid = my_cid
        src = info.get("source", "")
        if not enemy_role:                 # champ select / loading: enemies + scout not live yet
            if src == "champ select":
                # CHAMP SELECT: show your team forming + your runes/build; enemies hidden.
                # Only re-render when a pick actually changes (avoids needless window updates,
                # which is what made the overlay flicker/grab focus every couple seconds).
                if wait and not (my_cid or ally_role):
                    time.sleep(2)
                    continue
                sig = (my_cid, my_role, tuple(sorted(ally_role.items())), bool(build))
                if sig != last_cs_sig:
                    ally_ids = [c for c, _ in allies if c]
                    enemy_ids = [c for c, _ in enemies if c]
                    sugg = suggest_champs(dd, my_role, ally_ids, enemy_ids, topn=4)
                    emit(render_image(dd, my_cid, my_role, ally_role, {}, build, {}, {}, src,
                         "enemies are hidden in champ select - matchups + player scout load at the loading screen",
                         roles_known=True, live=False, champ_select=True, suggestions=sugg))
                    last_cs_sig = sig
                time.sleep(2)
                continue
            # LOADING screen: positional preview (no roles yet)
            champs_ready = bool(allies) and bool(enemies)
            if wait and not champs_ready:
                time.sleep(3)
                continue
            ar = {ROLES[i][0]: c for i, (c, _r) in enumerate(allies[:5]) if c}
            er = {ROLES[i][0]: c for i, (c, _r) in enumerate(enemies[:5]) if c}
            emit(render_image(dd, my_cid, my_role, ar, er, build, {}, {}, src,
                 "roles + live player scout load once the match starts...",
                 roles_known=False, live=False))
            time.sleep(3)
            continue
        # in-game: full board + matchup tip + progressive player scout
        lanes = {r: wr for a, r, e, wr, g in lb.gather_lane_matchups(dd, allies, enemies)}
        scout_map = {}
        patch = lm.patch_of(dd["ver"])
        opp_cid = enemy_role.get(my_role) if my_role != "jungle" else None
        tips_on = settings.get("matchup_tips", True)
        tip_box = {"tip": (lm.get_tip(dd["id2key"].get(my_cid, ""), dd["id2key"].get(opp_cid, ""),
                                      my_role, patch) if (tips_on and opp_cid) else None)}
        def paint(note=""):
            emit(render_image(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map,
                 src, note, lane_tip=tip_box["tip"]))

        paint()
        # Generate the matchup tip in the BACKGROUND (web search, ~60-120s) so it never
        # blocks the scout - the board fills in while the tip is being written, and each
        # repaint picks it up once it's ready.
        tip_thread = None
        if tips_on and opp_cid and not tip_box["tip"]:
            def _gen_tip():
                t, _e = lm.generate_tip(dd["id2name"].get(my_cid, ""), dd["id2key"].get(my_cid, ""),
                                        dd["id2name"].get(opp_cid, ""), dd["id2key"].get(opp_cid, ""),
                                        my_role, patch)
                if t:
                    tip_box["tip"] = t
            tip_thread = threading.Thread(target=_gen_tip, daemon=True)
            tip_thread.start()
        for r in ls.iter_scout_struct(dd, n_scout):
            if stop():
                return
            if "error" in r:
                paint(r["error"])
                break
            scout_map[(r["cid"], r["is_ally"])] = r
            paint()
        if tip_thread:                                # board's done; wait out the tip, repaint
            tip_thread.join(timeout=185)              # > the 170s tip-gen cap, so a slow tip
            paint()                                   # still lands (and gets cached) before we exit
        if not monitor:
            return
        # Overlay: board is complete -> keep it on screen and watch THIS game's phase.
        #   new champ select   -> refresh this same window to the new draft (don't go stale)
        #   game over (lobby)  -> close, so the next champ select opens fresh
        # Phase-driven, because lg.resolve can keep returning stale data after a session ends.
        miss, restart = 0, False
        while not stop():
            time.sleep(5)
            ph = phasecheck.phase()
            if ph in ("InProgress", "GameStart", "Reconnect"):
                miss = 0                              # still in this game
                continue
            if ph == "ChampSelect":                   # a NEW champ select -> refresh, don't close
                restart = True
                break
            miss += 1                                 # WaitingForStats / EndOfGame / Lobby / None
            if miss >= 3:                             # ~15s out of game -> match over, close
                return
        if not restart:
            return                                    # stop() requested -> close
        build_cid, last_cs_sig = 0, None              # re-render fresh for the new champ select
        continue


def main():
    argv = sys.argv[1:]
    wait = "--wait" in argv          # auto-open: don't draw anything until champs are present
    if wait:
        argv.remove("--wait")
    outp = _takeflag(argv, "--out") or os.path.expanduser("~/.claude/cache/smitecard.png")
    fm = _takeflag(argv, "--fm")
    try:
        count = int(_takeflag(argv, "--count"))      # None -> use the saved scout-depth setting
    except Exception:
        count = None
    try:
        run(lambda img: _save_png(img, outp), count=count, wait=wait, monitor=False)
    finally:
        if fm:
            try:
                open(fm, "w").close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
