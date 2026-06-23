# Smiteless

A League of Legends champ-select & in-game companion. It opens a **scoreboard-style
overlay** (rendered as an image) that shows everything you want before and during a
game — and it auto-opens when a match starts.

![overlay](docs/overlay.png)

The overlay has:

1. **Build / runes header** — keystone, core items, summoners, and your champ's win
   rate/tier, live from op.gg.
2. **Both teams aligned by role** — each lane is `your champ` vs the **real enemy in
   that role**, read straight from the live game (paired by slot, never inferred).
3. **Gank rating per enemy lane** — a transparent weighted score (no AI): your lane's
   matchup edge + the enemy laner's recent form + their win rate on the champ they're
   playing. Starts as the matchup, then shifts as the live scout loads (a tilted /
   off-role enemy becomes a clear gank).
4. **Per-player form bar** — each player's last-10 W/L from the Riot API (the "are they
   on a heater / tilted" read). Always current, unlike cached profile sites.
5. **Lane panel** — when you lock a **lane** (not jungle), a panel with your matchup, the
   opponent's recent form, and a **specific, current matchup tip** ("dodge her E, hold Wind
   Wall for her R, all-in at 6…"). Tips are generated once per patch by the LLM **with web
   search** (so they're up to date, not stale recall) and cached to disk — instant every
   game after, and the cache files are plain text you can hand-edit. Before a tip is cached
   it falls back to an archetype-based macro line.

Everything that states a number traces to a real source (op.gg or the Riot API).

## Behavior

- **Auto-opens at champ select** and fills in as picks lock — your team on the left, your
  full rune page + build on the right (enemies are hidden in champ select). At the loading
  screen / in-game it transitions to the full scoreboard, matchups, gank tags, and scout.
- **Win+B** reopens it after you close it.
- **Second monitor** — opens on your secondary display if you have one.
- Run League in **Borderless** so the overlay renders over the game (fullscreen-exclusive
  hides all overlays — same requirement as Blitz/Porofessor).

## The gank score (transparent, tunable)

The champ-vs-champ matchup is the **base** (dominant). Enemy recent form is a ~30%
modifier that **compounds** with the length of their win/loss streak, and an *extreme*
(near-0%/100% last-10 or a long streak) **overrides** the matchup entirely:

```
score =  1.0  * (your_lane_winrate - 50)                    # matchup edge (the base)
       + 0.15 * (50 - enemy_last10_winrate) * streak_comp   # enemy form, compounding w/ streak
       + 0.10 * (50 - enemy_champ_winrate)                  # comfort on this champ (>=3 games)
       + 4.0   if the enemy is off their champ
       ± 16    if the enemy is extreme (<=15% / >=85% last-10, or a 7+ streak) -> overrides
where  streak_comp = 1 + 0.18 * max(0, streak_len - 2)      # each game past 2-in-a-row amplifies form
score >= +6  -> gank      |  score <= -6  -> tough  |  else even
```

So a tilted enemy on a long loss streak reads as a clear gank no matter the matchup,
and a smurf/heater reads as tough even into a "winning" lane. Weights/threshold live at
the top of `smitecard.py` (`GANK_W_*`, `GANK_STREAK_COMP`, `GANK_EXTREME`, `GANK_T`).

## Requirements

- **Python 3** + **Pillow** (`pip install -r requirements.txt`). The rest is standard library.
- **AutoHotkey v2** — for `smiteless.ahk` (hotkey, auto-open, monitor placement).
- **Riot API key** (for the player scout) — put it in `~/.riot_api_key`. Dev keys expire
  every 24h; a free production key lifts the rate limit and never expires.

## Setup

1. Clone, then `pip install -r requirements.txt`.
2. Edit `smiteless.ahk` — set `PY` to your `python.exe` (or leave `"python"`).
3. (Optional) Save your Riot API key to `~/.riot_api_key` for the player scout.
4. Run `smiteless.ahk`. It auto-opens on game start; Win+B reopens.

Verify everything works: `python selftest.py` — checks Pillow, Data Dragon, op.gg, your
Riot key, the claude CLI, and the live client. Run it after a dev-key rotation or a patch.

Render a card standalone (writes a PNG): `python smitecard.py --out card.png`

## Components

- `lolgame.py` — resolves the current game (your champ/role + both teams **with roles**)
  from whichever source is live: champ-select session -> Live Client API -> gameflow.
- `lolbuild.py` — op.gg build card + per-lane matchup win rates (**paired strictly by role
  slot**) + cached, self-healing Data Dragon decode (champ names, icons, items, runes).
- `lolscout.py` — Riot API per-player recent form (last-10 W/L + current-champ record),
  rate-limit aware, permanent (capped) match caching.
- `phasecheck.py` — tiny stdlib helper that prints the LCU gameflow phase; the AHK watcher
  polls it to auto-open at champ select.
- `lolmatchup.py` — per-matchup lane tips: generated once per patch via `claude` with web
  search (current, not stale), cached to `~/.claude/cache/matchups/` as editable text.
- `claudecli.py` — thin shared wrapper around the logged-in `claude` CLI (no API key);
  used by the matchup tips and the standalone coach.
- `lolcoach.py` — standalone text coach (CLI): verified op.gg lane win rates + an AI
  tactical read for a quick console look. Not used by the overlay.
- `smitecard.py` — composites the scoreboard PNG; renders progressively (the matchup tip
  generates in the background so it never blocks the player scout) and waits for the
  match to come up so auto-open works from champ select onward.
- `selftest.py` — `python selftest.py` health-checks every dependency (Pillow, Data Dragon,
  op.gg, Riot key, claude CLI, LCU) and tells you what's working at a glance.

## Notes & roadmap

- **In-game only** for the full board — roles + player scout require the live game (the
  loading screen only exposes placeholder IDs). Pre-game it shows your build + a heads-up.
- **Rate limits:** with a dev key the 10-player scout is ~110 calls ≈ ~2 min cold, then
  instant from cache. A production key makes it fast.
- Config points still hardcoded for the author's setup (League drive, Python path, NA
  region) — moving these to a config file is on the list.
