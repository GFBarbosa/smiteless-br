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
    if not lm._single_instance():
        return FAIL, "a lolmute process is already running (or the mutex leaked)"
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
        ("Auto-mute (chat + settings)", c_mute),
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
