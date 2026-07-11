#!/usr/bin/env python3
"""lolmatchup.py - specific lane matchup tips from REAL WRITTEN GUIDES, cached per patch.

PRIMARY source: counterstats.net (MOBAFire) — actual prose counter-tips written by guide
authors for the exact enemy champion, filtered to your lane and (when available) authored
by players of YOUR champion. Fast (~1s scrape, cached per enemy+patch), deterministic, no
AI in the loop. FALLBACK when the site has nothing for the matchup: the old LLM+web-search
generator. Cache key includes the patch, so tips refresh when the game changes.

CLI (manual seeding / testing):
  python lolmatchup.py Yasuo Syndra mid
"""
import json
import os, re, sys
import time
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import claudecli as cc         # logged-in claude CLI (fallback path only)

CACHE = os.path.expanduser("~/.claude/cache/matchups")
CS_CACHE = os.path.expanduser("~/.claude/cache/counterstats")
CS_HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# our role names -> the site's data-lane tokens
CS_LANE = {"top": "top", "jungle": "jungle", "jg": "jungle", "mid": "mid", "middle": "mid",
           "adc": "adc", "bot": "adc", "bottom": "adc", "support": "support", "sup": "support"}


def _safe(s):
    return re.sub(r"[^A-Za-z0-9]", "", s or "")


def patch_of(ver):
    p = (ver or "").split(".")
    return ".".join(p[:2]) if len(p) >= 2 else (ver or "x")


def _file(my_key, opp_key, role, patch):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, f"{_safe(my_key)}_vs_{_safe(opp_key)}_{_safe(role)}_{_safe(patch)}.txt")


# Signatures that mean the "tip" is actually an error the CLI printed (auth/limit/etc). None of
# these appear in a real lane tip, so we can safely reject + never cache/show them.
_BAD_SIGNS = ("api error", "invalid authentication", "authentication credentials",
              "failed to authenticate", "authentication_error", "usage limit", "session limit",
              "rate limit", "invalid x-api-key", "credit balance", "claude auth")


def _looks_bad(text):
    tl = (text or "").lower()
    return any(s in tl for s in _BAD_SIGNS)


def get_tip(my_key, opp_key, role, patch):
    """Cached tip text for this patch, or None if not generated yet. Self-heals: a cache file
    that's actually an error message (from before this fix, or a transient auth blip) is dropped
    so the tip regenerates instead of showing the error forever."""
    fp = _file(my_key, opp_key, role, patch)
    if os.path.exists(fp):
        try:
            t = open(fp, encoding="utf-8").read().strip()
        except Exception:
            return None
        if t and not _looks_bad(t):
            return t
        try:
            os.remove(fp)                      # poisoned/empty -> drop it, regenerate next time
        except Exception:
            pass
    return None


def _cs_slug(name):
    """ddragon display name -> counterstats URL slug: 'Kha'Zix'->'khazix',
    'Lee Sin'->'lee-sin', 'Dr. Mundo'->'dr-mundo', 'Nunu & Willump'->'nunu-willump'."""
    s = (name or "").lower().replace("&", " ").replace("'", "").replace(".", "")
    return "-".join(s.split())


def _cs_clean(t):
    t = re.sub(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", r"\1", t)    # [[paranoia]] -> paranoia
    t = (t.replace("&#039;", "'").replace("&quot;", '"').replace("&amp;", "&")
          .replace("“", "").replace("”", "").replace("�", ""))
    return " ".join(t.split()).strip(' "')


_CS_BOX = re.compile(
    r"tip-box__tip'><span class='author'>[^<]*</span>\s*(.+?)</span>.*?"
    r"champion/square/([a-z0-9]+)\.png.*?class=\"score\">(-?\d+)</span>", re.S)


def fetch_cs_tips(enemy_name, patch):
    """Every written counter-tip for playing AGAINST `enemy_name`, scraped from
    counterstats.net: [{lane, champ, votes, text}]. champ = the author's champion (the
    matchup POV). Cached per enemy+patch; [] on any failure — caller falls back."""
    fp = os.path.join(CS_CACHE, f"{_safe(enemy_name)}_{_safe(patch)}.json")
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        pass
    try:
        req = urllib.request.Request(
            f"https://www.counterstats.net/league-of-legends/{_cs_slug(enemy_name)}",
            headers=CS_HDRS)
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return []
    tips = []
    # lane sections: <div class="champ-box__tips__wrap LANE" data-lane="LANE"> ... boxes ...
    secs = list(re.finditer(r'champ-box__tips__wrap\s+([a-z]+)"', html))
    for i, m in enumerate(secs):
        lane = m.group(1)
        chunk = html[m.end(): secs[i + 1].start() if i + 1 < len(secs) else len(html)]
        for b in _CS_BOX.finditer(chunk):
            text = _cs_clean(b.group(1))
            if len(text) < 60:                    # too short to be advice
                continue
            tips.append({"lane": lane, "champ": b.group(2), "votes": int(b.group(3)),
                         "text": text[:600]})
    if tips:
        try:
            os.makedirs(CS_CACHE, exist_ok=True)
            json.dump(tips, open(fp, "w", encoding="utf-8"))
        except Exception:
            pass
    return tips


def written_tip(dd, my_cid, opp_cid, role, patch):
    """The best HUMAN-WRITTEN tip for my champ vs the enemy in this lane, or None.
    Preference order: a tip written by a player of MY champion about this enemy (the true
    matchup POV, best votes first), else the best general 'how to beat them' tips for the
    lane. Returns display-ready text."""
    opp_name = dd["id2name"].get(opp_cid, "")
    if not opp_name:
        return None
    tips = fetch_cs_tips(opp_name, patch)
    if not tips:
        return None
    lane = CS_LANE.get((role or "").lower(), "")
    norm = dd["norm"]
    mine_norm = norm(dd["id2name"].get(my_cid, ""))
    pool = [t for t in tips if t["lane"] == lane] or tips
    def rank(t):                                  # votes first, then substance
        return (t["votes"], min(len(t["text"]), 420))
    mine = sorted((t for t in pool if norm(t["champ"]) == mine_norm), key=rank, reverse=True)
    if mine:
        return f"{mine[0]['text']}  — a {dd['id2name'].get(my_cid, '')} main (MOBAFire)"
    best = sorted(pool, key=rank, reverse=True)[:2]
    if not best:
        return None
    out = "  ·  ".join(t["text"] for t in best[:1] if t["text"])
    return f"{out}  — guide authors (MOBAFire)" if out else None


def generate_tip(my_name, my_key, opp_name, opp_key, role, patch):
    """Real written-guide tip first (counterstats.net scrape, cached); the LLM+web-search
    generator only as fallback when no written tip exists. Returns (text, error)."""
    try:
        dd = lb.ddragon()
        my_cid = dd["name2id"].get(dd["norm"](my_name), 0)
        opp_cid = dd["name2id"].get(dd["norm"](opp_name), 0)
        if my_cid and opp_cid:
            t = written_tip(dd, my_cid, opp_cid, role, patch)
            if t:
                try:
                    open(_file(my_key, opp_key, role, patch), "w", encoding="utf-8").write(t)
                except Exception:
                    pass
                return t, None
    except Exception:
        pass
    return _generate_tip_llm(my_name, my_key, opp_name, opp_key, role, patch)


def _generate_tip_llm(my_name, my_key, opp_name, opp_key, role, patch):
    """Fallback: generate with the logged-in CLI (web search) + cache. Returns (text, error)."""
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
    text, err = cc.call_claude(prompt, allow_tools="WebSearch,WebFetch", timeout=170)
    if not text or _looks_bad(text):          # never cache/return an error string as a tip
        return None, (err or "tip unavailable")
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
