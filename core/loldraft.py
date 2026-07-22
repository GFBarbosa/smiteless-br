#!/usr/bin/env python3
"""loldraft.py — the shareable LIVE DRAFT LINK.

Publishes the current champ select (both teams, bans, and per-seat pick suggestions
with runes/summs/core items) to a Firebase Realtime Database over plain REST, and
drops ONE link into the champ-select chat. Anyone in the lobby who clicks it lands on
the static GitHub Pages board (docs/draft/), which streams this data live over SSE —
no server, no account, updates as the draft evolves.

Costs nothing to run: the page is static hosting, the data channel is Firebase's free
Spark tier, and everything heavy (art, names) comes from Riot's public ddragon CDN in
the viewer's browser. This module only ships a few KB of champion/rune IDs.

Setup (one-time, see docs/DRAFTLINK.md): create a free Firebase RTDB, paste its URL
into Settings -> "Draft link database". No URL = the whole feature stays dormant.

CLI (manual seeding / testing, no lobby needed):
  python loldraft.py test        # publish a fake draft, print the link to open
"""
import json
import os, re, sys, threading, time, secrets
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import lolgame as lg
import phasecheck
import smiteconfig as cfg

# One publisher per process; champ select ending resets it for the next lobby.
_ST = {"thread": None, "draft_id": "", "posted": False, "opened": False, "last_pub": "",
       "sugg": {}, "sugg_key": {}, "stop": False}
_LOCK = threading.Lock()

SUGG_PER_SEAT = 3          # suggestion cards per seat (each carries runes -> keep payload lean)
PUBLISH_POLL = 2.0         # seconds between champ-select reads
_ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # unambiguous, URL-safe

# The DB host baked into the hosted page (docs/draft/index.html DEFAULT_DB). When the
# user's DB IS this one, the shared link can omit "&db=host.firebaseio.com" entirely and
# be just "…/draft/#d=ID" — short and not phishing-shaped. Keep the two in sync.
_DEFAULT_PAGE_DB = "smiteless-draft-default-rtdb.firebaseio.com"
BRAND = "DraftBoard"       # the shareable feature's identity (chat message + page)


def _new_id(n=12):
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(n))


def _db_url(settings=None):
    """The user's Firebase RTDB base URL from settings, normalized ('' = feature off).
    Accepts 'https://x-default-rtdb.firebaseio.com' or the bare host, with/without '/'."""
    s = settings or cfg.load()
    raw = (s.get("draft_db") or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = "https://" + raw
    host = raw.split("://", 1)[1].split("/", 1)[0]
    # only real Firebase RTDB hosts — anything else in the setting is a paste mistake
    if not (host.endswith(".firebaseio.com") or host.endswith(".firebasedatabase.app")):
        return ""
    return "https://" + host


def _page_url(settings=None):
    s = settings or cfg.load()
    return (s.get("draft_page") or "").strip().rstrip("/") or cfg.STRINGS["draft_page"].rstrip("/")


def link_for(draft_id, settings=None):
    """The URL that goes into chat. When the user's DB is the one the hosted page already
    bakes in (_DEFAULT_PAGE_DB — the normal case), the link is just '…/draft/#d=ID' — short
    and trustworthy. A self-hoster pointed at a different DB still gets the '&db=host' form
    so their page knows where to stream from."""
    db = _db_url(settings)
    host = db.split("://", 1)[1] if db else ""
    base = f"{_page_url(settings)}/#d={draft_id}"
    return base if host == _DEFAULT_PAGE_DB else f"{base}&db={host}"


# ---------- Firebase REST (stdlib only; the DB is public per its rules, auth-free) ----------
def _fb(method, db, path, obj=None, timeout=6):
    req = urllib.request.Request(f"{db}/{path}.json", method=method,
                                 data=(json.dumps(obj, separators=(",", ":")).encode()
                                       if obj is not None else None),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": lb.UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def publish(db, draft_id, payload):
    _fb("PUT", db, f"drafts/{draft_id}", payload)


def retire(db, draft_id):
    """Mark a draft ended (page shows 'draft over') and let it be tiny; full delete of
    stale drafts happens on the NEXT lobby so a refresh mid-game still shows something."""
    try:
        _fb("PATCH", db, f"drafts/{draft_id}", {"end": int(time.time())})
    except Exception:
        pass


def _delete(db, draft_id):
    try:
        _fb("DELETE", db, f"drafts/{draft_id}")
    except Exception:
        pass


# ---------- champ-select chat ----------
def post_chat_link(url):
    """Drop the link into the CHAMP SELECT chat via the LCU (lol-chat). True on success."""
    lc = lg._lcu()
    if not lc:
        return False
    port, hdr = lc
    try:
        convs = lb.http(f"https://127.0.0.1:{port}/lol-chat/v1/conversations",
                        headers=hdr, timeout=4, insecure=True)
        conv = next((c for c in (convs or []) if c.get("type") == "championSelect"), None)
        if not conv:
            return False
        msg = (cfg.load().get("draft_msg") or "").strip() or \
            f"{BRAND} — live picks + runes for our lobby:"
        body = json.dumps({"body": f"{msg} {url}", "type": "chat"}).encode()
        req = urllib.request.Request(
            f"https://127.0.0.1:{port}/lol-chat/v1/conversations/{conv['id']}/messages",
            data=body, headers={**hdr, "Content-Type": "application/json"}, method="POST")
        import ssl
        with urllib.request.urlopen(req, timeout=4,
                                    context=ssl._create_unverified_context()) as r:
            r.read()
        return True
    except Exception:
        return False


# ---------- payload ----------
def _rune_block(d):
    """Terse rune/summs/items block from an opgg() champ dict: ids only, the viewer's
    browser resolves names + icons from ddragon. None if the data is too thin."""
    pages = sorted((r for r in (d.get("runes") or []) if r.get("primary_rune_ids")),
                   key=lambda r: r.get("play", 0), reverse=True)
    if not pages:
        return None
    rp = pages[0]
    out = {"pp": rp.get("primary_page_id"), "pr": list(rp.get("primary_rune_ids") or []),
           "sp": rp.get("secondary_page_id"), "sr": list(rp.get("secondary_rune_ids") or [])}
    if rp.get("stat_mod_ids"):
        out["st"] = list(rp["stat_mod_ids"])
    sspells = sorted((x for x in (d.get("summoner_spells") or []) if x.get("ids")),
                     key=lambda x: x.get("play", 0), reverse=True)
    if sspells:
        out["sm"] = list(sspells[0]["ids"])
    cores = d.get("core_items") or []
    if cores:
        out["it"] = list(max(cores, key=lambda x: x.get("play", 0)).get("ids") or [])
    return out


def _suggestion(dd, cid, role, enemy_ids):
    """One suggestion card: champ + overall WR/tier + runes + the matchup WRs vs the
    locked enemies op.gg has a same-role sample for."""
    try:
        d = lb.opgg(cid, role)
    except Exception:
        return None
    if not d or "summary" not in d:
        return None
    av = d["summary"].get("average_stats") or {}
    card = {"c": cid, "wr": round((av.get("win_rate") or 0) * 100, 1),
            "t": {1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}.get(av.get("tier"), "")}
    r = _rune_block(d)
    if r:
        card["r"] = r
    vs = []
    cmap = {c.get("champion_id"): c for c in (d.get("counters") or []) if c.get("play", 0) >= 20}
    for eid in enemy_ids:
        c = cmap.get(eid)
        if c:
            vs.append({"c": eid, "wr": round(c["win"] / c["play"] * 100, 1)})
    if vs:
        card["vs"] = vs
    return card


def _seat_suggestions(dd, role, ally_ids, enemy_ids, taken):
    """Suggestion cards for one seat. Reuses the overlay's pick brain (counters + comp
    fit, meta fallback) with no mastery gate — these are for TEAMMATES whose champion
    pools we don't know, so it's 'good for THIS game', not 'good for you'."""
    import smitecard as sc                     # lazy: smitecard imports us back
    cids = sc.suggest_champs(dd, role, ally_ids, enemy_ids, topn=SUGG_PER_SEAT + 2, fam=None)
    out = []
    for cid in cids:
        if cid in taken:
            continue
        card = _suggestion(dd, cid, role, enemy_ids)
        if card:
            out.append(card)
        if len(out) >= SUGG_PER_SEAT:
            break
        time.sleep(0.1)                        # space op.gg fetches (cache absorbs repeats)
    return out


def build_payload(dd, info, with_suggestions=True):
    """The full draft document: tiny (IDs only), the page hydrates it from ddragon."""
    allies = info.get("allies") or []
    enemies = info.get("enemies") or []
    bans_my = [c for c in (info.get("bans_my") or []) if c]
    bans_their = [c for c in (info.get("bans_their") or []) if c]
    ally_ids = [c for c, _ in allies if c]
    enemy_ids = [c for c, _ in enemies if c]
    taken = set(bans_my) | set(bans_their) | set(ally_ids) | set(enemy_ids)
    seats = []
    for cid, role in allies:
        seat = {"role": role or "", "c": cid or 0}
        if cid and role:
            own = _suggestion(dd, cid, role, enemy_ids)   # runes/summs/items for the LOCKED pick
            if own:
                seat["own"] = own
        if with_suggestions and role:
            key = (role, tuple(sorted(taken)))
            with _LOCK:
                cached = _ST["sugg_key"].get(role) == key and _ST["sugg"].get(role)
            if cached:
                seat["sugg"] = _ST["sugg"][role]
            else:
                sugg = _seat_suggestions(dd, role, ally_ids, enemy_ids, taken)
                with _LOCK:
                    _ST["sugg"][role] = sugg
                    _ST["sugg_key"][role] = key
                if sugg:
                    seat["sugg"] = sugg
        seats.append(seat)
    return {"v": 1, "ts": int(time.time()), "patch": dd.get("ver", ""),
            "seats": seats, "enemy": enemy_ids,
            "bans": {"a": bans_my, "e": bans_their}}


# ---------- the per-lobby publisher thread ----------
def _worker(dd):
    db = ""
    try:
        while not _ST["stop"]:
            settings = cfg.load()
            db = _db_url(settings)
            if not db or not settings.get("draft_link", True):
                return
            if phasecheck.phase() != "ChampSelect":
                break                                  # lobby over -> retire below
            info = lg._from_champ_select(dd)
            if not info:
                time.sleep(PUBLISH_POLL)
                continue
            payload = build_payload(dd, info)
            blob = json.dumps(payload, sort_keys=True)
            # ts changes every call — compare everything BUT the timestamp
            sig = re.sub(r'"ts": \d+', "", blob)
            if sig != _ST["last_pub"]:
                try:
                    publish(db, _ST["draft_id"], payload)
                    _ST["last_pub"] = sig
                except Exception:
                    time.sleep(PUBLISH_POLL)           # network blip -> retry next round
                    continue
                if not _ST["posted"]:                  # first successful publish
                    link = link_for(_ST["draft_id"], settings)
                    _ST["posted"] = post_chat_link(link)     # ONE chat link
                    if settings.get("draft_autoopen", True) and not _ST["opened"]:
                        _ST["opened"] = True                 # open it for YOU, once per lobby
                        try:
                            import webbrowser
                            webbrowser.open(link)
                        except Exception:
                            pass
            time.sleep(PUBLISH_POLL)
    finally:
        if db and _ST["draft_id"]:
            retire(db, _ST["draft_id"])
        with _LOCK:
            _ST["thread"] = None                       # next champ select spawns fresh


def tick(dd):
    """Called from the overlay's champ-select loop. Spawns the publisher for this lobby
    (once) and returns immediately; a no-op when the feature isn't configured/enabled."""
    settings = cfg.load()
    if not settings.get("draft_link", True) or not _db_url(settings):
        return
    with _LOCK:
        if _ST["thread"] is not None:
            return
        prev, _ST["draft_id"] = _ST["draft_id"], _new_id()
        _ST.update(posted=False, opened=False, last_pub="", sugg={}, sugg_key={}, stop=False)
        t = threading.Thread(target=_worker, args=(dd,), daemon=True)
        _ST["thread"] = t
    if prev:                                           # tidy the previous lobby's node
        threading.Thread(target=_delete, args=(_db_url(settings), prev), daemon=True).start()
    t.start()


def current_link():
    """The live link for this lobby ('' if the publisher isn't running) — lets the
    overlay render it as a clickable line too."""
    with _LOCK:
        if _ST["thread"] is None or not _ST["draft_id"]:
            return ""
        return link_for(_ST["draft_id"])


# ---------- CLI: publish a fake draft so the Firebase + page setup can be tested ----------
def _demo(dd):
    def cid(nm):
        return dd["name2id"].get(dd["norm"](nm)) or 0
    allies = [(cid("Malphite"), "top"), (cid("Vi"), "jungle"), (cid("Ahri"), "mid"),
              (0, "adc"), (cid("Thresh"), "support")]
    enemies = [(cid("Darius"), ""), (cid("LeeSin"), ""), (cid("Yasuo"), "")]
    bans = dict(bans_my=[cid("Zed"), cid("Blitzcrank")], bans_their=[cid("Kayn"), cid("Shaco")])
    return dict(my=0, pos="", allies=allies, enemies=enemies, **bans)


def main():
    if "test" not in sys.argv:
        print(__doc__)
        return
    settings = cfg.load()
    db = _db_url(settings)
    if not db:
        print("no draft_db configured — Settings -> Draft link, or add \"draft_db\" to "
              f"{cfg.PATH}")
        return
    dd = lb.ddragon()
    _ST["draft_id"] = _new_id()
    payload = build_payload(dd, _demo(dd))
    publish(db, _ST["draft_id"], payload)
    print("published test draft ->", link_for(_ST["draft_id"], settings))


if __name__ == "__main__":
    main()
