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
    situ = [s["ids"][0] for s in sorted((x for x in d.get("last_items", []) if x["play"] >= 120),
                                        key=lambda x: -x["win"] / x["play"])]
    # core path + situational finals, with boots filtered out (they're a per-game choice,
    # surfaced only by the dedicated boots cue) and de-duped while preserving order.
    seq = [i for i in (list(core) + situ) if not _is_boots(dd, i)]
    seq = list(dict.fromkeys(seq))
    cats = {i: _cats(dd, i) for i in set(seq) | set(boots)}
    pool = {"seq": seq, "boots": boots, "cats": cats}
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
    e_ad = e_ap = comp_ad = comp_ap = cc = 0
    healers, heal_items, fed = [], False, []
    for p in enemies:
        cid = dd["name2id"].get(dd["norm"](p.get("championName", ""))) or 0
        key = _key(dd, cid)
        items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
        for iid in items:
            st = (dd.get("item_data", {}).get(iid, {}) or {}).get("stats", {}) or {}
            e_ad += st.get("FlatPhysicalDamageMod", 0) or 0
            e_ap += st.get("FlatMagicDamageMod", 0) or 0
            info = dd.get("item_data", {}).get(iid, {}) or {}
            if "LifeSteal" in info.get("tags", []) or "SpellVamp" in info.get("tags", []):
                heal_items = True
        if key in AP_CHAMPS or "Mage" in dd.get("id2tags", {}).get(cid, []):
            comp_ap += 1
        else:
            comp_ad += 1
        if key in HEAL_CHAMPS:
            healers.append(dd["id2name"].get(cid, key))
        if key in CC_CHAMPS:
            cc += 1
        sc = p.get("scores") or {}
        k, dth = sc.get("kills", 0), sc.get("deaths", 0)
        if k - dth >= 4 and k >= 5:
            fed.append((dd["id2name"].get(cid, key), k, dth, "AP" if (key in AP_CHAMPS or "Mage" in dd.get("id2tags", {}).get(cid, [])) else "AD"))
    # real built damage decides once there's enough; else fall back to comp
    if e_ad + e_ap >= 80:
        threat = "AD" if e_ad >= e_ap else "AP"
    else:
        threat = "AD" if comp_ad >= comp_ap else "AP"
    return {"my_cid": my_cid, "my_role": (me.get("position") or "").lower(), "my_items": my_items,
            "my_gold": my_gold, "threat": threat, "e_ad": int(e_ad), "e_ap": int(e_ap),
            "healers": healers, "heal_items": heal_items, "cc": cc, "fed": fed}


def recommend(dd, st=None):
    """The headline guidance for the widget. Returns dict with champ name + ordered lines
    [(kind, text)] from op.gg's real pool, prioritised by the live threat. None if not in game."""
    st = st if st is not None else live_state(dd)
    if not st or not st["my_cid"]:
        return None
    pool = champ_pool(dd, st["my_cid"], st["my_role"] or "mid")
    owned, lines, used = st["my_items"], [], set()
    nm = lambda i: dd["items"].get(i, str(i))
    threat = st["threat"] if st["threat"] in ("AD", "AP") else "AD"
    want = {"AD": "armor", "AP": "mr"}[threat]
    fed = st["fed"]
    has = lambda cat, ids: any(cat in pool["cats"].get(i, set()) for i in ids) if pool else False

    def add(kind, iid, text):
        lines.append((kind, text))
        if iid:
            used.add(iid)

    # 1) defensive counter vs the dominant LIVE threat, from the champ's real pool
    if pool:
        cand = next((i for i in pool["seq"]
                     if want in pool["cats"].get(i, set()) and i not in owned and i not in used), None)
        if cand:
            why = (f"vs {fed[0][0]} {fed[0][1]}/{fed[0][2]}" if fed and fed[0][3] == threat
                   else (f"vs {st['e_ad']} AD built" if threat == "AD" else f"vs {st['e_ap']} AP built"))
            add("counter", cand, f"{nm(cand)}  ·  {why}")
    # 2) anti-heal if the enemy sustains and you don't already have it
    if (st["healers"] or st["heal_items"]) and not has("antiheal", owned):
        ah = next((i for i in pool["seq"] if "antiheal" in pool["cats"].get(i, set()) and i not in used), None) if pool else None
        tag = ", ".join(st["healers"][:2]) or "lifesteal"
        add("antiheal", ah, f"{nm(ah) if ah else 'Grievous Wounds item'}  ·  cut {tag} healing")
    # 3) the next standard build item (advances as you buy)
    if pool:
        nxt = next((i for i in pool["seq"] if i not in owned and i not in used), None)
        if nxt:
            add("build", nxt, f"{nm(nxt)}  ·  next core")
    # 4) boots cue vs heavy CC / magic
    if pool and pool["boots"] and not (owned & set(pool["boots"])) and (st["cc"] >= 3 or threat == "AP"):
        merc = next((b for b in pool["boots"] if "Mercury" in nm(b) and b not in used), None)
        if merc:
            add("boots", merc, f"{nm(merc)}  ·  vs {'CC' if st['cc'] >= 3 else 'magic dmg'}")

    summary = f"enemy {st['e_ad']} AD / {st['e_ap']} AP" + (f" · {len(fed)} fed" if fed else "")
    return {"champ": dd["id2name"].get(st["my_cid"], "?"), "lines": lines[:4],
            "summary": summary, "no_pool": pool is None}
