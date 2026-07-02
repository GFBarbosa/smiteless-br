#!/usr/bin/env python3
"""lollive.py - live in-game intel from the Live Client Data API (:2999), no AI, no key.

Three reads off a single /liveclientdata/allgamedata fetch:
  - objectives(): next dragon / void-grub / baron spawn timers, event-driven (respawns come
    straight from the kill events, so they're correct regardless of patch tuning).
  - power_spike():the scariest enemy who has spiked (completed items) AND is ahead.
  - win_prob():   a transparent live win read from net item gold + levels + drakes (no model,
    just a logistic on the gold/level/objective lead - rough on purpose, tune with the consts).

All timings are Season-16 (2026) defaults and live at the top so they're trivial to dial in.
"""
import lolbuild as lb
import lolgame as lg

# ---- objective spawn model (seconds of game time). Respawns are event-driven (kill + delta);
#      first-spawn constants are the only patch-sensitive values, kept here for easy tuning. ----
DRAGON_FIRST, DRAGON_RESPAWN = 300, 300            # 5:00, then 5:00 after each kill
GRUBS_FIRST, GRUBS_RESPAWN, GRUBS_DESPAWN = 360, 240, 885   # 6:00, +4:00 once, gone ~14:45
BARON_FIRST, BARON_RESPAWN, BARON_OPEN = 1200, 360, 1140    # 20:00, +6:00; only show from 19:00
ALERT_LEAD = 45                                    # within this many seconds = "soon" (urgent)
SETUP_LEAD = 75                                    # inside this = start SETTING UP (shove + ward)

# ---- economy proxy weights for the win read (see win_prob) ----
LEVEL_GOLD = 130          # each champ level ~ this much "economy" (captures the XP lead)
KILL_GOLD = 230           # rough average bounty banked per kill
DRAKE_GOLD = 230          # standing value of a drake (buff + soul progress), per drake taken
BARON_GOLD = 1700         # an active baron is worth roughly this in pushing/teamfight power
GOLD_SCALE = 7000.0       # gold lead at which the read is ~73% - bigger = flatter curve


def _read():
    try:
        return lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata", timeout=3, insecure=True)
    except Exception:
        return None


def _events(data):
    return ((data.get("events") or {}).get("Events")) or []


def _last_time(events, name):
    """Game-time of the most recent event with this EventName, or None."""
    ts = [e.get("EventTime") for e in events if e.get("EventName") == name and e.get("EventTime") is not None]
    return max(ts) if ts else None


def _count(events, name):
    return sum(1 for e in events if e.get("EventName") == name)


def objectives(data):
    """Upcoming neutral objectives as [{label, secs, up, urgent}], soonest first.
    secs is time-to-spawn (<=0 means it's up now). Event-driven respawns stay correct
    even when Riot tweaks the numbers; only the first-spawn constants are patch-guessed."""
    gd = data.get("gameData") or {}
    gt = float(gd.get("gameTime") or 0.0)
    if gt <= 0:
        return []
    ev = _events(data)
    out = []

    def add(label, nxt):
        secs = int(round(nxt - gt))
        out.append({"label": label, "secs": secs, "up": secs <= 0,
                    "urgent": 0 < secs <= ALERT_LEAD,
                    "setup": ALERT_LEAD < secs <= SETUP_LEAD})

    # Dragon: first at 5:00, then 5:00 after each kill. Once a team has soul (4 elemental
    # kills) or Elder has spawned, there are no more elemental drakes -> drop the timer.
    drags = [e for e in ev if e.get("EventName") == "DragonKill"]
    elder = any(str(e.get("DragonType") or "").lower() == "elder" for e in drags)
    elem = [e.get("EventTime") for e in drags
            if str(e.get("DragonType") or "").lower() != "elder" and e.get("EventTime") is not None]
    if not (elder or len(elem) >= 4):
        add("Drake", (max(elem) + DRAGON_RESPAWN) if elem else DRAGON_FIRST)

    # Void grubs: 6:00, one respawn 4:00 after a clear, gone by ~14:45.
    if gt < GRUBS_DESPAWN:
        last_h = _last_time(ev, "HordeKill")
        nxt_h = (last_h + GRUBS_RESPAWN) if last_h is not None else GRUBS_FIRST
        if nxt_h < GRUBS_DESPAWN:
            add("Grubs", nxt_h)

    # Baron: only surfaces from ~19:00 on (irrelevant earlier). First 20:00, then 6:00.
    if gt >= BARON_OPEN:
        last_b = _last_time(ev, "BaronKill")
        add("Baron", (last_b + BARON_RESPAWN) if last_b is not None else BARON_FIRST)

    out.sort(key=lambda o: o["secs"])
    return out


def _completed_items(dd, items):
    """Count of pricey, finished items (a proxy for legendary spikes) + their summed gold."""
    n, gold = 0, 0
    idata = dd.get("item_data", {})
    for iid in items:
        info = idata.get(iid) or {}
        g = ((info.get("gold") or {}).get("total")) or 0
        gold += g
        tags = info.get("tags", [])
        if g >= 2000 and "Boots" not in tags and "Consumable" not in tags:
            n += 1
    return n, gold


def _team_split(data):
    players = data.get("allPlayers") or []
    act = data.get("activePlayer") or {}
    myg = lg._gname(act.get("riotId") or act.get("summonerName") or "")
    me = next((p for p in players if lg._gname(p.get("riotId") or p.get("summonerName") or "") == myg), None)
    if me is None or not players:
        return None
    myteam = me.get("team")
    allies = [p for p in players if p.get("team") == myteam]
    enemies = [p for p in players if p.get("team") != myteam]
    return me, allies, enemies, myteam


def power_spike(dd, data):
    """The scariest enemy who has SPIKED (>=2 completed items) AND is ahead - the moment to
    play safe / itemize. None if no enemy is both spiked and fed."""
    split = _team_split(data)
    if not split:
        return None
    _me, _allies, enemies, _t = split
    best = None
    for p in enemies:
        items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
        n, _g = _completed_items(dd, items)
        sc = p.get("scores") or {}
        k, d = int(sc.get("kills", 0)), int(sc.get("deaths", 0))
        lead = k - d
        if n >= 2 and lead >= 3:
            name = dd["id2name"].get(dd["name2id"].get(dd["norm"](p.get("championName", "")), 0),
                                     p.get("championName", "?"))
            score = n * 2 + lead
            if not best or score > best["score"]:
                best = {"name": name, "items": n, "k": k, "d": d, "score": score}
    return best


def win_prob(dd, data):
    """Transparent live win read: a logistic on net item-gold + level + drake/baron lead.
    Returns {pct, ahead, basis}. Deliberately simple - 'dial in later' lives in the consts."""
    split = _team_split(data)
    if not split:
        return None
    _me, allies, enemies, _t = split
    if not (allies and enemies):
        return None

    def econ(team):
        g = 0
        for p in team:
            items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
            _n, gold = _completed_items(dd, items)
            g += gold + int(p.get("level", 1)) * LEVEL_GOLD
            sc = p.get("scores") or {}
            g += int(sc.get("kills", 0)) * KILL_GOLD
        return g

    ev = _events(data)
    # drakes/baron are credited to the killing TEAM, which the Live Client doesn't label per
    # event - so approximate from killer side via player names on each team.
    ally_names = {lg._gname(p.get("riotId") or p.get("summonerName") or "") for p in allies}

    def team_objs(name):
        a = b = 0
        for e in ev:
            killer = lg._gname(e.get("KillerName") or "")
            on_ally = killer in ally_names
            if e.get("EventName") == "DragonKill":
                a += 1 if on_ally else 0
                b += 0 if on_ally else 1
            elif e.get("EventName") == "BaronKill":
                pass
        return a, b

    my_dr, en_dr = team_objs("d")
    # baron: count recent (<180s) barons per side as an "active" power swing
    gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
    my_bar = en_bar = 0
    for e in ev:
        if e.get("EventName") == "BaronKill" and gt - float(e.get("EventTime") or 0) < 180:
            if lg._gname(e.get("KillerName") or "") in ally_names:
                my_bar += 1
            else:
                en_bar += 1

    my_g = econ(allies) + my_dr * DRAKE_GOLD + my_bar * BARON_GOLD
    en_g = econ(enemies) + en_dr * DRAKE_GOLD + en_bar * BARON_GOLD
    diff = my_g - en_g
    import math
    pct = 1.0 / (1.0 + math.exp(-diff / GOLD_SCALE))
    pct = max(0.05, min(0.95, pct))
    kdiff = f"{diff/1000:+.1f}k gold"
    drk = f", {my_dr - en_dr:+d} drake" if (my_dr or en_dr) else ""
    return {"pct": int(round(pct * 100)), "ahead": diff >= 0, "basis": kdiff + drk}


_JG_SIDE = {"TOP": "topside", "MIDDLE": "mid", "MID": "mid", "BOTTOM": "botside", "UTILITY": "botside"}
JG_STALE = 120             # a sighting older than this is no read at all


def _is_jungler(p):
    if (p.get("position") or "").upper() == "JUNGLE":
        return True
    ss = p.get("summonerSpells") or {}
    for k in ("summonerSpellOne", "summonerSpellTwo"):
        if "smite" in ((ss.get(k) or {}).get("displayName") or "").lower():
            return True
    return False


def jungle_read(dd, data):
    """Where the enemy jungler was LAST SEEN, inferred from the events they took part in:
    drake = botside, grubs/herald/baron = topside, champion kills = the victim's lane side.
    The Live Client has no positions, but its event feed names everyone involved - which is
    exactly the info a jungler tracks by hand. Returns {champ, side, what, ago} or None."""
    split = _team_split(data)
    if not split:
        return None
    _me, _allies, enemies, _t = split
    jg = next((p for p in enemies if _is_jungler(p)), None)
    if jg is None:
        return None
    jg_name = lg._gname(jg.get("riotId") or jg.get("summonerName") or "")
    if not jg_name:
        return None
    gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
    pos_of = {}
    for p in (data.get("allPlayers") or []):
        pos_of[lg._gname(p.get("riotId") or p.get("summonerName") or "")] = (p.get("position") or "").upper()
    best = None                                   # (event_time, side, what)
    for e in _events(data):
        t, n = e.get("EventTime"), e.get("EventName")
        if t is None:
            continue
        involved = [e.get("KillerName", ""), e.get("VictimName", "")] + list(e.get("Assisters") or [])
        if jg_name not in (lg._gname(x) for x in involved if x):
            continue
        if n == "DragonKill":
            side, what = "botside", "drake"
        elif n == "HordeKill":
            side, what = "topside", "grubs"
        elif n == "RiftHeraldKill":
            side, what = "topside", "herald"
        elif n == "BaronKill":
            side, what = "topside", "baron"
        elif n == "ChampionKill":
            victim = lg._gname(e.get("VictimName") or "")
            if victim == jg_name:                 # the jungler DIED - that's a timer, not a sighting
                side, what = "dead", "died"
            else:
                side = _JG_SIDE.get(pos_of.get(victim, ""), "a fight")
                what = "kill"
        else:
            continue
        if best is None or t > best[0]:
            best = (t, side, what)
    if best is None:
        return None
    ago = int(gt - best[0])
    if ago > JG_STALE:
        return None
    champ = dd["id2name"].get(dd["name2id"].get(dd["norm"](jg.get("championName", "")), 0),
                              jg.get("championName", "?"))
    return {"champ": champ, "side": best[1], "what": best[2], "ago": ago}


GANK_LVL_GAP = 2           # enemy this many levels behind their lane = a gank window


def gank_window(dd, data):
    """The most gankable enemy LANE right now: alive and >=2 levels behind their direct
    counterpart (a level lead is the cleanest 'you win the 2v1' signal :2999 exposes).
    Returns {lane, champ, lvl, vs_lvl} or None. Positions come from the live client, so
    this only fires in ranked/normals where positions are reported."""
    split = _team_split(data)
    if not split:
        return None
    _me, allies, enemies, _t = split
    ally_lvl = {}
    for p in allies:
        pos = (p.get("position") or "").upper()
        if pos:
            ally_lvl[pos] = int(p.get("level", 1) or 1)
    best = None
    for p in enemies:
        pos = (p.get("position") or "").upper()
        if pos in ("", "JUNGLE") or pos not in ally_lvl:
            continue
        if p.get("isDead"):
            continue
        gap = ally_lvl[pos] - int(p.get("level", 1) or 1)
        if gap >= GANK_LVL_GAP and (best is None or gap > best[0]):
            champ = dd["id2name"].get(dd["name2id"].get(dd["norm"](p.get("championName", "")), 0),
                                      p.get("championName", "?"))
            best = (gap, {"lane": _JG_SIDE.get(pos, pos.lower()), "champ": champ,
                          "lvl": int(p.get("level", 1) or 1), "vs_lvl": ally_lvl[pos]})
    return best[1] if best else None


_UNSET = object()


def pulse(dd, data=_UNSET):
    """One-shot live intel for the widget: {objectives, spike, winprob} or None if not in game.
    Pass `data` (an already-fetched allgamedata payload) to share one :2999 fetch; passing an
    explicit None means 'no data this tick' and returns None without re-fetching."""
    if data is _UNSET:
        data = _read()
    if not data or not (data.get("allPlayers")):
        return None
    try:
        objs = objectives(data)
    except Exception:
        objs = []
    try:
        spike = power_spike(dd, data)
    except Exception:
        spike = None
    try:
        wp = win_prob(dd, data)
    except Exception:
        wp = None
    try:
        jg = jungle_read(dd, data)
    except Exception:
        jg = None
    try:
        gank = gank_window(dd, data)
    except Exception:
        gank = None
    if not (objs or spike or wp or jg or gank):
        return None
    return {"objectives": objs, "spike": spike, "winprob": wp, "jungle": jg, "gank": gank}


def _fmt(secs):
    if secs <= 0:
        return "UP"
    return f"{secs // 60}:{secs % 60:02d}"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    dd = lb.ddragon()
    p = pulse(dd)
    if not p:
        print("not in a live game")
    else:
        print("objectives:", [(o["label"], _fmt(o["secs"]), "!" if o["urgent"] else "") for o in p["objectives"]])
        print("spike:", p["spike"])
        print("winprob:", p["winprob"])
