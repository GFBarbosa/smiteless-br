#!/usr/bin/env python3
"""lolward.py - THE WARD CLOCK: the objective you were always going to fight over, and
whether you did anything about it before it spawned.

THE LEAK THIS EXISTS FOR
lolprofile.behavior_read tags a game `low_vision` when your vision score per minute
finishes under the bar for your role - 1.2/min as a support, 0.55/min as a jungler. It
was the LAST tag in the ledger with nothing in the game to answer it, and the README has
carried it as "not yet" since the ledger existed. BLEED (lolbleed) owns your health bar in
the first fourteen minutes, RE-ENTRY (lolreentry) the ninety seconds after a death, the
CLOSER (lolclose) the closeout, the GOLD CLOCK (lolgold) the lane-phase economy - and the
GOLD CLOCK is deliberately SILENT for jungle and support, because camps aren't on the wave
schedule and a support's CS was never the story. So the two roles that own the map had no
lane-phase surface at all. That is this module. The two can never collide: lolgold speaks
only for top/mid/adc, lolward only for jungle/support.

WHY NOT "WARD MORE"
Because it changes nothing. Vision is not a rate you grind, it is a DEADLINE you either
beat or miss: a ward that goes down when the drake spawns is decoration, and the same ward
forty seconds earlier is what decides whether the fight happens on your terms. The clock
this reads off is therefore not a vision-score-per-minute target, it is the objective timer
the app already computes (lollive.objectives), back-timed by its own setup lead:

    SETUP - drake in 58s · vision in by 4:15
            ward their botside jungle entrance - the side they walk in from, not yours

WHAT IT WATCHES, AND WHY THAT IS NEW
Four facts, all of them EXACT off :2999, none of them modelled - and three of them were
being thrown straight in the bin by every surface in this app:

  - scores.wardScore. Riot's own vision score, live, FOR ALL TEN PLAYERS. Nothing in
    Smiteless read it and nothing in League shows it to you mid-game. It is the only stat
    in the API where you can see your direct opponent's number next to yours while the
    game is still being played: "you 6 · their sup 14" is not coaching folklore, it is the
    scoreboard of the map you are about to fight on.
  - The control wards IN YOUR BAG (item 2055, count and all). Watched every tick, so the
    count going DOWN is a ward you placed and the count going UP is one you bought. From
    that: how many you have bought, how many you have actually placed, how long the one in
    your bag has been sitting there unplaced, and the number no tool anywhere has ever put
    in front of a player - the share of the game you have spent with NO control ward
    available at all. 75 gold is the cheapest map control in the game and the whole leak is
    usually that you never had one on you.
  - Your trinket (3340 / 3363 / 3364). The instruction changes completely depending on what
    you are actually holding: a sweeper means take theirs first, a farsight means you place
    from range and can't sweep at all. Advice you can't execute with the item in your hand
    is advice that gets ignored.
  - Your gold. "Buy a control ward" is only worth saying when you can afford one, and it is
    worth saying loudest in a recall window - which the tempo engine already knows about.

THE VERDICTS
PINK   - an objective's setup window is open and you are CARRYING a control ward. The 75
         gold in your bag wards nothing; this is the pit it was bought for.
SETUP  - the same window, nothing in the bag: get the ward that matters in NOW, with the
         entrance named, and the buy noted if you can afford one.
DARK   - the objective just spawned and your vision score has not moved in minutes. Stated
         as what the number did, never as an accusation about what you did - vision score
         only accrues while something of yours is alive on the map.
VISION - the quiet row. Your score against what the bar would have you on right now, your
         opponent's number, and the pink ledger. One line, all game.
None   - outside the window, dead, or a role whose vision the tag has never held to a bar
         (top/mid/adc: lolprofile has always evaluated `low_vision` for jungle and support
         only, and inventing a number for a mid laner is how a surface gets switched off).

It fires ONCE per objective, holds the card for a few seconds and hands the slot straight
back. It never outranks BLEED (something that can kill you beats a ward) and it stands down
to the quiet row the moment the tempo engine has a live TAKE/GIVE verdict - by design it
lives in the SETUP window, which closes exactly where tempo's urgent window opens.

House rule (docs/TAGS.md spirit): the card carries its receipt - YOUR OWN W/L split for the
habit, straight out of the behavior ledger, so it is your data talking and not folklore.

100% read-only off :2999. No input, no camera, nothing automated.

  python lolward.py        # print every branch from the fixtures
"""
import math
import time

CW_ID = 2055               # Control Ward — the only ward that deletes theirs
CW_COST = 75               # ...and the cheapest map control in the game
TRINKETS = {3340: "yellow", 3363: "farsight", 3364: "sweeper"}
TRINKET_SLOT = 6           # the trinket slot; the item read never depends on it (id-matched)

OPEN_AT = 180.0            # 3:00 — early enough to cover the first drake's setup window
CARD_SECS = 9.0            # how long a card owns the directive slot before going quiet
DARK_STALE = 105.0         # vision score flat for this long = nothing of yours is alive
                           # (a stealth ward lives 90-120s, so a full ward life has passed)
CARRY_NAG = 45.0           # a pink in the bag this long is dead gold worth mentioning
_EV_TTL = 600.0            # re-read the behavior ledger at most this often

# The roles lolprofile.behavior_read actually evaluates `low_vision` for, mapped from the
# tempo engine's role names to the position keys the ledger uses. A role that isn't in here
# never hears from this module.
_POS = {"jungle": "JUNGLE", "support": "UTILITY"}
# Objectives worth a setup card. Scuttle is deliberately out: it is a 6-second fight over a
# crab, not a window you set vision for.
_SIDE = {"Drake": "bot", "Elder": "bot", "Baron": "top", "Herald": "top", "Grubs": "top"}
_MOUTH = {"bot": "their botside jungle entrance", "top": "their topside jungle entrance",
          None: "the entrance they walk in from"}      # objective we can't place: stay neutral
                                                       # rather than point at the wrong river

_EV = {"t": 0.0, "text": None}
_BAR = {"v": None}
_LEAD = {"v": None}


def vis_bar(role):
    """Vision score per minute the `low_vision` tag holds this role to, READ OUT OF
    lolprofile rather than re-typed here - the live surface and the post-game tag must never
    be able to disagree about where the bar is. 0.0 for a role the tag never evaluates."""
    if _BAR["v"] is None:
        d = {"UTILITY": 1.2, "JUNGLE": 0.55}          # lolprofile.VIS_BAR's own values
        try:
            import lolprofile as lp
            if getattr(lp, "VIS_BAR", None):
                d = dict(lp.VIS_BAR)
        except Exception:
            pass
        _BAR["v"] = d
    return float(_BAR["v"].get(_POS.get(role) or "", 0.0) or 0.0)


def leads():
    """(urgent_lead, setup_lead) in seconds, DERIVED from lollive so this module's window
    and the objective chips the widget draws can never drift apart. The card lives in
    (urgent, setup]: the setup window, which ends exactly where tempo's urgent one starts."""
    if _LEAD["v"] is None:
        lo, hi = 45.0, 75.0
        try:
            import lollive as ll
            lo, hi = float(ll.ALERT_LEAD), float(ll.SETUP_LEAD)
        except Exception:
            pass
        _LEAD["v"] = (lo, hi)
    return _LEAD["v"]


def _evidence():
    """YOUR measured split for the no-vision habit ('with it: 3W-9L / without: 11W-5L'), or
    None until the ledger has both sides. Cached - it's a disk read on a 1s poll loop."""
    now = time.monotonic()
    if _EV["text"] is not None and (now - _EV["t"]) < _EV_TTL:
        return _EV["text"]
    txt = None
    try:
        import lolprofile as lp
        raw = lp.pattern_evidence("low_vision")
        if raw:
            txt = "your games under the vision bar — " + raw
    except Exception:
        txt = None
    _EV["t"], _EV["text"] = now, txt
    return txt


# ------------------------------------------------------------------ the inventory read ----
def _items(p):
    """The item rows, filtered to the ones that are actually dicts. :2999 has handed us a
    literal `None` inside `items` before (a payload read while the shop was open), and one
    bad row must never cost the widget a frame."""
    try:
        rows = (p or {}).get("items") or []
    except AttributeError:
        return []
    return [it for it in rows if isinstance(it, dict)]


def pinks(p):
    """Control wards in this player's bag RIGHT NOW - summed over stacks, because they
    stack and one entry with count 2 is two wards. Exact: the live client reports your own
    inventory every tick."""
    n = 0
    for it in _items(p):
        try:
            if int(it.get("itemID") or 0) == CW_ID:
                n += max(1, int(it.get("count") or 1))
        except (TypeError, ValueError):             # an item row caught mid-write
            continue
    return n


def trinket(p):
    """"yellow" / "farsight" / "sweeper", or None when the slot is empty (you sold it, or
    the payload was caught mid-write). Matched by item id, never by slot index."""
    for it in _items(p):
        try:
            t = TRINKETS.get(int(it.get("itemID") or 0))
        except (TypeError, ValueError):
            continue
        if t:
            return t
    return None


def ward_score(p):
    """Riot's own live vision score for a player, or None when the field isn't there (an
    older client, or a score line caught mid-write). None is not zero: a missing number
    must never read as 'you have warded nothing'."""
    try:
        v = (p or {}).get("scores", {}).get("wardScore")
    except AttributeError:
        return None
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def counterpart(role, enemies):
    """(label, ward_score) for the enemy whose vision number is the one that matters: your
    direct opposite by position, else their best. Labelled honestly either way - claiming
    'their support' about a number you took off their top laner is exactly the kind of lie
    that makes a player stop trusting a row."""
    want = _POS.get(role)
    lab = {"UTILITY": "their sup", "JUNGLE": "their jg"}.get(want)
    if want and lab:
        for p in enemies or []:
            if (p.get("position") or "").upper() == want:
                vs = ward_score(p)
                if vs is not None:
                    return lab, vs
    best = None
    for p in enemies or []:
        vs = ward_score(p)
        if vs is not None and (best is None or vs > best):
            best = vs
    return ("their best", best) if best is not None else (None, None)


def _mmss(s):
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


# What to actually do, and it changes with the item in your hand: a sweeper means take
# theirs first (a swept pit is worth more than the ward you add to it), a farsight means you
# place from range and cannot sweep at all, a yellow means you have to walk it in.
_BY_TRINKET = {
    "sweeper": "sweep {mouth} first, then ward it — take theirs, don't just add yours",
    "farsight": "farsight into the pit from range — you can't sweep, so get it in early",
    "yellow": "ward {mouth} — their side of the river, not your own",
}
_FALLBACK = "ward {mouth} — their side of the river, not your own"
_PINK_SPOT = "the control ward goes in the pit — it's the only ward that deletes theirs"


def spot(label, trink):
    """The concrete instruction for this objective and this trinket. Side-relative on
    purpose ('their botside entrance'): it is correct on blue side and red side, which a
    named bush is not."""
    mouth = _MOUTH.get(_SIDE.get(label)) or _MOUTH[None]
    return (_BY_TRINKET.get(trink) or _FALLBACK).format(mouth=mouth)


def _verdict(ctx):
    """Pure: context -> the card (or None). Split out from observe() so the fixtures below
    can drive every branch without a live game."""
    role = ctx.get("role")
    bar = vis_bar(role)
    if bar <= 0:                                   # a role the tag never holds to a bar
        return None
    gt = float(ctx.get("gt") or 0.0)
    if not math.isfinite(gt) or gt < OPEN_AT:
        return None
    mins = gt / 60.0
    vs = ctx.get("vs")
    vs = float(vs) if vs is not None else None
    pace = bar * mins                              # what the bar would have you on right now
    rate = (vs / mins) if (vs is not None and mins > 0) else None
    under = bool(rate is not None and rate < bar)
    held = int(ctx.get("pink") or 0)
    gold = float(ctx.get("gold") or 0.0)
    trink = ctx.get("trink")
    label, osecs = ctx.get("obj"), ctx.get("obj_secs")
    lo, hi = leads()

    # ---- the quiet row, as ORDERED SEGMENTS (the widget joins as many as fit, most
    # important first, so a long game state degrades instead of clipping a number in half).
    bits = []
    if vs is not None:
        bits.append(f"{int(round(vs))} of {int(round(pace))}")
        if rate is not None:
            bits.append(f"{rate:.1f}/min" + (f", bar {bar:g}" if under else ""))
    opp_lab, opp_vs = ctx.get("opp_label"), ctx.get("opp_vs")
    if opp_lab and opp_vs is not None:
        bits.append(f"{opp_lab} {int(round(float(opp_vs)))}")
    dark = float(ctx.get("dark_for") or 0.0)
    if held:
        bits.append(f"pink in bag {_mmss(ctx.get('carry') or 0)}" if float(ctx.get("carry") or 0) >= CARRY_NAG
                    else f"{held} pink" + ("s" if held > 1 else ""))
    elif dark >= 60.0:
        bits.append(f"no pink {_mmss(dark)}")
    if not bits:                                   # nothing measurable yet: say nothing
        return None
    # A recall window is the one moment "buy a control ward" is an action and not a wish.
    if ctx.get("base") and not held and gold >= CW_COST:
        bits.insert(0, f"+{CW_COST}g control ward")

    placed, bought = int(ctx.get("placed") or 0), int(ctx.get("bought") or 0)
    card = {"vs": (None if vs is None else round(vs, 1)), "bar": bar,
            "pace": round(pace, 1), "rate": (None if rate is None else round(rate, 2)),
            "under": under, "held": held, "placed": placed, "bought": bought,
            "dark_pct": int(round(float(ctx.get("dark_pct") or 0.0) * 100)),
            "opp_vs": (None if opp_vs is None else round(float(opp_vs), 1)),
            "obj": label, "obj_secs": (None if osecs is None else int(osecs)),
            "trink": trink, "row": " · ".join(bits), "bits": bits,
            "left": int(osecs) if osecs is not None else 0, "clock_txt": None}
    # The number nothing else has ever shown a player: the share of the game you actually
    # had 75 gold of map control ON you. Stated the way round that reads as a fact about you
    # rather than a scold, and the purchase ledger only when we saw a purchase at all (a
    # widget opened mid-game must not report "0 of 0" about wards it never watched you buy).
    have = 100 - card["dark_pct"]
    ledger = ((f"{placed} of {bought} placed · " if bought else "")
              + f"control ward on you {have}% of the game")

    # A live objective verdict outranks a ward every time - by then the ward is either in or
    # it isn't, and the decision on screen is the fight. The row still reads `under`.
    speak = not ctx.get("tempo_urgent")

    # ---- 1. the setup window is open and there is 75 gold in your bag doing nothing. The
    #         strongest thing this module can say, because the fix costs one right-click.
    if (speak and ctx.get("card") and label and osecs is not None and held
            and float(ctx.get("carry") or 0.0) >= CARRY_NAG):
        card.update(verdict="PINK", tone="plan", quiet=False,
                    line=(f"PINK — {label.lower()} in {int(osecs)}s · "
                          f"the {CW_COST}g in your bag wards nothing yet"),
                    sub=f"{_PINK_SPOT} · {spot(label, trink)}")
        return card

    # ---- 2. the same window, nothing to place. Name the entrance, and note the buy only
    #         when you can actually afford it.
    if speak and ctx.get("card") and label and osecs is not None:
        sub = spot(label, trink)
        if not held and gold >= CW_COST:      # never sell a ward to somebody already holding one
            sub += f" · +{CW_COST}g control ward on the next trip (you have {int(gold)})"
        card.update(verdict="SETUP", tone="plan", quiet=False,
                    line=(f"SETUP — {label.lower()} in {int(osecs)}s · "
                          f"vision in by {_mmss(gt + osecs - lo)}"),
                    sub=sub)
        return card

    # ---- 3. it spawned, and the number has not moved in minutes. What the NUMBER did -
    #         never an accusation about what you did.
    stale = ctx.get("stale")
    if speak and ctx.get("spawned") and under and stale is not None and float(stale) >= DARK_STALE:
        card.update(verdict="DARK", tone="hold", quiet=False,
                    line=(f"DARK — {(label or 'it').lower()} is up and your vision score "
                          f"hasn't moved in {_mmss(stale)}"),
                    sub=f"{spot(label, trink)} · {ledger}",
                    # the clock slot holds the number that DEFINES this card (the CLOSER does
                    # the same with its lead): a spawn countdown here would read "0s".
                    clock_txt=_mmss(stale))
        return card

    # ---- 4. the quiet row. A number you can glance at for a whole game, not a coach
    #         clearing its throat every thirty seconds.
    card.update(verdict="VISION", tone="hold" if under else "plan", quiet=True,
                line=f"VISION — {card['row']}", sub=ledger)
    return card


class Guard:
    """One instance per widget session. Stateful for three reasons, none of which can be
    seen in a single frame: a control ward LEAVING your bag is the only evidence in the API
    that you placed one, 'how long have you had none' is an integral over the game, and a
    card must fire once per objective rather than for the whole thirty-second window."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._gt = 0.0
        self._t0 = None            # the first clock we ever saw — the honest denominator for
                                   # 'share of the game': a widget opened at 12:00 (or a
                                   # reconnect) must measure the part it actually watched
                                   # rather than claim the first twelve minutes were fine
        self._pink = None          # last seen control-ward count (None = never read one)
        self._carry_at = None      # game-time the current carry started
        self._dark_at = None       # ...or the current dry spell
        self._dark = 0.0           # accumulated seconds with no control ward in the bag
        self._vs = None            # last seen vision score...
        self._vs_at = 0.0          # ...and when it last actually CHANGED
        self._done = set()         # objectives already carded (label, spawn bucket)
        self._card_until = 0.0     # game-time the current card stops owning the slot
        self._card_obj = None      # ...and which objective it belongs to
        self._spawn_until = 0.0    # the DARK window just after a spawn
        self._spawn_obj = None
        self.bought = 0            # control wards bought this game
        self.placed = 0            # ...and placed
        self.calls = 0             # cards opened this game (diagnostics / voice rate cap)

    # -- inventory bookkeeping: the count going down IS the placement event ---------------
    def _track_pink(self, gt, n):
        prev = self._pink
        if prev is None:
            self._pink = n
            (self._carry_at, self._dark_at) = ((gt, None) if n else (None, gt))
            return
        if n > prev:
            self.bought += n - prev
            if prev == 0:
                if self._dark_at is not None:
                    self._dark += max(0.0, gt - self._dark_at)
                self._dark_at, self._carry_at = None, gt
        elif n < prev:
            self.placed += prev - n
            if n == 0:
                self._carry_at, self._dark_at = None, gt
        self._pink = n

    def _track_vs(self, gt, vs):
        if vs is None:
            return
        if self._vs is None or abs(vs - self._vs) > 1e-9:
            self._vs, self._vs_at = vs, gt

    def observe(self, dd, data, tempo=None, objs=None):
        """One tick. Returns the VISION row (or a card) while you're in a role the tag holds
        to a vision bar; None every other moment. `tempo` and `objs` are this same tick's
        reads (ONE BRAIN - the widget already computed both): the card stands down to the row
        rather than talk over a live objective verdict, and the objective clock is the one
        the widget is already drawing."""
        if not data:
            return None
        import lollive as ll
        import loltempo as lt
        split = ll.team_split(data)
        if not split:
            return None
        me, _allies, enemies, _team = split
        try:
            gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
        except (TypeError, ValueError):            # a payload caught mid-write
            return None
        if not math.isfinite(gt):
            return None
        if gt + 1.0 < self._gt:                    # clock went backwards -> a different game
            self.reset()
        self._gt = gt
        if self._t0 is None:
            self._t0 = gt

        role = lt._my_role(dd, me)
        if role not in _POS:
            return None

        held = pinks(me)
        self._track_pink(gt, held)
        vs = ward_score(me)
        self._track_vs(gt, vs)
        if bool(me.get("isDead")):                 # the death screen owns the grey screen
            return None
        if gt < OPEN_AT:
            return None

        # the objective clock: the widget's own list, or our own read if we're driven bare
        if objs is None:
            try:
                objs = ll.objectives(data)
            except Exception:
                objs = []
        lo, hi = leads()
        nxt = next((o for o in (objs or []) if o.get("label") in _SIDE
                    and o.get("secs") is not None and float(o["secs"]) > 0), None)
        label = nxt.get("label") if nxt else None
        osecs = float(nxt["secs"]) if nxt else None

        # fire ONCE per objective: the setup window is thirty seconds long and a card that
        # sits there for all of it is a card you stop reading.
        if label and osecs is not None and lo < osecs <= hi:
            key = (label, int(round((gt + osecs) / 5.0)))
            if key not in self._done:
                self._done.add(key)
                self._card_until, self._card_obj = gt + CARD_SECS, label
                self.calls += 1
        # ...and a short window just AFTER it spawns, for the retrospective read
        up = next((o for o in (objs or []) if o.get("label") in _SIDE
                   and o.get("secs") is not None and -6.0 <= float(o["secs"]) <= 0.0), None)
        if up:
            self._spawn_until, self._spawn_obj = gt + CARD_SECS, up.get("label")

        carding = gt < self._card_until
        spawned = gt < self._spawn_until and not carding
        opp_lab, opp_vs = counterpart(role, enemies)
        dark_now = self._dark + (max(0.0, gt - self._dark_at) if self._dark_at is not None else 0.0)
        try:
            gold = float((data.get("activePlayer") or {}).get("currentGold") or 0.0)
        except (TypeError, ValueError):
            gold = 0.0
        ph = (tempo or {}).get("phase")
        card = _verdict({
            "gt": gt, "role": role, "vs": vs, "pink": held, "gold": gold,
            "trink": trinket(me), "opp_label": opp_lab, "opp_vs": opp_vs,
            "obj": (self._card_obj if carding else (self._spawn_obj if spawned else label)),
            "obj_secs": osecs if not spawned else None,
            "card": carding, "spawned": spawned,
            "carry": (gt - self._carry_at) if self._carry_at is not None else 0.0,
            "dark_for": (gt - self._dark_at) if self._dark_at is not None else 0.0,
            "dark_pct": min(1.0, dark_now / max(1.0, gt - float(self._t0 or 0.0))),
            "placed": self.placed, "bought": self.bought,
            "stale": (gt - self._vs_at) if self._vs is not None else None,
            "base": ph == "BASE",
            "tempo_urgent": bool((tempo or {}).get("urgent")),
        })
        if card is None:
            return None
        card["calls"] = self.calls
        card["evidence"] = _evidence()
        return card


# ---- fixtures for tools/selftest.py: each must land on exactly one verdict ----
def demo(kind):
    """A support at 8:20 with the grubs 58 seconds out - inside the setup window."""
    base = {"gt": 500.0, "role": "support", "vs": 6.0, "pink": 0, "gold": 320.0,
            "trink": "yellow", "opp_label": "their sup", "opp_vs": 19.0,
            "obj": "Grubs", "obj_secs": 58.0, "card": True, "spawned": False,
            "carry": 0.0, "dark_for": 300.0, "dark_pct": 0.9,
            "placed": 1, "bought": 2, "stale": 20.0, "base": False}
    if kind == "setup":                   # the window is open and the bag is empty
        pass
    elif kind == "pink":                  # ...and there is a control ward sitting in it
        base.update(pink=1, carry=120.0, dark_for=0.0)
    elif kind == "broke":                 # no pink and no gold: never mention the buy
        base.update(gold=20.0)
    elif kind == "justbought":            # bought it seconds ago: not "wards nothing yet",
        base.update(pink=1, carry=6.0, dark_for=0.0)    # and never sold another one
    elif kind == "sweeper":               # the instruction changes with the item in hand
        base.update(trink="sweeper")
    elif kind == "farsight":
        base.update(trink="farsight")
    elif kind == "row":                   # outside every window -> the quiet row
        base.update(card=False, obj_secs=180.0)
    elif kind == "onbar":                 # above the bar: the row, and not a warning color
        base.update(card=False, obj_secs=180.0, vs=20.0)
    elif kind == "dark":                  # it spawned and the number hasn't moved in 2:20
        base.update(card=False, spawned=True, obj_secs=None, stale=140.0)
    elif kind == "dark_onbar":            # ...but a player ON the bar is never accused
        base.update(card=False, spawned=True, obj_secs=None, stale=140.0, vs=20.0)
    elif kind == "base":                  # a recall window is when the buy is an action
        base.update(card=False, obj_secs=180.0, base=True)
    elif kind == "noscore":               # no wardScore in the payload: degrade, don't lie
        base.update(card=False, obj_secs=180.0, vs=None)
    elif kind == "quiet":                 # a live tempo verdict outranks the setup card
        base.update(tempo_urgent=True)
    elif kind == "mid":                   # a laner's vision was never held to a bar
        base.update(role="mid")
    elif kind == "jungle":                # the jungler's own (lower) bar
        base.update(role="jungle", opp_label="their jg", opp_vs=9.0)
    elif kind == "early":                 # before the first drake's setup window
        base.update(gt=100.0, card=False)
    return base


if __name__ == "__main__":                # python lolward.py — the bars + every branch
    print("the bar, straight out of lolprofile.VIS_BAR")
    for r in ("support", "jungle"):
        b = vis_bar(r)
        print(f"  {r:8} {b:g}/min  ->  by 20:00 that is {b * 20:.0f} vision score")
    lo, hi = leads()
    print(f"\nsetup window (from lollive): a card fires between {hi:.0f}s and {lo:.0f}s "
          f"before spawn\n")
    for k in ("setup", "pink", "justbought", "broke", "sweeper", "farsight", "row", "onbar",
              "dark",
              "dark_onbar", "base", "noscore", "quiet", "mid", "jungle", "early"):
        c = _verdict(demo(k))
        if not c:
            print(f"{k:11} (silent)")
        else:
            q = " [quiet row]" if c.get("quiet") else ""
            print(f"{k:11} {c['verdict']:6}{q} {c['line']}\n            {c['sub']}")
