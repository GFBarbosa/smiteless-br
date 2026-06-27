#!/usr/bin/env python3
"""lolitems.py - in-game item guidance from op.gg's REAL per-champ item pool (no AI).

The build path and the situational items come straight from op.gg for YOUR champ+role
(the same source as the build card), so they're always champ-correct. The live game then
drives them: your owned items advance the "next item", and the enemy's ACTUAL built damage
+ who's fed decide which defensive piece to surface. Everything updates as the game evolves.
"""
import time
import lolbuild as lb
import lolgame as lg

# Champs that deal primarily AP despite a non-Mage tag (used only as an early fallback,
# before the enemy has enough items to read their real damage).
AP_CHAMPS = {"Akali", "Ekko", "Fizz", "Diana", "Katarina", "Evelynn", "Gwen", "Teemo",
            "Kayle", "Rumble", "Mordekaiser", "Vladimir", "Singed", "Sylas", "Kennen",
            "Lillia", "Elise", "Nidalee", "Shaco", "Quinn"}
HEAL_CHAMPS = {"Soraka", "Vladimir", "Aatrox", "DrMundo", "Swain", "Yuumi", "Nami",
              "Warwick", "Sylas", "Sett", "Fiora", "Briar", "Sona", "Renekton", "Illaoi",
              "Taric", "Yorick", "Olaf", "Gangplank", "Irelia", "Kayn", "Ramus"}
# Heal-CENTRIC champs: sustain is core to their fights, so anti-heal is worth it whenever
# they're not behind. The rest of HEAL_CHAMPS heal a bit, but only warrant anti-heal once
# they're fed (or are the enemy you're actually fighting) - otherwise it's just noise.
HEAVY_HEAL = {"Soraka", "Vladimir", "Aatrox", "DrMundo", "Swain", "Yuumi", "Nami",
             "Warwick", "Sylas", "Briar", "Fiora", "Sona", "Taric", "Sett"}
CC_CHAMPS = {"Leona", "Nautilus", "Maokai", "Sejuani", "Morgana", "Lux", "Ashe", "Amumu",
            "Rell", "Ornn", "Sion", "Malphite", "Lissandra", "Annie", "Veigar", "Zoe",
            "Ahri", "JarvanIV", "Rammus", "Skarner", "Neeko", "Galio", "Thresh",
            "Blitzcrank", "Pyke", "Vi", "Hecarim", "Gragas", "Poppy", "Camille", "Sett",
            "Zyra", "TwistedFate", "Cassiopeia", "Pantheon", "Nocturne", "Warwick"}

# Grievous-wounds (anti-heal) + stasis/revive items, matched by name (ddragon has no stat for them).
ANTIHEAL = ("Morellonomicon", "Oblivion Orb", "Executioner", "Mortal Reminder",
            "Chempunk", "Thornmail", "Bramble")
STASIS = ("Zhonya", "Guardian Angel", "Gargoyle", "Stopwatch")

_POOL = {}   # (cid, role) -> pool dict, cached for the session


def _key(dd, cid):
    return dd.get("id2key", {}).get(cid, "")


def _cats(dd, iid):
    """Defensive categories an item provides: armor / mr / hp / antiheal / stasis."""
    info = dd.get("item_data", {}).get(iid, {}) or {}
    tags, name = info.get("tags", []), info.get("name", "")
    c = set()
    if "Armor" in tags:
        c.add("armor")
    if "SpellBlock" in tags:
        c.add("mr")
    if "Health" in tags:
        c.add("hp")
    if any(a in name for a in ANTIHEAL):
        c.add("antiheal")
    if any(s in name for s in STASIS):
        c.add("stasis")
    return c


def _is_boots(dd, iid):
    return "Boots" in (dd.get("item_data", {}).get(iid, {}) or {}).get("tags", [])


def _is_crit(dd, iid):
    info = dd.get("item_data", {}).get(iid, {}) or {}
    return "CriticalStrike" in info.get("tags", []) or (info.get("stats", {}) or {}).get("FlatCritChanceMod", 0) > 0


_ROLE_CACHE = {}
_OPGG_POS = {"TOP": "top", "JUNGLE": "jungle", "MID": "mid", "MIDDLE": "mid",
             "ADC": "adc", "BOTTOM": "adc", "SUPPORT": "support", "UTILITY": "support"}


def _role_guess(dd, cid):
    tags = dd.get("id2tags", {}).get(cid, [])
    if "Marksman" in tags:
        return "adc"
    if "Support" in tags:
        return "support"
    if "Mage" in tags or "Assassin" in tags:
        return "mid"
    return "top"                                       # Tank / Fighter default


def primary_role(dd, cid):
    """The champ's most-played role (op.gg's positions[0]), for when the Live Client doesn't
    report a position - otherwise we'd fetch the wrong pool (e.g. Tahm Kench 'mid'). Cached."""
    if cid in _ROLE_CACHE:
        return _ROLE_CACHE[cid]
    guess = _role_guess(dd, cid)
    try:
        pos = (lb.opgg(cid, guess).get("summary") or {}).get("positions") or []
        role = _OPGG_POS.get((pos[0].get("name") or "").upper(), guess) if pos else guess
    except Exception:
        role = guess
    _ROLE_CACHE[cid] = role
    return role


def champ_pool(dd, cid, role):
    """op.gg's real item pool for this champ+role: an ordered build sequence (core path +
    situational finals) plus per-item defensive categories. Boots are kept SEPARATE (in
    pool["boots"]) because the right boots are a per-game pick - they never go in the core
    "next item" sequence. Cached."""
    role = lb.ROLE.get((role or "").lower(), (role or "").lower())
    ck = (cid, role)
    if ck in _POOL:
        return _POOL[ck]
    try:
        d = lb.opgg(cid, role)
    except Exception:
        return None
    if not d or not d.get("core_items"):
        return None
    core = max(d["core_items"], key=lambda x: x["play"])["ids"]
    boots = [b["ids"][0] for b in sorted(d.get("boots", []), key=lambda x: -x["play"])]
    # Keep EVERY situational item with a real sample (most-played first), not just the top
    # couple - otherwise a champ's armor/MR options get dropped and there's nothing to
    # suggest once core is done. play counts let the recommender rank which counter to build.
    last = d.get("last_items", [])
    situ = [s["ids"][0] for s in sorted((x for x in last if x["play"] >= 20), key=lambda x: -x["play"])]
    play = {s["ids"][0]: s["play"] for s in last}
    # core path + situational finals, with boots filtered out (per-game pick) and de-duped.
    seq = list(dict.fromkeys(i for i in (list(core) + situ) if not _is_boots(dd, i)))
    cats = {i: _cats(dd, i) for i in set(seq) | set(boots)}
    pool = {"seq": seq, "boots": boots, "cats": cats, "play": play}
    _POOL[ck] = pool
    return pool


def live_state(dd):
    """Read the live game: your champ/role/items/gold, plus the enemy's ACTUAL built
    damage, healing, CC and who's fed. None if not in a game."""
    try:
        d = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata", timeout=3, insecure=True)
    except Exception:
        return None
    players = d.get("allPlayers") or []
    if not players:
        return None
    act = d.get("activePlayer") or {}
    myg = lg._gname(act.get("riotId") or act.get("summonerName") or "")
    me = next((p for p in players
               if lg._gname(p.get("riotId") or p.get("summonerName") or "") == myg), None)
    if me is None:
        return None
    my_cid = dd["name2id"].get(dd["norm"](me.get("championName", ""))) or 0
    my_items = {it.get("itemID") for it in (me.get("items") or []) if it.get("itemID")}
    my_gold = int((act.get("currentGold") or 0))
    myteam = me.get("team")
    enemies = [p for p in players if p.get("team") != myteam]
    elist = []                                            # per-enemy threat profile
    healers, heal_items, cc = [], False, 0
    for p in enemies:
        cid = dd["name2id"].get(dd["norm"](p.get("championName", ""))) or 0
        key = _key(dd, cid)
        name = dd["id2name"].get(cid, key)
        items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
        iad = iap = 0
        crit = heal_item = False
        for iid in items:
            stt = (dd.get("item_data", {}).get(iid, {}) or {}).get("stats", {}) or {}
            tags = (dd.get("item_data", {}).get(iid, {}) or {}).get("tags", [])
            iad += stt.get("FlatPhysicalDamageMod", 0) or 0
            iap += stt.get("FlatMagicDamageMod", 0) or 0
            if "CriticalStrike" in tags or stt.get("FlatCritChanceMod", 0) > 0:
                crit = True
            if "LifeSteal" in tags or "SpellVamp" in tags:
                heal_item = True
        if iad + iap >= 40:                               # enough items to read their real damage
            dtype = "AD" if iad >= iap else "AP"
        else:                                             # early game: fall back to champ class
            dtype = "AP" if (key in AP_CHAMPS or "Mage" in dd.get("id2tags", {}).get(cid, [])) else "AD"
        dmg = iad if dtype == "AD" else iap
        sc = p.get("scores") or {}
        k, dth = sc.get("kills", 0), sc.get("deaths", 0)
        lead = k - dth
        # "danger" = the damage they've actually built, amplified hard by how fed they are -
        # so a fed enemy is who you build against, even if their team has more total of the
        # other damage type. (+40 base so even a 0-item enemy registers; champ-class fallback
        # via damage_type means it still works before items exist.)
        danger = (dmg + 40) * (1 + 0.35 * min(max(0, lead), 14))
        heals = (key in HEAL_CHAMPS) or heal_item
        if key in HEAL_CHAMPS:
            healers.append(name)
        heal_items = heal_items or heal_item
        if key in CC_CHAMPS:
            cc += 1
        elist.append({"name": name, "dtype": dtype, "dmg": int(dmg), "crit": crit, "heals": heals,
                      "heavy": key in HEAVY_HEAL, "k": k, "d": dth, "lead": lead, "danger": danger})
    if not elist:
        return None
    ad_score = sum(e["danger"] for e in elist if e["dtype"] == "AD")
    ap_score = sum(e["danger"] for e in elist if e["dtype"] == "AP")
    threat = "AD" if ad_score >= ap_score else "AP"
    primary = max(elist, key=lambda e: e["danger"])                        # scariest enemy overall
    of_type = [e for e in elist if e["dtype"] == threat]
    main = max(of_type, key=lambda e: e["danger"]) if of_type else primary  # scariest of the threat type
    # Anti-heal is only worth it when the healing actually matters - not just because some
    # enemy can heal. A healer counts if they're heal-CENTRIC and not behind, OR they're fed,
    # OR they're the enemy you're building against. Two+ healers also stack into a threat.
    heal_sig = [e["name"] for e in elist if e["heals"]
                and ((e["heavy"] and e["lead"] >= 0) or e["lead"] >= 4 or e is main)]
    n_healers = sum(1 for e in elist if e["heals"])
    heal_threat = bool(heal_sig) or n_healers >= 2
    heal_names = heal_sig or [e["name"] for e in elist if e["heals"]]
    return {"my_cid": my_cid, "my_role": (me.get("position") or "").lower(), "my_items": my_items,
            "my_gold": my_gold, "threat": threat,
            "e_ad": int(sum(e["dmg"] for e in elist if e["dtype"] == "AD")),
            "e_ap": int(sum(e["dmg"] for e in elist if e["dtype"] == "AP")),
            "healers": healers, "heal_items": heal_items, "cc": cc,
            "heal_threat": heal_threat, "heal_names": heal_names,
            "primary": primary, "main": main}


def _why(main, threat):
    """Short reason naming the biggest threat of the type we're countering."""
    if not main:
        return f"vs enemy {threat}"
    if main["lead"] >= 4:
        return f"vs fed {main['name']} ({main['k']}/{main['d']})"
    return f"vs {main['name']}'s {threat}"


def _pick_counter(dd, cands, threat, main, play):
    """Which armor/MR item to build from the matching options: crit -> Randuin's,
    healing/auto-attack AD -> Thornmail, otherwise the FINISHED item this champ builds most
    (a finished item beats a cheap component like Bramble Vest)."""
    if not cands:
        return None
    nm = lambda i: dd["items"].get(i, "")
    fin = lambda i: not (dd.get("item_data", {}).get(i, {}) or {}).get("into")   # no build-up = finished
    if threat == "AD" and main:
        if main.get("crit"):
            r = next((i for i in cands if "Randuin" in nm(i)), None)
            if r:
                return r
        if main.get("heals"):
            t = next((i for i in cands if "Thornmail" in nm(i)), None)
            if t:
                return t
    return max(cands, key=lambda i: (fin(i), play.get(i, 0)))   # finished first, then most-built


def recommend(dd, st=None):
    """The headline guidance for the widget. Returns dict with champ name + ordered lines
    [(kind, text)] from op.gg's real pool, prioritised by the BIGGEST live threat (fed-weighted).
    None if not in game."""
    st = st if st is not None else live_state(dd)
    if not st or not st["my_cid"]:
        return None
    role = st["my_role"] or primary_role(dd, st["my_cid"])   # Live Client often omits position
    pool = champ_pool(dd, st["my_cid"], role)
    owned, lines, used = st["my_items"], [], set()
    nm = lambda i: dd["items"].get(i, str(i))
    threat = st["threat"] if st["threat"] in ("AD", "AP") else "AD"
    want = {"AD": "armor", "AP": "mr"}[threat]
    main, primary = st.get("main"), st.get("primary")
    play = pool["play"] if pool else {}
    has = lambda cat, ids: any(cat in pool["cats"].get(i, set()) for i in ids) if pool else False

    def add(kind, iid, text):
        lines.append((kind, text))
        if iid:
            used.add(iid)

    # a real threat exists once enemies have built damage, or someone is meaningfully fed
    real = (st["e_ad"] + st["e_ap"] >= 80) or (primary and primary["lead"] >= 4)

    # 1) the defensive item to build vs the biggest threat, from THIS champ's pool. Fires all
    #    game (the most important time), not just while core is unfinished - picks Randuin's vs
    #    crit, Thornmail vs healing/auto AD, else what the champ builds most.
    if pool and real:
        cands = [i for i in pool["seq"]
                 if want in pool["cats"].get(i, set()) and i not in owned and i not in used]
        cand = _pick_counter(dd, cands, threat, main, play)
        if cand:
            add("counter", cand, f"{nm(cand)}  ·  {_why(main, threat)}")
    # 2) anti-heal - ONLY when the healing actually matters (a fed / heal-centric enemy, or
    #    the one you're fighting), not just because someone on the team can heal a little
    if st["heal_threat"] and not has("antiheal", owned):
        ah = next((i for i in pool["seq"] if "antiheal" in pool["cats"].get(i, set()) and i not in used), None) if pool else None
        tag = ", ".join(st["heal_names"][:2]) or "lifesteal"
        add("antiheal", ah, f"{nm(ah) if ah else 'Grievous Wounds item'}  ·  cut {tag} healing")
    # 3) the next standard build item (advances as you buy)
    if pool:
        nxt = next((i for i in pool["seq"] if i not in owned and i not in used), None)
        if nxt:
            add("build", nxt, f"{nm(nxt)}  ·  next item")
    # 4) boots cue vs heavy CC / magic
    if pool and pool["boots"] and not (owned & set(pool["boots"])) and (st["cc"] >= 3 or threat == "AP"):
        merc = next((b for b in pool["boots"] if "Mercury" in nm(b) and b not in used), None)
        if merc:
            add("boots", merc, f"{nm(merc)}  ·  vs {'CC' if st['cc'] >= 3 else 'magic dmg'}")

    if primary and primary["lead"] >= 4:
        summary = f"biggest threat: {primary['name']} {primary['k']}/{primary['d']}  ·  enemy {st['e_ad']} AD / {st['e_ap']} AP"
    else:
        summary = f"enemy {st['e_ad']} AD / {st['e_ap']} AP"
    return {"champ": dd["id2name"].get(st["my_cid"], "?"), "lines": lines[:4],
            "summary": summary, "no_pool": pool is None}
