#!/usr/bin/env python3
"""lolitems.py - rule-based in-game item suggestions (no AI, no tokens).

Reads the enemy team's champions + their CURRENT items from the Live Client API
(port 2999), builds a threat profile (physical vs magic damage, healing, hard CC),
and suggests counter-items tailored to YOUR champion's class. As the enemy builds,
their actual items override the champ-class guess, so the read evolves through the game.
"""
import lolbuild as lb
import lolgame as lg

# Champs that deal primarily AP despite a non-Mage tag (Mage-tagged are caught by the tag).
AP_CHAMPS = {"Akali", "Ekko", "Fizz", "Diana", "Katarina", "Evelynn", "Gwen", "Teemo",
            "Kayle", "Rumble", "Mordekaiser", "Vladimir", "Singed", "Sylas", "Kennen",
            "Lillia", "Elise", "Nidalee", "Shaco", "Quinn"}
# Enemies with notable self/team healing -> push anti-heal.
HEAL_CHAMPS = {"Soraka", "Vladimir", "Aatrox", "DrMundo", "Swain", "Yuumi", "Nami",
              "Warwick", "Sylas", "Sett", "Fiora", "Briar", "Sona", "Renekton", "Illaoi",
              "Taric", "Yorick", "Olaf", "Ramus", "Gangplank", "Irelia", "Kayn"}
# Hard-CC champs -> push tenacity when several are present.
CC_CHAMPS = {"Leona", "Nautilus", "Maokai", "Sejuani", "Morgana", "Lux", "Ashe", "Amumu",
            "Rell", "Ornn", "Sion", "Malphite", "Lissandra", "Annie", "Veigar", "Zoe",
            "Ahri", "JarvanIV", "Rammus", "Skarner", "Neeko", "Galio", "Thresh",
            "Blitzcrank", "Pyke", "Vi", "Hecarim", "Gragas", "Poppy", "Camille", "Sett",
            "Zyra", "TwistedFate", "Cassiopeia", "Pantheon", "Nocturne", "Warwick"}

ARMOR = {  # vs mostly-physical enemy, by YOUR class
    "Tank": "Thornmail / Randuin's", "Fighter": "Frozen Heart / Randuin's",
    "Marksman": "Plated Steelcaps now, GA later", "Mage": "Zhonya's Hourglass",
    "Assassin": "Zhonya's / Guardian Angel", "Support": "Plated Steelcaps + Knight's Vow"}
MR = {     # vs mostly-magic enemy, by YOUR class
    "Tank": "Spirit Visage / Force of Nature", "Fighter": "Maw / Spirit Visage",
    "Marksman": "Maw / Wit's End", "Mage": "Banshee's Veil",
    "Assassin": "Maw / Mercurial", "Support": "Mercs + Force of Nature"}
ANTIHEAL = {"AD": "Mortal Reminder / Executioner's", "AP": "Morellonomicon",
            "mixed": "Chempunk Chainsword"}


def _key(dd, cid):
    return dd.get("id2key", {}).get(cid, "")


def damage_type(dd, cid, items=None):
    """'AD' or 'AP'. If the player's actual items carry enough damage stats, they decide;
    otherwise fall back to the champion's profile."""
    if items:
        ad = ap = 0
        for iid in items:
            st = (dd.get("item_data", {}).get(iid, {}) or {}).get("stats", {}) or {}
            ad += st.get("FlatPhysicalDamageMod", 0) or 0
            ap += st.get("FlatMagicDamageMod", 0) or 0
        if ad + ap >= 40:
            return "AD" if ad >= ap else "AP"
    if _key(dd, cid) in AP_CHAMPS:
        return "AP"
    return "AP" if "Mage" in dd.get("id2tags", {}).get(cid, []) else "AD"


def my_class(dd, cid):
    tags = dd.get("id2tags", {}).get(cid, [])
    for t in ("Marksman", "Mage", "Assassin", "Tank", "Fighter", "Support"):
        if t in tags:
            return t
    return "Fighter"


def live_threat(dd):
    """Enemy threat profile from the Live Client API, or None if not in a game."""
    try:
        d = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata", timeout=3, insecure=True)
    except Exception:
        return None
    players = d.get("allPlayers") or []
    if not players:
        return None
    ap = d.get("activePlayer") or {}
    myg = lg._gname(ap.get("riotId") or ap.get("summonerName") or "")
    me = next((p for p in players
               if lg._gname(p.get("riotId") or p.get("summonerName") or "") == myg), None)
    myteam = me.get("team") if me else "ORDER"      # spectator: ORDER = "your" side
    enemies = [p for p in players if p.get("team") != myteam]
    if not enemies:
        return None
    ad = apt = cc = 0
    healers, heal_items = [], False
    for p in enemies:
        cid = dd["name2id"].get(dd["norm"](p.get("championName", ""))) or 0
        items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
        if damage_type(dd, cid, items) == "AD":
            ad += 1
        else:
            apt += 1
        key = _key(dd, cid)
        if key in HEAL_CHAMPS:
            healers.append(dd["id2name"].get(cid, key))
        if key in CC_CHAMPS:
            cc += 1
        for iid in items:
            info = dd.get("item_data", {}).get(iid, {}) or {}
            if "LifeSteal" in info.get("tags", []) or "SpellVamp" in info.get("tags", []) \
                    or (info.get("stats", {}) or {}).get("PercentLifeStealMod", 0) > 0:
                heal_items = True
    return {"ad": ad, "ap": apt, "healers": healers, "heal_items": heal_items, "cc": cc}


def suggest(dd, my_cid, threat):
    """A single compact 'THREAT … -> BUY …' line, or None."""
    if not threat or not my_cid:
        return None
    cls = my_class(dd, my_cid)
    my_dmg = damage_type(dd, my_cid)
    ad, apt = threat["ad"], threat["ap"]
    buys = []
    if ad > apt:
        buys.append(ARMOR.get(cls, "armor"))
    elif apt > ad:
        buys.append(MR.get(cls, "magic resist"))
    else:
        buys.append("mixed dmg - boots + a flex resist")
    if threat["healers"] or threat["heal_items"]:
        buys.append(ANTIHEAL.get(my_dmg, "anti-heal"))
    if threat["cc"] >= 3:
        buys.append("Mercury's Treads / QSS")
    parts = [f"{ad} AD", f"{apt} AP"]
    if threat["healers"]:
        parts.append("heals: " + ", ".join(threat["healers"][:2]))
    elif threat["heal_items"]:
        parts.append("lifesteal")
    if threat["cc"] >= 3:
        parts.append(f"{threat['cc']} CC")
    return "THREAT: " + " · ".join(parts) + "   →   BUY: " + " · ".join(buys[:3])
