#!/usr/bin/env python3
"""lolimport.py - write the op.gg runes + summoners into the League client (LCU).

Shared by the champ-select panel's Import button and the AUTO-IMPORT path (imports the
moment you lock a champion, when the toggle is on). POSTs a fresh "Smiteless ..." rune
page (recycling an old Smiteless page / the current editable one when the page limit is
hit) and PATCHes the summoner picks, honoring the Flash-on-D/F preference.
"""
import json
import ssl
import time
import urllib.request

import lolgame as lg
import smiteconfig as cfg


def _lcu_json(method, path, payload=None, timeout=5):
    lc = lg._lcu()
    if not lc:
        raise RuntimeError("League client not found")
    port, hdr = lc
    headers = dict(hdr)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"https://127.0.0.1:{port}{path}", headers=headers,
                                 data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as r:
        raw = r.read()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def hover_champ(cid):
    """HOVER (select, not lock) a champion in champ select via the LCU: PATCH your in-progress
    pick action with the championId and no 'completed' flag. The client then shows it as your
    intent, and the overlay re-renders to that champ. Returns "hovered"; raises RuntimeError
    with a friendly message on anything expected. Never locks — that's a separate action."""
    if not cid:
        raise RuntimeError("no champion")
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        raise RuntimeError("not in champ select")
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        raise RuntimeError("not in champ select")
    cell = sess.get("localPlayerCellId")
    action_id = None
    for group in (sess.get("actions") or []):
        for a in group:
            if (a.get("actorCellId") == cell and a.get("type") == "pick"
                    and not a.get("completed")):
                action_id = a.get("id")               # your current (un-locked) pick slot
    if action_id is None:
        raise RuntimeError("can't hover yet — wait for your turn (or you've already locked)")
    _lcu_json("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}",
              {"championId": int(cid)})
    return "hovered"


BAN_WAIT_MS = 12000        # hold the auto-ban until this little is left on the phase clock


def auto_ban(dd, targets, extra_avoid=()):
    """If it's YOUR ban turn right now, LOCK the first champ in `targets` that's safe to ban:
    not already banned/picked and not a teammate's hovered pick (never ban an ally's champ).
    DELIBERATELY WAITS until the last ~12s of the ban phase before locking — every extra
    second lets more teammates hover, and the team-wide ban math gets sharper with each
    hover (the caller recomputes `targets` every poll). Fires immediately if the timer
    isn't readable (never risk missing the ban). Returns the banned championId or None.
    Never raises — auto-ban must never disrupt champ select."""
    if not targets:
        return None
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        return None
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        return None
    cell = sess.get("localPlayerCellId")
    action_id = None
    for group in (sess.get("actions") or []):
        for a in group:
            if (a.get("actorCellId") == cell and a.get("type") == "ban"
                    and a.get("isInProgress") and not a.get("completed")):
                action_id = a.get("id")
    if action_id is None:
        return None                              # not your ban turn
    tmr = sess.get("timer") or {}
    left = tmr.get("adjustedTimeLeftInPhase")
    if (not tmr.get("isInfinite")) and isinstance(left, (int, float)) and left > BAN_WAIT_MS:
        return None                              # clock still fat -> wait for more hovers
    avoid = set(int(c) for c in extra_avoid if c)
    b = sess.get("bans") or {}
    for c in (b.get("myTeamBans") or []) + (b.get("theirTeamBans") or []):
        if c:
            avoid.add(int(c))
    for m in (sess.get("myTeam") or []):         # don't ban a teammate's hovered / locked champ
        pi = m.get("championPickIntent") or m.get("championId") or 0
        if pi:
            avoid.add(int(pi))
    for group in (sess.get("actions") or []):    # or anything already locked
        for a in group:
            if a.get("completed") and a.get("championId"):
                avoid.add(int(a["championId"]))
    pick = next((int(c) for c in targets if c and int(c) not in avoid), None)
    if not pick:
        return None
    try:
        _lcu_json("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}",
                  {"championId": pick, "completed": True})
        return pick
    except Exception:
        return None


_POS_SWAP_LAST = {"sid": None, "ts": 0.0}     # anti-spam for our outgoing ROLE-swap requests


def _post_pos_swap(sid, cellid, action):
    """POST a position-swap action. request/accept can key off the swap id or the holder's
    cellId depending on client version — try both; the wrong one 404s harmlessly."""
    for seg in (sid, cellid):
        if seg is None:
            continue
        try:
            _lcu_json("POST", f"/lol-champ-select/v1/session/position-swaps/{int(seg)}/{action}")
            return True
        except Exception:
            continue
    return False


def auto_accept_swap(want_roles):
    """Work the ROLE (assigned-position) swaps toward a lane you want — the autofill escape.
    `want_roles` = the app roles you'll play ('top','jungle','mid','adc','support'); empty ->
    no-op. If you're already on a wanted role, does nothing. Otherwise it ACCEPTS any incoming
    offer that lands you on a wanted role, and otherwise proactively REQUESTS a swap from a
    teammate who's ON one of your wanted roles (one live ask, 10s anti-spam). It only ever
    moves you ONTO a wanted role, never off one. Returns a short status ('jungle' /
    'ask jungle') or None. Never raises — must not disrupt champ select. (LCU: positionSwaps.)"""
    want = [r for r in (want_roles or []) if r]
    if not want:
        return None
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        return None
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        return None
    swaps = sess.get("positionSwaps") or []
    if not swaps:
        return None
    local = sess.get("localPlayerCellId")
    pos_of, my_pos = {}, ""
    for m in (sess.get("myTeam") or []):
        role = lg.ROLE.get((m.get("assignedPosition") or "").lower(), "")
        pos_of[m.get("cellId")] = role
        if m.get("cellId") == local:
            my_pos = role
    if not my_pos or my_pos in want:
        return None                              # no assigned role (blind/ARAM), or already happy

    # 1) ACCEPT an incoming offer that lands you on a wanted role.
    for s in swaps:
        if s.get("state") != "RECEIVED":
            continue
        their = pos_of.get(s.get("cellId"), "")
        if their and their in want:
            return their if _post_pos_swap(s.get("id"), s.get("cellId"), "accept") else None

    # 2) Otherwise REQUEST a swap from a teammate who's ON a wanted role (want-order preference).
    for role in want:
        cell = next((c for c, r in pos_of.items() if r == role and c != local), None)
        if cell is None:
            continue
        s = next((x for x in swaps if x.get("cellId") == cell), None)
        if not s or s.get("state") not in (None, "AVAILABLE"):
            continue                             # already SENT/BUSY/DECLINED -> leave it
        sid = s.get("id")
        now = time.time()
        if _POS_SWAP_LAST["sid"] == sid and now - _POS_SWAP_LAST["ts"] < 10:
            return None                          # don't hammer the same teammate
        _POS_SWAP_LAST.update(sid=sid, ts=now)
        return f"ask {role}" if _post_pos_swap(sid, cell, "request") else None
    return None


_PICK_SWAP_LAST = {"sid": None, "ts": 0.0}    # anti-spam for our outgoing pick-order requests


def _post_pick_swap(sid, action):
    """POST a pick-order-swap action. The LCU has shipped TWO spellings for this path across
    patches (/session/swaps/ and /session/pick-order-swaps/), so try both — the wrong one just
    404s harmlessly. Returns True on success."""
    for base in ("swaps", "pick-order-swaps"):
        try:
            _lcu_json("POST", f"/lol-champ-select/v1/session/{base}/{int(sid)}/{action}")
            return True
        except Exception:
            continue
    return False


def auto_pick_order_swap(target):
    """Handle champ-select PICK ORDER swaps. `target`:
      'any'         -> just ACCEPT every incoming pick-order request (no direction, no asking).
      'first'/'last'-> pick as early / late as possible (last = counter-pick).
      '1'..'5'      -> seek that exact pick slot (clamped to the lobby size); '4'/'5' let you
                       pick near the end without insisting on dead-last.
      '' / anything else = off.
    Accepts an incoming offer that moves you closer to the target, otherwise requests a swap
    toward it. Returns a short status string or None. Never raises — must not disrupt champ
    select. (LCU: pickOrderSwaps in the session.)"""
    target = str(target).strip().lower()
    if target not in ("any", "first", "last") and not (target.isdigit() and target != "0"):
        return None
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        return None
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        return None
    local = sess.get("localPlayerCellId")
    team_cells = {m.get("cellId") for m in (sess.get("myTeam") or [])}
    # Pick slots 1..N for our team, from the ORDER of pick actions in the session.
    order, done = [], False
    for grp in (sess.get("actions") or []):
        for a in grp:
            if a.get("type") == "pick" and a.get("actorCellId") in team_cells:
                c = a.get("actorCellId")
                if c not in order:
                    order.append(c)
                if c == local and a.get("completed"):
                    done = True                  # you've already locked -> swapping is moot
    pos = {c: i + 1 for i, c in enumerate(order)}
    my_pos = pos.get(local)
    if done:
        return None
    swaps = sess.get("pickOrderSwaps") or []

    if target == "any":                          # simplest mode: accept EVERY incoming request
        for s in swaps:
            if s.get("state") == "RECEIVED":
                return (f"pick {pos.get(s.get('cellId'), '?')}"
                        if _post_pick_swap(s.get("id"), "accept") else None)
        return None

    if not my_pos or len(order) < 2:
        return None
    # Resolve the desired slot number, clamped to the actual lobby size.
    if target == "first":
        want = 1
    elif target == "last":
        want = len(order)
    else:
        want = max(1, min(len(order), int(target)))
    if my_pos == want:
        return None                              # already where you want to be
    # A slot is "better" if it's strictly closer to the target than where you are now.
    dist = lambda p: abs(p - want)
    better = lambda p: p and dist(p) < dist(my_pos)

    # 1) Accept the incoming offer that lands you CLOSEST to the target (among those that help).
    incoming = [(pos.get(s.get("cellId")), s) for s in swaps if s.get("state") == "RECEIVED"]
    incoming = [(tp, s) for tp, s in incoming if better(tp)]
    if incoming:
        tp, s = min(incoming, key=lambda t: dist(t[0]))
        return f"pick {tp}" if _post_pick_swap(s.get("id"), "accept") else None

    # 2) Otherwise request a swap toward the available slot CLOSEST to the target.
    cands = sorted(((pos.get(s.get("cellId")), s) for s in swaps if s.get("state") == "AVAILABLE"),
                   key=lambda t: (dist(t[0]) if t[0] else 99))
    cands = [(tp, s) for tp, s in cands if better(tp)]
    if cands:
        tp, s = cands[0]
        sid, now = s.get("id"), time.time()
        if _PICK_SWAP_LAST["sid"] == sid and now - _PICK_SWAP_LAST["ts"] < 12:
            return None                          # don't hammer the same holder
        _PICK_SWAP_LAST.update(sid=sid, ts=now)
        return f"asked pick {tp}" if _post_pick_swap(sid, "request") else None
    return None


def import_build(dd, cid, role, build):
    """Push `build`'s runes + summoners for cid/role into the client. Returns a status
    string; raises RuntimeError with a friendly message on anything expected."""
    if not cid:
        raise RuntimeError("lock a champion first")
    if not build:
        raise RuntimeError("no op.gg build for this champ/role yet")
    perks = (build.get("primary_ids") or []) + (build.get("secondary_ids") or []) + (build.get("stat_mod_ids") or [])
    if len(perks) < 9:
        raise RuntimeError("rune data incomplete")
    page = {
        "name": f"Smiteless {dd['id2name'].get(cid, 'Champ')} {str(role or '').title()}",
        "primaryStyleId": int(build.get("primary_page_id") or 0),
        "subStyleId": int(build.get("secondary_page_id") or 0),
        "selectedPerkIds": [int(x) for x in perks[:9]],
        "current": True,
    }
    try:
        _lcu_json("POST", "/lol-perks/v1/pages", page)
    except Exception:
        pages = _lcu_json("GET", "/lol-perks/v1/pages") or []
        editable = [p for p in pages if p.get("isEditable", True)]
        target = None
        for p in editable:
            if (p.get("name") or "").startswith("Smiteless "):
                target = p
                break
        if target is None:
            target = next((p for p in editable if p.get("current")), None)
        if target is None and editable:
            target = editable[0]
        if not target or not target.get("id"):
            raise RuntimeError("rune page limit reached and no editable page is available")
        up = dict(page)
        up["id"] = int(target["id"])
        _lcu_json("PUT", f"/lol-perks/v1/pages/{int(target['id'])}", up)
    sums = build.get("summoner_ids") or []
    if len(sums) >= 2:
        s1, s2 = int(sums[0]), int(sums[1])
        flash_on_d = cfg.load().get("flash_on_d", True)
        if 4 in (s1, s2):
            if flash_on_d and s2 == 4:
                s1, s2 = s2, s1
            if (not flash_on_d) and s1 == 4:
                s1, s2 = s2, s1
        _lcu_json("PATCH", "/lol-champ-select/v1/session/my-selection",
                  {"spell1Id": s1, "spell2Id": s2})
    return f"imported for {dd['id2name'].get(cid, '?')} ({role})"
