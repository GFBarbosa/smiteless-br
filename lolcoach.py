#!/usr/bin/env python3
"""lolcoach.py — basic lane-matchup + mid-game macro guide for the current game.

Reads champ select from the running League client (LCU), pulls op.gg matchup
win rates, then asks `claude -p` (fast model, no tools) for a short, role-aware
coaching read. Designed to run right after lolbuild.py from the Win+B AHK macro.

Role-aware output:
  - JUNGLE  -> enemy-jungler matchup + STRONG SIDE / WEAK SIDE + objective plan
  - MID     -> lane matchup + mid-game macro
  - other   -> generic lane matchup + mid-game macro

Usage:
  python lolcoach.py                          # AUTO from champ select (LCU)
  python lolcoach.py Ahri mid Zed Leona       # manual: champ role [enemy champs...]
"""
import sys, os, time, subprocess, shutil, tempfile

# reuse the verified ddragon/op.gg plumbing from lolbuild.py + multi-source resolver
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lolbuild as lb
import lolgame as lg

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CLAUDE_MODEL = "sonnet"  # best quality for the guide
CLAUDE_TIMEOUT = 120     # generous: finishes even a throttled call (typical ~35s;
                         # quick read covers the wait). AHK caps the whole thing at 125s.


def gather_matchups(dd, my_cid, role, enemy_ids):
    """op.gg same-role matchup win rates for the enemy champs that appear in the table."""
    try:
        d = lb.opgg(my_cid, role)
    except Exception:
        return [], None
    if not d or "summary" not in d:
        return [], None
    cmap = {c["champion_id"]: c for c in d.get("counters", []) if c.get("play", 0) >= 20}
    out = []
    for e in enemy_ids:
        c = cmap.get(e)
        if c:
            out.append((dd["id2name"].get(e, e), c["win"] / c["play"] * 100, c["play"]))
    tier = d["summary"]["average_stats"].get("win_rate")
    return out, tier


def gather_lane_matchups(dd, allies, enemies):
    """Pair each lane STRICTLY BY ROLE using the real champion in that slot - no
    guessing. ally[role] is matched against enemy[role] (the actual enemy who plays
    that role, read from the live game), and the WR is op.gg's number for THAT exact
    pair, or None if op.gg has no sample for it. We never substitute a different
    enemy. Both `allies` and `enemies` are lists of (champ_id, role); a lane is only
    returned when BOTH the ally's and the enemy's role for it are known (i.e. in-game;
    in champ select enemy roles are hidden, so no pairings are produced).
    Returns [(ally_name, role, enemy_name, wr_or_None, games_or_None), ...]."""
    enemy_by_role = {}
    for cid, role in enemies:
        if cid and role and role not in enemy_by_role:
            enemy_by_role[role] = cid
    out = []
    for cid, role in allies:
        if not cid or not role:
            continue
        opp = enemy_by_role.get(role)
        if not opp:
            continue  # enemy role for this lane unknown -> do NOT fabricate a pairing
        wr = games = None
        try:
            d = lb.opgg(cid, role)
        except Exception:
            d = None
        if isinstance(d, dict):
            for c in d.get("counters", []):
                if c.get("champion_id") == opp and c.get("play", 0) >= 20:
                    wr, games = c["win"] / c["play"] * 100, c["play"]
                    break
        out.append((dd["id2name"].get(cid, cid), role,
                    dd["id2name"].get(opp, opp), wr, games))
        time.sleep(0.1)  # rapid op.gg calls get throttled; space them out
    return out


def deterministic_analysis(lane_mu, role):
    """Strong/weak side computed PURELY from the verified lane winrates - no LLM,
    nothing invented. Returns '' if we have no per-lane data."""
    rated = [x for x in lane_mu if x[3] is not None]
    nodata = [x for x in lane_mu if x[3] is None]
    if not rated and not nodata:
        return ""
    fmt = lambda x: f"{x[1]} {x[0]} vs {x[2]} {x[3]:.0f}% ({x[4]}g)"
    ranked = sorted(rated, key=lambda x: x[3], reverse=True)
    strong = [x for x in ranked if x[3] >= 52]
    weak = [x for x in ranked if x[3] < 48]
    even = [x for x in ranked if 48 <= x[3] < 52]
    out = []
    if strong:
        tail = " -> path/gank these lanes" if role == "jungle" else " -> play for these"
        out.append("STRONG (data): " + "; ".join(fmt(x) for x in strong) + tail)
    if weak:
        tail = (" -> play safe; the enemy jungler likely camps here"
                if role == "jungle" else " -> respect, play safe")
        out.append("WEAK (data): " + "; ".join(fmt(x) for x in weak) + tail)
    if even:
        out.append("EVEN (data): " + "; ".join(fmt(x) for x in even))
    if nodata:
        out.append("NO OP.GG SAMPLE (pairing known, WR not): "
                   + "; ".join(f"{x[1]} {x[0]} vs {x[2]}" for x in nodata))
    return "\n".join(out)


def matchup_text(lane_mu, my_matchups, myname, role, ver):
    """One verified-data string for the prompt + quick read. Prefers full per-lane
    data; falls back to the user's own matchups; else says so plainly."""
    if lane_mu:
        parts = []
        for a, r, e, wr, g in lane_mu:
            parts.append(f"{r} {a} vs {e} (no op.gg sample)" if wr is None
                         else f"{r} {a} vs {e} {wr:.1f}% ({g}g)")
        return ("VERIFIED LANE WINRATES (op.gg Emerald+, patch %s) - your team vs the "
                "enemy in that lane (paired by role): " % ver + "; ".join(parts))
    if my_matchups:
        return (f"VERIFIED op.gg winrates for {myname} {role}: "
                + "; ".join(f"vs {n} {wr:.1f}% ({g}g)" for n, wr, g in my_matchups))
    return ("No op.gg matchup data for this game (roles not yet known, or no sample). "
            "Do NOT invent win rates.")


MACRO_PRINCIPLES = (
    "Macro principles to ground your advice: prio is the right to leave lane; "
    "crash the wave (esp. cannon) BEFORE you roam/recall/rotate; don't roam on a "
    "wave pushing to you; set up objectives ~60-90s early by shoving for prio + "
    "deep vision; identify the win condition by archetype (control mage = prio+"
    "scale+zone, assassin = tempo+picks, skirmisher = side-lane 1v1 + flanks, "
    "scaling = farm safe then take over); group when you win 5v5, split when you "
    "don't but have a strong 1v1; bias to self-sufficient, forgiving lines (Gold/Plat)."
)


def build_prompt(dd, myname, role, allies, enemy_names, mu_text, ver):
    role_known = bool(role)
    rlabel = role if role_known else "UNKNOWN — infer it from my champion + team"
    lines = [
        f"PATCH {ver}, op.gg Emerald+ (NA), ranked solo queue.",
        f"ME: {myname} ({rlabel}).",
    ]
    if allies:
        team = ", ".join(f"{r or '?'}:{dd['id2name'].get(c, c)}" for c, r in allies if c)
        lines.append(f"MY TEAM: {team}")
    lines.append("ENEMY CHAMPS (roles hidden in solo queue): "
                 + (", ".join(enemy_names) or "none locked yet"))
    lines.append(mu_text)
    data = "\n".join(lines)

    common = (
        "You are a sharp, concise League of Legends coach. Output PLAIN TEXT, skimmable, "
        "lines under 88 chars. No preamble; no markdown except the SECTION LABELS I "
        "specify (CAPS, own line). Keep the WHOLE response under 12 lines, terse.\n"
        "HARD RULES (do not break):\n"
        "1. Only name champions that appear in MY TEAM or ENEMY CHAMPS. NEVER mention any "
        "other champion.\n"
        "2. The ONLY win rates you may state are the VERIFIED ones in the data. NEVER "
        "invent, estimate, or guess a number.\n"
        "3. Base STRONG SIDE / WEAK SIDE on the verified lane winrates: your highest-WR "
        "lane is the strong side, your lowest-WR lane is the weak side. If a lane has no "
        "verified number, say 'no data' for it - do NOT guess who wins it.\n"
        "4. Tactical advice (what a champ does) may use your own knowledge, but any "
        "matchup VERDICT must trace to a verified number above.\n"
    )

    if not role_known:
        ask = (
            "\nFIRST output one line `ROLE: <your inferred role>` (infer it from my "
            "champion and team). THEN:\n"
            "- If you're the JUNGLER, write JUNGLE MATCHUP (early read vs the likely enemy "
            "jungler), STRONG SIDE / WEAK SIDE (which side to path toward & gank vs which to "
            "play safe, given both teams), and OBJECTIVE & MACRO.\n"
            "- If you're a LANER, write LANE MATCHUP (likely opponent + key tips) and "
            "MID-GAME MACRO (win condition, group vs pick/split vs this comp).\n"
            "Cite an op.gg WR only if present. Keep under 16 lines.\n"
        )
    elif role == "jungle":
        ask = (
            "\nWrite these three sections:\n"
            "JUNGLE MATCHUP — identify the likely enemy jungler from the enemy champs; "
            "give the early read: scuttle/level-2-3 duel, invade/counter-invade, and their "
            "gank threat vs yours. Cite the op.gg WR if present. 2 lines.\n"
            "STRONG SIDE / WEAK SIDE — using MY TEAM's laners vs the enemy champs, say which "
            "side (TOP or BOT) is your STRONG side to path toward and gank (winning matchup, "
            "kill pressure, follow-up CC) and which is your WEAK side to play around / expect "
            "the enemy jungler to camp. Add a level-1 start + first-clear direction. 2-3 lines.\n"
            "OBJECTIVE & MACRO — first objective to prioritize (void grubs / dragon / herald) "
            "given both comps, plus your mid-game win condition. 2 lines.\n"
        )
    elif role == "mid":
        ask = (
            "\nWrite these two sections:\n"
            "LANE MATCHUP — identify your likely lane opponent from the enemy champs; give the "
            "trading pattern, wave plan (push for prio vs freeze), all-in / level-6 threats, and "
            "how to get prio. Cite the op.gg WR if present. 3 lines.\n"
            "MID-GAME MACRO — your win condition by archetype, roam vs side-lane plan, and whether "
            "to GROUP or PICK/SPLIT vs THIS enemy comp. 3 lines.\n"
        )
    else:
        ask = (
            "\nWrite these two sections:\n"
            "LANE MATCHUP — identify your likely lane opponent; trading/wave/all-in tips and what "
            "to respect. Cite the op.gg WR if present. 3-5 lines.\n"
            "MID-GAME MACRO — your win condition, grouping vs splitting vs THIS enemy comp, and "
            "objective/teamfight role. 3-5 lines.\n"
        )
    return common + ask + "\nDATA:\n" + data


def _find_claude():
    """Prefer the real claude.exe (lets us exec without a shell so the timeout can
    kill the process directly). Fall back to whatever `claude` resolves to on PATH."""
    exe = os.path.expanduser(
        r"~/AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe")
    if os.path.exists(exe):
        return exe
    return shutil.which("claude")


def call_claude(prompt, allow_tools=None, timeout=None):
    """Return (text, error). Uses the logged-in claude CLI; no API key needed.

    Runs from a neutral temp cwd so claude does NOT load the heavy C:\\ project
    memory (that was adding 30-60s). Hard timeout kills the whole process tree.
    Pass allow_tools="WebSearch,WebFetch" to let it pull up-to-date info."""
    claude = _find_claude()
    if not claude:
        return None, "claude CLI not found"
    args = [claude, "-p", "--model", CLAUDE_MODEL, "--strict-mcp-config"]
    if allow_tools:
        args += ["--allowedTools", allow_tools]
    try:
        p = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", cwd=tempfile.gettempdir(),
        )
    except (FileNotFoundError, OSError) as e:
        return None, f"couldn't launch claude ({e})"
    try:
        out, err = p.communicate(input=prompt, timeout=(timeout or CLAUDE_TIMEOUT))
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                       capture_output=True)
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        return None, "timed out"
    out = (out or "").strip()
    err = (err or "").strip()
    blob = (out + "\n" + err).lower()
    if "session limit" in blob or "usage limit" in blob:
        return None, "Claude usage/session limit reached"
    if p.returncode != 0 and not out:
        return None, (err[:200] or f"claude exited {p.returncode}")
    if not out:
        return None, "claude returned no text"
    return out, None


FALLBACK_MACRO = {
    "jungle": ("Path toward your winning/kill-pressure lanes (strong side); play safe "
               "around your losing lanes. Crash camps on tempo, contest scuttle with prio, "
               "and set up the first objective (grubs/herald top-side, dragon bot-side) "
               "~30-60s early with vision. Gank where there's CC follow-up + a low/immobile "
               "target; avoid forcing into the enemy jungler's strong-side."),
    "mid": ("Crash the wave (esp. cannon) BEFORE you roam or recall; never roam on a wave "
            "pushing to you. Use prio to help scuttle/objectives and to roam with a target. "
            "Win condition by archetype: control mage = prio + scale + zone, assassin = tempo "
            "+ picks, skirmisher = side-lane 1v1 + flanks. Group only if you win 5v5; else "
            "pick/split."),
}
FALLBACK_MACRO_DEFAULT = ("Manage your wave for prio, set up objectives early with vision, "
                          "and pick group-vs-split by whether you win a straight 5v5.")


def fallback(mu_text, role):
    return (mu_text + "\n\nMACRO (" + (role or "?").upper() + "): "
            + FALLBACK_MACRO.get(role, FALLBACK_MACRO_DEFAULT))


def _write(path, text):
    """Atomic write so the AHK poller never reads a half-written file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="replace") as f:
        f.write(text)
    os.replace(tmp, path)


def _touch(path):
    if path:
        try:
            open(path, "w").close()
        except Exception:
            pass


def _takeflag(argv, name):
    if name in argv:
        i = argv.index(name)
        val = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
        return val
    return None


def main():
    # File mode (from Win+B): write a QUICK read immediately, then upgrade to the
    # full AI guide in place. Stdout mode (manual/console): just print the result.
    argv = sys.argv[1:]
    outp = _takeflag(argv, "--out")
    qm = _takeflag(argv, "--qm")
    fm = _takeflag(argv, "--fm")
    args = argv

    dd = lb.ddragon()
    ver = dd["ver"]

    if args:  # manual mode (testing / no client)
        my_cid = dd["name2id"].get(dd["norm"](args[0]))
        if not my_cid:
            print(f"Unknown champ '{args[0]}'.")
            return
        role = lb.ROLE.get((args[1].lower() if len(args) > 1 else "jungle"), "jungle")
        allies = []
        enemies = [(cid, "") for cid in (dd["name2id"].get(dd["norm"](a)) for a in args[2:]) if cid]
        source = "manual"
    else:  # AUTO: champ select / loading screen / in-game
        info, errmsg = lg.resolve(dd)
        if errmsg:
            if outp:
                _write(outp, errmsg); _touch(qm); _touch(fm)
            else:
                print(errmsg)
            return
        my_cid, role = info["my"], info["pos"]   # role may be "" on the loading screen
        allies = info["allies"]
        enemies = info["enemies"]                 # [(champ_id, role)] — roles known in-game
        source = info.get("source", "auto")

    myname = dd["id2name"].get(my_cid, str(my_cid))
    enemy_names = [dd["id2name"].get(c, str(c)) for c, _ in enemies]
    enemy_cids = [c for c, _ in enemies]
    # Per-lane winrates need BOTH teams' roles (in-game). gather_lane_matchups pairs
    # strictly by role and returns only the lanes it could pair; else fall back.
    lane_mu = gather_lane_matchups(dd, allies, enemies) if (allies and enemies) else []
    my_mu = gather_matchups(dd, my_cid, role, enemy_cids)[0] if (role and not lane_mu) else []
    mu_text = matchup_text(lane_mu, my_mu, myname, role, ver)
    analysis = deterministic_analysis(lane_mu, role)

    # VERIFIED block = everything that is real op.gg data + computed-from-data calls +
    # evergreen macro principles. Nothing here is invented. This is ALWAYS the output.
    verified = mu_text
    if analysis:
        verified += "\n\n" + analysis
    verified += ("\n\nMACRO (" + (role or "?").upper() + ", general principles): "
                 + FALLBACK_MACRO.get(role, FALLBACK_MACRO_DEFAULT))

    header = f"[{source}] {myname} ({role or 'role?'}) vs " + (", ".join(enemy_names) or "unknown")
    base = header + "\n\n=== VERIFIED (op.gg data) ===\n" + verified
    prompt = build_prompt(dd, myname, role, allies, enemy_names, mu_text, ver)

    def with_ai(text, err):
        if text:
            return base + "\n\n=== AI TACTICAL NOTES (commentary, not a data source) ===\n" + text
        return base + "\n\n(AI tactical notes skipped — the verified data above is complete.)"

    if outp:
        _write(outp, base + "\n\n(AI tactical notes loading… the verified data above is already complete.)")
        _touch(qm)
        text, err = call_claude(prompt)
        _write(outp, with_ai(text, err))
        _touch(fm)
    else:
        text, err = call_claude(prompt)
        print(with_ai(text, err))


if __name__ == "__main__":
    main()
