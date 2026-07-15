#!/usr/bin/env python3
"""lolrecords.py - GHOST: a live personal-best pace race against your own best game.

For each champ+role you play, the profile loop learns a "ghost" from your single
best-GRADED game on it (grade A or better): the per-minute CS/gold trace, deaths
through 15:00, and the final clock. In your next game on that champ, the widget
races you against that ghost like a speedrun timer - CS and deaths are exact on
both sides (live scores vs Riot timeline); gold is the live ESTIMATE vs Riot's
exact totalGold, so it's shown as secondary. Beat the ghost and it gets faster.

House rule: ghosts are built ONLY from your own in-game performance - never rank,
win/loss, or another account. Your only opponent is who you were last week.
"""
import os, json, time, threading

PATH = os.path.expanduser("~/.claude/cache/lol_records.json")
SEED_MIN = 85              # grade A: a ghost must come from a game that hit its role goals
MIN_DUR = 900              # <15 min (early surrender) can't set a meaningful pace record
SPLITS = (600, 900)        # split checkpoints: CS@10:00, deaths@15:00
SPLIT_SHOW = 8.0           # seconds a crossed split stays on screen


def _norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _key(champ, role):
    return f"{_norm(champ)}|{(role or '').upper()}"


def load_records():
    try:
        d = json.load(open(PATH, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_records(recs):
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = f"{PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(recs, f)
        os.replace(tmp, PATH)
    except Exception:
        pass


def build_record(tl, puuid, mine, score, mid, dur):
    """Distill a PB ghost from a match_timeline payload: my per-minute cs/gold trace,
    my death timestamps, deaths through 15:00. None if I'm not in the timeline."""
    pids = (tl or {}).get("pids") or []
    if puuid not in pids:
        return None
    my_pid = str(pids.index(puuid) + 1)
    cs, g = [], []
    for row in tl.get("mins") or []:
        p = row.get(my_pid) or {}
        cs.append(int(p.get("cs", 0) or 0))
        g.append(int(p.get("g", 0) or 0))
    if len(cs) < 10:                       # a trace too short to race against
        return None
    deaths_t = sorted(int(d["t"]) for d in (tl.get("deaths") or [])
                      if d.get("v") is not None and str(d["v"]) == my_pid)
    return {"champ": mine.get("champ", ""), "role": (mine.get("pos") or "").upper(),
            "mid": mid, "score": int(score), "ts": int(time.time()),
            "dur": int(dur or len(cs) * 60),
            "cs": cs, "g": g, "deaths_t": deaths_t,
            "deaths15": sum(1 for t in deaths_t if t <= 900)}


def maybe_record(key, puuid, mid, mine, score, dur):
    """Called from the profile loop for each graded SELF game: seed/refresh the ghost
    when this game out-grades the stored record for its champ+role. The timeline is
    only fetched for actual PB candidates, so this adds ~zero API cost. True if saved."""
    if score < SEED_MIN or (dur or 0) < MIN_DUR:
        return False
    role = (mine.get("pos") or "").upper()
    champ = mine.get("champ") or ""
    if not champ or not role:
        return False
    recs = load_records()
    cur = recs.get(_key(champ, role))
    if cur and (cur.get("mid") == mid or int(cur.get("score", 0)) >= score):
        return False
    import lolscout as ls
    tl = ls.match_timeline(mid, key)
    rec = build_record(tl, puuid, mine, score, mid, dur)
    if not rec:
        return False
    recs[_key(champ, role)] = rec
    save_records(recs)
    return True


def _interp(arr, minute):
    """Value of a per-minute trace at a fractional minute, clamped to the trace ends."""
    if not arr:
        return 0.0
    if minute <= 0:
        return float(arr[0])
    i = int(minute)
    if i >= len(arr) - 1:
        return float(arr[-1])
    f = minute - i
    return arr[i] * (1.0 - f) + arr[i + 1] * f


class GhostRace:
    """Stateful live race vs the ghost, one update per widget tick off the shared :2999
    payload. Returns a compact render dict every tick (or None before identification):
      {status: 'first'|'ahead'|'behind', line, ghost_score, split, new_record_event, final}
    CS and deaths are exact on both sides; gold is the live estimate vs Riot's exact
    totalGold, so it rides along as the last, softest number. A gameTime reset (new
    game) clears everything; the end-of-game verdict comes from the GameEnd event the
    live client emits, and is PROVISIONAL - the authoritative record rewrite happens
    from Riot match data on the next profile load."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.rec = None
        self.looked = False
        self.champ = None
        self.last_gt = 0.0
        self.split = None          # (expires_at_gt, text, ok)
        self.fired = set()         # split thresholds already shown
        self.ended = False

    def _find_record(self, champ, role):
        """Record for champ+role; a role-less payload (some queues) falls back to the
        best-scored ghost on that champ in any role."""
        recs = load_records()
        r = recs.get(_key(champ, role)) if role else None
        if r:
            return r
        cands = [v for k, v in recs.items() if k.split("|")[0] == _norm(champ)]
        return max(cands, key=lambda v: int(v.get("score", 0))) if cands else None

    def update(self, dd, data):
        import lollive as ll
        gt = float(((data or {}).get("gameData") or {}).get("gameTime") or 0.0)
        if gt + 30 < self.last_gt:                 # gameTime went backwards -> new game
            self.reset()
        prev_gt, self.last_gt = self.last_gt, max(self.last_gt, gt)
        split = ll._team_split(data or {})
        if not split:
            return None
        me = split[0]
        champ = me.get("championName") or ""
        if not self.looked and champ:
            self.looked = True
            self.champ = champ
            self.rec = self._find_record(champ, (me.get("position") or "").upper())
        if not self.looked:
            return None
        if self.rec is None:
            return {"status": "first", "line": "GHOST ▸ setting your first record",
                    "split": None, "new_record_event": False, "final": False}

        sc = me.get("scores") or {}
        my_cs = int(sc.get("creepScore", 0) or 0)
        my_d = int(sc.get("deaths", 0) or 0)
        m = gt / 60.0
        # Past the record game's final clock the ghost keeps farming at its average
        # pace (a frozen trace would gift a "record" to any longer game).
        rec_min = max(1.0, float(self.rec.get("dur") or len(self.rec["cs"]) * 60) / 60.0)
        def ghost_at(arr):
            return _interp(arr, m) if m <= rec_min else float(arr[-1]) * m / rec_min
        gh_cs = ghost_at(self.rec["cs"])
        gh_d = sum(1 for t in self.rec.get("deaths_t", []) if t <= gt)
        cs_d = int(round(my_cs - gh_cs))
        gold_d = 0
        try:
            gold_d = int(round(ll.est_gold(me, gt) - ghost_at(self.rec["g"])))
        except Exception:
            pass
        ahead = cs_d >= 0 and my_d <= gh_d

        # split checkpoints: flash the result for a few seconds after crossing
        for thr in SPLITS:
            if thr not in self.fired and prev_gt and prev_gt < thr <= gt:
                self.fired.add(thr)
                if thr == 600:
                    ok = my_cs >= int(round(_interp(self.rec["cs"], 10.0)))
                    txt = f"CS@10: {my_cs} (record {int(round(_interp(self.rec['cs'], 10.0)))}) {'✓' if ok else '✗'}"
                else:
                    ok = my_d <= self.rec.get("deaths15", 0)
                    txt = f"deaths@15: {my_d} (record {self.rec.get('deaths15', 0)}) {'✓' if ok else '✗'}"
                self.split = (gt + SPLIT_SHOW, txt, ok)
        if self.split and gt > self.split[0]:
            self.split = None

        # end of game: the live client emits a GameEnd event - fire the verdict once
        new_rec = False
        final = False
        if not self.ended:
            evs = ((data or {}).get("events") or {}).get("Events") or []
            if any(e.get("EventName") == "GameEnd" for e in evs):
                self.ended = final = True
                new_rec = gt >= MIN_DUR and ahead

        line = (f"GHOST ▸ CS {cs_d:+d} · deaths {my_d}/{gh_d} · {gold_d:+d}g"
                if gt >= 90 else "GHOST ▸ on the line")
        return {"status": "ahead" if ahead else "behind", "line": line,
                "split": (self.split[1], self.split[2]) if self.split else None,
                "new_record_event": new_rec, "final": final}


if __name__ == "__main__":
    recs = load_records()
    if not recs:
        print("no ghosts yet - play (and grade A on) a champ, then open your profile")
    for k, r in sorted(recs.items()):
        print(f"{k:28s} score {r['score']:3d}  cs@10 {int(_interp(r['cs'], 10.0)):3d}  "
              f"deaths@15 {r['deaths15']}  ({time.strftime('%Y-%m-%d', time.localtime(r['ts']))})")
