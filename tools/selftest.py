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


def _llm_health_result(selected, found):
    import llmcli
    selected = llmcli.normalize_provider(selected)
    states = "; ".join(
        f"{llmcli.provider_label(provider)}="
        f"{os.path.basename(found[provider]) if found.get(provider) else 'missing'}"
        for provider in llmcli.PROVIDERS
    )
    if found.get(selected):
        return OK, f"selected {llmcli.provider_label(selected)}; {states}"
    alternatives = [llmcli.provider_label(p) for p in llmcli.PROVIDERS
                    if p != selected and found.get(p)]
    action = (f"select installed {'/'.join(alternatives)} in Settings"
              if alternatives else f"install {llmcli.provider_label(selected)} CLI")
    return FAIL, (f"selected {llmcli.provider_label(selected)} is missing -> {action}; "
                  f"{states}")


def c_llm_cli():
    import llmcli
    import smiteconfig as cfg
    selected = cfg.load().get("matchup_tip_provider", cfg.MATCHUP_TIP_PROVIDER_DEFAULT)
    return _llm_health_result(selected, llmcli.availability())


def c_llm_providers():
    """Deterministic contracts for Claude/Codex discovery, dispatch and failures."""
    import subprocess
    from unittest import mock
    import claudecli as claude
    import codexcli as codex
    import llmcli
    import llmprocess

    prompt = "Give one short, generic matchup tip."
    calls = []

    class FakeProcess:
        def __init__(self, args, fake_stdout="", fake_stderr="", code=0, write_last=None,
                     timeout_once=False, **kwargs):
            self.args = args
            self.stdout_text = fake_stdout
            self.stderr_text = fake_stderr
            self.returncode = code
            self.pid = 4242
            self.write_last = write_last
            self.timeout_once = timeout_once
            self.timed_out = False
            calls.append((args, kwargs, self))

        def communicate(self, input=None, timeout=None):
            self.input = input
            if self.timeout_once and not self.timed_out:
                self.timed_out = True
                raise subprocess.TimeoutExpired(self.args, timeout)
            if self.write_last is not None:
                path = self.args[self.args.index("--output-last-message") + 1]
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(self.write_last)
            return self.stdout_text, self.stderr_text

    bad = []
    with mock.patch.object(claude.os.path, "exists", return_value=False), \
            mock.patch.object(claude.shutil, "which", return_value=r"C:\bin\claude.exe"):
        claude_found = claude.find_claude()
    with mock.patch.object(codex.shutil, "which", return_value=r"C:\bin\codex.exe"):
        codex_found = codex.find_codex()
    if claude_found != r"C:\bin\claude.exe" or codex_found != r"C:\bin\codex.exe":
        bad.append("independent discovery")

    with mock.patch.object(claude, "call_claude", return_value=("claude", None)) as ccall, \
            mock.patch.object(codex, "call_codex", return_value=("codex", None)) as xcall:
        if llmcli.call(prompt, "claude", allow_web=True) != ("claude", None):
            bad.append("Claude dispatch")
        if xcall.called:
            bad.append("Claude failure could fail over to Codex")
        if llmcli.call(prompt, "codex", allow_web=True) != ("codex", None):
            bad.append("Codex dispatch")
        if ccall.call_count != 1 or xcall.call_count != 1:
            bad.append("provider dispatch count")

    calls.clear()
    with mock.patch.object(claude, "find_claude", return_value="claude.exe"), \
            mock.patch.object(claude.subprocess, "Popen",
                              side_effect=lambda args, **kw: FakeProcess(
                                  args, fake_stdout="Claude answer", **kw)):
        got = claude.call_claude(prompt, allow_tools="WebSearch,WebFetch", timeout=3)
    if got != ("Claude answer", None):
        bad.append("Claude success contract")
    else:
        args, kwargs, process = calls[-1]
        if process.input != prompt or "--allowedTools" not in args \
                or kwargs.get("shell") is not None:
            bad.append("Claude args/stdin")

    calls.clear()
    with mock.patch.object(codex, "find_codex", return_value="codex.exe"), \
            mock.patch.object(codex.subprocess, "Popen",
                              side_effect=lambda args, **kw: FakeProcess(
                                  args, fake_stdout="progress must be ignored",
                                  write_last="Codex answer", **kw)):
        got = codex.call_codex(prompt, timeout=3, allow_web=True)
    if got != ("Codex answer", None):
        bad.append("Codex last-message contract")
    else:
        args, kwargs, process = calls[-1]
        required = ("exec", "--ephemeral", "read-only", "--cd",
                    "--output-last-message", "-")
        if process.input != prompt or any(value not in args for value in required) \
                or kwargs["cwd"] != args[args.index("--cd") + 1]:
            bad.append("Codex args/stdin")

    cases = (
        ("auth", dict(fake_stdout="authentication_error"), "auth/API error"),
        ("limit", dict(fake_stderr="rate limit exceeded"), "limit"),
        ("exit", dict(fake_stdout="must not become a tip", code=7), "must not become a tip"),
        ("empty", dict(), "no text"),
        ("missing output", dict(fake_stdout="progress only"), "no text"),
    )
    for name, behavior, expected in cases:
        calls.clear()
        with mock.patch.object(codex, "find_codex", return_value="codex.exe"), \
                mock.patch.object(codex.subprocess, "Popen",
                                  side_effect=lambda args, _b=behavior, **kw: FakeProcess(
                                      args, **_b, **kw)):
            text, error = codex.call_codex(prompt, timeout=3)
        if text is not None or expected not in (error or ""):
            bad.append(f"Codex {name} failure")

    calls.clear()
    killed = []
    with mock.patch.object(codex, "find_codex", return_value="codex.exe"), \
            mock.patch.object(codex.subprocess, "Popen",
                              side_effect=lambda args, **kw: FakeProcess(
                                  args, timeout_once=True, **kw)), \
            mock.patch.object(llmprocess.subprocess, "run",
                              side_effect=lambda *a, **kw: killed.append((a, kw))):
        got = codex.call_codex(prompt, timeout=1)
    if got != (None, "timed out") or not killed:
        bad.append("Codex timeout/tree termination")

    claude_cases = (
        ("auth", dict(fake_stdout="authentication_error"), "auth/API error"),
        ("limit", dict(fake_stderr="usage limit reached"), "limit"),
        ("exit", dict(fake_stderr="bad invocation", code=7), "bad invocation"),
        ("empty", dict(), "no text"),
    )
    for name, behavior, expected in claude_cases:
        calls.clear()
        with mock.patch.object(claude, "find_claude", return_value="claude.exe"), \
                mock.patch.object(claude.subprocess, "Popen",
                                  side_effect=lambda args, _b=behavior, **kw: FakeProcess(
                                      args, **_b, **kw)):
            text, error = claude.call_claude(prompt, timeout=3)
        if text is not None or expected not in (error or ""):
            bad.append(f"Claude {name} failure")

    calls.clear()
    killed = []
    with mock.patch.object(claude, "find_claude", return_value="claude.exe"), \
            mock.patch.object(claude.subprocess, "Popen",
                              side_effect=lambda args, **kw: FakeProcess(
                                  args, timeout_once=True, **kw)), \
            mock.patch.object(llmprocess.subprocess, "run",
                              side_effect=lambda *a, **kw: killed.append((a, kw))):
        got = claude.call_claude(prompt, timeout=1)
    if got != (None, "timed out") or not killed:
        bad.append("Claude timeout/tree termination")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, "Claude/Codex discovery, dispatch, stdin, output and failures are isolated"


def c_llm_integration():
    """Provider config, matchup/coach dispatch and health behavior without live inference."""
    import tempfile
    from unittest import mock
    import lolcoach
    import lolmatchup
    import llmcli
    import smiteconfig as cfg

    bad = []
    real_path = cfg.PATH
    with tempfile.TemporaryDirectory(prefix="smiteless-llm-fixture-") as tmp:
        cfg.PATH = os.path.join(tmp, "settings.json")
        try:
            cases = ((None, "claude"), ("claude", "claude"), ("codex", "codex"),
                     ("other", "claude"))
            for raw_value, expected in cases:
                raw = {} if raw_value is None else {"matchup_tip_provider": raw_value}
                with open(cfg.PATH, "w", encoding="utf-8") as handle:
                    json.dump(raw, handle)
                if cfg.load()["matchup_tip_provider"] != expected:
                    bad.append(f"config normalization {raw_value!r}")

            with open(cfg.PATH, "w", encoding="utf-8") as handle:
                json.dump({"matchup_tip_provider": "codex", "matchup_tips": False}, handle)
            saved = cfg.save({"board_size": 80})
            if saved.get("matchup_tip_provider") != "codex" \
                    or saved.get("matchup_tips") is not False:
                bad.append("partial save did not preserve provider/toggle")

            dd = {
                "norm": lambda value: "".join(c for c in value.lower() if c.isalnum()),
                "name2id": {"yasuo": 1, "syndra": 2},
                "id2name": {1: "Yasuo", 2: "Syndra"},
            }
            tip_path = os.path.join(tmp, "tip.txt")
            with mock.patch.object(lolmatchup.lb, "ddragon", return_value=dd), \
                    mock.patch.object(lolmatchup, "written_tip",
                                      return_value="Written guide tip"), \
                    mock.patch.object(lolmatchup, "_file", return_value=tip_path), \
                    mock.patch.object(lolmatchup.llmcli, "call") as call_mock:
                got = lolmatchup.generate_tip(
                    "Yasuo", "Yasuo", "Syndra", "Syndra", "mid", "16.15")
            if got != ("Written guide tip", None) or call_mock.called:
                bad.append("written tip did not precede CLI")

            with open(tip_path, "w", encoding="utf-8") as handle:
                handle.write("Cached guide tip")
            with mock.patch.object(lolmatchup, "_file", return_value=tip_path), \
                    mock.patch.object(lolmatchup.llmcli, "call") as call_mock:
                cached = lolmatchup.get_tip("Yasuo", "Syndra", "mid", "16.15")
            if cached != "Cached guide tip" or call_mock.called:
                bad.append("cache did not precede CLI")

            for provider in llmcli.PROVIDERS:
                if os.path.exists(tip_path):
                    os.remove(tip_path)
                with mock.patch.object(lolmatchup.cfg, "load",
                                       return_value={"matchup_tip_provider": provider}), \
                        mock.patch.object(lolmatchup, "_file", return_value=tip_path), \
                        mock.patch.object(lolmatchup.llmcli, "call",
                                          return_value=(f"{provider} tip", None)) as call_mock:
                    text, error = lolmatchup._generate_tip_llm(
                        "Yasuo", "Yasuo", "Syndra", "Syndra", "mid", "16.15")
                if (text, error) != (f"{provider} tip", None) \
                        or call_mock.call_args.args[1] != provider:
                    bad.append(f"matchup {provider} dispatch")

                if os.path.exists(tip_path):
                    os.remove(tip_path)
                with mock.patch.object(lolmatchup.cfg, "load",
                                       return_value={"matchup_tip_provider": provider}), \
                        mock.patch.object(lolmatchup, "_file", return_value=tip_path), \
                        mock.patch.object(lolmatchup.llmcli, "call",
                                          return_value=(None, f"{provider} unavailable")):
                    text, error = lolmatchup._generate_tip_llm(
                        "Yasuo", "Yasuo", "Syndra", "Syndra", "mid", "16.15")
                if text is not None or not error or os.path.exists(tip_path):
                    bad.append(f"matchup {provider} error cached")

            with mock.patch.object(lolcoach.cfg, "load",
                                   return_value={"matchup_tip_provider": "codex"}), \
                    mock.patch.object(lolcoach.llmcli, "call",
                                      return_value=("coach", None)) as coach_call:
                coach_got = lolcoach._call_ai("generic coach prompt")
            if coach_got != ("coach", None) or coach_call.call_args.args[1] != "codex":
                bad.append("coach configured provider")
        finally:
            cfg.PATH = real_path

    for selected in llmcli.PROVIDERS:
        for mask in range(4):
            found = {
                "claude": ("claude.exe" if mask & 1 else None),
                "codex": ("codex.exe" if mask & 2 else None),
            }
            status, detail = _llm_health_result(selected, found)
            expected = OK if found[selected] else FAIL
            if status != expected or "Claude=" not in detail or "Codex=" not in detail:
                bad.append(f"health {selected}/{mask}")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, "config, written/cache precedence, matchup/coach dispatch and health matrix"


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
    """The WARD CLOCK (core/lolward) — the live vision war for jungle + support. Four things
    must hold forever and none of them are visible without playing a game: it is SILENT until
    the live feed has proven it reports a vision score at all (otherwise it accuses a support
    who has warded all game of being dark), it never bills you for dark time you spent on the
    grey screen, its bar is lolprofile's own, and it stays quiet for the roles the profile has
    never graded on vision."""
    import lolward as lw, lolprofile as lp, loltempo as lt, smitei18n as i18n
    # --- ONE BRAIN: the bar is lolprofile's, the pit sides are loltempo's. Both are read at
    #     runtime rather than re-typed, so a change on either side can't silently diverge.
    if lw.vpm_bar("support") != lp.VPM_BAR["UTILITY"] or lw.vpm_bar("jungle") != lp.VPM_BAR["JUNGLE"]:
        return FAIL, f"vision bar {lw._BAR['v']} has drifted from lolprofile.VPM_BAR"
    if set(lw.ROLE_POS.values()) != set(lp.VPM_BAR):
        return FAIL, "the roles this speaks for aren't the roles low_vision is evaluated for"
    if lw.OBJ_SIDE != lt._OBJ_SIDE:
        return FAIL, f"pit sides {lw.OBJ_SIDE} have drifted from loltempo._OBJ_SIDE"
    # --- None and 0.0 are NOT the same: one is 'hasn't warded', one is 'not being reported',
    #     and coaching on the second is the whole reason the arming tripwire exists.
    if lw.ward_score({"scores": {"wardScore": 0}}) != 0.0:
        return FAIL, "a reported vision score of 0 was collapsed to 'no data'"
    for bad in ({}, {"scores": {}}, {"scores": {"wardScore": None}}, {"scores": {"wardScore": "x"}},
                {"scores": {"wardScore": float("nan")}}, None):
        if lw.ward_score(bad) is not None:
            return FAIL, f"ward_score invented a number from {bad!r}"
    if lw.feed_live([{"scores": {"wardScore": 0}}] * 10) or not lw.feed_live(
            [{"scores": {"wardScore": 0}}] * 9 + [{"scores": {"wardScore": 3.5}}]):
        return FAIL, "the feed tripwire arms on an all-zero game (or won't arm on a live one)"
    if lw.ctrl_wards({"items": [{"itemID": 2055, "count": 2}, {"itemID": 3340, "count": 1}]}) != 2:
        return FAIL, "control wards are counted by slot instead of by stack count"
    # --- the counterpart is the same role or it is nothing: a wrong comparison is worse than
    #     no comparison, so an ambiguous lobby must drop the segment rather than guess.
    en = [{"position": "UTILITY", "scores": {"creepScore": 20}},
          {"position": "JUNGLE", "scores": {"creepScore": 120}},
          {"position": "MIDDLE", "scores": {"creepScore": 140}}]
    if lw.counterpart({"position": "UTILITY"}, en) is not en[0]:
        return FAIL, "counterpart didn't match support to support"
    if lw.counterpart({"position": "JUNGLE"}, en) is not en[1]:
        return FAIL, "counterpart didn't match jungler to jungler"
    nop = [{"scores": {"creepScore": 15}}, {"scores": {"creepScore": 15}}]
    if lw.counterpart({"position": "UTILITY"}, nop) is not None:
        return FAIL, "counterpart guessed between two equally plausible players"
    smite = [{"scores": {"creepScore": 90},
              "summonerSpells": {"summonerSpellOne": {"displayName": "Smite"}}},
             {"scores": {"creepScore": 90}}]
    if lw.counterpart({"position": "JUNGLE"}, smite) is not smite[0]:
        return FAIL, "counterpart ignored the smite fallback when positions are missing"
    # --- the pit window is lollive's own flags, plus a tail; scuttle is not a pit.
    if lw.pit_window([{"label": "Scuttle", "secs": 20, "urgent": True}]) is not None:
        return FAIL, "scuttle read as a pit"
    if lw.pit_window([{"label": "Drake", "secs": 60, "setup": True}]) is None:
        return FAIL, "an open setup window didn't register as a pit"
    if lw.pit_window([{"label": "Baron", "secs": -(lw.PIT_TAIL + 5), "up": True}]) is not None:
        return FAIL, "a pit stayed open forever after the objective spawned"
    # --- every verdict branch is reachable and lands where it should
    want = {"row": "WARD", "under": "WARD", "pit": "PIT", "pitup": "PIT", "pitshort": "WARD",
            "pitfight": "WARD", "dark": "DARK", "darkquiet": "WARD", "pink": "PINK",
            "pinkquiet": "WARD", "jungle": "WARD", "adc": None, "mid": None,
            "notarmed": None, "nofield": None, "early": None, "nocounterpart": "WARD"}
    got = {k: (lw._verdict(lw.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    for k in ("pitfight", "pitshort", "darkquiet", "pinkquiet", "row", "under"):
        if not (lw._verdict(lw.demo(k)) or {}).get("quiet"):
            return FAIL, f"{k} took the directive card when it should be a quiet row"
    if (lw._verdict(lw.demo("nocounterpart")) or {}).get("them") is not None:
        return FAIL, "an unknown counterpart still produced a head-to-head number"
    # --- the guard, driven through whole games. A support who wards on a normal cadence must
    #     never be accused; one who stops must be caught; and neither must be billed for the
    #     seconds he spent dead.
    def game(vs_at, dead=lambda t: False, pinks=lambda t: 0, role="UTILITY", n=1500,
             trink=3340, gold=300.0):
        g, out = lw.Guard(), []
        for t in range(n):
            me = {"riotId": "M#1", "team": "ORDER", "position": role, "isDead": dead(t),
                  "level": 9, "championName": "Nautilus",
                  "items": ([{"itemID": 2055, "count": pinks(t)}] if pinks(t) else [])
                           + [{"itemID": trink, "slot": 6}],
                  "scores": {"creepScore": 10, "kills": 0, "assists": 3, "deaths": 0,
                             "wardScore": vs_at(t)}}
            foe = {"riotId": "E#1", "team": "CHAOS", "position": role, "level": 9,
                   "scores": {"creepScore": 12, "wardScore": 0.02 * t}}
            out.append((t, g.observe({}, {"activePlayer": {"riotId": "M#1",
                                                            "currentGold": gold},
                                          "allPlayers": [me, foe],
                                          "gameData": {"gameTime": float(t)},
                                          "events": {"Events": []}})))
        return g, out
    _g, warder = game(lambda t: 0.03 * t)                  # a ward alive basically always
    if any(c and not c.get("quiet") for _t, c in warder):
        return FAIL, "a support warding all game was still handed a card"
    if not any(c for _t, c in warder):
        return FAIL, "a normal support game produced no vision row at all"
    _g, stops = game(lambda t: 0.03 * min(t, 400))         # ...who stops warding at 6:40
    darks = [t for t, c in stops if c and c.get("verdict") == "DARK"]
    if not darks or darks[0] < 400 + lw.DARK_SECS:
        return FAIL, f"DARK fired at {darks[:1]} — before the score had actually been flat"
    # dead time is FROZEN, not reset and not accrued: 200s on the grey screen must neither
    # hand out a free window nor bill a death two other guards already own.
    _g, dd_ = game(lambda t: 0.03 * min(t, 300), dead=lambda t: 320 <= t < 520)
    if any(c for t, c in dd_ if 320 <= t < 520):
        return FAIL, "the ward clock spoke while the player was dead"
    # He went dark at 5:00 and died at 5:20, so 20s of dark is banked when he respawns at
    # 8:40. FROZEN means the card is due exactly DARK_SECS-20 later; ACCRUED would fire the
    # instant he stands up, RESET would cost him a full extra window.
    dark_after = [t for t, c in dd_ if c and c.get("verdict") == "DARK"]
    due = 520 + (lw.DARK_SECS - 20)
    if not dark_after:
        return FAIL, "a support who went dark before dying was never told after he respawned"
    if dark_after[0] < due - 5:
        return FAIL, f"DARK at {dark_after[0]}s, due {due:.0f} — dark time accrued while dead"
    if dark_after[0] > due + 5:
        return FAIL, f"DARK at {dark_after[0]}s, due {due:.0f} — the clock RESET on death"
    # the arming tripwire: a whole game with no vision score reported anywhere is total silence
    _g, quiet = game(lambda t: None)
    if any(c for _t, c in quiet):
        return FAIL, "spoke about vision in a game where :2999 reported no vision score"
    # a carried control ward is said ONCE per stock — one card window (it holds the slot for
    # CARD_SECS so it can be read), never a second one for the same ward.
    pkg, pk = game(lambda t: 0.03 * t, pinks=lambda t: 1 if t > 200 else 0)
    on = [t for t, c in pk if c and c.get("verdict") == "PINK"]
    windows = sum(1 for a, b in zip([-99] + on, on) if b - a > 1)
    if windows != 1:
        return FAIL, f"the carried-control-ward card opened {windows} windows for one ward"
    if not on or abs(len(on) - lw.CARD_SECS) > 1:
        return FAIL, f"the PINK card held the slot for {len(on)}s, not {lw.CARD_SECS:.0f}s"
    if max(c.get("calls") or 0 for _t, c in pk if c) != 1:
        return FAIL, "calls counts frames instead of card windows (a voice line would stutter)"
    # laners are never graded on vision here, exactly as lolprofile never grades them
    for pos in ("TOP", "MIDDLE", "BOTTOM"):
        if any(c for _t, c in game(lambda t: 0.0, role=pos, n=800)[1]):
            return FAIL, f"the ward clock spoke to a {pos} laner"
    # malformed payloads must never crash the widget's poll thread
    g = lw.Guard()
    for junk in (None, {}, {"allPlayers": []}, {"activePlayer": {}, "allPlayers": [{}]},
                 {"activePlayer": {"riotId": "M#1"}, "allPlayers": [{"riotId": "M#1"}],
                  "gameData": {"gameTime": "soon"}},
                 {"activePlayer": {"riotId": "M#1"}, "allPlayers": [{"riotId": "M#1"}],
                  "gameData": {"gameTime": float("nan")}},
                 {"activePlayer": {"riotId": "M#1"},
                  "allPlayers": [{"riotId": "M#1", "position": "UTILITY", "items": [{}],
                                  "scores": {"wardScore": "?"}}],
                  "gameData": {"gameTime": 600.0}}):
        if g.observe({}, junk) is not None:
            return FAIL, f"produced a card from a malformed payload: {junk!r}"
    # --- v0.9.69: the trinket read, the deadline, the pink LEDGER and the recall buy prompt.
    #     All four change what the card SAYS, so each is checked on the text and not just on
    #     a verdict name.
    for iid, want in ((3340, "yellow"), (3363, "farsight"), (3364, "sweeper")):
        if lw.trinket({"items": [{"itemID": 2055}, {"itemID": iid, "slot": 6}]}) != want:
            return FAIL, f"trinket {iid} read as something else"
    if lw.trinket({"items": [{"itemID": 2055}]}) is not None:
        return FAIL, "an empty trinket slot must read None, not a guess"
    for junk in (None, {}, {"items": None}, {"items": [None]}, {"items": [{"itemID": "x"}]}):
        if lw.trinket(junk) is not None or lw.ctrl_wards(junk):
            return FAIL, f"the inventory read invented something from {junk!r}"
    sw = lw._verdict(lw.demo("pitsweeper"))
    sweep_copy = i18n.t(lw._HOW["sweeper"])
    if sweep_copy not in sw["sub"]:
        return FAIL, "a sweeper wasn't told to take theirs first"
    fs = lw._verdict(lw.demo("pitfarsight"))
    farsight_copy = i18n.t(lw._HOW["farsight"])
    if farsight_copy not in fs["sub"] or sweep_copy in fs["sub"]:
        return FAIL, "a farsight was told to sweep, which it cannot do"
    if lw._HOW.get("yellow"):
        return FAIL, "a plain yellow trinket adds a clause that says nothing"
    # the DEADLINE: named while there is still one, and never once the fight has started
    dl = lw._verdict(lw.demo("pitdeadline"))
    import lollive as ll
    want_by = lw._mmss(lw.demo("pitdeadline")["gt"] + 68 - ll.ALERT_LEAD)
    if want_by not in dl["line"]:
        return FAIL, f"the deadline isn't spawn minus lollive's own lead ({want_by})"
    for k in ("pit", "pitup"):                       # inside the fight there is no deadline
        if want_by in (lw._verdict(lw.demo(k)) or {})["line"]:
            return FAIL, f"{k} printed a deadline that has already passed"
    # the LEDGER, and its absence when there is nothing to report
    placed_copy = i18n.tf("{placed} of {bought} placed", placed=1, bought=2)
    if placed_copy not in lw._verdict(lw.demo("pink"))["sub"]:
        return FAIL, "the PINK card lost the buy/place ledger"
    share_copy = i18n.tf("control ward on you {percent}% of the game", percent=42)
    if share_copy not in lw._verdict(lw.demo("dark"))["sub"]:
        return FAIL, "the share-of-game control-ward number is gone"
    if "%" in lw._verdict(lw.demo("noledger"))["sub"]:
        return FAIL, "a percentage was printed before there was a sample for one"
    for pct, lo, hi in ((-1.0, 0, 0), (5.0, 100, 100)):       # never out of range, ever
        d = dict(lw.demo("pink"), have_pct=pct)
        if not lo <= lw._verdict(d)["have_pct"] <= hi:
            return FAIL, f"have_pct {pct} escaped 0-100"
    # the buy prompt: only in a recall window, only if affordable, never while carrying
    buy_copy = i18n.tf("+{gold}g control ward", gold=lw.CTRL_GOLD)
    if buy_copy not in lw._verdict(lw.demo("base"))["row"]:
        return FAIL, "a recall window is the one moment the buy must lead the row"
    for k in ("basebroke", "basecarrying", "row"):
        if buy_copy in lw._verdict(lw.demo(k))["row"]:
            return FAIL, f"{k} was sold a control ward it doesn't need or can't afford"

    # --- and the purchase ledger against the truth, over a whole game: two bought, one
    #     placed, and the share-of-game number inside the possible.
    lg, frames = game(lambda t: 0.03 * t,
                      pinks=lambda t: 1 if (200 <= t < 500 or t >= 900) else 0)
    if (lg.bought, lg.placed) != (2, 1):
        return FAIL, f"the pink ledger says {lg.bought} bought / {lg.placed} placed, want 2/1"
    pcts = [c["have_pct"] for _t, c in frames if c and c.get("have_pct") is not None]
    if not pcts or min(pcts) < 0 or max(pcts) > 100:
        return FAIL, f"share-of-game out of range: {min(pcts or [0])}..{max(pcts or [0])}"
    if pcts[-1] > 60:                       # carried for 600 of 1500s -> can't read as most
        return FAIL, f"share-of-game reads {pcts[-1]}% for a ward carried 40% of the game"
    if any(c["have_pct"] is not None for t, c in frames if c and t < 60):
        return FAIL, "a percentage was printed in the first minute of watching"

    # --- the legend must actually CONTAIN the section: PIL draws past a canvas silently, so
    #     an overrun vanishes off the bottom of the card instead of raising.
    try:
        import smitewidget as sw_
        leg = sw_._render_legend()
        band = leg.crop((0, leg.height - 30, leg.width, leg.height - 4))
        if not any(sum(px) > 150 for px in list(band.getdata())):
            return FAIL, "the legend's last WARD row fell off the bottom of its canvas"
    except Exception:
        pass                                # not on Windows / no Win32: skip the render
    return OK, ("24 fixtures, arming tripwire, dead-time freeze, trinket + deadline + pink "
                "ledger + 6 simulated games hold")


def c_mute():
    """AUTO-MUTE. It used to TYPE `/fullmute all` into the game and could never tell whether
    that landed - so it claimed success for four releases while muting nobody. It now writes
    the client's own settings, which means the state is READABLE, and this check reads it.
    A key Riot renames must fail here rather than silently do nothing."""
    import lolmute as lm, lolgame as lg
    from unittest import mock

    # Run deterministic layout contracts BEFORE any machine/League checks. A developer's
    # current HKL must never hide a broken AltGr chord, mutex, timing gate or LCU layer.
    bad = []
    hkl = 0x0416
    layout_calls = []
    window_hkl = lm._game_keyboard_layout(
        123,
        get_window_thread=lambda hwnd, _pid: layout_calls.append(("thread", hwnd)) or 77,
        get_keyboard_layout=lambda thread_id:
            layout_calls.append(("layout", thread_id)) or hkl,
    )
    if window_hkl != hkl or layout_calls != [("thread", 123), ("layout", 77)]:
        bad.append("League window thread HKL")

    support_scans = {
        lm.VK_RETURN: 0x1C, lm.VK_ESCAPE: 0x01, lm.VK_SHIFT: 0x2A,
        lm.VK_CONTROL: 0x1D, lm.VK_MENU: 0x38,
    }

    def mapped(vk, _kind, _hkl):
        return support_scans.get(vk, {0x51: 0x10, 0xBF: 0x35}.get(vk, vk & 0x7F))

    direct, problem = lm.resolve_chord(
        "/", hkl, vk_key_scan=lambda _ch, _hkl: 0xBF, map_virtual=mapped)
    if problem or direct.scan != 0x35 or direct.modifiers:
        bad.append("direct slash layout")

    altgr, problem = lm.resolve_chord(
        "/", hkl, vk_key_scan=lambda _ch, _hkl: (0x06 << 8) | 0x51,
        map_virtual=mapped)
    if problem or altgr.scan != 0x10 \
            or altgr.modifiers != (lm.MOD_CONTROL | lm.MOD_ALT):
        bad.append("PT-BR Ctrl+Alt+Q slash")

    shifted, problem = lm.resolve_chord(
        "A", hkl, vk_key_scan=lambda _ch, _hkl: (0x01 << 8) | 0x41,
        map_virtual=mapped)
    if problem or shifted.modifiers != lm.MOD_SHIFT:
        bad.append("Shift character")

    failure_cases = (
        ("VkKeyScanExW -1", lambda _ch, _hkl: -1, mapped),
        ("zero scan", lambda _ch, _hkl: 0x41, lambda *_args: 0),
        ("unknown modifiers", lambda _ch, _hkl: (0x08 << 8) | 0x41, mapped),
    )
    for name, vk_scan, map_scan in failure_cases:
        chord, problem = lm.resolve_chord("x", hkl, vk_key_scan=vk_scan,
                                          map_virtual=map_scan)
        if chord is not None or problem is None:
            bad.append(name)

    events = []
    lm._emit_chord(
        lm.KeyChord("/", 0x51, 0x10, lm.MOD_CONTROL | lm.MOD_ALT),
        ((lm.MOD_SHIFT, 0x2A), (lm.MOD_CONTROL, 0x1D), (lm.MOD_ALT, 0x38)),
        key_fn=lambda scan, down: events.append((scan, down)), hold=0)
    expected = [(0x1D, True), (0x38, True), (0x10, True), (0x10, False),
                (0x38, False), (0x1D, False)]
    if events != expected:
        bad.append(f"AltGr chord order {events!r}")

    cleanup = []

    def failing_key(scan, down):
        cleanup.append((scan, down))
        if scan == 0x10 and down:
            raise RuntimeError("fixture")

    try:
        lm._emit_chord(
            lm.KeyChord("/", 0x51, 0x10, lm.MOD_CONTROL | lm.MOD_ALT),
            ((lm.MOD_SHIFT, 0x2A), (lm.MOD_CONTROL, 0x1D), (lm.MOD_ALT, 0x38)),
            key_fn=failing_key, hold=0)
    except RuntimeError:
        pass
    if cleanup[-2:] != [(0x38, False), (0x1D, False)]:
        bad.append("modifier cleanup after exception")

    problem = lm.LayoutProblem(hkl, "/", 0x51, 0x06, 0, "fixture incompatible")
    with mock.patch.object(lm, "_validated_game_window", return_value=123), \
            mock.patch.object(lm, "_game_keyboard_layout", return_value=hkl), \
            mock.patch.object(lm, "_resolve_command", return_value=(None, problem)), \
            mock.patch.object(lm, "_key") as key_mock:
        result = lm.send_fullmute()
    if result.status != lm.SEND_LAYOUT_INCOMPATIBLE or key_mock.called:
        bad.append("pre-resolution emitted input on failure")

    if lm._typed_layer_remains_armed(lm.SendResult(lm.SEND_LAYOUT_INCOMPATIBLE)) \
            or not lm._typed_layer_remains_armed(lm.SendResult(lm.SEND_TRANSIENT)) \
            or lm._typed_layer_remains_armed(lm.SendResult(lm.SEND_OK)):
        bad.append("typed-layer disarm classification")

    # Exercise main's session state: structural incompatibility applies LCU first and sends
    # once; a transient focus/idle/input failure remains armed and retries in the safe window.
    with mock.patch.object(lm.cfg, "load", return_value={"auto_mute": True}), \
            mock.patch.object(lm, "_single_instance", return_value=True), \
            mock.patch.object(lm, "apply", return_value=(True, "fixture")) as apply_mock, \
            mock.patch.object(lm.cfg, "tray_gone", side_effect=[False, True]), \
            mock.patch.object(lm, "game_time", return_value=4.0), \
            mock.patch.object(lm, "send_fullmute",
                              return_value=lm.SendResult(
                                  lm.SEND_LAYOUT_INCOMPATIBLE, "fixture")) as send_mock, \
            mock.patch.object(lm.time, "monotonic", return_value=0.0), \
            mock.patch.object(lm.time, "sleep"):
        lm.main()
    if apply_mock.call_count != 1 or send_mock.call_count != 1:
        bad.append("incompatible session did not preserve LCU/disarm typing")

    with mock.patch.object(lm.cfg, "load", return_value={"auto_mute": True}), \
            mock.patch.object(lm, "_single_instance", return_value=True), \
            mock.patch.object(lm, "apply", return_value=(True, "fixture")), \
            mock.patch.object(lm.cfg, "tray_gone", side_effect=[False, False, True]), \
            mock.patch.object(lm, "game_time", side_effect=[4.0, 5.0]), \
            mock.patch.object(lm, "send_fullmute",
                              return_value=lm.SendResult(lm.SEND_TRANSIENT, "focus")) \
                    as send_mock, \
            mock.patch.object(lm.time, "monotonic", return_value=0.0), \
            mock.patch.object(lm.time, "sleep"):
        lm.main()
    if send_mock.call_count != 2:
        bad.append("transient failure disarmed typed layer")

    if bad:
        return FAIL, "; ".join(bad)

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
    # The real machine is diagnostic only: incompatible layouts are a supported, safely
    # disarmed state, while the deterministic matrix above proves all behavior.
    real_hkl = int(lm._u32.GetKeyboardLayout(0) or 0)
    real_command, real_problem = lm._resolve_command(real_hkl)
    if real_problem:
        layout_detail = "typed layer safely unavailable: " + lm._problem_detail(real_problem)
    else:
        slash = next(chord for chord in real_command.chords if chord.char == "/")
        layout_detail = (f"{lm._layout_label(real_hkl)}, '/' scan=0x{slash.scan:02x}, "
                         f"modifiers=0x{slash.modifiers:02x}")
    detail = (f"direct/Shift/PT-BR AltGr/incompatible fixtures pass; {layout_detail}; "
              f"{lm.CMD!r} pre-resolved")
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
        hkl = int(lm._u32.GetKeyboardLayout(0) or 0)
        sh = lm._u32.MapVirtualKeyExW(lm.VK_SHIFT, 0, hkl)
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


def c_new_i18n():
    """New v0.9.55-v0.9.69 surfaces must switch copy without changing their internal
    contracts. Exercise the same deterministic fixtures in both languages."""
    import ast
    import collections
    import string

    import loldraft as draft
    import lolbleed as bleed, lolclose as close, lolfit as fit, lolrunes as runes
    import lolgold as gold, lolward as ward
    import smitei18n as i18n

    # Audit the source literal rather than the imported dict so a duplicate key cannot be
    # silently overwritten before this test sees it.
    catalog_path = os.path.join(_ROOT, "core", "i18n_pt_BR.py")
    source = open(catalog_path, encoding="utf-8").read()
    tree = ast.parse(source, filename=catalog_path)
    catalog = next((node.value for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "MESSAGES"
                            for target in node.targets)), None)
    if not isinstance(catalog, ast.Dict):
        return FAIL, "PT-BR catalog is not a literal MESSAGES dict"
    literal_keys = [key.value for key in catalog.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)]
    duplicates = sorted(key for key, count in collections.Counter(literal_keys).items()
                        if count > 1)
    if duplicates:
        return FAIL, f"duplicate PT-BR catalog keys: {duplicates[:3]}"
    formatter = string.Formatter()
    placeholder_errors = []
    for msgid, translated in i18n.PT_BR_MESSAGES.items():
        source_fields = collections.Counter(
            (field, spec, conversion) for _text, field, spec, conversion
            in formatter.parse(msgid) if field is not None)
        translated_fields = collections.Counter(
            (field, spec, conversion) for _text, field, spec, conversion
            in formatter.parse(translated) if field is not None)
        if source_fields != translated_fields:
            placeholder_errors.append(msgid)
    if placeholder_errors:
        return FAIL, f"PT-BR placeholder mismatch: {placeholder_errors[:3]}"

    def localized_guards():
        gold_kinds = ("pace", "behind", "miss", "cannon", "roaming", "unrecoverable",
                      "onpace_miss", "jungle", "support", "early", "late")
        ward_kinds = ("row", "under", "pit", "pitup", "pitshort", "pitfight",
                      "pitdeadline", "pitsweeper", "pitfarsight", "dark", "darkquiet",
                      "pink", "pinkquiet", "noledger", "base", "basebroke",
                      "basecarrying", "jungle", "adc", "mid", "notarmed", "nofield",
                      "early", "nocounterpart")
        return ({kind: gold._verdict(gold.demo(kind)) for kind in gold_kinds},
                {kind: ward._verdict(ward.demo(kind)) for kind in ward_kinds})

    def contract(card):
        if card is None:
            return None
        presentation = {"line", "sub", "row", "bits", "evidence"}
        return {key: value for key, value in card.items() if key not in presentation}

    previous = i18n.lang()
    try:
        i18n.set_lang("en")
        bleed_en = bleed._verdict(bleed.demo("bleed"))
        close_en = close._verdict(close.demo("end"))
        gold_en, ward_en = localized_guards()
        rec = {"baseline": 83, "recent": [],
               "champs": {"loser": {"g": 10, "w": 1, "avg": 60}}}
        fit_en = fit.verdict(rec, "loser")
        dd, opts, enemies = runes.demo("tank")
        rune_en = runes.choose(dd, opts, enemies)
        demo_names = ("Sett", "Kha'Zix", "Ahri", "Jinx", "Thresh",
                      "Darius", "Graves", "Zed", "Caitlyn", "Lux")
        demo_dd = {
            "norm": lambda value: "".join(c for c in value.lower() if c.isalnum()),
            "name2id": {},
        }
        demo_dd["name2id"] = {
            demo_dd["norm"](name): idx + 1 for idx, name in enumerate(demo_names)
        }
        draft_en = draft._demo_scout(demo_dd)

        i18n.set_lang("pt_BR")
        bleed_pt = bleed._verdict(bleed.demo("bleed"))
        close_pt = close._verdict(close.demo("end"))
        gold_pt, ward_pt = localized_guards()
        fit_pt = fit.verdict(rec, "loser")
        rune_pt = runes.choose(dd, opts, enemies)
        draft_pt = draft._demo_scout(demo_dd)
        bad = []
        if bleed_en["verdict"] != "BLEED" or bleed_pt["verdict"] != "BLEED":
            bad.append("BLEED internal verdict changed with locale")
        if not bleed_en["line"].startswith("BACK OFF") or not bleed_pt["line"].startswith("RECUE"):
            bad.append("BLEED copy did not switch EN/PT")
        if close_en["verdict"] != "END" or close_pt["verdict"] != "END":
            bad.append("CLOSER internal verdict changed with locale")
        if not close_en["line"].startswith("END IT") or not close_pt["line"].startswith("TERMINE"):
            bad.append("CLOSER copy did not switch EN/PT")
        for name, english, portuguese in (("GOLD", gold_en, gold_pt),
                                          ("WARD", ward_en, ward_pt)):
            for kind in english:
                if contract(english[kind]) != contract(portuguese[kind]):
                    bad.append(f"{name} {kind} contract changed with locale")
                    break
        for kind, verdict in (("miss", "MISS"), ("cannon", "CANNON"), ("behind", "PACE")):
            if not gold_en[kind]["line"].startswith(verdict) \
                    or not gold_pt[kind]["line"].startswith(verdict):
                bad.append(f"GOLD {verdict} internal ID changed with locale")
        for kind, verdict in (("pit", "PIT"), ("dark", "DARK"),
                              ("pink", "PINK"), ("row", "WARD")):
            if not ward_en[kind]["line"].startswith(verdict) \
                    or not ward_pt[kind]["line"].startswith(verdict):
                bad.append(f"WARD {verdict} internal ID changed with locale")
        if gold_en["miss"]["line"] == gold_pt["miss"]["line"] \
                or "onda" not in gold_pt["miss"]["line"] \
                or gold_en["cannon"]["sub"] == gold_pt["cannon"]["sub"]:
            bad.append("GOLD card/plan copy did not switch EN/PT")
        if ward_en["pit"]["line"] == ward_pt["pit"]["line"] \
                or "dragão" not in ward_pt["pit"]["line"] \
                or ward_en["pink"]["sub"] == ward_pt["pink"]["sub"]:
            bad.append("WARD card/objective copy did not switch EN/PT")
        if len(gold_en["behind"]["bits"]) != len(gold_pt["behind"]["bits"]) \
                or len(ward_en["under"]["bits"]) != len(ward_pt["under"]["bits"]):
            bad.append("GOLD/WARD quiet-row segment shape changed with locale")
        if fit_en[0] != "veto" or fit_pt[0] != "veto" \
                or "W-" not in fit_en[1] or "V-" not in fit_pt[1]:
            bad.append("personal-fit evidence did not switch EN/PT")
        if rune_en[0] != 1 or rune_pt[0] != 1 or "frontline locked" not in rune_en[1] \
                or "linha de frente" not in rune_pt[1]:
            bad.append("adaptive-rune evidence did not switch EN/PT")
        if i18n.t("ESCAPE KEY") == "ESCAPE KEY" or i18n.t("Back off.") == "Back off." \
                or i18n.t("Ward it.") == "Ward it.":
            bad.append("new Settings/TTS catalog entries are missing")
        if i18n.t("Gold clock (farm pace, first 10 min)").startswith("Gold") \
                or i18n.t("Ward clock (the vision war, jg / sup)").startswith("Ward") \
                or i18n.t("GOLD CLOCK — THE FIRST TEN MINUTES").startswith("GOLD"):
            bad.append("GOLD/WARD Settings or legend catalog entries are missing")
        if i18n.t("Matchup AI fallback:") == "Matchup AI fallback:" \
                or "dica escrita" not in i18n.t(
                    "Used only when no written matchup tip is available. The selected local "
                    "CLI is authoritative; failures never switch providers automatically."):
            bad.append("matchup provider Settings copy did not switch PT/EN")
        mute_copy = i18n.t(
            "Each game, Smiteless safely types Riot's own /fullmute all while the League "
            "window is focused. That per-game layer hides chat and ping markers. Separately, "
            "it writes League's own settings to hide ally/all chat and mute ping audio, then "
            "reads them back; those settings persist until disabled. If the League window's "
            "keyboard layout cannot produce the command safely, typing stays off for that "
            "session while the verified settings layer remains active.")
        if "Em cada partida" not in mute_copy or "camada verificada" not in mute_copy:
            bad.append("auto-mute two-layer Settings copy did not switch PT/EN")
        if "main · 140k pts" not in draft_en["allies"][0]["t"][0][0] \
                or "principal · 140 mil pts" not in draft_pt["allies"][0]["t"][0][0] \
                or draft_en["allies"][0]["n"] != "You" \
                or draft_pt["allies"][0]["n"] != "Você" \
                or "7W in last 10" not in draft_en["allies"][0]["t"][1][0] \
                or "7V nas últimas 10" not in draft_pt["allies"][0]["t"][1][0] \
                or not draft_pt["allies"][0]["tip"].startswith("Respeite") \
                or draft_en["plan"][0].startswith("O inimigo") \
                or not draft_pt["plan"][0].startswith("O inimigo"):
            bad.append("DraftBoard demo tags/plan did not switch EN/PT")
        if bad:
            return FAIL, "; ".join(bad)
        return OK, ("catalog unique/placeholders valid; BLEED, CLOSER, GOLD, WARD, fit, "
                    "runes, DraftBoard demo and Settings/TTS switch PT/EN")
    finally:
        i18n.set_lang(previous)


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
        ("LLM CLI (matchup tips)", c_llm_cli),
        ("LLM provider contracts", c_llm_providers),
        ("LLM provider integration", c_llm_integration),
        ("Tag spec (docs/TAGS.md)", c_tagspec),
        ("Glyph coverage (tofu)", c_glyphs),
        ("Queue call (verdict engine)", c_queuecall),
        ("Re-entry guard (90s window)", c_reentry),
        ("Bleed guard (first 14 min)", c_bleed),
        ("Closer (win conversion)", c_closer),
        ("Gold clock (farm pace)", c_gold),
        ("Ward clock (vision war)", c_ward),
        ("Auto-mute (chat + settings)", c_mute),
        ("Auto-mute input guard", c_muteguard),
        ("Personal fit (your results)", c_fit),
        ("Adaptive runes (comp-aware)", c_runes),
        ("New feature i18n (PT/EN)", c_new_i18n),
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
