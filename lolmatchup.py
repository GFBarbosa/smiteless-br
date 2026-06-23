#!/usr/bin/env python3
"""lolmatchup.py - specific lane matchup tips, generated ONCE per patch by the LLM
WITH web search (so they're up to date, not stale training recall) and cached to
disk. Costs tokens only the first time you see a matchup on a given patch; instant
from disk after, and the cache files are plain text you can hand-edit. Claude pulls
current guidance from the web (Mobafire/u.gg/Mobalytics) and falls back to its own
knowledge if it finds nothing current. Cache key includes the patch, so tips refresh
when the game changes but don't burn tokens within a patch.

CLI (manual seeding / testing):
  python lolmatchup.py Yasuo Syndra mid
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lolbuild as lb
import lolcoach as lc          # reuse call_claude (logged-in claude CLI, no API key)

CACHE = os.path.expanduser("~/.claude/cache/matchups")


def _safe(s):
    return re.sub(r"[^A-Za-z0-9]", "", s or "")


def patch_of(ver):
    p = (ver or "").split(".")
    return ".".join(p[:2]) if len(p) >= 2 else (ver or "x")


def _file(my_key, opp_key, role, patch):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, f"{_safe(my_key)}_vs_{_safe(opp_key)}_{_safe(role)}_{_safe(patch)}.txt")


def get_tip(my_key, opp_key, role, patch):
    """Cached tip text for this patch, or None if not generated yet."""
    fp = _file(my_key, opp_key, role, patch)
    if os.path.exists(fp):
        try:
            return open(fp, encoding="utf-8").read().strip() or None
        except Exception:
            return None
    return None


def generate_tip(my_name, my_key, opp_name, opp_key, role, patch):
    """Generate (web-search, current-patch) + cache. Returns (text, error)."""
    prompt = (
        f"Patch {patch}. Search the web for the CURRENT {my_name} vs {opp_name} {role} matchup "
        f"(Mobafire, u.gg, Mobalytics, Reddit). In 2-3 sentences, give a SPECIFIC, up-to-date tip on "
        f"HOW TO PLAY THE LANE: which enemy ability/abilities to dodge or bait and how, the trade and "
        f"wave pattern, and when you win vs when you lose (you may reference generic timings like "
        f"'level 6' or 'your first item spike'). "
        f"CRITICAL: do NOT recommend or name ANY runes, keystones, summoner spells, or items - the "
        f"live op.gg build is shown to the player separately and the LLM gets builds wrong. Keep it "
        f"purely to lane mechanics and decisions. If you can't find current info, use your own best "
        f"knowledge. Plain text only - no preamble, no markdown, no bullet points, no headers."
    )
    text, err = lc.call_claude(prompt, allow_tools="WebSearch,WebFetch", timeout=170)
    if not text:
        return None, err
    text = " ".join(text.split())          # collapse to one block
    try:
        open(_file(my_key, opp_key, role, patch), "w", encoding="utf-8").write(text)
    except Exception:
        pass
    return text, None


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("usage: python lolmatchup.py <myChamp> <oppChamp> [role]")
        return
    dd = lb.ddragon()
    patch = patch_of(dd["ver"])
    my = dd["name2id"].get(dd["norm"](args[0]))
    opp = dd["name2id"].get(dd["norm"](args[1]))
    role = (args[2].lower() if len(args) > 2 else "mid")
    if not my or not opp:
        print("unknown champ name")
        return
    mk, ok = dd["id2key"][my], dd["id2key"][opp]
    cached = get_tip(mk, ok, role, patch)
    if cached:
        print("[cached]", cached)
        return
    print("(generating with web search, ~60-120s...)")
    t, err = generate_tip(dd["id2name"][my], mk, dd["id2name"][opp], ok, role, patch)
    print(t if t else f"[failed: {err}]")


if __name__ == "__main__":
    main()
