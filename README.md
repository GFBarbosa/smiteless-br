# Smiteless

A League of Legends champ-select & in-game companion. One hotkey (**Win+B**) opens
an always-on-top window with three sections that fill in progressively:

1. **Build card** — runes, summoners, skill order, core items, boots, and situational
   items for your champion, pulled live from op.gg and decoded via Data Dragon.
2. **Coach guide** — **verified op.gg lane win rates** for every lane (your team vs the
   enemy they face) and a **strong-side / weak-side call computed directly from those
   numbers** — nothing invented. An optional AI commentary layer (via the `claude` CLI)
   adds tactical notes, clearly labeled and never a data source.
3. **Player scout** — **live Riot API match data** for each of the 10 players: account
   win rate over their last 10 ranked games + their win rate on the champ they're playing
   *this* game (one-trick / smurf / autofill detector). Always current, unlike cached
   profile sites. In-game only.

Everything that states a number traces to a real source (op.gg or the Riot API). The
design rule is **verified data first; the LLM is optional commentary that can't
contaminate it.**

## How it works by phase

| You press Win+B during… | Source | What you get |
|---|---|---|
| **Champ select** (incl. the post-lock window) | LCU champ-select session | build + lane matchups (your team's roles are known; enemies anonymized) |
| **Loading screen** | LCU gameflow session | build + coach (roles inferred where needed) |
| **In-game** | Live Client API (`:2999`) + Riot API | build + coach + **full player scout** (all 10 resolved via riotId) |

> For the overlay to render over the game, run League in **Borderless** mode —
> fullscreen-exclusive hides all overlays (same requirement as Blitz/Porofessor).

## Requirements

- **Python 3** — standard library only, no `pip install` needed.
- **AutoHotkey v2** — for the Win+B hotkey (`smiteless.ahk`).
- **Riot API key** (for the player scout only) — put it in `~/.riot_api_key`. Dev keys
  expire every 24h; a free production key lifts the rate limit and never expires.
- **`claude` CLI** (optional) — only for the AI commentary in the coach section. The
  verified data works without it.

## Setup

1. Clone this repo.
2. Edit `smiteless.ahk` and set `PY` to your `python.exe` (or leave `"python"` if it's on PATH).
3. (Optional) Save your Riot API key to `~/.riot_api_key` for the player scout.
4. Run `smiteless.ahk` (AutoHotkey v2). Press **Win+B** in champ select or a game.

The Python scripts can also be run directly:

```
python lolbuild.py                 # build card (auto-detects champ select / game)
python lolbuild.py Ahri mid Zed    # manual: champ, role, optional enemy
python lolcoach.py                 # verified lane matchups + macro (+ optional AI)
python lolscout.py --count 10      # live per-player scout (in-game)
```

## Components

- `lolgame.py` — resolves the current game (champ + role + both teams) from whichever
  source is live: champ-select session → Live Client API → gameflow. Caches your role.
- `lolbuild.py` — op.gg build card + cached Data Dragon decode.
- `lolcoach.py` — verified per-lane op.gg win rates, computed strong/weak side, evergreen
  macro principles, and an optional `claude -p` commentary pass.
- `lolscout.py` — Riot API per-player recent-form scout, rate-limit aware, with permanent
  match caching (a match result never changes) so repeat lookups are instant.

## Notes & roadmap

- **Data sources:** op.gg (build + matchup win rates), Riot Data Dragon (static decode),
  the official Riot API (player match history), and Riot's local LCU + Live Client APIs
  (the current game). The scout uses the same official endpoints overlays like
  Blitz/Porofessor use — it reads APIs, not game memory.
- **Rate limits:** with a dev key the full 10-player scout is ~110 calls ≈ ~2 min cold,
  then instant from cache. A production key makes it fast.
- **Config points (currently hardcoded for the author's setup):** League install drive,
  Python path, NA region. Moving these to a small config file is on the list.
- The live deployment also runs from `~/.claude/scripts` via a central AHK script; this
  repo is the canonical source going forward.
