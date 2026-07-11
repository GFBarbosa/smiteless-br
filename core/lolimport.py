#!/usr/bin/env python3
"""lolimport.py - write the op.gg runes + summoners into the League client (LCU).

Shared by the champ-select panel's Import button and the AUTO-IMPORT path (imports the
moment you lock a champion, when the toggle is on). POSTs a fresh "Smiteless ..." rune
page (recycling an old Smiteless page / the current editable one when the page limit is
hit) and PATCHes the summoner picks, honoring the Flash-on-D/F preference.
"""
import json
import ssl
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


def auto_ban(dd, targets, extra_avoid=()):
    """If it's YOUR ban turn right now, LOCK the first champ in `targets` that's safe to ban:
    not already banned/picked and not a teammate's hovered pick (never ban an ally's champ).
    Returns the banned championId, or None (not your ban turn / nothing safe / no client).
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


def auto_accept_swap(want_roles):
    """If a teammate has offered a ROLE (assigned-position) swap that would put you on a role you
    want — and you're not already on one of your wanted roles — ACCEPT it. `want_roles` is the
    set/list of app roles you'll swap INTO ('top','jungle','mid','adc','support'); empty -> no-op.
    Only ever moves you ONTO a wanted role, never off one, so it can't strand you on a lane you
    didn't ask for. Returns the role you swapped into, or None. Never raises — must not disrupt
    champ select. (LCU: positionSwaps in the session; POST .../position-swaps/{id}/accept.)"""
    want = {r for r in (want_roles or []) if r}
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
    for s in swaps:
        if s.get("state") != "RECEIVED":         # a teammate's incoming offer, awaiting your call
            continue
        their = pos_of.get(s.get("cellId"), "")  # the role you'd RECEIVE = their current lane
        if their and their in want:
            try:
                _lcu_json("POST", f"/lol-champ-select/v1/session/position-swaps/{int(s['id'])}/accept")
                return their
            except Exception:
                return None
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
