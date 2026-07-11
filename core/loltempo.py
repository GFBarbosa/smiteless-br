#!/usr/bin/env python3
"""loltempo.py - the TEMPO ENGINE: a live objective-setup directive system.

THE CONCEPT
Games below Master aren't decided AT the objective fight - they're decided in the ~90
seconds BEFORE it: someone farms one wave too long, backs at the wrong moment, and the
team fights 4v5 with no vision. Pro teams schedule this window; solo-queue players wing
it. This module computes the schedule, live, every tick - and answers the one question
that matters when the fight starts: "do we actually win this?" from death timers + item
gold + levels, not vibes.

WHY THIS CONCEPT (research, Diamond+ sample of 8M games, machineloling.com, split 1 2025):
  - 1 drake at even gold  -> +8.0% win rate; 2 drakes -> +16.9%
  - all 6 grubs           -> +11% (plus ~+2.1% from the plate advantage they convert to)
  - dragon SOUL           -> the soul team wins ~85-90% of games (consistent across seasons)
Objective control is the highest-leverage, most schedulable win condition in the game.

VERIFIED CONSTANTS (wiki.leagueoflegends.com, checked 2026-07-10; current patch values)
  - Drake 5:00 first / 5:00 respawn; soul at 4 drakes; Elder 6:00 timers  [Dragon page]
  - Voidgrubs 8:00, ONE spawn (no respawn since 25.09), despawn 14:45     [Voidgrub page]
  - Herald 15:00 -> 19:45, once per game                                  [Rift Herald page]
  - Baron 20:00, 6:00 respawn, buff 180s                                  [Baron Nashor page]
  - Atakhan REMOVED in V26.01 (deliberately absent here)                  [Atakhan page]
  - Death timers: BRW by level x time-increase factor (formula below)     [Death page]
  - Recall: 0.5s cast + 8s channel                                        [Recall page]
  - Homeguard: +80%->40% MS decaying 4s pre-14:00; +150% decaying post    [Homeguard page]
  - XP to reach level L (cumulative table below)                          [Experience page]

MODELING ASSUMPTIONS (not facts - tunable, and labeled as such):
  - XP is valued at 0.25 gold per point when comparing team power (analyst convention).
  - A missing body is worth BODY_GOLD on top of its gold (a 4v5 loses more than one
    player's items: zoning, damage uptime, smite presence).
  - Travel to a pit ~= PATH_UNITS / current move speed, minus a homeguard credit,
    clamped to a sane band. Positions aren't exposed by the Live Client API, so travel
    is a fountain->pit estimate; that's exactly the number back-timing needs anyway.
"""
import lollive as ll

# ---- death timer (wiki "Death"): BRW by level, then a time-increase factor (TIF) that
#      accrues per HALF-MINUTE: +0.425%/half-min from 15:00, +0.30% from 30:00,
#      +1.45% from 45:00, capped at +50%. Sanity anchor: lvl18 at 55:00 = 52.5*1.5 = 78.75s.
BRW = {1: 10, 2: 10, 3: 12, 4: 12, 5: 14, 6: 16, 7: 20, 8: 25, 9: 28, 10: 32.5,
       11: 35, 12: 37.5, 13: 40, 14: 42.5, 15: 45, 16: 47.5, 17: 50, 18: 52.5}


def death_timer(level, gt):
    """Seconds a champion of `level` waits when dying at game-time `gt` (seconds)."""
    brw = BRW.get(max(1, min(18, int(level))), 30)
    halves = 0.0
    m = gt / 60.0
    if m > 15:
        halves += (min(m, 30) - 15) * 2 * 0.425
    if m > 30:
        halves += (min(m, 45) - 30) * 2 * 0.30
    if m > 45:
        halves += (m - 45) * 2 * 1.45
    tif = min(50.0, halves) / 100.0
    return brw * (1.0 + tif)


# ---- XP -> gold-equivalent power (wiki "Experience": cumulative XP to reach each level) ----
XP_CUM = {1: 0, 2: 280, 3: 660, 4: 1140, 5: 1720, 6: 2400, 7: 3180, 8: 4060, 9: 5040,
          10: 6120, 11: 7300, 12: 8580, 13: 9960, 14: 11440, 15: 13020, 16: 14700,
          17: 16480, 18: 18360}
XP_GOLD = 0.25             # modeling assumption: gold value per XP point
BODY_GOLD = 900            # modeling assumption: man-advantage value beyond the missing gold

# ---- travel model. Fountain->pit path length in map units (~14.8k-unit map, estimated
#      path with turns); divided by LIVE move speed, minus a homeguard credit (verified:
#      +80%->40% decay pre-14:00, +150% post), clamped to a believable band. ----
PATH_UNITS = 13500.0
HG_CREDIT_EARLY, HG_CREDIT_LATE = 2.0, 4.0     # seconds saved leaving base with homeguard
TRAVEL_MIN, TRAVEL_MAX = 24.0, 48.0

RECALL_S = 8.5             # 0.5 cast + 8.0 channel (wiki "Recall")
SHOP_S = 10.0              # human time to buy + reset camera (modeling)
SETUP_LEAD = 30.0          # arrive this early: pit ward + river control + positioning
FIGHT_GRACE = 12.0         # dead player back within this of the fight start still counts
LATE_ARRIVAL = 32.0        # back within this = arrives mid-fight, counted at half power

# TAKE / GIVE decision thresholds on the gold-equivalent fight edge E (modeling).
E_TAKE, E_GIVE = 500.0, -500.0

# priority majors, in the order the widget should care about them
_MAJOR = ("Elder", "Baron", "Drake", "Herald", "Grubs")


def _travel(ms, gt):
    ms = float(ms or 0) or 390.0
    hg = HG_CREDIT_LATE if gt >= 840 else HG_CREDIT_EARLY   # homeguard upgrades at 14:00
    return max(TRAVEL_MIN, min(TRAVEL_MAX, PATH_UNITS / max(200.0, ms) - hg))


def _power(dd, p):
    """One player's gold-equivalent fight power: item gold + XP valued at XP_GOLD."""
    items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
    _n, gold = ll._completed_items(dd, items)
    return gold + XP_CUM.get(max(1, min(18, int(p.get("level", 1)))), 0) * XP_GOLD


def _avail(p, t_obj, travel, gt):
    """How much of this player shows up to a fight starting in t_obj seconds: 1 alive/back
    in time, 0.5 arriving mid-fight, 0 misses it. Uses the LIVE respawnTimer."""
    if not p.get("isDead"):
        return 1.0
    back = float(p.get("respawnTimer") or 0.0) + travel
    if back <= t_obj + FIGHT_GRACE:
        return 1.0
    if back <= t_obj + LATE_ARRIVAL:
        return 0.5
    return 0.0


def _drake_counts(data, allies):
    """(ally_drakes, enemy_drakes) from DragonKill events, credited via killer name."""
    import lolgame as lg
    names = {lg._gname(p.get("riotId") or p.get("summonerName") or "") for p in allies}
    a = e = 0
    for ev in ll._events(data):
        if ev.get("EventName") == "DragonKill":
            if lg._gname(ev.get("KillerName") or "") in names:
                a += 1
            else:
                e += 1
    return a, e


def fight_edge(dd, data, t_obj, travel, gt):
    """The core math: gold-equivalent fight edge E at an objective starting in t_obj
    seconds. E = (ally available power - enemy available power) + BODY_GOLD * body diff,
    where availability is death-timer-and-travel aware. Returns (E, ally_up_bodies,
    detail-string)."""
    split = ll._team_split(data)
    if not split:
        return None
    _me, allies, enemies, _t = split
    ap = ab = 0.0
    for p in allies:
        av = _avail(p, t_obj, travel, gt)
        ap += _power(dd, p) * av
        ab += av
    ep = eb = 0.0
    for p in enemies:
        av = _avail(p, t_obj, travel, gt)
        ep += _power(dd, p) * av
        eb += av
    bodies = ab - eb
    e = (ap - ep) + BODY_GOLD * bodies
    detail = f"{(ap - ep) / 1000:+.1f}k gold-eq"
    if abs(bodies) >= 0.5:
        detail += f", {bodies:+.1f} bodies"
    return e, bodies, detail


def tempo_read(dd, data):
    """The directive: what YOU should be doing right now relative to the next major
    objective. Returns {phase, line, sub, obj, secs, urgent} or None outside a game.

    Timeline, walked backward from spawn T (all live-computed):
      base_by = T - travel - SETUP_LEAD - RECALL_S - SHOP_S   (last moment to start recall)
      move_by = T - travel - SETUP_LEAD                        (last moment to start walking)
    Phases: FARM (before base_by) -> BASE (recall window) -> MOVE (walk + ward) ->
    EXECUTE at spawn: TAKE / EVEN / GIVE from fight_edge. A live numbers window
    (enemies dead, you not) overrides FARM/BASE with FORCE."""
    if not data or not (data.get("allPlayers")):
        return None
    gd = data.get("gameData") or {}
    gt = float(gd.get("gameTime") or 0.0)
    if gt < 60:
        return None
    try:
        objs = ll.objectives(data)
    except Exception:
        objs = []
    nxt = next((o for o in objs if o.get("label") in _MAJOR), None)

    act = data.get("activePlayer") or {}
    ms = ((act.get("championStats") or {}).get("moveSpeed"))
    travel = _travel(ms, gt)

    split = ll._team_split(data)
    if not split:
        return None
    _me, allies, enemies, _t = split

    # ---- soul-point escalation: 3 drakes on either side makes the next drake the game ----
    a_dr, e_dr = _drake_counts(data, allies)
    soul_point = (nxt is not None and nxt.get("label") in ("Drake", "Elder")
                  and max(a_dr, e_dr) >= 3)

    # ---- live numbers window: enemies dead while your side is up bodies -> FORCE.
    #      Suppressed inside an objective's setup window: there the TAKE/GIVE verdict
    #      below already prices the dead enemies in, and names the objective. ----
    dead_e = [p for p in enemies if p.get("isDead") and float(p.get("respawnTimer") or 0) >= 10]
    dead_a = [p for p in allies if p.get("isDead")]
    if (dead_e and len(dead_e) > len(dead_a)
            and (nxt is None or float(nxt["secs"]) > SETUP_LEAD)):
        win = min(float(p.get("respawnTimer") or 0) for p in dead_e)
        n_up, n_en = len(allies) - len(dead_a), len(enemies) - len(dead_e)
        return {"phase": "FORCE", "obj": (nxt or {}).get("label"), "secs": int(win),
                "urgent": True,
                "line": f"FORCE: {n_up}v{n_en} for {int(win)}s",
                "sub": f"{len(dead_e)} enemy dead — take a fight, tower or camps, then reset on your terms"}

    if nxt is None:
        return None
    T = float(nxt["secs"])
    label = nxt["label"]

    # ---- at / near spawn: the TAKE / EVEN / GIVE verdict ----
    if T <= SETUP_LEAD:
        fe = fight_edge(dd, data, T, travel, gt)
        if fe is None:
            return None
        e, bodies, detail = fe
        soul_tag = " — SOUL POINT (soul team wins ~85-90%)" if soul_point else ""
        if e >= E_TAKE:
            return {"phase": "TAKE", "obj": label, "secs": int(T), "urgent": True,
                    "line": f"TAKE {label.lower()} — you win this fight ({detail})",
                    "sub": f"edge +{int(e)}g{soul_tag} — commit with vision, don't dance"}
        if e <= E_GIVE:
            alt = "grubs" if label == "Drake" and gt < 850 else \
                  "the opposite side — push a lane, take camps/plates"
            return {"phase": "GIVE", "obj": label, "secs": int(T), "urgent": True,
                    "line": f"GIVE {label.lower()} — you lose this fight ({detail})",
                    "sub": (f"edge {int(e)}g — trade: {alt}{soul_tag}" if not soul_point else
                            f"edge {int(e)}g — SOUL POINT: only contest with a pick first{soul_tag}")}
        return {"phase": "EVEN", "obj": label, "secs": int(T), "urgent": True,
                "line": f"{label} is a 50/50 ({detail})",
                "sub": f"take it only with a vision or smite edge{soul_tag} — never coinflip blind"}

    # ---- scheduled deadlines, walked back from spawn ----
    base_by = T - travel - SETUP_LEAD - RECALL_S - SHOP_S
    move_by = T - travel - SETUP_LEAD
    mmss = f"{int(T) // 60}:{int(T) % 60:02d}"
    star = "★ " if soul_point else ""
    if base_by <= 0 < move_by:
        return {"phase": "MOVE", "obj": label, "secs": int(T), "urgent": move_by <= 10,
                "line": f"{star}ROTATE — leave for {label.lower()} in {int(max(0, move_by))}s",
                "sub": f"arrive {int(SETUP_LEAD)}s early: pit ward + river control ({label} {mmss})"}
    if base_by <= 20:
        return {"phase": "BASE", "obj": label, "secs": int(T), "urgent": base_by <= 8,
                "line": f"{star}BASE window — recall inside {int(max(0, base_by))}s",
                "sub": f"buy fast, you'll reach {label.lower()} {int(SETUP_LEAD)}s early ({mmss})"}
    return {"phase": "FARM", "obj": label, "secs": int(T), "urgent": False,
            "line": f"{star}farm window {int(base_by)}s — path toward {label.lower()}",
            "sub": f"{label} {mmss} · recall by -{int(T - base_by)}s, arrive by -{int(SETUP_LEAD + travel)}s"}
