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


# XP->gold table + per-player power/est-gold now live in lollive (ONE BRAIN): the same
# economy model feeds fight_edge here, win_prob there, and the GHOST gold trace.
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

# TAKE / GIVE decision thresholds on the gold-equivalent fight edge E (modeling). Sized
# for the score-estimated power scale (bigger absolute numbers than the old item-only read).
E_TAKE, E_GIVE = 800.0, -800.0
VERDICT_LEAD = 45.0        # the contest/give call fires this early (setup deadlines stay 30s)

# priority majors, in the order the widget should care about them
_MAJOR = ("Elder", "Baron", "Drake", "Herald", "Grubs")

# ---- role model: the schedule differs by WHERE you live on the map. A bot laner is 12s
#      from drake and a cross-map hike from baron; a top laner is the reverse; mid and
#      jungle sit roughly equidistant. Path lengths are map-unit estimates (modeling). ----
_LC_ROLE = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid", "MID": "mid",
            "BOTTOM": "adc", "UTILITY": "support"}
_OBJ_SIDE = {"Drake": "bot", "Elder": "bot", "Baron": "top", "Herald": "top", "Grubs": "top"}
_LANE_SIDE = {"top": "top", "adc": "bot", "support": "bot"}   # mid/jungle: no home side
_LANE_PATH = {"top": (4800.0, 13800.0), "mid": (6600.0, 6600.0), "adc": (4800.0, 13800.0),
              "support": (4800.0, 13800.0), "jungle": (7200.0, 7200.0)}
LANE_TRAVEL_MIN, LANE_TRAVEL_MAX = 8.0, 60.0


def _my_role(dd, me):
    """Your role this game: the Live Client position (ranked/normals), else the role saved
    at champ select, else jungle (the engine's original flavor)."""
    r = _LC_ROLE.get((me.get("position") or "").upper(), "")
    if not r:
        try:
            import lolgame as lg
            cid = dd["name2id"].get(dd["norm"](me.get("championName") or ""), 0)
            r = lg.load_role(cid) or ""
        except Exception:
            r = ""
    return r or "jungle"


def _lane_travel(role, obj_label, ms):
    """Seconds from your LANE to this objective's pit (walking): same-side lanes are close,
    cross-map lanes are a hike. Used for the rotate deadline + can-you-even-make-it check
    (the recall/BASE deadline still uses the fountain path — you back to the fountain)."""
    side = _OBJ_SIDE.get(obj_label, "bot")
    same, cross = _LANE_PATH.get(role, _LANE_PATH["jungle"])
    home = _LANE_SIDE.get(role)
    dist = same if (home is None or home == side) else cross
    return max(LANE_TRAVEL_MIN, min(LANE_TRAVEL_MAX, dist / max(200.0, float(ms or 0) or 390.0)))


def _has_tp(me):
    s = me.get("summonerSpells") or {}
    for k in ("summonerSpellOne", "summonerSpellTwo"):
        if "teleport" in ((s.get(k) or {}).get("displayName") or "").lower():
            return True
    return False


def _travel(ms, gt):
    ms = float(ms or 0) or 390.0
    hg = HG_CREDIT_LATE if gt >= 840 else HG_CREDIT_EARLY   # homeguard upgrades at 14:00
    return max(TRAVEL_MIN, min(TRAVEL_MAX, PATH_UNITS / max(200.0, ms) - hg))


_est_gold = ll.est_gold    # legacy aliases: the economy moved to lollive (ONE BRAIN);
_power = ll.player_power   # fight_edge math below is unchanged, only its inputs moved.


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


_drake_counts = ll.drake_counts   # moved to lollive (ONE BRAIN); win_prob shares it


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
        ap += _power(dd, p, gt) * av
        ab += av
    ep = eb = 0.0
    for p in enemies:
        av = _avail(p, t_obj, travel, gt)
        ep += _power(dd, p, gt) * av
        eb += av
    bodies = ab - eb
    e = (ap - ep) + BODY_GOLD * bodies
    detail = f"{e / 1000:+.0f}k"                 # ONE number: the whole edge, gold-equivalent
    if bodies <= -0.5:
        detail += f" · {abs(bodies):.0f} down"
    elif bodies >= 0.5:
        detail += f" · {bodies:.0f} up"
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
    majors = [o for o in objs if o.get("label") in _MAJOR]
    nxt = majors[0] if majors else None
    # FIRST-spawn baron is a posture objective, not an alarm — almost nobody rushes it on
    # spawn. Until a baron has died: prefer a drake/elder even if it's a few minutes later,
    # and when baron IS the only thing coming, schedule it gently (no recall pressure).
    first_baron = False
    if (nxt is not None and nxt["label"] == "Baron" and nxt["secs"] > 0
            and ll._last_time(ll._events(data), "BaronKill") is None):
        alt = next((o for o in majors[1:] if o["label"] in ("Drake", "Elder")), None)
        if alt is not None and alt["secs"] <= nxt["secs"] + 240:
            nxt = alt
        else:
            first_baron = True

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
            and (nxt is None or float(nxt["secs"]) > VERDICT_LEAD)):
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

    # ---- role-aware geometry: the recall deadline uses the FOUNTAIN path (you back to
    #      base), but the rotate deadline + reachability use YOUR LANE's path to this pit ----
    role = _my_role(dd, _me)
    laner = role in ("top", "mid", "adc", "support")
    lane_tv = _lane_travel(role, label, ms)
    # leaving right now, do you make the fight? Pre-spawn: beat spawn + grace. Already UP:
    # a pit fight lasts ~25s+, so anyone within that window is still a contester.
    reachable = lane_tv <= (T + FIGHT_GRACE if T > 0 else 25.0)

    # ---- approaching spawn: the TAKE / EVEN / GIVE verdict, fired EARLY (45s out) so the
    #      call lands while you can still act on it, not as the pit fight starts ----
    if T <= VERDICT_LEAD:
        if not reachable:
            if _has_tp(_me):
                return {"phase": "PUSH", "obj": label, "secs": int(T), "urgent": True,
                        "line": f"SHOVE — then TP to {label.lower()}",
                        "sub": "you can't walk there in time; crash the wave and TP the fight"}
            return {"phase": "PUSH", "obj": label, "secs": int(T), "urgent": True,
                    "line": f"too far — SHOVE for the cross-trade",
                    "sub": f"you can't reach {label.lower()}: hard-push your lane, take plates/camps"}
        fe = fight_edge(dd, data, T, travel, gt)
        if fe is None:
            return None
        e, bodies, detail = fe
        soul_tag = " · SOUL POINT" if soul_point else ""
        if e >= E_TAKE:
            return {"phase": "TAKE", "obj": label, "secs": int(T), "urgent": True,
                    "line": f"TAKE {label.lower()} ({detail}){soul_tag}",
                    "sub": "you win this fight — commit with vision, don't dance"}
        if e <= E_GIVE:
            alt = "trade: grubs" if label == "Drake" and gt < 850 else \
                  "trade: push the opposite lane, take camps/plates"
            return {"phase": "GIVE", "obj": label, "secs": int(T), "urgent": True,
                    "line": f"GIVE {label.lower()} ({detail}){soul_tag}",
                    "sub": (f"you lose this fight — {alt}" if not soul_point else
                            "SOUL POINT — only contest off a pick; otherwise trade BIG")}
        return {"phase": "EVEN", "obj": label, "secs": int(T), "urgent": True,
                "line": f"{label} is a 50/50 ({detail}){soul_tag}",
                "sub": "only take it with a vision or smite edge — never coinflip blind"}

    # ---- scheduled deadlines, walked back from spawn ----
    base_by = T - travel - SETUP_LEAD - RECALL_S - SHOP_S
    move_by = T - lane_tv - SETUP_LEAD
    mmss = f"{int(T) // 60}:{int(T) % 60:02d}"
    star = "★ " if soul_point else ""
    if first_baron:
        # gentle handling: no recall countdown, no urgency — just keep it on the radar
        # and suggest posture once it's close. The verdict still runs when it's UP.
        if T <= 60:
            return {"phase": "MOVE", "obj": "Baron", "secs": int(T), "urgent": False,
                    "line": f"first baron {mmss} — posture, don't force",
                    "sub": "ward the pit + river; punish them for starting it, don't start it"}
        return {"phase": "FARM", "obj": "Baron", "secs": int(T), "urgent": False,
                "line": f"farm — first baron {mmss} (posture play, no rush)",
                "sub": "keep waves pushed and vision alive topside; nobody rushes spawn baron"}
    if base_by <= 0 < move_by:
        if laner:
            return {"phase": "MOVE", "obj": label, "secs": int(T), "urgent": move_by <= 10,
                    "line": f"{star}CRASH your wave → rotate to {label.lower()} in {int(max(0, move_by))}s",
                    "sub": f"never rotate off a slow push — crash it, then ward pit ({label} {mmss})"}
        return {"phase": "MOVE", "obj": label, "secs": int(T), "urgent": move_by <= 10,
                "line": f"{star}ROTATE — leave for {label.lower()} in {int(max(0, move_by))}s",
                "sub": f"arrive {int(SETUP_LEAD)}s early: pit ward + river control ({label} {mmss})"}
    if base_by <= 20:
        return {"phase": "BASE", "obj": label, "secs": int(T), "urgent": base_by <= 8,
                "line": f"{star}BASE window — recall inside {int(max(0, base_by))}s",
                "sub": f"buy fast, you'll reach {label.lower()} {int(SETUP_LEAD)}s early ({mmss})"}
    tail = ("crash your wave before you leave" if laner else f"path toward {label.lower()}")
    return {"phase": "FARM", "obj": label, "secs": int(T), "urgent": False,
            "line": f"{star}farm window {int(base_by)}s → {label.lower()}",
            "sub": f"recall by -{int(T - base_by)}s · leave by -{int(SETUP_LEAD + lane_tv)}s · {tail}"}


# how early before spawn a fresh respawn should still bother walking to the pit; beyond
# this the objective is too far out to be THE respawn plan (farm/shove instead).
RESPAWN_HORIZON = 120.0


def respawn_plan(dd, data):
    """DEATH-SCREEN plan: None unless the ACTIVE player is dead right now. The grey screen
    is the one moment the fountain->pit travel model is EXACTLY right (you respawn at the
    fountain), so the make-it/miss-it call is at its most trustworthy here. Returns
    {secs, obj, line, sub, tone} — tone: 'go' (teal) / 'hold' (red) / 'plan' (gold)."""
    if not data or not (data.get("allPlayers")):
        return None
    split = ll._team_split(data)
    if not split:
        return None
    me = split[0]
    if not me.get("isDead"):
        return None
    gd = data.get("gameData") or {}
    gt = float(gd.get("gameTime") or 0.0)
    secs = float(me.get("respawnTimer") or 0.0)
    if secs <= 0.0:                                # payload lag on the flip: estimate once
        secs = death_timer(me.get("level", 1), gt) * 0.5
    act = data.get("activePlayer") or {}
    ms = ((act.get("championStats") or {}).get("moveSpeed"))
    travel = _travel(ms, gt)                       # fountain path — literally where you are
    role = _my_role(dd, me)

    try:
        majors = [o for o in ll.objectives(data) if o.get("label") in _MAJOR]
    except Exception:
        majors = []
    # the plan targets the first ACTIONABLE major: a future spawn, or something already
    # up that you can still reach — an objective that's been sitting up out of reach
    # (uncontested grubs) shouldn't hijack the respawn plan from the next real fight.
    nxt = next((o for o in majors
                if float(o["secs"]) > 0 or (secs + travel) <= 25.0), None)

    def mmss(t):
        t = max(0, int(t))
        return f"{t // 60}:{t % 60:02d}"

    if nxt is not None and float(nxt["secs"]) <= secs + travel + RESPAWN_HORIZON:
        label, T = nxt["label"], float(nxt["secs"])
        arrival = secs + travel
        side = _OBJ_SIDE.get(label, "bot")
        # pre-spawn you must beat spawn+grace; an already-up pit fight lasts ~25s
        make_it = arrival <= (T + FIGHT_GRACE if T > 0 else 25.0)
        head = f"{label.upper()} {mmss(T)}" if T > 0 else f"{label.upper()} IS UP"
        if not make_it:
            return {"secs": secs, "obj": label, "tone": "hold",
                    "line": f"{head} — you won't make it.",
                    "sub": "don't run at a lost fight — shove the opposite lane, take camps/plates"}
        fe = fight_edge(dd, data, max(T, arrival), travel, gt)
        e = fe[0] if fe else 0.0
        if e >= E_TAKE:
            return {"secs": secs, "obj": label, "tone": "go",
                    "line": f"{head} — you make it, and you win it.",
                    "sub": f"buy fast, path {side} river"}
        if e <= E_GIVE:
            return {"secs": secs, "obj": label, "tone": "hold",
                    "line": f"{head} — you make it, but you lose the 5v5.",
                    "sub": "don't force it — trade cross-map, take what they leave open"}
        return {"secs": secs, "obj": label, "tone": "plan",
                "line": f"{head} — you make it. It's a 50/50.",
                "sub": f"buy, path {side} river — go in with vision or not at all"}

    # nothing major soon: the productive default for your role, next objective on the radar
    radar = f" · {nxt['label']} {mmss(nxt['secs'])}" if nxt is not None else ""
    if role == "jungle":
        line, sub = "reset your camps, safe side first", f"full clear toward the next spawn{radar}"
    elif role in ("adc", "support"):
        line, sub = "group bot, catch the wave", f"reset the lane before the next play{radar}"
    else:
        line, sub = "shove your wave back in", f"kill the freeze before it sets{radar}"
    return {"secs": secs, "obj": None, "tone": "plan", "line": line, "sub": sub}
