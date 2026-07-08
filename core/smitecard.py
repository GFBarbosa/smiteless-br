#!/usr/bin/env python3
"""smitecard.py - renders the Smiteless overlay as a scoreboard-style PNG.

One image: build/runes header, both teams aligned by role (matchups paired by the
REAL champ in each slot), a data-only gank rating per enemy lane, and a last-10 W/L
form bar per player. Renders progressively (build + lanes first, scout fills in).

Usage:
  python smitecard.py --out card.png [--fm done.flag] [--count 10]
"""
import sys, os, time, threading, urllib.request, urllib.parse, io, json
from PIL import Image, ImageDraw, ImageFont, ImageOps

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import lolgame as lg
import lolscout as ls
import lolmatchup as lm
import lollive as ll
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
GANK = {"BEST": ((28, 82, 46), (150, 240, 168)),
        "GANK": ((34, 74, 47), (122, 214, 146)),
        "EVEN": ((58, 52, 24), (214, 185, 74)),
        "TOUGH": ((78, 36, 41), (228, 130, 130)),
        "AVOID": ((88, 26, 32), (240, 110, 110))}
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
PW = 1150               # the profile window renders WIDER than the board (landscape home page)
ICONCACHE = os.path.expanduser("~/.claude/cache/icons")
_FONTS = {}
_ICONS = {}   # (cid, size) -> resized RGBA Image; avoids re-reading/resizing every repaint
_SPLASH = {}      # (cid, (w,h)) -> cropped RGB splash art
_SPLASH_RAW = {}  # cid -> base RGB splash art (full-size, in-memory only)


# Glyphs Segoe UI regular/bold don't carry -> they render as tofu boxes. Segoe UI Symbol
# has all of them AND the same Latin, so a mixed string ("★ gank") drawn wholly in it looks
# right (it just loses bold weight on those few short labels, which is fine).
_SYM_MISSING = "▸▾★⚠✓⟳✚⚑◆"


def font(size, bold=False, text=None):
    """Segoe UI (bold optional). If `text` carries a glyph Segoe UI lacks (★ ▸ ⚠ ✓ …),
    fall back to Segoe UI Symbol for the whole string so it doesn't render as a tofu box."""
    if text and any(ch in _SYM_MISSING for ch in text):
        key = ("sym", size)
        if key not in _FONTS:
            try:
                _FONTS[key] = ImageFont.truetype(r"C:\Windows\Fonts\seguisym.ttf", size)
            except Exception:
                _FONTS[key] = font(size, bold)      # no symbol font -> at least don't crash
        return _FONTS[key]
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


_ICON_PRUNED = False


def _prune_icon_cache(keep_ver):
    """Drop icon dirs for OLD patches (they accumulate ~2MB every two weeks, forever)."""
    global _ICON_PRUNED
    _ICON_PRUNED = True
    try:
        for name in os.listdir(ICONCACHE):
            p = os.path.join(ICONCACHE, name)
            if name != keep_ver and os.path.isdir(p):
                import shutil
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def get_icon(dd, cid, size):
    ck = (cid, size)
    if ck in _ICONS:
        return _ICONS[ck]
    key = dd.get("id2key", {}).get(cid)
    if not key:
        return None
    if not _ICON_PRUNED:
        _prune_icon_cache(dd["ver"])
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


_ITEM_ICONS = {}


def get_item_icon(dd, iid, size):
    """Item icon from ddragon, disk-cached per patch like champ icons."""
    ck = (iid, size)
    if ck in _ITEM_ICONS:
        return _ITEM_ICONS[ck]
    if not iid:
        return None
    d = os.path.join(ICONCACHE, dd["ver"], "items")
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, f"{iid}.png")
    if not os.path.exists(fp):
        url = f"https://ddragon.leagueoflegends.com/cdn/{dd['ver']}/img/item/{iid}.png"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": lb.UA})
            data = urllib.request.urlopen(req, timeout=8).read()
            tmp = f"{fp}.{os.getpid()}.tmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, fp)
        except Exception:
            return None
    try:
        im = Image.open(fp).convert("RGBA").resize((size, size))
        if len(_ITEM_ICONS) > 200:
            _ITEM_ICONS.clear()
        _ITEM_ICONS[ck] = im
        return im
    except Exception:
        try:
            os.remove(fp)
        except Exception:
            pass
        return None


_FACES = {}             # cid -> (fx, fy) normalized face center in the splash (or None)
_FACES_LOADED = False


def _faces_path():
    return os.path.join(ICONCACHE, "faces.json")


def _face_center(dd, cid, splash):
    """Face center for banner cropping: template-match the champ's icon (Riot's own face
    crop) inside the splash once, then disk-cache forever. None -> caller's fixed bias."""
    global _FACES_LOADED
    if not _FACES_LOADED:
        _FACES_LOADED = True
        try:
            _FACES.update({int(k): (tuple(v) if v else None)
                           for k, v in json.load(open(_faces_path(), encoding="utf-8")).items()})
        except Exception:
            pass
    if cid in _FACES:
        return _FACES[cid]
    try:
        import lolvision as lv
        icon = get_icon(dd, cid, 96)
        face = lv.find_face(splash, icon) if icon else None
    except Exception:
        face = None
    _FACES[cid] = face
    try:
        os.makedirs(ICONCACHE, exist_ok=True)
        json.dump({str(k): (list(v) if v else None) for k, v in _FACES.items()},
                  open(_faces_path(), "w", encoding="utf-8"))
    except Exception:
        pass
    return face


def get_splash(dd, cid, size):
    ck = (cid, size)
    if ck in _SPLASH:
        return _SPLASH[ck]
    key = dd.get("id2key", {}).get(cid)
    if not key:
        return None
    if cid not in _SPLASH_RAW:
        urls = [
            f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{key}_0.jpg",
            f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{key}_0.jpg",
        ]
        base = None
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": lb.UA})
                data = urllib.request.urlopen(req, timeout=8).read()
                base = Image.open(io.BytesIO(data)).convert("RGB")
                break
            except Exception:
                continue
        if base is None:
            return None
        if len(_SPLASH_RAW) >= 4:       # full splashes are ~2.6MB each; keep only a handful
            _SPLASH_RAW.clear()
        if len(_SPLASH) >= 12:          # cropped variants too (a few hundred KB each)
            _SPLASH.clear()
        _SPLASH_RAW[cid] = base
    try:
        tw, th = size
        base = _SPLASH_RAW[cid]
        face = _face_center(dd, cid, base)         # (fx, fy) or None
        im = base.copy()
        sw, sh = im.size
        scale = max(float(tw) / max(1, sw), float(th) / max(1, sh))
        rw, rh = max(1, int(sw * scale)), max(1, int(sh * scale))
        im = im.resize((rw, rh), Image.LANCZOS)
        if face:
            # center the crop on the FACE (slightly above center vertically - portraits
            # read better with headroom), clamped to the art bounds
            x0 = int(max(0, min(rw - tw, face[0] * rw - tw * 0.5)))
            y0 = int(max(0, min(rh - th, face[1] * rh - th * 0.42)))
        else:
            x0 = (rw - tw) // 2
            y0 = int(max(0, min(rh - th, (rh - th) * 0.22)))   # old fixed upper-bias fallback
        im = im.crop((x0, y0, x0 + tw, y0 + th))
        _SPLASH[ck] = im
        return im
    except Exception:
        return None


_SHARD = {5008: "Adaptive", 5005: "AtkSpd", 5007: "Haste", 5011: "Health",
          5001: "HP-scale", 5010: "MoveSpd", 5013: "Tenacity"}


def _rune_page(dd, rp):
    """Decode ONE op.gg rune page into the fields render + import both use."""
    pr = rp.get("primary_rune_ids", [])
    sr = rp.get("secondary_rune_ids", [])
    pl, wn = rp.get("play", 0) or 0, rp.get("win", 0) or 0
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
                shards=[_SHARD.get(i, "") for i in rp.get("stat_mod_ids", [])],
                rune_play=pl,
                rune_wr=(wn / pl * 100) if pl else 0.0)


# Which of the op.gg rune pages is currently selected in the champ-select panel (a click
# on a rune-set chip changes this). Process-wide, since the overlay's click handler and its
# render loop share this module; reset to 0 (most-played) whenever the champ changes.
_RUNE_SEL = {"idx": 0}


def set_rune_idx(n):
    _RUNE_SEL["idx"] = max(0, int(n))


def get_rune_idx():
    return _RUNE_SEL["idx"]


def pick_rune(build, idx=None):
    """`build` with its rune fields set to the selected rune page (default = the current
    selection). Non-destructive; used for BOTH the panel display and the import so the two
    never disagree."""
    opts = (build or {}).get("rune_options") or []
    if not opts:
        return build
    i = _RUNE_SEL["idx"] if idx is None else int(idx)
    i = max(0, min(i, len(opts) - 1))
    b = dict(build)
    b.update(opts[i])
    return b


def build_data(dd, cid, role):
    """op.gg build/runes for a champ+role, or None on any missing/odd data (never crashes).
    Carries the top rune pages in `rune_options` (index 0 = most-played, the default);
    top-level rune fields mirror option 0 so old callers keep working unchanged."""
    try:
        d = lb.opgg(cid, role or "jungle")
        if not d or "summary" not in d or not d.get("runes"):
            return None
        av = d["summary"]["average_stats"]
        pages = sorted((r for r in d["runes"] if r.get("primary_rune_ids")),
                       key=lambda r: r.get("play", 0), reverse=True)
        opts = [_rune_page(dd, rp) for rp in pages[:3]]
        if not opts:
            return None
        core = max(d["core_items"], key=lambda x: x["play"])
        ss = max(d["summoner_spells"], key=lambda x: x["play"])
        sm = max(d["skill_masteries"], key=lambda x: x["play"]) if d.get("skill_masteries") else None
        base = dict(opts[0])                       # default = most-played rune page
        base.update(rune_options=opts,
                    core=[dd["items"].get(i, "") for i in core["ids"]],
                    core_ids=list(core["ids"]),
                    summoner_ids=ss["ids"],
                    summs=[dd["spells"].get(i, "") for i in ss["ids"]],
                    skills=(sm["ids"] if sm else []),
                    wr=av.get("win_rate", 0) * 100,
                    tier={1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}.get(av.get("tier"), ""))
        return base
    except Exception:
        return None


_ROLE_ALIAS = {"jg": "jungle", "jung": "jungle", "jungle": "jungle", "mid": "mid",
               "middle": "mid", "top": "top", "adc": "adc", "bot": "adc", "bottom": "adc",
               "marksman": "adc", "carry": "adc", "sup": "support", "supp": "support",
               "support": "support", "utility": "support"}


def _norm_role(r):
    return _ROLE_ALIAS.get((r or "").strip().lower(), (r or "").strip().lower())


def recommend_favs(dd, my_role, taken, fav_list, topn=6):
    """Ordered champ ids from the user's favourites still OPEN this champ select (not banned
    or picked). A favourite tagged with a role ('Ahri, mid') only shows when it matches your
    assigned role; untagged favourites always qualify. Recommend-only — never hovers/locks."""
    mr = _norm_role(my_role)
    taken = set(taken or [])
    out, seen = [], set()
    for entry in (fav_list or []):
        parts = [p.strip() for p in str(entry).split(",")]
        name = parts[0] if parts else ""
        tag = _norm_role(parts[1]) if len(parts) > 1 and parts[1] else None
        cid = dd["name2id"].get(dd["norm"](name)) if name else None
        if not cid or cid in seen or cid in taken:
            continue
        if tag and mr and tag != mr:
            continue
        out.append(cid)
        seen.add(cid)
        if len(out) >= topn:
            break
    return out


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


def rank_gank_labels(scores):
    """{role: label} with RELATIVE forcing: with 2+ scored lanes, SOMEONE is always the
    strong side (BEST) and someone the weak side (AVOID) - ganking is a comparison, not an
    absolute. Lanes in between keep their absolute GANK/EVEN/TOUGH labels."""
    out = {r: gank_label(s) for r, s in scores.items()}
    if len(scores) >= 2:
        best = max(scores, key=scores.get)
        worst = min(scores, key=scores.get)
        if best != worst:
            out[best] = "BEST"
            out[worst] = "AVOID"
    return out


def queue_prediction(my_cid, scout_map, duo_map):
    """Winners/losers queue read from recent team WR vs enemy WR.
    Excludes you and your detected duo partner(s) from the ally average."""
    me = (my_cid, True) if my_cid else None
    my_duo = duo_map.get(me) if me else None
    ally_wrs, enemy_wrs = [], []
    excl_duo = 0
    for k, sc in scout_map.items():
        n = int(sc.get("n") or 0)
        if n <= 0:
            continue
        wr = (float(sc.get("w") or 0) / n) * 100.0
        cid, is_ally = k
        if is_ally:
            if me and k == me:
                continue
            if my_duo is not None and duo_map.get(k) == my_duo:
                excl_duo += 1
                continue
            ally_wrs.append(wr)
        else:
            enemy_wrs.append(wr)
    if not ally_wrs or not enemy_wrs:
        return {"text": "QUEUE READ: scouting...", "fill": MUTED, "bg": (34, 38, 48)}
    aavg = sum(ally_wrs) / len(ally_wrs)
    eavg = sum(enemy_wrs) / len(enemy_wrs)
    diff = aavg - eavg
    if diff >= 2.5:
        lab, col = "WINNERS QUEUE", GREEN
    elif diff <= -2.5:
        lab, col = "LOSERS QUEUE", REDWR
    else:
        lab, col = "EVEN QUEUE", TAN
    excl = "excl. you+duo" if excl_duo > 0 else "excl. you"
    txt = f"{lab}  {aavg:.0f}% vs {eavg:.0f}%  ({excl})"
    return {"text": txt, "fill": col, "bg": _dim(col, 0.24)}


_DODGE_CACHE = {}
# Dodge gate - deliberately STRICT (you get ~one free dodge a day, so only call it when the
# draft is genuinely lost on paper). All four must hold across the known lanes.
DODGE_MIN_LANES = 4        # need most of the draft locked + sampled before judging
DODGE_AVG = -3.0           # average lane win-rate delta this far below 50%
DODGE_LOSING = 3           # at least this many clearly-losing lanes
DODGE_HARDCOUNTERS = 1     # at least one hard counter (>=6% under)
DODGE_BEST_CAP = 5.0       # ...and no lane is hard-winning enough to carry the draft


def dodge_read(dd, allies, enemies):
    """High-confidence 'consider dodging' read from op.gg lane matchups (champ select).
    Returns {reason, avg, worst} only when the draft is lost across most lanes; else None.
    Conservative on purpose - a false dodge costs the user a real, scarce free dodge."""
    sig = (tuple(sorted((c, r) for c, r in allies if c and r)),
           tuple(sorted((c, r) for c, r in enemies if c and r)))
    if sig in _DODGE_CACHE:
        return _DODGE_CACHE[sig]
    if len(_DODGE_CACHE) > 64:          # every hover permutation lands here; don't grow forever
        _DODGE_CACHE.clear()
    result = None
    try:
        rows = lb.gather_lane_matchups(dd, allies, enemies)
    except Exception:
        rows = []
    deltas = [(role, ally, enemy, wr - 50.0) for ally, role, enemy, wr, g in rows
              if wr is not None and g and g >= 20]
    if len(deltas) >= DODGE_MIN_LANES:
        ds = [x[3] for x in deltas]
        avg = sum(ds) / len(ds)
        losing = sum(1 for v in ds if v <= -3)
        hard = sum(1 for v in ds if v <= -6)
        best = max(ds)
        if avg <= DODGE_AVG and losing >= DODGE_LOSING and hard >= DODGE_HARDCOUNTERS and best < DODGE_BEST_CAP:
            worst = min(deltas, key=lambda x: x[3])
            result = {"avg": avg, "losing": losing,
                      "worst": (worst[1], worst[2], worst[3]),
                      "reason": f"{losing}/{len(deltas)} lanes behind · worst {worst[1]} vs {worst[2]} ({worst[3]:+.0f}%)"}
    _DODGE_CACHE[sig] = result
    return result


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
LABEL_COL = {
    # wins
    "hard carry": (255, 214, 122),
    "carried": (236, 206, 128),
    "great game": (118, 214, 150),
    "solid win": (95, 200, 126),
    "decent game": (168, 206, 132),
    "scrappy win": (160, 180, 140),
    # losses
    "carried, lost": (120, 166, 232),
    "great game, lost": (130, 170, 225),
    "kept fighting": (150, 165, 200),
    "tough loss": (210, 150, 104),
    "rough game": (206, 86, 94),
}
_POS_ABBR = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID", "MID": "MID", "BOTTOM": "ADC", "UTILITY": "SUP"}


def _dim(c, f):
    return tuple(max(0, min(255, int(x * f))) for x in c)


def _rrect(d, box, r, fill=None, outline=None, width=1):
    try:
        d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)
    except Exception:
        d.rectangle(box, fill=fill, outline=outline)


def _sparkline(d, x0, y0, w, h, vals):
    """A tiny LP-over-time line; green if net-up, red if net-down. Endpoint dotted."""
    if not vals or len(vals) < 2:
        return
    lo, hi = min(vals), max(vals)
    rng = max(1, hi - lo)
    n = len(vals)
    pts = [(x0 + int(i / (n - 1) * w), y0 + h - int((v - lo) / rng * h)) for i, v in enumerate(vals)]
    col = GREEN if vals[-1] >= vals[0] else REDWR
    try:
        d.line(pts, fill=col, width=2, joint="curve")
    except Exception:
        d.line(pts, fill=col, width=2)
    ex, ey = pts[-1]
    d.ellipse((ex - 2, ey - 2, ex + 2, ey + 2), fill=col)


def _draw_session_coach(d, p, y):
    """Session band: W-L + LP swing + streak/tilt on the left, pool-coach advice on the right.
    For ANOTHER player's profile the session half is meaningless (it's local history) - show
    only their pool read."""
    W = PW                                        # profile surfaces render at the wide layout
    f = font(11, 1)
    sess = p.get("session") or {}
    bits = []
    if p.get("other"):
        bits = [("VIEWING", GOLD), (p.get("riot_id", "?"), TAN),
                ("· their last games, scored the same way", MUTED)]
    else:
        if sess.get("games"):
            bits.append(("SESSION", GOLD))
            bits.append((f"{sess['wins']}W-{sess['losses']}L", TAN))
            if sess.get("lp_delta") is not None:
                dv = sess["lp_delta"]
                bits.append((f"{dv:+d} LP", GREEN if dv >= 0 else REDWR))
        stv = sess.get("streak", 0)
        if abs(stv) >= 2:
            bits.append((f"{'W' if stv > 0 else 'L'}{abs(stv)} streak", GREEN if stv > 0 else REDWR))
        if not bits:
            bits = [("SESSION", GOLD), ("play a ranked game to start tracking", MUTED)]
    x = 20
    for txt, col in bits:
        d.text((x, y), txt, font=f, fill=col)
        x += d.textlength(txt, font=f) + 12
    if sess.get("tilt"):
        d.text((x, y), "· take a breather, tilt risk", font=f, fill=REDWR)
    coach = p.get("coach")
    if coach:
        cx = W - 22
        order = [k for k in ("more", "less", "slump") if coach.get(k)]
        for k in order:                                   # right-anchored, first = rightmost
            c = coach[k]
            if k == "more":
                txt, col = f"▸ play more {c['champ']} {c['wr']}%", GREEN
            elif k == "less":
                txt, col = f"▸ ease off {c['champ']} {c['wr']}%", REDWR
            else:                                         # a slumping MAIN: variance, not the pick
                txt, col = f"▸ rough patch on {c['champ']} — variance, not the pick", TAN
            cf = font(11, 1, txt)                          # ▸ needs Segoe UI Symbol
            d.text((cx, y), txt, font=cf, fill=col, anchor="ra")
            cx -= d.textlength(txt, font=cf) + 16


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
    return f"{p['wr']}% over your last {p['n']}. Avg game score {p['avg_score']}/100; each game is graded against your role's benchmarks."


def _champ_id_from_name(dd, name):
    nm = (name or "").strip()
    if not nm:
        return 0
    cid = dd["name2id"].get(dd["norm"](nm))
    if cid:
        return cid
    nn = dd["norm"](nm)
    for i, n in dd.get("id2name", {}).items():
        if dd["norm"](n).startswith(nn) or nn.startswith(dd["norm"](n)):
            return i
    return 0


DETAIL_H = 258          # height of an expanded game's 10-player breakdown + quick review


def _draw_match_detail(d, img, dd, parts, my_puuid, x0, y0, w, review=None, review_kind="improve", duos=None):
    """The 10-player breakdown for an expanded game: name (clickable -> their profile),
    KDA, full item build as icons, damage/cs/gold/vision, duo markers - both teams, plus
    the review panel. Returns {'review': box, 'players': [(x0,y0,x1,y1,puuid,name)]}."""
    duos = duos or {}
    _rrect(d, (x0, y0, x0 + w, y0 + DETAIL_H), 9, fill=(19, 22, 30), outline=PEDGE, width=1)
    me = next((pl for pl in parts if pl["puuid"] == my_puuid), None)
    myteam = me["team"] if me else 100
    maxd = max((pl["dmg"] for pl in parts), default=1) or 1
    pad, rw = 16, 232
    colw = (w - (pad * 2) - rw - 24) // 2
    teams = [[pl for pl in parts if pl["team"] == myteam],
             [pl for pl in parts if pl["team"] != myteam]]
    player_hits = []
    for ci, team in enumerate(teams):
        cx = x0 + pad + ci * (colw + 16)
        d.text((cx, y0 + 9), "YOUR TEAM" if ci == 0 else "ENEMY", font=font(10, 1),
               fill=(125, 166, 216) if ci == 0 else (216, 130, 130))
        ry = y0 + 28
        for pl in team[:5]:
            cid = dd["name2id"].get(dd["norm"](pl["champ"]))
            ic = get_icon(dd, cid, 26)
            if ic:
                img.paste(ic, (cx, ry + 1), ic)
            mine = pl["puuid"] == my_puuid
            if pl["puuid"] in duos:                       # premade marker (same color = same duo)
                _duo_marker(d, cx - 6, ry + 6, duos[pl["puuid"]], "L")
            name = (pl.get("name") or pl.get("champ") or "?").split("#")[0][:14]
            d.text((cx + 32, ry), name, font=font(10, 1 if mine else 0),
                   fill=GOLD if mine else TEXT)
            d.text((cx + colw - 2, ry), f"{pl['k']}/{pl['d']}/{pl['a']}",
                   font=font(10, 1 if mine else 0), fill=GOLD if mine else TAN, anchor="ra")
            # damage bar under the name, then items + economy line
            bx, bw_ = cx + 32, 92
            _rrect(d, (bx, ry + 14, bx + bw_, ry + 18), 2, fill=(40, 44, 56))
            _rrect(d, (bx, ry + 14, bx + max(2, int(bw_ * pl["dmg"] / maxd)), ry + 18), 2,
                   fill=(214, 130, 96))
            ix = cx + 32 + bw_ + 8
            for iid in (pl.get("items") or [])[:6]:
                iic = get_item_icon(dd, iid, 15)
                if iic:
                    img.paste(iic, (ix, ry + 12), iic)
                ix += 17
            d.text((cx + colw - 2, ry + 22), f"{pl['dmg'] // 1000}k dmg · {pl['cs']}cs · "
                   f"{pl['gold'] // 1000}k g · {pl.get('vision', 0)}v",
                   font=font(9), fill=MUTED, anchor="ra")
            player_hits.append((cx, ry, cx + colw, ry + 34, pl.get("puuid", ""),
                                pl.get("name") or ""))
            ry += 42
    rx = x0 + w - rw - 12
    _rrect(d, (rx, y0 + 8, rx + rw, y0 + DETAIL_H - 8), 8, fill=(23, 27, 37), outline=PEDGE, width=1)
    good = (review_kind == "positive")
    d.text((rx + 12, y0 + 18), "POST-GAME REVIEW", font=font(10, 1), fill=GOLD)
    d.text((rx + 12, y0 + 34), ("What you did well" if good else "3 things to improve"),
           font=font(10), fill=(GREEN if good else MUTED))
    tips = list(review or [])
    if not tips:
        tips = ["Loading role-specific review..."]
    yy = y0 + 54
    line_h = 14
    tip_gap = 6
    max_w = rw - 30
    for t in tips[:3]:
        wrapped = _wrap(t, font(10), max_w)
        if not wrapped:
            continue
        wrapped = wrapped[:2]  # keep each tip compact so all 3 fit
        d.text((rx + 12, yy), "• " + wrapped[0], font=font(10), fill=(TAN if good else TEXT))
        yy += line_h
        for ln in wrapped[1:]:
            d.text((rx + 24, yy), ln, font=font(10), fill=(TAN if good else TEXT))
            yy += line_h
        yy += tip_gap
        if yy > y0 + DETAIL_H - 18:
            break
    return {"review": (rx, y0 + 8, rx + rw, y0 + DETAIL_H - 8), "players": player_hits}


def render_profile(dd, p, expanded=None, details=None):
    """The home page: rank, recent form, champ win rates, and per-game scores graded vs the
    lobby. Carded; games in `expanded` (indices) show the 10-player breakdown from `details`
    (mid -> parts). Sets img.hit_games = [(y0, y1, index)] for click-to-expand."""
    W = PW                                        # landscape layout: everything below uses the wide width
    expanded = expanded or set()
    details = details or {}
    games = p.get("games", [])
    HEAD, CHAMPS, BAND, STATS = 132, 96, 30, 26
    games_top = HEAD + BAND + STATS + CHAMPS + 34
    H = games_top + 16
    for i in range(len(games)):
        H += 50 + (DETAIL_H + 8 if i in expanded else 0)
    H = max(H, games_top + 60)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ---- header card ----
    hx0, hy0, hx1, hy1 = 14, 12, W - 14, 122
    _rrect(d, (hx0, hy0, hx1, hy1), 14, fill=PCARD, outline=None, width=1)
    best = (p.get("champs") or [{}])[0].get("champ")
    if not best:
        best = (p.get("games") or [{}])[0].get("champ")
    best_cid = _champ_id_from_name(dd, best)
    if best_cid:
        bw, bh = (hx1 - hx0), (hy1 - hy0)
        splash = get_splash(dd, best_cid, (bw, bh))
        if not splash:
            # Hard fallback: use champion square art stretched into the banner so it never renders flat/black.
            fic = get_icon(dd, best_cid, 512)
            if fic:
                splash = fic.convert("RGB").resize((bw, bh), Image.LANCZOS)
        if splash:
            mask = Image.new("L", (bw, bh), 0)
            md = ImageDraw.Draw(mask)
            try:
                md.rounded_rectangle((0, 0, bw, bh), radius=14, fill=255)
            except Exception:
                md.rectangle((0, 0, bw, bh), fill=255)
            img.paste(splash, (hx0, hy0), mask)
            shade_mask = mask.point(lambda v: int(v * 0.33))
            img.paste((10, 14, 22), (hx0, hy0, hx1, hy1), shade_mask)
            # bottom gradient so the headline/sparkline sit on a readable base
            gh = 46
            grad = Image.new("L", (bw, gh), 0)
            gd = ImageDraw.Draw(grad)
            for yy_ in range(gh):
                gd.line([(0, yy_), (bw, yy_)], fill=int(200 * (yy_ / gh)))
            img.paste((12, 15, 24), (hx0, hy1 - gh, hx1, hy1), grad)
        else:
            # Fallback: enlarge champ icon so the header never appears blank.
            fic = get_icon(dd, best_cid, hy1 - hy0 - 8)
            if fic:
                img.paste(fic, (hx0 + 10, hy0 + 4), fic)
    _rrect(d, (hx0, hy0, hx1, hy1), 14, fill=None, outline=PEDGE, width=1)
    name = p.get("riot_id", "?").split("#")[0]
    d.text((30, 22), name, font=name_font(25, name), fill=TEXT)
    # rank as a tier-colored chip
    rs, rc = rank_str(p.get("rank"))
    rf = font(13, 1)
    rw = d.textlength(rs, font=rf)
    _rrect(d, (28, 56, 28 + rw + 18, 78), 8, fill=_dim(rc, 0.22), outline=_dim(rc, 0.6), width=1)
    d.text((37, 60), rs, font=rf, fill=rc)
    # avg KDA chip next to the rank (from the loaded games)
    av = p.get("avgs") or {}
    if av.get("kda") is not None:
        ktxt = f"{av['kda']} KDA"
        kw = d.textlength(ktxt, font=rf)
        kx = 28 + rw + 28
        _rrect(d, (kx, 56, kx + kw + 18, 78), 8, fill=(28, 32, 43), outline=PEDGE, width=1)
        d.text((kx + 9, 60), ktxt, font=rf, fill=TAN)
    # win bar + record
    bx, by, bw2 = 30, 82, 230
    _rrect(d, (bx, by, bx + bw2, by + 8), 4, fill=(46, 50, 64))
    if p["wr"] > 0:
        _rrect(d, (bx, by, bx + int(bw2 * min(1.0, p["wr"] / 100.0)), by + 8), 4,
               fill=GREEN if p["wr"] >= 50 else REDWR)
    d.text((bx + bw2 + 14, by - 4), f"{p['wins']}W {p['losses']}L  ·  {p['wr']}%  ·  last {p['n']}",
           font=font(12, 1), fill=TEXT)
    # top-right avg score (color-only, no icon)
    avg = int(p.get("avg_score", 0) or 0)
    if avg >= 115:
        sc_col = GRADE_COLOR["S+"]
    elif avg >= 100:
        sc_col = GRADE_COLOR["S"]
    elif avg >= 85:
        sc_col = GRADE_COLOR["A"]
    elif avg >= 70:
        sc_col = GRADE_COLOR["B"]
    elif avg >= 55:
        sc_col = GRADE_COLOR["C"]
    else:
        sc_col = GRADE_COLOR["D"]
    d.text((W - 30, 30), str(p["avg_score"]), font=font(34, 1), fill=sc_col, anchor="ra")
    d.text((W - 30, 74), "AVG GAME SCORE", font=font(9, 1), fill=MUTED, anchor="ra")
    # headline
    for ln in _wrap(_profile_headline(p), font(12), W - 360)[:1]:
        d.text((30, 98), ln, font=font(12), fill=TAN)
    # LP trend sparkline (bottom-right of the header card)
    trend = p.get("lp_trend") or []
    if len(trend) >= 2:
        spw, sph, sy = 150, 18, 94
        sx = W - 30 - spw
        d.text((W - 30, sy - 12), "LP TREND", font=font(8, 1), fill=MUTED, anchor="ra")
        _sparkline(d, sx, sy, spw, sph, trend)
        net = trend[-1] - trend[0]
        d.text((sx - 8, sy + sph // 2), f"{net:+d}", font=font(11, 1),
               fill=GREEN if net >= 0 else REDWR, anchor="rm")

    # ---- session + pool-coach band ----
    _draw_session_coach(d, p, HEAD - 2)

    # ---- averages strip: your numbers across the loaded games + role split ----
    ay = HEAD + BAND - 2
    av = p.get("avgs") or {}
    if av:
        f11 = font(11, 1)
        d.text((20, ay), "AVG", font=f11, fill=GOLD)
        x = 58
        for lab, val, col in (("KDA", f"{av.get('k', 0)}/{av.get('d', 0)}/{av.get('a', 0)}", TEXT),
                              ("KP", f"{av.get('kp', 0)}%", TEXT),
                              ("CS/M", f"{av.get('csm', 0)}", TEXT),
                              ("DMG", f"{av.get('dmg_share', 0)}%", TEXT)):
            d.text((x, ay), lab, font=font(10, 1), fill=MUTED)
            x += d.textlength(lab, font=font(10, 1)) + 6
            d.text((x, ay), val, font=f11, fill=col)
            x += d.textlength(val, font=f11) + 22
        roles = p.get("roles") or {}
        if roles:
            rx = W - 22
            total = max(1, sum(roles.values()))
            for pos, cnt in sorted(roles.items(), key=lambda kv: -kv[1])[:3]:
                txt = f"{_POS_ABBR.get(pos, pos[:3])} {round(cnt / total * 100)}%"
                d.text((rx, ay), txt, font=font(10, 1), fill=MUTED, anchor="ra")
                rx -= d.textlength(txt, font=font(10, 1)) + 16

    # ---- top champions ----
    cy = HEAD + BAND + STATS + 6
    ch_label = "TOP CHAMPIONS · THIS SEASON" if p.get("season_champs") else "TOP CHAMPIONS · RECENT"
    d.text((20, cy), ch_label, font=font(11, 1), fill=GOLD)
    d.line([40 + int(d.textlength(ch_label, font=font(11, 1))), cy + 7, W - 20, cy + 7],
           fill=(36, 40, 52), width=1)
    nch = max(1, min(6, len(p.get("champs", [])) or 1))
    cw = min(186, (W - 28) // nch)               # wider cards in the landscape layout
    x = 14
    for c in p.get("champs", [])[:6]:
        cid = dd["name2id"].get(dd["norm"](c["champ"]))
        _rrect(d, (x, cy + 18, x + cw - 8, cy + 66), 10, fill=PCARD, outline=PEDGE, width=1)
        ic = get_icon(dd, cid, 36)
        if ic:
            img.paste(ic, (x + 10, cy + 24), ic)
        d.text((x + 54, cy + 24), dd["id2name"].get(cid, c["champ"])[:8], font=font(12, 1), fill=TEXT)
        wcol = GREEN if c["wr"] >= 55 else (REDWR if c["wr"] < 45 else TAN)
        d.text((x + 54, cy + 42), f"{c['wr']}%", font=font(13, 1), fill=wcol)
        d.text((x + 92, cy + 44), f"{c['g']}g", font=font(10), fill=MUTED)
        # mini win-rate bar along the card bottom
        bw_ = cw - 28
        _rrect(d, (x + 10, cy + 60, x + 10 + bw_, cy + 62), 1, fill=(42, 46, 60))
        _rrect(d, (x + 10, cy + 60, x + 10 + int(bw_ * min(1.0, c["wr"] / 100.0)), cy + 62), 1, fill=_dim(wcol, 0.9))
        if c.get("avg") is not None:
            gcol = GRADE_COLOR["A"] if c["avg"] >= 85 else (GRADE_COLOR["B"] if c["avg"] >= 70 else MUTED)
            d.text((x + cw - 16, cy + 25), str(c["avg"]), font=font(11, 1), fill=gcol, anchor="ra")
            d.text((x + cw - 16, cy + 40), "avg", font=font(8), fill=MUTED, anchor="ra")
        x += cw

    # ---- recent games ----
    d.text((20, games_top - 22), "RECENT GAMES", font=font(11, 1), fill=GOLD)
    d.line([124, games_top - 15, W - 350, games_top - 15], fill=(36, 40, 52), width=1)
    d.text((W - 20, games_top - 21), "click a game to expand  ·  score = vs your role's goals",
           font=font(10), fill=(118, 116, 108), anchor="ra")
    hit_games, hit_reviews, hit_players, yy = [], [], [], games_top
    for i, g in enumerate(games):
        acc = GREEN if g["win"] else REDWR
        rowbg = PCARD2 if i % 2 == 0 else (28, 32, 43)     # alternate row tint
        _rrect(d, (14, yy, W - 14, yy + 44), 9, fill=_dim(acc, 0.9))
        _rrect(d, (21, yy, W - 14, yy + 44), 9, fill=rowbg)
        cid = dd["name2id"].get(dd["norm"](g["champ"]))
        ic = get_icon(dd, cid, 32)
        if ic:
            img.paste(ic, (30, yy + 6), ic)
        d.text((70, yy + 13), "W" if g["win"] else "L", font=font(15, 1), fill=acc)
        d.text((92, yy + 6), dd["id2name"].get(cid, g["champ"])[:12], font=font(13, 1), fill=TEXT)
        d.text((92, yy + 25), f"{g['k']}/{g['d']}/{g['a']}", font=font(11), fill=MUTED)
        gc = GRADE_COLOR.get(g["letter"], TAN)
        _rrect(d, (330, yy + 9, 396, yy + 35), 7, fill=_dim(gc, 0.20), outline=_dim(gc, 0.5), width=1)
        d.text((342, yy + 14), g["letter"], font=font(14, 1), fill=gc)
        d.text((371, yy + 16), str(g["score"]), font=font(12, 1), fill=gc)
        d.text((436, yy + 16), _POS_ABBR.get((g.get("pos") or "").upper(), ""), font=font(10, 1), fill=MUTED)
        d.text((510, yy + 15), g["label"], font=font(12, 1), fill=LABEL_COL.get(g["label"], MUTED))
        extra = []
        if (g.get("pos") or "").upper() == "UTILITY":     # a support's cs/min is noise: show vision
            if g.get("vision") and g.get("dur"):
                extra.append(f"{g['vision'] / max(1.0, g['dur'] / 60.0):.1f} vis/m")
        elif g.get("csm"):
            extra.append(f"{g['csm']} cs/m")
        if g.get("kp") is not None:
            extra.append(f"{g['kp']}% kp")
        if g.get("dur"):
            extra.append(f"{int(g['dur'] // 60)}m")
        if extra:
            d.text((W - 46, yy + 16), "  ·  ".join(extra), font=font(10), fill=(110, 108, 100), anchor="ra")
        d.text((W - 26, yy + 15), "▾" if i in expanded else "▸", font=font(13, text="▾"), fill=MUTED, anchor="ra")
        hit_games.append((yy, yy + 44, i))
        yy += 50
        if i in expanded:
            det = details.get(g.get("mid")) or {}
            parts = det.get("parts")
            if parts:
                rb = _draw_match_detail(d, img, dd, parts, p.get("puuid"), 14, yy, W - 28,
                                        g.get("review"), g.get("review_kind", "improve"),
                                        duos=det.get("duos"))
                if rb:
                    r = rb["review"]
                    hit_reviews.append((r[0], r[1], r[2], r[3], i))
                    hit_players.extend(rb["players"])
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
    img.hit_reviews = hit_reviews
    img.hit_players = hit_players
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


# How good has this player been IN THEIR GAMES — regardless of rank. A Silver stomping 20/0
# every game is God Mode (S, gold glow); a feeder is a black hole (F, avoid). Driven by recent
# win rate + KDA (are they carrying or inting) + hot/cold streak. Rank is deliberately ignored.
_RATE_COLOR = {"S": (236, 206, 128), "A": (95, 200, 126), "B": (120, 166, 232),
               "C": (150, 148, 138), "D": (206, 130, 86), "F": (210, 66, 74)}


def player_rating(sc):
    """(grade, color) from how the player has been PERFORMING lately, or (None, None) with too
    few recent games to judge. Rank is not a factor — it's win rate + KDA + streak."""
    if not sc:
        return None, None
    n, w = sc.get("n", 0) or 0, sc.get("w", 0) or 0
    kda = sc.get("kda") or {}
    kg = kda.get("g", 0) or 0
    if n < 3 and kg < 3:
        return None, None
    score = 50.0
    if n >= 3:                                        # winning your games = the core signal
        score += (w / n * 100.0 - 50.0) * 0.55
    if kg >= 2:                                       # KDA = carrying vs inting (when we have it)
        avg = (kda.get("k", 0) + kda.get("a", 0)) / max(1, kda.get("d", 0))
        score += max(-24.0, min(34.0, (avg - 2.6) * 8.0))   # ~2.6 KDA is average; cap the stomps
    stv = _streak(sc.get("form") or [])               # hot/cold hands
    if abs(stv) >= 3:
        score += 6 if stv > 0 else -6
    score = max(0.0, min(100.0, score))
    g = ("S" if score >= 84 else "A" if score >= 71 else "B" if score >= 58
         else "C" if score >= 45 else "D" if score >= 33 else "F")
    return g, _RATE_COLOR[g]


_GRADE_NUM = {"S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
_NUM_GRADE = {6: "S", 5: "A", 4: "B", 3: "C", 2: "D", 1: "F"}


def team_avg_grades(scout_map):
    """(ally_grade, enemy_grade) — each team's AVERAGE player grade (S..F) from the live scout,
    or (None, None) if not enough scouted. A KDA/form-based second opinion on the WR queue read."""
    def avg(team):
        gs = [_GRADE_NUM[player_rating(sc)[0]] for k, sc in scout_map.items()
              if k[1] is team and player_rating(sc)[0]]
        return _NUM_GRADE[max(1, min(6, round(sum(gs) / len(gs))))] if gs else None
    return avg(True), avg(False)


def _grade_chip(d, cx, cy, grade, col):
    """A bold grade letter in a chip, centered on (cx, cy)."""
    w, h = 22, 20
    fill = tuple(int(c * 0.28) for c in col)
    _rrect(d, (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2), 6, fill=fill, outline=col, width=1)
    d.text((cx, cy), grade, font=font(13, 1, grade), fill=col, anchor="mm")


def draw_player(d, img, dd, x, y, cid, sc, is_me, side, accent, accent_bg, live=True):
    if not cid:
        return
    grade, gcol = player_rating(sc)
    box_fill, box_edge, box_w = accent_bg, PEDGE, 1
    if grade == "S":
        box_edge, box_w = gcol, 2                     # banner glows gold
    elif grade == "F":
        box_fill, box_edge, box_w = (14, 11, 13), gcol, 2   # black-hole: dark fill, red ring
    name = dd["id2name"].get(cid, "?")
    icon = get_icon(dd, cid, 38)
    cw = 372
    if side == "L":
        if box_w == 2:                                # S/F: soft outer glow ring
            _rrect(d, (x - 2, y + 7, x + cw + 2, y + ROWH - 3), 11,
                   outline=tuple(int(c * 0.5) for c in box_edge), width=1)
        _rrect(d, (x, y + 9, x + cw, y + ROWH - 5), 9, fill=box_fill, outline=box_edge, width=box_w)
        d.rectangle([x, y + 16, x + 3, y + ROWH - 12], fill=accent)
        ix = x + 12
        if icon:
            img.paste(icon, (ix, y + 13), icon)
        tx = ix + 46
        nm, nf = name + ("  YOU" if is_me else ""), font(14, 1)
        d.text((tx, y + 13), nm, font=nf, fill=GOLD if is_me else TEXT)
        if grade:                                     # right after the name -> clearly the player's grade
            _grade_chip(d, tx + d.textlength(nm, font=nf) + 18, y + 21, grade, gcol)
        _wr_line(d, tx, y + 35, sc, "la", live)
        if sc and sc.get("form"):
            draw_form(d, x + cw - 88, y + 38, sc["form"])
    else:
        if box_w == 2:
            _rrect(d, (x - cw - 2, y + 7, x + 2, y + ROWH - 3), 11,
                   outline=tuple(int(c * 0.5) for c in box_edge), width=1)
        _rrect(d, (x - cw, y + 9, x, y + ROWH - 5), 9, fill=box_fill, outline=box_edge, width=box_w)
        d.rectangle([x - 3, y + 16, x, y + ROWH - 12], fill=accent)
        ix = x - 12 - 38
        if icon:
            img.paste(icon, (ix, y + 13), icon)
        tx = ix - 8
        nf = font(14, 1)
        d.text((tx, y + 13), name, font=nf, fill=TEXT, anchor="ra")
        if grade:                                     # left of the (right-anchored) name
            _grade_chip(d, tx - d.textlength(name, font=nf) - 18, y + 21, grade, gcol)
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
    label = {"BEST": "★ gank", "GANK": "gank", "EVEN": "even",
             "TOUGH": "tough", "AVOID": "avoid"}[rating]
    f = font(11, 1, label)
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
    _rrect(d, (x, y, x + w, y + ph), 10, fill=(24, 27, 37), outline=PEDGE, width=1)
    d.rectangle([x, y + 8, x + 3, y + ph - 8], fill=GOLD)
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


def draw_build_block(d, img, dd, x, y, build, hits=None):
    """The champ-select runes/build card: keystone + rune words, the core build as real
    ITEM ICONS, summoners, skill order, and the import button - in one framed card."""
    cw, chh = 396, 236
    _rrect(d, (x - 16, y - 10, x - 16 + cw, y - 10 + chh), 12, fill=(20, 23, 32), outline=PEDGE, width=1)
    d.text((x, y), "RUNES", font=font(10, 1), fill=GOLD)
    d.text((x, y + 16), build.get("keystone", ""), font=font(15, 1), fill=TEXT)
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
    d.line([x, y + 98, x - 32 + cw, y + 98], fill=PEDGE, width=1)
    d.text((x, y + 106), "CORE BUILD", font=font(10, 1), fill=GOLD)
    ids = build.get("core_ids") or []
    ix = x
    if ids:
        for j, iid in enumerate(ids[:4]):
            ic = get_item_icon(dd, iid, 34)
            if ic:
                _rrect(d, (ix - 1, y + 121, ix + 35, y + 157), 6, outline=PEDGE, width=1)
                img.paste(ic, (ix, y + 122), ic)
            if j < min(len(ids), 4) - 1:
                d.text((ix + 40, y + 132), "›", font=font(14, 1), fill=MUTED)
            ix += 52
    else:
        d.text((x, y + 124), " > ".join(c for c in build.get("core", []) if c), font=font(12), fill=TEXT)
    d.text((x, y + 164), "Summoners:  " + " / ".join(build.get("summs", [])), font=font(11), fill=MUTED)
    skills = [s for s in build.get("skills", []) if s]
    if skills:
        d.text((x + 190, y + 164), "Skill max:  " + " > ".join(skills), font=font(11), fill=MUTED)
    # Keep import action visually grouped with the runes/summoners block.
    bx, by, bw, bh = x, y + 186, 188, 28
    _rrect(d, (bx, by, bx + bw, by + bh), 8, fill=(35, 44, 68), outline=(72, 86, 120), width=1)
    d.text((bx + (bw // 2), by + (bh // 2) + 1), "Import runes + summs", font=font(10, 1), fill=TEXT, anchor="mm")
    if hits is not None:
        hits.append((bx, by, bx + bw, by + bh, "action:import_build"))
    _auto_chip(d, bx + bw + 8, by + 3, cfg_load_auto(), hits)


def cfg_load_auto():
    try:
        import smiteconfig as _cfg
        return bool(_cfg.load().get("auto_import", False))
    except Exception:
        return False


_SITE_REGION = {"na1": "na", "euw1": "euw", "eun1": "eune", "kr": "kr", "br1": "br",
                "jp1": "jp", "oc1": "oce", "la1": "lan", "la2": "las", "tr1": "tr", "ru": "ru"}


def _profile_url(riot_id):
    """u.gg profile URL for a 'Name#TAG' riot id, or None. (u.gg plays nicer than op.gg
    behind Cloudflare WARP.) u.gg uses the platform code directly, e.g. na1."""
    if not riot_id or "#" not in riot_id:
        return None
    region = getattr(ls, "PLATFORM", "na1")
    name, tag = riot_id.rsplit("#", 1)
    return f"https://u.gg/lol/profile/{region}/{urllib.parse.quote(name)}-{urllib.parse.quote(tag)}/overview"


def site_urls(riot_id):
    """[(label, url)] to look a player up across the sites, for the right-click menu.
    Porofessor links to their LIVE game if they're in one (best 'info gathering')."""
    if not riot_id or "#" not in riot_id:
        return []
    plat = getattr(ls, "PLATFORM", "na1")
    reg = _SITE_REGION.get(plat, "na")
    name, tag = riot_id.rsplit("#", 1)
    q = urllib.parse.quote(name)
    slug = f"{q}-{urllib.parse.quote(tag)}"
    return [
        ("u.gg", f"https://u.gg/lol/profile/{plat}/{slug}/overview"),
        ("op.gg", f"https://op.gg/summoners/{reg}/{slug}"),
        ("League of Graphs", f"https://www.leagueofgraphs.com/summoner/{reg}/{slug}"),
        ("Deeplol", f"https://www.deeplol.gg/summoner/{reg}/{slug}"),
        ("Porofessor (live game)", f"https://porofessor.gg/live/{reg}/{slug}"),
    ]


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


def game_plan(dd, ally_ids, enemy_ids):
    """2-3 blunt win-condition bullets from the two comps (champ tags only — robust, no
    per-patch curation): the enemy's damage split, whether they have a frontline, and how much
    engage each side has. Returns [] when there isn't enough to say."""
    tags = dd.get("id2tags", {})

    def prof(ids):
        rows = [set(tags.get(i, [])) for i in ids if i]
        return {
            "n": len(rows),
            "ad": sum(1 for s in rows if ("Marksman" in s or "Fighter" in s or "Assassin" in s) and "Mage" not in s),
            "ap": sum(1 for s in rows if "Mage" in s),
            "front": sum(1 for s in rows if "Tank" in s),
            "engage": sum(1 for s in rows if ("Tank" in s) or ("Fighter" in s)),
        }
    them, me = prof(enemy_ids), prof(ally_ids)
    out = []
    if them["n"] >= 3:
        if them["ad"] >= 3 and them["ad"] >= them["ap"] * 2:
            out.append("Enemy damage is mostly AD — an early armor item swings fights.")
        elif them["ap"] >= 3 and them["ap"] >= them["ad"] * 2:
            out.append("Enemy damage is mostly AP — an early MR item swings fights.")
    if them["n"] >= 4 and them["front"] == 0:
        out.append("They have no real frontline — dive their carries, win the chaos.")
    if them["engage"] >= 3:
        out.append("Heavy engage comp — respect all-ins; hold summs/peel for their dive.")
    elif them["n"] >= 4 and them["engage"] <= 1:
        out.append("Low enemy engage — you pick the fights; poke, then all-in when they group.")
    if me["n"] >= 4 and me["front"] == 0:
        out.append("No frontline on your team — play for picks, avoid messy 5v5s.")
    return out[:3]


MIN_MASTERY = 5         # only suggest champs you're at LEAST this mastery level on
PREF_MASTERY = 7        # ...preferring mastery 7+ ("comfort") first


def suggest_champs(dd, role, ally_ids, enemy_ids, topn=4, fam=None):
    """A few role-appropriate champ suggestions for champ select, scored by enemy counters
    (op.gg) + ally comp fit. When `fam` (a {championId: masteryLevel} map) is given, it ONLY
    suggests champs you're mastery MIN_MASTERY+ on, mastery 7+ first — never a champ you can't
    play. If mastery is unavailable (client closed / API down) it falls back to the meta ranking
    so the section isn't just empty."""
    role = lb.ROLE.get((role or "").lower(), (role or "").lower())
    if role not in _ROLE_FALLBACK:
        return []
    ally_ids = tuple(sorted(i for i in ally_ids if i))
    enemy_ids = tuple(sorted(i for i in enemy_ids if i))
    have_fam = bool(fam)
    elig = {c: lvl for c, lvl in (fam or {}).items() if (lvl or 0) >= MIN_MASTERY}   # M5+ only
    ck = (role, ally_ids, enemy_ids, have_fam, frozenset(elig.items()))
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

    def _key(kv):
        cid, s = kv
        base = (s["sum"] / max(1, s["n"])) + s.get("comp", 0.0)
        lvl = elig.get(cid, 0)                 # M7+ first, then M5/6, then the meta score
        return (lvl >= PREF_MASTERY, lvl, base, s["play"])
    ranked = sorted(scores.items(), key=_key, reverse=True)
    if have_fam:
        # HARD mastery gate: only champs you're M5+ on. No meta fallback — better to show fewer
        # than to suggest a champ you don't play.
        picked = [cid for cid, _ in ranked if cid in elig and cid not in banned][:topn]
    else:
        picked = [cid for cid, _ in ranked if cid not in banned][:topn]
        if len(picked) < topn:                 # mastery unknown -> old meta fill so it's not empty
            for nm in _ROLE_FALLBACK[role]:
                cid = dd["name2id"].get(dd["norm"](nm))
                if cid and cid not in banned and cid not in picked:
                    picked.append(cid)
                if len(picked) >= topn:
                    break
    _PICK_CACHE[ck] = picked
    return picked


_BAN_CACHE = {}


def suggest_bans(dd, my_cid, role, taken=(), topn=3):
    """Good bans for YOUR champ: op.gg counters you statistically lose to (your WR into
    them, min sample), boosted when the counter is itself strong this patch (their own
    overall WR in your role - the 'extremely OP' factor). Skips already banned/picked."""
    if not my_cid:
        return []
    role = lb.ROLE.get((role or "").lower(), (role or "").lower())
    if not role:                                   # blind pick / no assigned position -> the
        try:                                       # champ's most-played role (else no data at all,
            import lolitems as _li                 # which showed as 'lock or hover' despite a lock)
            role = _li.primary_role(dd, my_cid)
        except Exception:
            role = "mid"
    ck = (my_cid, role)
    if ck in _BAN_CACHE:
        cands = _BAN_CACHE[ck]
    else:
        try:
            d = lb.opgg(my_cid, role)
        except Exception:
            return []
        raw = []
        for c in d.get("counters", []):
            play = c.get("play", 0) or 0
            if not c.get("champion_id") or play < 60:
                continue
            my_wr = (c.get("win", 0) / play) * 100.0
            if my_wr < 49.0:                       # you actually lose this matchup
                raw.append((c["champion_id"], my_wr, play))
        raw.sort(key=lambda x: x[1])               # hardest counters first
        cands = []
        for cid, my_wr, play in raw[:6]:            # OP-boost only the finalists (cached calls)
            op = 0.0
            try:
                av = (lb.opgg(cid, role).get("summary") or {}).get("average_stats") or {}
                op = max(0.0, (float(av.get("win_rate") or 0.5) * 100.0) - 50.0)
            except Exception:
                pass
            cands.append((cid, (49.0 - my_wr) * 2.0 + op * 1.5, my_wr))
        cands.sort(key=lambda x: -x[1])
        if len(_BAN_CACHE) > 32:
            _BAN_CACHE.clear()
        _BAN_CACHE[ck] = cands
    out = [(cid, my_wr) for cid, _s, my_wr in cands if cid not in set(taken)]
    return out[:topn]


def _ban_icon(img, dd, cid, x, y, size, slash=True):
    """A grayed champ icon with a red slash - the universal 'banned' visual."""
    ic = get_icon(dd, cid, size)
    if not ic:
        return
    try:
        gray = ImageOps.grayscale(ic).convert("RGBA")
        gray.putalpha(ic.getchannel("A"))
        img.paste(gray, (x, y), gray)
        if slash:
            dr = ImageDraw.Draw(img)
            dr.line([x + 3, y + size - 3, x + size - 3, y + 3], fill=(206, 86, 94), width=2)
    except Exception:
        img.paste(ic, (x, y), ic)


def _draw_draft_band(d, img, dd, x0, y0, w, bans, enemy_picks, ban_ideas):
    """Champ-select intel band: GOOD BANS (your hardest counters) · the lobby's bans · any
    visible enemy picks."""
    _rrect(d, (x0, y0, x0 + w, y0 + 52), 9, fill=(20, 23, 32), outline=PEDGE, width=1)
    x = x0 + 14
    # --- good bans ---
    d.text((x, y0 + 6), "GOOD BANS", font=font(9, 1), fill=GOLD)
    if ban_ideas:
        for cid, my_wr in ban_ideas[:3]:
            ic = get_icon(dd, cid, 28)
            if ic:
                img.paste(ic, (x, y0 + 19), ic)
            d.text((x + 32, y0 + 25), f"{my_wr:.0f}%", font=font(9), fill=REDWR)
            x += 62
    elif ban_ideas is not None:                    # champ known, but nothing statistically scary
        d.text((x, y0 + 26), "no hard counters — ban comfort/meta", font=font(10), fill=MUTED)
        x += 150
    else:                                          # truly no champ hovered yet
        d.text((x, y0 + 26), "hover your champ for ban ideas", font=font(10), fill=MUTED)
        x += 150
    x = max(x, x0 + 210) + 18
    d.line([x - 12, y0 + 8, x - 12, y0 + 44], fill=PEDGE, width=1)
    # --- lobby bans ---
    bm, bt = (bans or ({}, {}))[0] or [], (bans or ((), ()))[1] or []
    d.text((x, y0 + 6), "BANS", font=font(9, 1), fill=(125, 166, 216))
    bx = x
    for cid in bm[:5]:
        _ban_icon(img, dd, cid, bx, y0 + 19, 26)
        bx += 30
    if bm and bt:
        d.text((bx + 3, y0 + 24), "·", font=font(12, 1), fill=MUTED)
        bx += 14
    for cid in bt[:5]:
        _ban_icon(img, dd, cid, bx, y0 + 19, 26)
        bx += 30
    if not (bm or bt):
        d.text((x, y0 + 26), "none yet", font=font(10), fill=MUTED)
        bx = x + 70
    # --- enemy picks (visible in some queues / after reveal) ---
    x = max(bx + 26, x0 + 560)
    d.line([x - 12, y0 + 8, x - 12, y0 + 44], fill=PEDGE, width=1)
    d.text((x, y0 + 6), "ENEMY PICKS", font=font(9, 1), fill=(216, 130, 130))
    if enemy_picks:
        for cid in enemy_picks[:5]:
            ic = get_icon(dd, cid, 26)
            if ic:
                img.paste(ic, (x, y0 + 19), ic)
            x += 30
    else:
        d.text((x, y0 + 26), "hidden in ranked", font=font(10), fill=MUTED)


VW = 384                 # width of the vertical (docked) champ-select panel


def _auto_chip(d, x, y, on, hits):
    """The AUTO toggle drawn beside the import button; clicking flips cfg.auto_import."""
    label = "AUTO ✓" if on else "AUTO"
    f = font(9, 1, label)
    w = int(d.textlength(label, font=f)) + 18
    fill = (34, 64, 46) if on else (30, 34, 46)
    edge = (95, 200, 126) if on else PEDGE
    _rrect(d, (x, y, x + w, y + 22), 7, fill=fill, outline=edge, width=1)
    d.text((x + 9, y + 5), label, font=f, fill=(150, 220, 170) if on else MUTED)
    if hits is not None:
        hits.append((x, y, x + w, y + 22, "action:toggle_auto_import"))
    return w


def _rune_chip(d, x, y, idx, wr, sel, hits):
    """A little clickable rune-set tab: '1 · 52%'. Selected one is highlighted green."""
    label = f"{idx + 1} · {wr:.0f}%"
    f = font(9, 1)
    w = int(d.textlength(label, font=f)) + 16
    fill = (40, 54, 40) if sel else (28, 32, 44)
    edge = (140, 190, 118) if sel else PEDGE
    _rrect(d, (x, y, x + w, y + 20), 6, fill=fill, outline=edge, width=1)
    d.text((x + 8, y + 4), label, font=f, fill=(178, 222, 150) if sel else MUTED)
    if hits is not None:
        hits.append((x, y, x + w, y + 20, f"action:rune:{idx}"))
    return w


def render_cs_vertical(dd, my_cid, my_role, allies, build, suggestions=None, bans=None,
                       enemy_picks=None, ban_ideas=None, dodge=None, auto_import=False,
                       note=None, favs=None):
    """The champ-select helper as a TALL panel meant to dock LEFT of the League client:
    your champ + runes + core icons + import, suggested picks, good bans, lobby bans, and
    your team - stacked vertically. Returns a PIL image with .hitmap for the import button."""
    H = 1130
    img = Image.new("RGB", (VW, H), BG)
    d = ImageDraw.Draw(img)
    hits = []
    if build:
        build = pick_rune(build)                   # show/import the selected rune set (#3)
    # header: splash strip + champ + role
    if my_cid:
        strip = get_splash(dd, my_cid, (VW, 84))
        if strip:
            img.paste(strip, (0, 0))
            shade = Image.new("L", (VW, 84), 0)
            sd = ImageDraw.Draw(shade)
            for yy in range(84):
                sd.line([(0, yy), (VW, yy)], fill=min(255, 140 + int(yy * 1.5)))
            img.paste(Image.new("RGB", (VW, 84), BG), (0, 0), shade)
    ic = get_icon(dd, my_cid, 52)
    if ic:
        img.paste(ic, (14, 14), ic)
    d.text((78, 16), dd["id2name"].get(my_cid, "pick a champ"), font=font(17, 1), fill=GOLD)
    sub = (my_role or "?").upper()
    if build:
        sub += f"   ·   {build['wr']:.1f}%  {build['tier']}"
    d.text((78, 44), sub, font=font(11, 1), fill=TEXT)
    d.text((VW - 12, 6), "SMITELESS", font=font(8, 1), fill=(120, 118, 108), anchor="ra")
    y = 92
    if dodge:
        _rrect(d, (10, y, VW - 10, y + 26), 8, fill=(70, 26, 30), outline=(206, 86, 94), width=1)
        d.text((VW // 2, y + 13), "⚠ CONSIDER DODGING — " + str(dodge.get("losing", "")) + " lanes behind",
               font=font(10, 1, "⚠"), fill=(240, 150, 150), anchor="mm")
        y += 34
    # runes + build card
    if build:
        card_h = 214
        _rrect(d, (10, y, VW - 10, y + card_h), 10, fill=(20, 23, 32), outline=PEDGE, width=1)
        x = 24
        d.text((x, y + 10), "RUNES", font=font(9, 1), fill=GOLD)
        opts = build.get("rune_options") or []
        if len(opts) > 1:                                  # rune-set picker (#3): click to switch
            cxr = 78
            for oi, opt in enumerate(opts):
                cxr += _rune_chip(d, cxr, y + 6, oi, opt.get("rune_wr", 0.0),
                                  oi == get_rune_idx(), hits) + 6
        d.text((x, y + 24), build.get("keystone", ""), font=font(14, 1), fill=TEXT)
        minor = "  ·  ".join(r for r in build.get("primary", [])[1:] if r)
        for i, ln in enumerate(_wrap(minor, font(10), VW - 48)[:2]):
            d.text((x, y + 46 + i * 14), ln, font=font(10), fill=MUTED)
        sec = "  ·  ".join(r for r in build.get("secondary", []) if r)
        d.text((x, y + 76), f"{build.get('secondary_tree', '')}: {sec}"[:60], font=font(10), fill=(150, 170, 200))
        shards = " / ".join(s for s in build.get("shards", []) if s)
        d.text((x, y + 92), f"Shards: {shards}", font=font(10), fill=MUTED)
        d.line([x, y + 110, VW - 24, y + 110], fill=PEDGE, width=1)
        d.text((x, y + 116), "CORE BUILD", font=font(9, 1), fill=GOLD)
        ix = x
        for j, iid in enumerate((build.get("core_ids") or [])[:4]):
            iic = get_item_icon(dd, iid, 32)
            if iic:
                _rrect(d, (ix - 1, y + 131, ix + 33, y + 165), 6, outline=PEDGE, width=1)
                img.paste(iic, (ix, y + 132), iic)
            if j < min(len(build.get("core_ids") or []), 4) - 1:
                d.text((ix + 37, y + 141), "›", font=font(12, 1), fill=MUTED)
            ix += 48
        d.text((x, y + 172), "Summs: " + " / ".join(build.get("summs", [])), font=font(10), fill=MUTED)
        sk = [s for s in build.get("skills", []) if s]
        if sk:
            d.text((x + 170, y + 172), "Max: " + " > ".join(sk), font=font(10), fill=MUTED)
        bx, by, bw, bh = x, y + 186, 160, 22
        _rrect(d, (bx, by, bx + bw, by + bh), 7, fill=(35, 44, 68), outline=(72, 86, 120), width=1)
        d.text((bx + bw // 2, by + bh // 2), "Import runes + summs", font=font(9, 1), fill=TEXT, anchor="mm")
        hits.append((bx, by, bx + bw, by + bh, "action:import_build"))
        aw = _auto_chip(d, bx + bw + 8, by, auto_import, hits)
        if note:
            d.text((bx + bw + 8 + aw + 8, by + 5), note, font=font(9, text=note), fill=GREEN)
        y += card_h + 10
    else:
        d.text((20, y + 6), "lock or hover a champ for runes + build", font=font(11), fill=MUTED)
        y += 30
    # GAME PLAN — comp win-conditions, shown the moment the enemy team locks in (draft).
    plan = game_plan(dd, [c for c, _ in (allies or []) if c], enemy_picks or [])
    if plan:
        wrapped = []
        for b in plan:
            wrapped += _wrap("▸ " + b, font(10), VW - 42)[:2]
        ph_ = 22 + len(wrapped) * 14 + 4
        _rrect(d, (10, y, VW - 10, y + ph_ - 4), 9, fill=(22, 25, 34), outline=PEDGE, width=1)
        d.text((22, y + 6), "GAME PLAN", font=font(9, 1), fill=GOLD)
        for i, ln in enumerate(wrapped):
            d.text((22, y + 22 + i * 14), ln, font=font(10, text="▸"), fill=(206, 210, 218))
        y += ph_ + 6
    # YOUR favorites, in your priority order, filtered to what's still open for your role
    # (#5, recommend-only: no hover/lock, purely "pick one of these").
    if favs:
        d.text((20, y), "YOUR PICKS", font=font(9, 1), fill=(214, 184, 120))
        xx = 20
        for rank_i, cid in enumerate(favs[:6]):
            fic = get_icon(dd, cid, 40)
            if fic:
                img.paste(fic, (xx, y + 16), fic)
                _rrect(d, (xx, y + 16, xx + 15, y + 30), 4, fill=(0, 0, 0))
                d.text((xx + 3, y + 17), str(rank_i + 1), font=font(9, 1), fill=GOLD)
            xx += 50
        y += 66
    # suggested picks (horizontal icons) — click a face to HOVER it in champ select (not lock)
    d.text((20, y), "GOOD THIS GAME", font=font(9, 1), fill=GOLD)
    if suggestions:
        d.text((VW - 12, y + 1), "click to hover", font=font(8), fill=(120, 118, 108), anchor="ra")
    xx = 20
    for cid in (suggestions or [])[:6]:
        sic = get_icon(dd, cid, 40)
        if sic:
            img.paste(sic, (xx, y + 16), sic)
        hits.append((xx, y + 16, xx + 40, y + 56, f"action:pick:{cid}"))
        xx += 50
    if not suggestions:
        d.text((20, y + 20), "no mastery-5+ picks for this role", font=font(10), fill=MUTED)
    y += 66
    # good bans
    d.text((20, y), "GOOD BANS", font=font(9, 1), fill=GOLD)
    if ban_ideas:
        xx = 20
        for cid, my_wr in ban_ideas[:3]:
            bic = get_icon(dd, cid, 34)
            if bic:
                img.paste(bic, (xx, y + 16), bic)
            d.text((xx + 17, y + 54), f"{my_wr:.0f}%", font=font(9), fill=REDWR, anchor="ma")
            xx += 58
    elif ban_ideas is not None:
        d.text((20, y + 20), "no hard counters — ban comfort/meta", font=font(10), fill=MUTED)
    else:
        d.text((20, y + 20), "hover your champ for ban ideas", font=font(10), fill=MUTED)
    y += 74
    # lobby bans
    bm, bt = (bans or ((), ()))[0] or [], (bans or ((), ()))[1] or []
    d.text((20, y), "BANS", font=font(9, 1), fill=(125, 166, 216))
    xx = 20
    for cid in bm[:5]:
        _ban_icon(img, dd, cid, xx, y + 15, 26)
        xx += 30
    if bm and bt:
        d.text((xx + 4, y + 20), "·", font=font(12, 1), fill=MUTED)
        xx += 16
    for cid in bt[:5]:
        _ban_icon(img, dd, cid, xx, y + 15, 26)
        xx += 30
    if not (bm or bt):
        d.text((60, y), "none yet", font=font(9), fill=MUTED)
    y += 52
    # enemy picks when a queue reveals them
    if enemy_picks:
        d.text((20, y), "ENEMY PICKS", font=font(9, 1), fill=(216, 130, 130))
        xx = 20
        for cid in enemy_picks[:5]:
            eic = get_icon(dd, cid, 26)
            if eic:
                img.paste(eic, (xx, y + 15), eic)
            xx += 30
        y += 52
    # your team
    d.text((20, y), "YOUR TEAM", font=font(9, 1), fill=(125, 166, 216))
    y += 16
    for cid, role in (allies or [])[:5]:
        _rrect(d, (12, y, VW - 12, y + 40), 8, fill=ALLY_BG, outline=PEDGE, width=1)
        if cid:
            aic = get_icon(dd, cid, 30)
            if aic:
                img.paste(aic, (20, y + 5), aic)
            me = (cid == my_cid)
            d.text((58, y + 11), dd["id2name"].get(cid, "?") + ("  YOU" if me else ""),
                   font=font(12, 1), fill=GOLD if me else TEXT)
        else:
            d.text((58, y + 11), "picking…", font=font(11), fill=MUTED)
        rl = lb.ROLE.get((role or "").lower(), role or "")
        if rl:
            cf = font(8, 1)
            cw_ = d.textlength(rl.upper(), font=cf)
            _rrect(d, (VW - 26 - cw_ - 12, y + 11, VW - 26, y + 27), 6, fill=(30, 34, 46), outline=PEDGE, width=1)
            d.text((VW - 32 - cw_ / 2 - 3, y + 14), rl.upper(), font=cf, fill=(150, 148, 138), anchor="ma")
        y += 46
    d.text((20, y + 6), "enemies hidden in ranked · board opens at loading screen",
           font=font(9), fill=(110, 108, 100))
    out = img.crop((0, 0, VW, min(H, y + 26)))    # trim the unused tail; panel ends after the team
    out.hitmap = hits
    out.dock_left = True                          # smiteoverlay: park this next to the client
    return out


def render_image(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map, source, note="", roles_known=True, live=True, lane_tip=None, champ_select=False, suggestions=None, dodge=None, bans=None, enemy_picks=None, ban_ideas=None, live_gank=None):
    panel = bool(roles_known and not champ_select and my_role and my_role != "jungle" and my_role in dict(ROLES))
    tip_lines = _wrap(lane_tip, font(12), (W - 32) - 28) if (panel and lane_tip) else []
    panel_h = (77 + len(tip_lines) * 18) if tip_lines else (108 if panel else 0)
    band_h = 60 if champ_select else 0           # draft-intel band: good bans · bans · enemy picks
    # game plan: comp-level win conditions (in-game / loading, once both teams are known)
    plan = game_plan(dd, list(ally_role.values()), list(enemy_role.values())) if (roles_known and not champ_select and enemy_role) else []
    plan_h = (20 + len(plan) * 15 + 6) if plan else 0
    H = ((TOP + 5 * ROWH + 12 + panel_h + 48) if panel else (TOP + 5 * ROWH + 46 + band_h)) + plan_h
    rail_w = 96 if (champ_select and suggestions) else 0
    W2 = W + rail_w
    xoff = rail_w
    img = Image.new("RGB", (W2, H), BG)
    d = ImageDraw.Draw(img)
    hits = []                                    # clickable icon rects -> op.gg URL
    if my_cid:                                   # splash strip behind the header (all boards)
        strip = get_splash(dd, my_cid, (W2, 66))
        if strip:
            img.paste(strip, (0, 0))
            shade = Image.new("L", (W2, 66), 0)
            sd = ImageDraw.Draw(shade)
            for yy_ in range(66):                # darken evenly + fade to BG at the bottom edge
                sd.line([(0, yy_), (W2, yy_)], fill=min(255, 150 + int(yy_ * 1.6)))
            img.paste(Image.new("RGB", (W2, 66), BG), (0, 0), shade)
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
    duo_all = detect_duos(scout_map) if (roles_known and not champ_select) else {}
    duo_of = duo_all if DUO_ON else {}
    if roles_known and not champ_select:
        qr = queue_prediction(my_cid, scout_map, duo_all)
        ga, ge = team_avg_grades(scout_map)          # grade-based read alongside the WR read
        text = qr["text"] + (f"   ·   grades {ga} vs {ge}" if (ga and ge) else "")
        qf = font(10, 1)
        tw = d.textlength(text, font=qf)
        qx0, qx1 = cxc - (tw / 2) - 10, cxc + (tw / 2) + 10
        _rrect(d, (qx0, 69, qx1, 87), 8, fill=qr["bg"], outline=PEDGE, width=1)
        d.text((cxc, 78), text, font=qf, fill=qr["fill"], anchor="mm")
    if champ_select and dodge:
        txt = "⚠ CONSIDER DODGING — " + dodge["reason"]
        bf = font(12, 1, txt)
        tw = d.textlength(txt, font=bf)
        bx0, bx1 = cxc - tw / 2 - 12, cxc + tw / 2 + 12
        _rrect(d, (bx0, 68, bx1, 92), 8, fill=(70, 26, 30), outline=(206, 86, 94), width=1)
        d.text((cxc, 80), txt, font=bf, fill=(240, 150, 150), anchor="mm")
    if champ_select and build:
        draw_build_block(d, img, dd, cxc + 50, TOP + 16, build, hits=hits)
    # gank scores for every enemy lane FIRST, so labels can be RELATIVE (someone is always
    # the strong side, someone the weak side) and shifted by the live game state.
    glabels = {}
    if roles_known and not champ_select:
        gscores = {}
        for role, _lbl in ROLES:
            e_cid = enemy_role.get(role)
            if not e_cid or role == my_role:
                continue
            es = scout_map.get((e_cid, False))
            a = (es["n"], es["w"], es["cg"], es["cw"], es.get("form")) if es else (0, 0, 0, 0, None)
            s = gank_score(lanes.get(role), *a, self_kit=my_kit)
            if live_gank:
                s += float(live_gank.get(role, 0.0))
            gscores[role] = s
        glabels = rank_gank_labels(gscores)
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
            if role in glabels:
                draw_badge(d, cxc, y + 25, glabels[role])
            else:
                d.text((cxc, y + 28), "vs", font=font(10), fill=(100, 98, 92), anchor="ma")
        elif champ_select:
            cf = font(9, 1)
            cw_ = d.textlength(lbl.upper(), font=cf)
            _rrect(d, (384, y + 20, 384 + cw_ + 14, y + 36), 7, fill=(30, 34, 46), outline=PEDGE, width=1)
            d.text((391, y + 24), lbl.upper(), font=cf, fill=(150, 148, 138))
    if champ_select and suggestions:
        # Draw this AFTER the team rows so it can't be covered by row backgrounds. Header and
        # icons are flush top-left of the rail; tight vertical step fits 5 suggestions.
        sx, sy = 6, TOP + 2
        _rrect(d, (sx, sy, sx + 78, sy + 322), 10, fill=(20, 24, 34), outline=PEDGE, width=1)
        d.text((sx + 9, sy + 9), "GOOD THIS", font=font(9, 1), fill=GOLD, anchor="la")
        d.text((sx + 9, sy + 21), "GAME", font=font(9, 1), fill=GOLD, anchor="la")
        yy = sy + 40
        for cid in suggestions[:5]:
            ic = get_icon(dd, cid, 36)
            if ic:
                img.paste(ic, (sx + 9, yy), ic)
            yy += 56
    ly = TOP + 5 * ROWH + 12
    if champ_select and band_h:
        _draw_draft_band(d, img, dd, 16 + xoff, ly, W2 - xoff - 32, bans, enemy_picks, ban_ideas)
        ly += band_h
    if panel:
        opp = enemy_role.get(my_role)
        draw_lane_panel(d, img, dd, 16 + xoff, ly, W2 - xoff - 32, my_cid, my_role, opp,
                        lanes.get(my_role), scout_map.get((opp, False)) if opp else None,
                        tip_lines, panel_h)
        ly += panel_h + 14
    if plan:
        _rrect(d, (12 + xoff, ly, W2 - 12, ly + plan_h - 4), 8, fill=(22, 25, 34), outline=PEDGE, width=1)
        d.text((22 + xoff, ly + 6), "GAME PLAN", font=font(9, 1), fill=GOLD)
        for i, b in enumerate(plan):
            d.text((22 + xoff, ly + 22 + i * 15), "▸ " + b, font=font(10, text="▸"), fill=(206, 210, 218))
        ly += plan_h
    _legend = "rank · L10 W/L · mastery · S-F = how they've been playing (recent W/L + KDA, not rank) · ● duo = premade   |   ★ gank = strong side, avoid = weak side (live)   |   click → u.gg"
    d.text((16 + xoff, ly), _legend, font=font(11, text=_legend), fill=(120, 118, 110))
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
    auto_done = 0                         # champ we already auto-imported for (once per lock)
    auto_note = None                      # "auto-imported ✓" note shown on the panel
    last_cs_sig = None                    # champ-select frame signature (skip identical re-renders)
    shown = False                         # have we rendered a real session (champ select / game)?
    inactive = 0                          # consecutive reads with the client out of an active phase
    acct_captured = False                 # auto-remember the logged-in account once per session
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
        # allow_unlocked: show the champ-select panel the moment champ select opens, before
        # you've hovered anything (resolve otherwise treats "no champ hovered yet" as an error).
        info, err = lg.resolve(dd, allow_unlocked=True)
        if err:                            # in an active phase but nothing resolvable yet (loading)
            time.sleep(3)
            continue
        shown = True                       # resolve succeeded -> we're in a session
        if not acct_captured:              # remember this account (main/smurf) for pooled familiarity
            acct_captured = True

            def _cap():
                try:
                    ca = lg.current_account()
                    if ca:
                        ls.remember_account(ca[1], source="auto")
                except Exception:
                    pass
            threading.Thread(target=_cap, daemon=True).start()
        my_cid, my_role = info["my"], info["pos"]
        allies, enemies = info["allies"], info["enemies"]
        ally_role = {r: c for c, r in allies if r and c}
        enemy_role = {r: c for c, r in enemies if r and c}
        if my_cid and my_cid != build_cid:        # (re)fetch on champ change (champ-select hover/lock)
            build = build_data(dd, my_cid, my_role)
            build_cid = my_cid
            set_rune_idx(0)                        # new champ -> back to the most-played rune set
        src = info.get("source", "")
        if not enemy_role:                 # champ select / loading: enemies + scout not live yet
            if src == "champ select":
                # CHAMP SELECT: show your team forming + your runes/build the moment champ
                # select opens (even before anyone's hovered) — the panel is useful right away
                # (your role, suggested picks, good bans). We still only RE-render when a pick
                # actually changes, via the signature below, so it doesn't flicker/grab focus.
                bans_my = info.get("bans_my") or []
                bans_their = info.get("bans_their") or []
                # AUTO-IMPORT: the moment the champ is LOCKED (not hovered), push runes+summs
                # once. A different lock (re-pick) imports again; failures show on the panel.
                if (settings.get("auto_import", False) and info.get("locked")
                        and my_cid and build and auto_done != my_cid):
                    auto_done = my_cid
                    try:
                        import lolimport as limp
                        limp.import_build(dd, my_cid, my_role, pick_rune(build))   # selected rune set
                        auto_note = "auto-imported ✓"
                    except Exception as e:
                        auto_note = f"auto-import failed: {str(e)[:38]}"
                    last_cs_sig = None            # re-render with the note
                ally_ids = [c for c, _ in allies if c]
                enemy_ids = [c for c, _ in enemies if c]
                taken = set(bans_my) | set(bans_their) | set(ally_ids) | set(enemy_ids)
                favs = recommend_favs(dd, my_role, taken, settings.get("fav_champs"))
                sig = (my_cid, my_role, tuple(sorted(ally_role.items())),
                       tuple(sorted((c, r) for c, r in enemies if c)), bool(build),
                       tuple(bans_my), tuple(bans_their),
                       bool(settings.get("auto_import", False)), auto_note,
                       get_rune_idx(), tuple(favs))
                if sig != last_cs_sig:
                    # champs you actually play, pooled across ALL your accounts (main + smurfs):
                    # the live current-account mastery merged with the cross-account aggregate.
                    sugg = suggest_champs(dd, my_role, ally_ids, enemy_ids, topn=5,
                                          fam=ls.familiarity(lg.my_mastery()))
                    # High-confidence dodge read from op.gg lane matchups once enough enemies lock.
                    dodge = dodge_read(dd, allies, enemies) if settings.get("dodge_alerts", True) else None
                    ideas = suggest_bans(dd, my_cid, my_role, taken=taken) if my_cid else None
                    if settings.get("dock_champ_select", True):
                        # tall panel that docks LEFT of the client (the overlay parks it there
                        # and nudges the client right if there's no room)
                        emit(render_cs_vertical(dd, my_cid, my_role, allies, build,
                             suggestions=sugg, bans=(bans_my, bans_their),
                             enemy_picks=enemy_ids, ban_ideas=ideas, dodge=dodge,
                             auto_import=bool(settings.get("auto_import", False)),
                             note=auto_note, favs=favs))
                    else:
                        emit(render_image(dd, my_cid, my_role, ally_role, {}, build, {}, {}, src,
                             "enemies are hidden in champ select - matchups + player scout load at the loading screen",
                             roles_known=True, live=False, champ_select=True, suggestions=sugg, dodge=dodge,
                             bans=(bans_my, bans_their), enemy_picks=enemy_ids, ban_ideas=ideas))
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
        live_box = {"adj": None}                      # live gank adjustments (evolves in-game)

        def paint(note=""):
            emit(render_image(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map,
                 src, note, lane_tip=tip_box["tip"], live_gank=live_box["adj"]))

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
        # DUO RE-CHECK (#4): if the initial scout left gaps (a player's match list came back
        # empty — rate-limit / transient failure), a real premade can go unflagged. Once, a
        # little later (so the rate-limit window clears), re-scout and fill those gaps, then
        # ask the loop to repaint. NOTE: Riot's API exposes no party/premade info, so duos are
        # always inferred from shared recent games; a genuine first-game-together pair that
        # shares no history still can't be detected — this only recovers ones we missed.
        rescan = {"repaint": False}
        gaps = [k for k, e in scout_map.items() if not e.get("mids")]
        if gaps:
            def _refill():
                time.sleep(20)
                try:
                    fresh = {}
                    for r in ls.iter_scout_struct(dd, n_scout):
                        if "error" in r:
                            return
                        fresh[(r["cid"], r["is_ally"])] = r
                    for k in gaps:
                        fr = fresh.get(k)
                        if fr and fr.get("mids"):
                            scout_map[k] = fr          # atomic item set; loop repaints below
                            rescan["repaint"] = True
                except Exception:
                    pass
            threading.Thread(target=_refill, daemon=True).start()
        # Overlay: board is complete -> keep it on screen and watch THIS game's phase.
        #   new champ select   -> refresh this same window to the new draft (don't go stale)
        #   game over (lobby)  -> close, so the next champ select opens fresh
        # Phase-driven, because lg.resolve can keep returning stale data after a session ends.
        miss, blip, restart = 0, 0, False
        while not stop():
            time.sleep(5)
            if rescan["repaint"]:                     # gap-fill found new duo data -> redraw
                rescan["repaint"] = False
                paint()
            ph = phasecheck.phase()
            if ph in ("InProgress", "GameStart", "Reconnect"):
                miss = blip = 0                       # still in this game
                # LIVE gank shift: strong/weak side follows the game state (deaths, level
                # deficits, deaths-in-progress). Repaint only when the read actually moves.
                try:
                    raw = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata",
                                  timeout=2, insecure=True)
                    adj = ll.lane_live_adj(dd, raw, ally_role, enemy_role)
                    if adj and adj != live_box["adj"]:
                        live_box["adj"] = adj
                        paint()
                except Exception:
                    pass
                continue
            if ph == "ChampSelect":                   # a NEW champ select -> refresh, don't close
                restart = True
                break
            if ph == "":                              # client unreachable (lag spike / closing) -> tolerate
                blip += 1
                if blip >= 6:                         # ~30s truly gone -> close out
                    return
                continue
            miss += 1                                 # a DEFINITE end phase (WaitingForStats/EndOfGame/Lobby/None)
            if miss >= 2:                             # ~10s after the game ends -> close so the profile takes over
                return
        if not restart:
            return                                    # stop() requested -> close
        build_cid, last_cs_sig = 0, None              # re-render fresh for the new champ select
        auto_done, auto_note = 0, None
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
