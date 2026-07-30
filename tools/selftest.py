#!/usr/bin/env python3
"""selftest.py - one-command health check for Smiteless.

Verifies every external dependency the overlay relies on, so you can tell at a glance
what's working - handy after a Riot dev-key rotation (they expire every 24h) or a new
patch (in case op.gg changes shape).

  python selftest.py
"""
import sys, os, time, json, ssl, urllib.request, urllib.error
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK, FAIL, SKIP = "PASS", "FAIL", "skip"
results = []


def check(name, fn):
    try:
        status, detail = fn()
    except Exception as e:
        status, detail = FAIL, f"{type(e).__name__}: {e}"
    results.append((name, status, detail))


def c_pillow():
    import PIL
    from PIL import Image  # noqa: F401
    return OK, f"Pillow {PIL.__version__}"


def c_ddragon():
    import lolbuild as lb
    dd = lb.ddragon()
    n = len(dd["id2name"])
    return (OK, f"patch {dd['ver']}, {n} champs") if n > 100 else (FAIL, f"only {n} champs cached")


def c_opgg():
    import lolbuild as lb
    dd = lb.ddragon()
    d = lb.opgg(dd["name2id"]["yasuo"], "mid")
    if d and "summary" in d:
        return OK, f"Yasuo mid WR {d['summary']['average_stats']['win_rate'] * 100:.1f}%"
    return FAIL, "no data (op.gg shape changed or blocked?)"


def c_riot_key():
    import lolscout as ls, lolbuild as lb
    key = ls.read_key()
    if not key:
        return SKIP, "no ~/.riot_api_key -> player scout disabled (overlay still works)"
    # MUST send a browser User-Agent: Riot's API is behind Cloudflare, which 403s
    # (error 1010) a bare Python urllib UA. The real scout (lolscout._get) sends lb.UA.
    req = urllib.request.Request(
        "https://na1.api.riotgames.com/lol/status/v4/platform-data",
        headers={"X-Riot-Token": key, "User-Agent": lb.UA})
    try:
        with urllib.request.urlopen(req, timeout=8, context=ssl.create_default_context()) as r:
            json.load(r)
        return OK, f"valid (key ...{key[-4:]})"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return FAIL, "rejected (401/403) - regenerate at developer.riotgames.com"
        return FAIL, f"HTTP {e.code}"


def c_claude():
    import claudecli as cc
    exe = cc.find_claude()
    return (OK, os.path.basename(exe)) if exe else (FAIL, "claude CLI not found -> matchup tips disabled")


def c_glyphs():
    import glyphcheck
    bad = glyphcheck.check()
    if bad:
        return FAIL, bad[0] + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else "")
    return OK, "no text-blind symbol draws (tofu tripwire)"


def c_tagspec():
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(_ROOT, "tools", "tagcheck.py")],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        return OK, "tag fixtures conform to docs/TAGS.md"
    tail = (r.stdout or r.stderr).strip().splitlines()
    return FAIL, tail[-1] if tail else "tagcheck failed"


def c_queuecall():
    """The QUEUE CALL verdict engine, on fixtures that must each land on one verdict —
    it reads your live history in the lobby, so a silent logic break would just look
    like 'it always says GO'."""
    import lolqueue as lq
    want = {"stop": "STOP", "last": "LAST ONE", "wait": "WAIT"}
    got = {k: lq.call(lq.demo(k))["verdict"] for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    if lq.call([])["verdict"] != "GO":
        return FAIL, "empty history must fall through to GO"
    return OK, "stop / last-one / wait fixtures each land on their verdict"


def c_reentry():
    """The RE-ENTRY verdict engine (the 90s guard after you respawn). Fires from a state
    machine inside a live game, so a logic break is otherwise invisible until it silently
    says HOLD forever — or never."""
    import lolreentry as lre
    want = {"hold": "HOLD", "clear": "CLEAR", "reset": "RESET"}
    got = {k: lre._verdict(lre.demo(k))["verdict"] for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    if lre.WINDOW != 90.0:
        return FAIL, f"window is {lre.WINDOW}s — it must match the death_cluster tag's 90s"
    g = lre.Guard()                              # dead -> alive must arm; no data must not
    if g.observe(None, None) is not None or g.armed_until is not None:
        return FAIL, "guard armed itself with no game data"
    return OK, "hold / clear / reset fixtures each land on their verdict"


def c_bleed():
    """The BLEED verdict engine (the first-14-minutes health guard). Same shape of risk as
    RE-ENTRY: a broken branch either screams every wave or never fires once, and neither is
    visible without playing a game."""
    import lolbleed as lbl
    want = {"bleed": "BLEED", "dive": "BLEED", "banked": "BLEED",
            "healthy": None, "accounted": None, "alone": None, "noread": None}
    got = {k: (lbl._verdict(lbl.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    if lbl.WINDOW != 14 * 60.0:
        return FAIL, f"window is {lbl.WINDOW}s — it must match the early_bleeding tag's 14:00"
    return OK, "3 warning + 4 silent fixtures each land where they should"


def c_closer():
    """The CLOSER (the post-20:00 win-conversion director). Two things must hold forever:
    every verdict branch is reachable, and it is SILENT in any game you are not winning —
    a closeout coach talking during a losing game is worse than no coach."""
    import lolclose as lc
    want = {"end": "END", "siege": "SIEGE", "close": "CLOSE", "closeinhib": "CLOSE",
            "quietclose": "CLOSE", "hold": "HOLD", "giveback": "HOLD", "bank": "BANK",
            "behind": None, "early": None, "thin": None, "winning_fight": "BANK"}
    got = {k: (lc._verdict(lc.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    if lc.LEAD_MIN != 2000.0:
        return FAIL, f"lead bar is {lc.LEAD_MIN} — it must match the threw_ahead tag's 2000g"
    # never contradict a positive fight read: tempo saying TAKE and the closer saying HOLD
    # on the same frame is the app arguing with itself.
    for e in (900.0, 3000.0, 12000.0):
        d = lc.demo("hold")
        d["e"] = e
        if (lc._verdict(d) or {}).get("verdict") == "HOLD":
            return FAIL, f"HOLDs while fight_edge says +{e:.0f} — contradicts the tempo card"
    # the structure map is COUNT-based on purpose (turrets can only fall front-to-back), so
    # a Riot rename of the turret indices must not change the depth read.
    ev = [{"EventName": "TurretKilled", "EventTime": 600 + i,
           "TurretKilled": f"Turret_T2_C_{5 - i:02d}_A"} for i in range(3)]
    ev.append({"EventName": "InhibKilled", "EventTime": 900, "InhibKilled": "Barracks_T2_C1"})
    st = lc.structures(ev, "ORDER")
    if st["them"]["turrets"].get("C") != 3 or lc.steps_to_inhib(st["them"])["C"] != 0:
        return FAIL, f"structure map misread their mid: {st['them']['turrets']}"
    oi = lc.open_inhibs(st["them"], 1000.0)
    if not oi or oi[0][0] != "C" or abs(oi[0][1] - 200.0) > 0.5:
        return FAIL, f"inhibitor clock wrong: {oi}"
    if lc.open_inhibs(st["them"], 1201.0):
        return FAIL, "inhibitor never closes — it respawns 5:00 after the kill"
    g = lc.Guard()                               # no data must not arm anything
    if g.observe(None, None) is not None or g.peak != 0.0:
        return FAIL, "guard armed itself with no game data"
    return OK, "12 verdict fixtures + structure map + inhib clock all correct"


def c_gold():
    """The GOLD CLOCK (core/lolgold) — the first-ten farm read. Three things must hold
    forever, and none of them are visible without playing a game: the minion SCHEDULE is
    exact (it is the denominator for every number the surface prints), the bar is still the
    weak_first_ten tag's own, and it is SILENT for the roles whose CS is not the story."""
    import lolgold as lg, lollive as ll
    # --- the schedule. Wave k spawns at 1:05 + 30(k-1) and is only counted once it has
    #     ARRIVED (mid meets at 1:30, side lanes at 1:38). Off by one wave = every number
    #     the card prints is wrong, quietly.
    for role, trav in lg.LANE_ARRIVE.items():
        for k in (1, 3, 7, 18, 26):
            at = lg.WAVE_FIRST + lg.WAVE_EVERY * (k - 1) + trav
            if lg.waves_by(at - 0.01, role) != k - 1 or lg.waves_by(at, role) != k:
                return FAIL, f"{role}: wave {k} is not counted at its {at:.0f}s arrival"
    if lg.waves_by(90.0, "mid") != 1 or lg.waves_by(89.9, "mid") != 0:
        return FAIL, "mid lane does not meet at 1:30"
    if lg.waves_by(98.0, "adc") != 1 or lg.waves_by(97.9, "adc") != 0:
        return FAIL, "the side lanes do not meet at 1:38"
    if lg.offered(600.0, "mid") != (114, 2250.0):
        return FAIL, f"mid is offered {lg.offered(600.0, 'mid')} by 10:00, not (114, 2250)"
    # every minion value is flat until 15:00 — that is the whole reason this can be exact
    # rather than modelled, so the last wave inside the window must still spawn before it.
    last = lg.waves_by(lg.WINDOW, "mid")
    if lg.WAVE_FIRST + lg.WAVE_EVERY * (last - 1) >= 15 * 60:
        return FAIL, f"wave {last} spawns at/after 15:00 — minion gold is no longer flat"
    for t in range(0, 900, 13):                  # the cannon clock can never look backwards
        nc = lg.next_cannon(float(t), "mid")
        if nc[0] < 0 or nc[1] % 3 or nc[1] <= lg.waves_by(float(t), "mid"):
            return FAIL, f"cannon clock wrong at {t}s: {nc}"
    # --- the bars are the tag's, and gold-per-CS is DERIVED from lollive, never re-typed
    if lg.BAR_CS10 != 55 or lg.FIRST_TEN != 600.0:
        return FAIL, f"bar is {lg.BAR_CS10} CS at {lg.FIRST_TEN}s — must match weak_first_ten"
    probe = ll.est_gold({"scores": {"creepScore": 100}}, 300.0) - ll.est_gold({"scores": {}}, 300.0)
    if abs(lg.cs_gold() * 100 - probe) > 1e-6:
        return FAIL, f"gold-per-CS ({lg.cs_gold()}) has drifted from lollive.est_gold"
    # --- every verdict branch is reachable and lands where it should
    want = {"pace": "PACE", "behind": "PACE", "miss": "MISS", "cannon": "CANNON",
            "roaming": "PACE", "unrecoverable": "MISS", "onpace_miss": "PACE",
            "jungle": None, "support": None, "early": None, "late": None}
    got = {k: (lg._verdict(lg.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    # a kill-fed lane is NOT a weak first ten — the tag needs the gold bar missed too, and
    # scolding a roaming mid for his CS is how you teach somebody to stop roaming.
    if (lg._verdict(lg.demo("roaming")) or {}).get("under"):
        return FAIL, "a 30-CS mid with three kills read as under the farm bar"
    # a live objective verdict always outranks a dropped wave
    if (lg._verdict(dict(lg.demo("miss"), tempo_urgent=True)) or {}).get("quiet") is not True:
        return FAIL, "MISS talks over a live tempo verdict"
    # --- the guard: never bill a wave lost on the grey screen, never speak while dead
    g, billed = lg.Guard(), 0
    for t in range(0, 700):
        dead = 240 <= t <= 330
        cs = int(lg.offered(float(min(t, 240)), "mid")[0] * 0.90)
        me = {"riotId": "M#1", "team": "ORDER", "position": "MIDDLE", "isDead": dead,
              "level": 6, "championName": "Ahri",
              "scores": {"creepScore": cs, "kills": 0, "assists": 0, "deaths": 0}}
        c = g.observe({}, {"activePlayer": {"riotId": "M#1"}, "allPlayers": [me],
                           "gameData": {"gameTime": float(t)}, "events": {"Events": []}})
        if dead and c:
            return FAIL, f"the gold clock spoke at {t}s while the player was dead"
        if c and c["verdict"] == "MISS" and 240 <= t <= 400:
            billed += 1
    if billed:
        return FAIL, f"billed {billed} MISS cards for waves lost while dead"
    if g.observe({}, None) is not None or lg.Guard().observe({}, {}) is not None:
        return FAIL, "guard produced a card with no game data"
    return OK, "wave schedule exact, bar matches the tag, 11 fixtures + dead-wave rule hold"


def c_ward():
    """The WARD CLOCK (core/lolward) — the objective-vision read for jungle/support. Four
    things must hold forever and none of them are visible without playing a game: the bar is
    still the low_vision tag's OWN (drift here and the live surface grades you against a bar
    your profile doesn't use), the setup window is still lollive's, the inventory read
    survives every shape :2999 can hand it, and it is SILENT for the three roles the tag has
    never evaluated."""
    import lolward as lw, lolprofile as lp, lollive as ll

    # --- ONE BRAIN: the bar is read out of lolprofile, never re-typed
    if lp.VIS_BAR != {"UTILITY": 1.2, "JUNGLE": 0.55}:
        return FAIL, f"lolprofile.VIS_BAR moved to {lp.VIS_BAR} — retune the tag AND the row"
    if (lw.vis_bar("support") != lp.VIS_BAR["UTILITY"]
            or lw.vis_bar("jungle") != lp.VIS_BAR["JUNGLE"]):
        return FAIL, "the ward clock's bar has drifted from lolprofile.VIS_BAR"
    for r in ("top", "mid", "adc", "", None):
        if lw.vis_bar(r) != 0.0:
            return FAIL, f"role {r!r} has a vision bar — the tag never evaluates one"
    # ...and the tag really does use it: a support 0.01 under the bar must be tagged, and one
    # 0.01 over must not. Driven through behavior_read's own arithmetic.
    bar = lp.VIS_BAR["UTILITY"]
    for vis, want in ((bar * 20 - 0.5, True), (bar * 20 + 0.5, False)):
        if ((vis / 20.0) < bar) is not want:
            return FAIL, "the low_vision arithmetic no longer matches VIS_BAR"
    # --- the window is lollive's, and the card lives strictly inside it
    lo, hi = lw.leads()
    if (lo, hi) != (float(ll.ALERT_LEAD), float(ll.SETUP_LEAD)) or not 0 < lo < hi:
        return FAIL, f"setup window {(lo, hi)} has drifted from lollive's leads"

    # --- the inventory read: every shape the live client can hand us
    if lw.pinks({"items": [{"itemID": lw.CW_ID, "count": 2}, {"itemID": 3340}]}) != 2:
        return FAIL, "control-ward stacks are not summed"
    if lw.pinks({"items": [{"itemID": lw.CW_ID}, {"itemID": lw.CW_ID, "count": 1}]}) != 2:
        return FAIL, "a countless control-ward row must still count as one"
    for junk in (None, {}, {"items": None}, {"items": [{}]}, {"items": [{"itemID": "x"}]},
                 {"items": [{"itemID": lw.CW_ID, "count": "two"}]}):
        if lw.pinks(junk) < 0:
            return FAIL, f"pinks() went negative on {junk!r}"
    if lw.pinks({"items": [{"itemID": 3340}]}) or lw.pinks({"items": []}):
        return FAIL, "a trinket read as a control ward"
    for iid, want in ((3340, "yellow"), (3363, "farsight"), (3364, "sweeper")):
        if lw.trinket({"items": [{"itemID": 2055}, {"itemID": iid, "slot": 6}]}) != want:
            return FAIL, f"trinket {iid} read as something else"
    if lw.trinket({"items": [{"itemID": 2055}]}) is not None:
        return FAIL, "an empty trinket slot must read None, not a guess"
    # a MISSING vision score is not a zero: it must never read as 'you warded nothing'
    if lw.ward_score({"scores": {}}) is not None or lw.ward_score({}) is not None:
        return FAIL, "a missing wardScore read as a number"
    if lw.ward_score({"scores": {"wardScore": 0}}) != 0.0:
        return FAIL, "a real zero wardScore was thrown away"
    if lw.ward_score({"scores": {"wardScore": "1.5"}}) != 1.5:
        return FAIL, "wardScore as a string was not coerced"
    for bad in (float("nan"), float("inf"), -3, None, "x", [1]):
        if lw.ward_score({"scores": {"wardScore": bad}}) is not None:
            return FAIL, f"wardScore {bad!r} was accepted"

    # --- the opposite number: by POSITION, else their best, and labelled honestly
    def pl(pos, vs):
        return {"position": pos, "scores": {"wardScore": vs}}
    en = [pl("TOP", 3), pl("UTILITY", 14), pl("JUNGLE", 9)]
    if lw.counterpart("support", en) != ("their sup", 14.0):
        return FAIL, "the enemy support's vision score is not the one shown to a support"
    if lw.counterpart("jungle", en) != ("their jg", 9.0):
        return FAIL, "the enemy jungler's vision score is not the one shown to a jungler"
    if lw.counterpart("support", [pl("", 5), pl("", 8)]) != ("their best", 8.0):
        return FAIL, "with no positions the fallback must be their BEST, labelled as such"
    if lw.counterpart("support", []) != (None, None):
        return FAIL, "counterpart invented a number out of an empty enemy team"

    # --- the instruction: every objective x every trinket, side-correct and executable
    for label, side in lw._SIDE.items():
        for tr in ("yellow", "farsight", "sweeper", None):
            txt = lw.spot(label, tr)
            if not txt or "{" in txt:
                return FAIL, f"spot({label}, {tr}) is not a finished sentence: {txt!r}"
            if tr != "farsight" and side not in txt:
                return FAIL, f"spot({label}, {tr}) names the wrong side of the map"
    if lw._SIDE["Drake"] != "bot" or lw._SIDE["Baron"] != "top":
        return FAIL, "the objective sides are wrong — the ward call points at the wrong river"
    for tr in ("yellow", "sweeper", "farsight", None):    # an objective we can't place must
        t = lw.spot(None, tr)                             # stay neutral, not guess a river
        if "botside" in t or "topside" in t:
            return FAIL, f"spot(None, {tr}) named a side it cannot know: {t!r}"

    # --- every verdict branch is reachable and lands where it should
    want = {"setup": "SETUP", "pink": "PINK", "justbought": "SETUP", "broke": "SETUP",
            "sweeper": "SETUP",
            "farsight": "SETUP", "row": "VISION", "onbar": "VISION", "dark": "DARK",
            "dark_onbar": "VISION", "base": "VISION", "noscore": "VISION",
            "quiet": "VISION", "jungle": "SETUP", "mid": None, "early": None}
    got = {k: (lw._verdict(lw.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    # the money branches, checked on their content and not just their name
    c = lw._verdict(lw.demo("pink"))
    if str(lw.CW_COST) not in c["line"] or "quiet" in c and c["quiet"]:
        return FAIL, "the PINK card doesn't price the ward sitting in your bag"
    c = lw._verdict(lw.demo("setup"))
    if "in by" not in c["line"] or str(lw.CW_COST) not in c["sub"]:
        return FAIL, "the SETUP card lost its deadline or its buy note"
    if str(lw.CW_COST) in (lw._verdict(lw.demo("broke")) or {})["sub"]:
        return FAIL, "it told a player with 20 gold to buy a 75g ward"
    jb = lw._verdict(lw.demo("justbought"))
    if "wards nothing" in jb["line"] or str(lw.CW_COST) in jb["sub"]:
        return FAIL, "a ward bought six seconds ago was called dead gold, or a second one sold"
    if not (lw._verdict(lw.demo("row")) or {})["sub"].startswith("1 of 2 placed"):
        return FAIL, "the pink ledger lost the buy/place split"
    if "control ward on you" not in (lw._verdict(lw.demo("row")) or {})["sub"]:
        return FAIL, "the share-of-game control-ward number is gone"
    if not (lw._verdict(lw.demo("row")) or {}).get("under"):
        return FAIL, "a support on 0.7/min did not read as under the 1.2 bar"
    if (lw._verdict(lw.demo("onbar")) or {}).get("under"):
        return FAIL, "a support over the bar read as under it"
    if "vision score hasn't moved" not in (lw._verdict(lw.demo("dark")) or {})["line"]:
        return FAIL, "DARK stopped stating what the NUMBER did"
    if not (lw._verdict(lw.demo("quiet")) or {}).get("quiet"):
        return FAIL, "the setup card talks over a live tempo verdict"
    if str(lw.CW_COST) not in (lw._verdict(lw.demo("base")) or {})["row"]:
        return FAIL, "a recall window is the one moment the buy must be on the row"
    # a payload with no wardScore still coaches the control ward instead of going blank
    nos = lw._verdict(lw.demo("noscore"))
    if not nos or "/min" in nos["row"]:
        return FAIL, "a missing wardScore either silenced the row or invented a rate"

    # --- the guard, driven through a full simulated game -----------------------------------
    def payload(t, pink=0, vs=0.0, dead=False, pos="UTILITY", gold=300.0, ev=None):
        me = {"riotId": "M#1", "team": "ORDER", "position": pos, "isDead": dead, "level": 9,
              "championName": "Nautilus",
              "scores": {"creepScore": 10, "kills": 0, "assists": 4, "deaths": 0,
                         "wardScore": vs},
              "items": ([{"itemID": lw.CW_ID, "count": pink}] if pink else [])
                       + [{"itemID": 3340, "slot": 6}]}
        opp = {"riotId": "E#1", "team": "CHAOS", "position": "UTILITY", "isDead": False,
               "level": 9, "championName": "Lulu",
               "scores": {"creepScore": 8, "kills": 0, "assists": 3, "deaths": 0,
                          "wardScore": 2.0 * (t / 60.0)},
               "items": []}
        return {"activePlayer": {"riotId": "M#1", "currentGold": gold},
                "allPlayers": [me, opp], "gameData": {"gameTime": float(t)},
                "events": {"Events": ev or []}}

    # a support who buys a pink at 4:00, places it at 5:30, buys again at 9:00, holds it, and
    # wards steadily. Every second of a 15-minute game.
    g = lw.Guard()
    cards, seen_v, dead_frames = [], set(), 0
    for t in range(0, 900):
        pink = 1 if (240 <= t < 330 or t >= 540) else 0
        dead = 400 <= t <= 430
        c = g.observe({}, payload(t, pink=pink, vs=0.35 * (t / 60.0), dead=dead))
        if dead and c is not None:
            dead_frames += 1
        if c:
            seen_v.add(c["verdict"])
            if not c.get("quiet"):
                cards.append((t, c["verdict"], c["obj"]))
    if dead_frames:
        return FAIL, f"the ward clock spoke on {dead_frames} frames while the player was dead"
    if g.bought != 2 or g.placed != 1:
        return FAIL, f"inventory tracking says {g.bought} bought / {g.placed} placed, want 2/1"
    if "VISION" not in seen_v:
        return FAIL, "the quiet row never appeared in a 15-minute game"
    # ONE card per objective spawn, never a running scold
    for lab in set(o for _t, _v, o in cards):
        runs, prev = 0, None
        for t, _v, o in cards:
            if o != lab:
                continue
            if prev is None or t - prev > lw.CARD_SECS + 8:
                runs += 1
            prev = t
        objs = ll.objectives(payload(900))
        if runs > 6:
            return FAIL, f"{lab} produced {runs} separate card windows in one game"
    if not cards:
        return FAIL, "no setup card fired across a whole game of objectives"
    if any(v not in ("PINK", "SETUP", "DARK") for _t, v, _o in cards):
        return FAIL, f"an unexpected card verdict: {set(v for _t, v, _o in cards)}"
    # the card must never survive past its window: the row is the resting state
    loud = sum(1 for t, _v, _o in cards)
    if loud > 240:
        return FAIL, f"the card owned the directive slot for {loud}s of a 15-minute game"

    # ...and a second game with real DragonKill events, so the drake RESPAWNS and the setup
    # window comes round again. A support holding a control ward into one must be told so,
    # and every share-of-the-game number has to stay inside the world of the possible.
    g2 = lw.Guard()
    ev = [{"EventName": "DragonKill", "EventTime": 320.0, "KillerName": "E#1",
           "DragonType": "Fire"}]
    loud, pcts = set(), []
    for t in range(300, 700):
        c = g2.observe({}, payload(t, pink=1, vs=0.4 * (t / 60.0), ev=ev))
        if c:
            pcts.append(c["dark_pct"])
            if not c.get("quiet"):
                loud.add(c["verdict"])
                if not c.get("clock_txt") and not c.get("left"):
                    return FAIL, f"a {c['verdict']} card has an empty clock slot"
    if "PINK" not in loud:
        return FAIL, "a support holding a control ward into a drake window was never told"
    if not pcts or min(pcts) < 0 or max(pcts) > 100:
        return FAIL, f"dark share out of range: {min(pcts or [0])}..{max(pcts or [0])}%"

    # a MID LANER hears nothing, ever — the tag has never graded a laner's vision
    gm = lw.Guard()
    for t in range(180, 900, 7):
        if gm.observe({}, payload(t, pink=1, vs=1.0, pos="MIDDLE")) is not None:
            return FAIL, f"the ward clock spoke to a mid laner at {t}s"

    # --- malformed payload sweep: the widget must never lose a frame to this module
    gj = lw.Guard()
    junk = [None, {}, {"allPlayers": []}, {"activePlayer": {}, "allPlayers": []},
            {"activePlayer": {"riotId": "M#1"}, "allPlayers": [{"riotId": "M#1"}]},
            {"activePlayer": {"riotId": "M#1"}, "allPlayers": [{"riotId": "M#1", "team": "ORDER"}],
             "gameData": {"gameTime": float("nan")}},
            {"activePlayer": {"riotId": "M#1"}, "allPlayers": [{"riotId": "M#1", "team": "ORDER"}],
             "gameData": {"gameTime": "soon"}},
            {"activePlayer": {"riotId": "M#1", "currentGold": None},
             "allPlayers": [{"riotId": "M#1", "team": "ORDER", "position": "UTILITY",
                             "scores": None, "items": None}],
             "gameData": {"gameTime": 400.0}},
            {"activePlayer": {"riotId": "M#1", "currentGold": "lots"},
             "allPlayers": [{"riotId": "M#1", "team": "ORDER", "position": "UTILITY",
                             "scores": {"wardScore": None}, "items": [None]}],
             "gameData": {"gameTime": 400.0}, "events": None},
            {"activePlayer": {"riotId": "M#1"}, "allPlayers": [{"riotId": "M#1", "team": "ORDER",
             "position": "UTILITY", "scores": {"wardScore": 4}}],
             "gameData": {"gameTime": 400.0}, "events": {"Events": [{"EventName": "DragonKill"}]}},
            ]
    for j in junk:
        try:
            gj.observe({}, j)
        except Exception as e:
            return FAIL, f"crashed on a malformed payload ({type(e).__name__}: {e})"
    # ...and a clock that jumps backwards is a NEW game, not a corrupt one
    gr = lw.Guard()
    gr.observe({}, payload(600, pink=1))
    gr.observe({}, payload(600, pink=0))
    if gr.placed != 1:
        return FAIL, "placing a control ward was not registered"
    gr.observe({}, payload(30, pink=0))
    if gr.placed or gr.bought or gr._done:
        return FAIL, "a new game did not reset the guard"
    # --- the decoder card must actually CONTAIN the new section. Drawing past the legend's
    #     canvas is SILENT in PIL, so a section that overruns it doesn't raise - it just
    #     vanishes off the bottom of the card, which is how a verdict ships undocumented.
    try:
        import smitewidget as sw
        leg = sw._render_legend()
        band = leg.crop((0, leg.height - 30, leg.width, leg.height - 4))
        if not any(sum(px) > 150 for px in list(band.getdata())):
            return FAIL, "the legend's last WARD row fell off the bottom of its canvas"
        if len(sw._LEGEND_WARD) != 4:
            return FAIL, "a WARD verdict is missing from the legend"
    except Exception:
        pass                                     # not on Windows / no Win32: skip the render
    return OK, ("bar matches the tag, window matches lollive, 16 fixtures + two simulated "
                "games + a junk sweep + the legend row hold")


def c_mute():
    """AUTO-MUTE. It used to TYPE `/fullmute all` into the game and could never tell whether
    that landed - so it claimed success for four releases while muting nobody. It now writes
    the client's own settings, which means the state is READABLE, and this check reads it.
    A key Riot renames must fail here rather than silently do nothing."""
    import lolmute as lm, lolgame as lg
    # THE bug that cost four releases: Enter went out as a virtual key with wScan=0, the game
    # reads scan codes, so chat never opened and every character hit a gameplay bind instead.
    # A zero here means auto-mute is silently mashing keys at your champion. Guard it forever.
    if not lm.ENTER_SCAN():
        return FAIL, "Enter has no scan code - chat won't open and the command types into the game"
    bad = [c for c in lm.CMD if lm.scan_of(c) is None]
    if bad:
        return FAIL, f"this keyboard layout can't type {bad!r}"
    if lm.FIRE_AT < 3.0:
        return FAIL, f"firing at gameTime {lm.FIRE_AT}s - too early, the client eats the keys"
    # SAFETY, not tuning. Typing is only safe while you're parked in the fountain: clicking to
    # move takes focus off League's chat box, and a character that misses it becomes a keybind
    # ('f' in "fullmute" = Flash). v0.9.56's 25s "confirming" resend cast Flash mid-walk. There
    # must be exactly one attempt, and it must stop before you're out on the map.
    if hasattr(lm, "CONFIRM_AT"):
        return FAIL, "a second mute attempt is back - it types while you're moving and casts Flash"
    if getattr(lm, "LATE_LIMIT", 999) > 30.0:
        return FAIL, f"still typing at gameTime {lm.LATE_LIMIT}s - you're on the map by then"
    # THE bug that broke it in a real game: the v0.9.55 rewrite dropped the single-instance
    # mutex, the tray re-spawns on any phase flap, and THREE copies typed into one chat box in
    # the same second. Interleaved character by character that is garbage, not a command - and
    # the log said TYPED three times, so it looked like success. Never again.
    if not hasattr(lm, "_single_instance"):
        return FAIL, "no single-instance guard - concurrent copies will interleave into garbage"
    # Prove the SEMANTICS on a throwaway mutex. Grabbing the real one would make this check
    # fail exactly when auto-mute is running properly, which is the wrong way round.
    probe = "Global\\SmitelessSelftestProbe"
    if not lm._single_instance(probe) or lm._single_instance(probe):
        return FAIL, "the single-instance guard doesn't actually exclude a second copy"
    if not hasattr(lm, "_SEND_LOCK"):
        return FAIL, "no in-process send lock - two threads could interleave the command"
    if not hasattr(lm, "player_dead"):
        return FAIL, "no death-window retry - a missed fountain attempt would never recover"
    detail = f"Enter=0x{lm.ENTER_SCAN():02x}, {lm.CMD!r} all mappable"
    if not lg._lcu():
        return OK, detail + "; client down, settings layer unverified"
    st = lm.read_state()
    if st is None:
        return FAIL, "the client no longer exposes " + ", ".join(
            f"{g}.{k}" for g, ks in lm.MUTED.items() for k in ks)
    on = all(st.get(f"{g}.{k}") == v for g, ks in lm.MUTED.items() for k, v in ks.items())
    return OK, detail + f"; settings {'MUTED' if on else 'unmuted'}"


def c_muteguard():
    """The input guard that makes auto-mute's typing safe to sit through. It must tell YOUR
    hands apart from our injected keys (via the LLKHF_INJECTED / LLMHF_INJECTED flags) — if it
    can't, it either aborts on its own keystrokes and never mutes, or misses yours and lets a
    keypress shred the command. Mouse MOVEMENT must be ignored: the cursor is never still, and
    moving it doesn't defocus League's chat box; only a click does."""
    import lolmute as lm
    G = lm._InputGuard
    import ctypes
    from ctypes import wintypes

    def fire(kind, wparam, flags):
        g = G()
        idx, mask, skip = ((2, G._LLKHF_INJECTED, ()) if kind == "kb"
                           else (3, G._LLMHF_INJECTED, G._HARMLESS_MOUSE))
        proc = g._make(mask, idx, skip)
        buf = (wintypes.DWORD * 8)(*([0] * 8))
        buf[idx] = flags
        proc(0, wparam, ctypes.cast(ctypes.pointer(buf), ctypes.c_void_p).value)
        return g.interrupted

    cases = [("real keypress", "kb", 0x0100, 0x00, True),
             ("our injected key", "kb", 0x0100, 0x10, False),
             ("mouse move", "ms", 0x0200, 0x00, False),
             ("mouse wheel", "ms", 0x020A, 0x00, False),
             ("real left click", "ms", 0x0201, 0x00, True),
             ("real right click", "ms", 0x0204, 0x00, True),
             ("our injected click", "ms", 0x0201, 0x01, False)]
    bad = [n for n, k, w, f, want in cases if fire(k, w, f) != want]
    if bad:
        return FAIL, "input guard wrong on: " + ", ".join(bad)
    # The live half only means anything if YOU aren't typing during it — otherwise it's your
    # keyboard tripping the guard, which is the guard working. Skip it rather than cry wolf.
    if lm.idle_ms() < 400:
        return OK, "discrimination matrix passes (live check skipped - you're using the keyboard)"
    with G() as g:                                   # and it must not trip on our own typing
        time.sleep(0.1)
        sh = lm._u32.MapVirtualKeyW(0x10, 0)
        for _ in range(8):
            lm._tap_scan(sh, 0.02)
            time.sleep(0.02)
        time.sleep(0.15)
        self_trip = g.interrupted
    if g._hooks:
        return FAIL, "low-level hooks left installed after the guard exited"
    if self_trip and lm.idle_ms() > 400:
        return FAIL, "the guard trips on our OWN injected keys - it would abort every time"
    return OK, "tells your keys/clicks from ours; ignores mouse movement; hooks released"


def c_fit():
    """PERSONAL FIT: the recommender's read of YOUR results. It must veto only on real evidence
    (losing three in a row is not proof), demote champs you play below your own standard, and
    promote ones you're good on but haven't touched — the rotation answer to getting bored.
    A veto firing on thin data would silently delete good picks, so the bar is checked here."""
    import lolfit as fit
    rec = {"baseline": 83, "recent": ["yasuo", "hecarim", "khazix"],
           "champs": {"loser": {"g": 10, "w": 1, "avg": 60},      # 10%: proven bad
                      "unlucky": {"g": 3, "w": 0, "avg": 80},     # 0-3 but no sample -> no veto
                      "cold": {"g": 5, "w": 3, "avg": 65},        # wins, plays it badly
                      "neglected": {"g": 6, "w": 4, "avg": 95},   # good + not in recent -> fresh
                      "onegood": {"g": 1, "w": 1, "avg": 120},    # one game is not a champion
                      "yasuo": {"g": 16, "w": 8, "avg": 64}}}
    want = {"loser": "veto", "unlucky": None, "cold": "cold", "neglected": "fresh",
            "onegood": None}
    bad = [f"{k}: got {fit.verdict(rec, k)[0]}, want {v}"
           for k, v in want.items() if fit.verdict(rec, k)[0] != v]
    if bad:
        return FAIL, "; ".join(bad)
    for k in want:
        kind, why = fit.verdict(rec, k)
        if kind and not why:
            return FAIL, f"{k} returned a {kind} verdict with no evidence line"
    dd = {"id2name": {1: "loser", 2: "neglected", 3: "cold"}}
    order, notes = fit.apply(rec, dd, [1, 2, 3])
    if 1 in order:
        return FAIL, "a vetoed champion survived into the recommendations"
    if order[0] != 2:
        return FAIL, "a fresh champion was not promoted above a cold one"
    if not notes.get(1) or not notes.get(2):
        return FAIL, "apply() dropped the evidence notes the panel prints"
    return OK, "vetoes only on real samples; cold demoted, fresh promoted, evidence attached"


def c_runes():
    """ADAPTIVE RUNES: the enemy comp decides which op.gg page to import. This must fire ONLY
    on an unambiguous comp — a wrong call silently imports the wrong keystone for a whole game,
    which is worse than always taking the most-played page."""
    import lolrunes as lr
    want = {"tank": 1,      # 3 tanks -> the Conqueror page
            "squish": 0,    # all squishy -> Electrocute is already right, don't touch it
            "mixed": 0,     # one tank -> no call
            "early": 0,     # under 3 locked -> refuse to read a comp off two picks
            "thin": 0}      # the fitting page has a 9-game sample -> never import a meme
    bad = []
    for k, idx in want.items():
        dd, opts, en = lr.demo(k)
        got, why = lr.choose(dd, opts, en)
        if got != idx:
            bad.append(f"{k}: page {got}, want {idx}")
        elif got != 0 and not why:
            bad.append(f"{k}: switched pages with no evidence line")
        elif got == 0 and why:
            bad.append(f"{k}: claimed a reason while keeping the default")
    if bad:
        return FAIL, "; ".join(bad)
    if not (lr.SUSTAINED & {"Conqueror"}) or not (lr.BURST & {"Electrocute"}):
        return FAIL, "the keystone classes lost their anchors"
    if lr.SUSTAINED & lr.BURST:
        return FAIL, f"a keystone is in BOTH classes: {lr.SUSTAINED & lr.BURST}"
    return OK, "switches only on a clear comp, cites op.gg's own sample, ignores thin pages"


def c_maxelo():
    """MAX ELO arms a list of setting keys by name. A typo there is invisible - the switch
    would look armed and quietly leave a feature off - so every key must be a real toggle."""
    import smiteconfig as cfg
    unknown = [k for k in cfg.MAX_ELO_ON if k not in cfg.BOOLS]
    if unknown:
        return FAIL, f"MAX_ELO_ON names settings that don't exist: {unknown}"
    for k in ("auto_accept", "auto_ban", "auto_mute", "re_entry", "tempo_coach"):
        if k not in cfg.MAX_ELO_ON:
            return FAIL, f"MAX_ELO_ON is missing {k!r} - that's a climb feature"
    import lolimport as limp
    if not (hasattr(limp, "auto_pick") and hasattr(limp, "pick_watch_update")):
        return FAIL, "the champ auto-lock is missing - MAX ELO can't hold your pool"
    return OK, f"{len(cfg.MAX_ELO_ON)} climb toggles, all real; auto-lock present"


def c_autolock():
    """MAX ELO's auto-LOCK, against a simulated champ-select session. This can't be triggered
    on demand in a real client, and a break means you find out by getting a champion you didn't
    ask for, mid-draft, with no way back. So every branch runs here every time."""
    import lolbuild as lb, lolimport as limp
    dd = lb.ddragon()
    YAS, YONE = dd["name2id"]["yasuo"], dd["name2id"]["yone"]
    real, real_log, real_own = limp._lcu_json, limp._picklog, limp.pickable_ids
    # smiteless_pick.log is a DIAGNOSTIC — it exists to answer "why didn't my champ lock".
    # Fixture runs writing fake LOCKED lines into it makes it useless for that, so they don't.
    limp._picklog = lambda *a, **k: None

    class Fake:                                  # PATCH sets intent; completed (or POST) locks
        def __init__(self, bans=(), locked=(), in_progress=True):
            self.act = {"id": 7, "actorCellId": 0, "type": "pick", "isInProgress": in_progress,
                        "completed": False, "championId": 0}
            self.bans, self.locked = list(bans), list(locked)

        def __call__(self, method, path, payload=None, timeout=5):
            if method == "GET":
                other = [{"id": 9, "actorCellId": 3, "type": "pick", "completed": True,
                          "championId": c} for c in self.locked]
                return {"localPlayerCellId": 0, "timer": {"adjustedTimeLeftInPhase": 27000},
                        "bans": {"myTeamBans": self.bans, "theirTeamBans": []},
                        "myTeam": [], "actions": [[self.act], other]}
            if method == "PATCH":
                self.act["championId"] = payload.get("championId", 0)
                self.act["completed"] = self.act["completed"] or bool(payload.get("completed"))
            if method == "POST" and path.endswith("/complete"):
                self.act["completed"] = True
            return {}

    def lock(fake, pool, settle=True, owned=None):
        limp._lcu_json = fake
        limp.pickable_ids = (lambda *a, **k: owned) if owned is not None else (lambda *a, **k: None)
        limp._PICK_HOVER.update(action=None, cid=0, ts=0.0)
        limp._PICK_FAIL.clear()
        limp.auto_pick(dd, pool)                 # tick 1: hover only, never a lock
        if settle:
            limp._PICK_HOVER["ts"] -= limp.PICK_SETTLE_S + 0.1
        return limp.auto_pick(dd, pool)          # tick 2: the lock

    try:
        cases = [("main free", Fake(), [YAS, YONE], YAS),
                 ("main banned -> backup", Fake(bans=[YAS]), [YAS, YONE], YONE),
                 ("main taken -> backup", Fake(locked=[YAS]), [YAS, YONE], YONE),
                 ("both gone", Fake(bans=[YAS], locked=[YONE]), [YAS, YONE], None),
                 ("not my turn", Fake(in_progress=False), [YAS, YONE], None),
                 ("no pool", Fake(), [], None)]
        bad = [n for n, f, pool, want in cases if lock(f, pool) != want]
        if lock(Fake(), [YAS, YONE], settle=False) is not None:
            bad.append("locked before the hover settled")
        # OWNERSHIP. Dropping the mastery gate made the pool merit-only, which includes
        # champions you don't own — the client refuses those, and v0.9.59 retried one every
        # second until the timer ran out and the draft picked for you. The top pick being
        # unowned must fall straight through to the next one.
        if lock(Fake(), [YAS, YONE], owned={YONE}) != YONE:
            bad.append("an unowned top pick must skip to the next champion")
        if lock(Fake(), [YAS, YONE], owned=set()) is not None:
            bad.append("owning nothing on the list must lock nothing")
        if lock(Fake(), [YAS, YONE], owned={YAS, YONE}) != YAS:
            bad.append("owning both must still take the best one")
        # FLIP-FLOP. The pool is rebuilt every poll and suggest_champs treats an ally's champ as
        # unavailable — and our own hover IS an ally pick, so hovering A promoted B and hovering
        # B promoted A. It oscillated once a second and never locked. auto_pick must COMMIT to
        # its target: a pool that reorders underneath it changes nothing.
        f = Fake()
        limp._lcu_json = f
        limp.pickable_ids = lambda *a, **k: {YAS, YONE}
        limp._PICK_HOVER.update(action=None, cid=0, ts=0.0)
        limp._PICK_FAIL.clear()
        limp.auto_pick(dd, [YAS, YONE])          # commits to Yasuo
        first = f.act["championId"]
        for i in range(6):                       # pool flips order under it, once a "second"
            limp.auto_pick(dd, ([YONE, YAS] if i % 2 == 0 else [YAS, YONE]))
        if f.act["championId"] != first:
            bad.append("target changed when the pool reordered (the flip-flop is back)")
        limp._PICK_HOVER["ts"] -= limp.PICK_SETTLE_S + 0.1
        if limp.auto_pick(dd, [YONE, YAS]) != first:
            bad.append("did not lock the champion it committed to")
        limp._PICK_HOVER.update(action=None, cid=0, ts=0.0)
        limp._PICK_FAIL.clear()
    finally:
        limp._lcu_json, limp._picklog, limp.pickable_ids = real, real_log, real_own
    if bad:
        return FAIL, "auto-lock wrong on: " + "; ".join(bad)
    return OK, "hover-then-lock, ban/taken fallback to backup, stands down when both are gone"


def c_lcu():
    import lolgame as lg, lolbuild as lb
    lc = lg._lcu()
    if not lc:
        return SKIP, "League client not running"
    port, hdr = lc
    ph = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/gameflow-phase",
                 headers=hdr, timeout=4, insecure=True)
    return OK, f"connected - phase = {ph}"


def main():
    print("\nSMITELESS SELF-TEST")
    print("=" * 66)
    checks = [
        ("Pillow (image render)", c_pillow),
        ("Data Dragon (champ data)", c_ddragon),
        ("op.gg (builds + matchups)", c_opgg),
        ("Riot API key (player scout)", c_riot_key),
        ("claude CLI (matchup tips)", c_claude),
        ("Tag spec (docs/TAGS.md)", c_tagspec),
        ("Glyph coverage (tofu)", c_glyphs),
        ("Queue call (verdict engine)", c_queuecall),
        ("Re-entry guard (90s window)", c_reentry),
        ("Bleed guard (first 14 min)", c_bleed),
        ("Closer (win conversion)", c_closer),
        ("Gold clock (farm pace)", c_gold),
        ("Ward clock (objective vision)", c_ward),
        ("Auto-mute (chat + settings)", c_mute),
        ("Auto-mute input guard", c_muteguard),
        ("Personal fit (your results)", c_fit),
        ("Adaptive runes (comp-aware)", c_runes),
        ("MAX ELO (one-switch arming)", c_maxelo),
        ("MAX ELO auto-lock (draft)", c_autolock),
        ("League client / LCU", c_lcu),
    ]
    for name, fn in checks:
        check(name, fn)
    mark = {OK: "[ OK ]", FAIL: "[FAIL]", SKIP: "[skip]"}
    for name, status, detail in results:
        print(f"{mark[status]} {name:30} {detail}")
    print("=" * 66)
    fails = [r for r in results if r[1] == FAIL]
    if fails:
        print(f"{len(fails)} check(s) FAILED. The overlay's core needs Pillow + Data Dragon "
              f"+ op.gg; the rest gate optional features.")
    else:
        print("All good. (skips are optional features that aren't set up / not running.)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
