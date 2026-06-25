# Smiteless

> ⚠️ **Personal project — not intended for public use (for now).** This is built for my
> own machine and isn't packaged, supported, or hardened for general use: some assumptions
> (NA region, Windows, AutoHotkey, local paths) are baked in, and it can break or change
> at any time. No warranty, no support — use at your own risk. **Not affiliated with or
> endorsed by Riot Games**; respect the [Riot API terms](https://developer.riotgames.com/policies/general)
> and the terms of any third-party sites it links to (op.gg, u.gg). Provide your own Riot
> API key.

A League of Legends champ-select & in-game companion. It opens a **scoreboard-style
overlay** — a live, always-on-top window that polls the League client/API directly and
updates **in place** as champ-select picks come in and the game progresses. It auto-opens
when a match starts and never steals focus from the game.

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
4. **Per-player rank + form** — each player's solo-queue **rank** (e.g. `D2 67LP`,
   tier-colored) plus their last-10 W/L from the Riot API (the "are they on a heater /
   tilted" read). Always current, unlike cached profile sites. Click an icon for u.gg.
5. **Lane panel** — when you lock a **lane** (not jungle), a panel with your matchup, the
   opponent's recent form, and a **specific, current matchup tip** ("dodge her E, hold Wind
   Wall for her R, all-in at 6…"). Tips are generated once per patch by the LLM **with web
   search** (so they're up to date, not stale recall) and cached to disk — instant every
   game after, and the cache files are plain text you can hand-edit. Before a tip is cached
   it falls back to an archetype-based macro line.

Everything that states a number traces to a real source (op.gg or the Riot API).

## Behavior

- **Lives in your system tray.** A tray icon with a right-click menu: **Open overlay**,
  **Settings**, **Auto-open at champ select** (toggle), **Reload**, **Exit**.
- **Auto-opens at champ select** and **fills in live** as picks lock — your team on the
  left, your full rune page + build (and skill order) on the right (enemies are hidden in
  champ select). At the loading screen / in-game it transitions to the full scoreboard,
  matchups, gank tags, and the player scout, all updating in the same window.
- **Click a champ icon** to open that player's **u.gg** profile in your browser.
- **Ctrl+Alt+X** opens it manually (global). **Left-drag** moves the overlay; **right-click or Esc**
  closes it; it **auto-closes** ~1.5 min after the match ends so the next game is fresh.
- **Never steals focus** (`WS_EX_NOACTIVATE`) — opens on your second monitor if you have one.
- Run League in **Borderless** so the overlay renders over the game (fullscreen-exclusive
  hides all overlays — same requirement as Blitz/Porofessor).

The tray app is `smiteless.ahk` (AutoHotkey — the reliable, zero-dep shell for the tray +
global hotkey); the overlay and settings windows are Python/Tk (`smiteoverlay.py` /
`smitesettings.py`). A **pure-Python alternative** (`smiteless_tray.py`, needs `pip install
pystray`) is included if you'd rather not use AutoHotkey.

## Settings

Right-click the tray icon → **Settings** (a Tk window). Everything applies **live** — the
overlay re-reads it every frame, so gank tags update within a few seconds.

- **Win/loss streak influence** (the headline dial) — how much an enemy's recent form and
  win/loss streak swing the gank rating. **0** = ignore it (pure champ-vs-champ matchup);
  **50** = balanced (matchup is the base, form nudges it); **100** = form/streak dominate.
- **Gank decisiveness** — the score threshold for the GANK / TOUGH tags (lower = more lanes
  tagged).
- **Scout depth** — recent games pulled per player (more = steadier read, slower first scout).
- **Auto-open at champ select** — same toggle as the tray menu.
- **Start with Windows** — adds/removes a registry Run key so the tray launches at login.

Saved to `~/.claude/smiteless_settings.json` (plain JSON you can also hand-edit).

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

- **Python 3** + **Pillow**. The window uses **Tkinter** (stdlib) + Pillow's `ImageTk`.
- **AutoHotkey v2** — runs `smiteless.ahk` (the tray + Ctrl+Alt+X hotkey + auto-open watcher).
  *Or* skip AHK and run the pure-Python tray `smiteless_tray.py` (`pip install pystray`).
- **Riot API key** (for the player scout) — put it in `~/.riot_api_key`. Dev keys expire
  every 24h; a free production key lifts the rate limit and never expires. You can refresh
  an expired key **right from the overlay**: the bottom bar has a **Get key** button (opens
  developer.riotgames.com), a paste field, **Paste** (from clipboard) and **Save** — no need
  to edit files. It applies on the next game.

## Setup

1. Clone, then `pip install -r requirements.txt`.
2. (Optional) Save your Riot API key to `~/.riot_api_key` for the player scout.
3. Run `smiteless.ahk`. It sits in your **system tray** (right-click for the menu),
   auto-opens at champ select, and binds **Ctrl+Alt+X**. *(No AutoHotkey? Run
   `pythonw smiteless_tray.py` instead — `pip install pystray` first.)*

> **Heads-up:** Windows hides new tray icons in the **overflow** (the **^** chevron by the
> clock). If you don't see the gold "S", click the chevron and drag it onto the taskbar to
> pin it. The **Ctrl+Alt+X** hotkey works either way.

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
- `smiteoverlay.py` — the live overlay window (Tk + Pillow `ImageTk`). Runs `smitecard.run()`
  in a worker thread and updates the displayed image in place; topmost, no-focus-steal,
  second-monitor, single-instance, auto-close at game end.
- `smitecard.py` — the renderer: builds each scoreboard frame as a PIL Image (`render_image`)
  and drives the resolve→render loop (`run()`, with the matchup tip generated in the
  background so it never blocks the scout). Also a PNG CLI (`--out`) for debugging.
- `smitesettings.py` — the Tk settings window (the streak-influence dial, gank threshold,
  scout depth, auto-open).
- `smiteconfig.py` — tiny shared settings store (`~/.claude/smiteless_settings.json` +
  the auto-open marker); read live by the overlay's gank math.
- `smiteless.ahk` — the persistent **tray app** (AutoHotkey, default): tray icon + right-click
  menu, the **Ctrl+Alt+X** global hotkey, and the champ-select auto-open watcher. Launches
  the overlay/settings windows.
- `smiteless_tray.py` — optional **pure-Python** tray (same role, `pip install pystray`):
  `pystray` icon + native Win32 hotkey + watcher + a "Start with Windows" registry toggle.
- `selftest.py` — `python selftest.py` health-checks every dependency (Pillow, Data Dragon,
  op.gg, Riot key, claude CLI, LCU) and tells you what's working at a glance.

## Notes & roadmap

- **In-game only** for the full board — roles + player scout require the live game (the
  loading screen only exposes placeholder IDs). Pre-game it shows your build + a heads-up.
- **Rate limits:** with a dev key the 10-player scout is ~110 calls ≈ ~2 min cold, then
  instant from cache. A production key makes it fast.
- Config points still hardcoded for the author's setup (League drive, Python path, NA
  region) — moving these to a config file is on the list.
