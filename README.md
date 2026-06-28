# Smiteless

> ⚠️ **Small personal project — Windows + NA only, no warranty.** Built for me and a few
> friends; it can break or change at any time, and there's no official support. **Not
> affiliated with or endorsed by Riot Games**; respect the
> [Riot API terms](https://developer.riotgames.com/policies/general) and the terms of any
> third-party sites it links to (op.gg, u.gg). The optional player scout needs your own free
> Riot API key.

## ⬇️ Install (no Python or setup needed)

**[Download the latest `SmitelessSetup.exe`](https://github.com/bobbyroylee/smiteless/releases/latest)**,
double-click it, and click **Install**. Everything it needs is bundled — you do **not** need
Python, AutoHotkey, or anything else. Works on **Windows 10/11 (64-bit)**. Run League in
**Borderless** mode. Full step-by-step (with the optional Riot-key walkthrough) is in
**[INSTALL.md](INSTALL.md)** — written so anyone can follow it.

Once installed it lives in your system tray (gold **S**), auto-opens at champ select and
in-game, auto-checks GitHub for updates every few minutes, attempts update apply on launch,
and starts with Windows. Hotkeys:
**Ctrl+Alt+X** (overlay), **Ctrl+Alt+B** (item widget).

The rest of this README is for building from source / hacking on it.

---

A League of Legends champ-select & in-game companion. It opens a **scoreboard-style
overlay** — a live, always-on-top window that polls the League client/API directly and
updates **in place** as champ-select picks come in and the game progresses. It auto-opens
when a match starts and never steals focus from the game.

![Smiteless overlay](docs/overlay-v2.png)

The overlay has:

1. **Build / runes header** — keystone, core items, summoners, and your champ's win
   rate/tier, live from op.gg.
2. **Both teams aligned by role** — each lane is `your champ` vs the **real enemy in
   that role**, read straight from the live game (paired by slot, never inferred).
3. **Gank rating per enemy lane** — a transparent weighted score (no AI): your lane's
   matchup edge + the enemy laner's recent form + their win rate on the champ they're
   playing + **your own champ's gank kit** (a Maokai's CC makes every lane gankable; a
   Nidalee's lack of it doesn't). Starts as the matchup, then shifts as the live scout
   loads (a tilted / off-role enemy becomes a clear gank).
4. **Per-player rank, form + mastery** — each player's solo-queue **rank** (e.g. `D2 67LP`,
   tier-colored), their last-10 W/L (the "heater / tilted" read), and their **mastery** on
   the champ they're playing (`M7 1.2M` = one-trick) — all live from the Riot API, always
   current unlike cached profile sites. Click an icon for u.gg.
5. **Lane panel** — when you lock a **lane** (not jungle), a panel with your matchup, the
   opponent's recent form, and a **specific, current matchup tip** ("dodge her E, hold Wind
   Wall for her R, all-in at 6…"). Tips are generated once per patch by the LLM **with web
   search** (so they're up to date, not stale recall) and cached to disk — instant every
   game after, and the cache files are plain text you can hand-edit. Before a tip is cached
   it falls back to an archetype-based macro line.
6. **Duo / premade detection** — teammates who share several of their recent ranked games
   get a matching **duo** marker (same color = same group). Inferred from match-history
   overlap, since the API doesn't expose lobby premades directly.
7. **Floating item helper** — a *separate* small, draggable, always-on-top widget (not part
   of the board) you leave in a corner all game. It shows your **next item** from op.gg's
   real per-champ pool, and surfaces a defensive piece (Zhonya's vs a fed AD threat, an MR
   item vs magic, anti-heal vs a healer) **only when the enemy's actual built damage + who's
   fed calls for it** — dropping each suggestion the moment you own it. Real op.gg items, no
   generic tables, no AI. See [Floating item widget](#floating-item-widget) below.
8. **Home / profile page** — open outside a game and you get a dedicated profile window with
   a fixed top section + scroll-only match history, in-card **Load more**, expandable game
   details, and click-through full review panels.
9. **Post-game review engine** — each recent game gets role/champion-aware review notes from
   deaths, KP, damage share, objective participation (plus farm/vision/lane pressure context);
   **A/S** games switch to positive "what you did well" notes.
10. **Scoring overhaul** — lobby-relative score that can exceed 100 for hard-carry games.
    Grades: **S = 100+**, **A = 85–99**, **B = 70–84**, **C = 55–69**, **D < 55**.
11. **Champ-select helpers** — "Good this game" suggested champions rail, one-click
    **Import runes + summs** in the build block, and Flash key preference support.
12. **Queue read** — in-game winners/losers/even queue prediction from team-vs-enemy recent
    WR, excluding your own account and detected duo from ally averaging.
13. **Live game intel** (in the item widget) — a transparent **win read** (logistic on net
    item-gold + level + drake/baron lead), **objective spawn timers** (drake / void grubs /
    baron, event-driven off the Live Client so respawns stay correct), and a **power-spike
    alert** when an enemy carry has completed items *and* is fed. No model, no key — straight
    off the :2999 Live Client API.
14. **Dodge alerts** — a high-confidence "**consider dodging**" banner in champ select when
    op.gg lane matchups say the draft is lost across most lanes. Deliberately strict (it has
    to clear an average-disadvantage, losing-lane-count, hard-counter, and no-carry-lane gate
    all at once) because a free dodge is scarce.
15. **Profile session + coach** — the home page tracks your **session** (W-L, LP swing, win/loss
    streak, and a take-a-break **tilt** nudge after a loss streak), a **pool coach** ("play more
    X / ease off Y" from your champ win rates), and an **LP-trend sparkline**.

Everything that states a number traces to a real source (op.gg, the Riot API, or the Live Client).

## Behavior

- **Lives in your system tray.** A tray icon with a right-click menu: **Open overlay**,
  **Item widget**, **Settings**, **Auto-open at champ select** (toggle), **Reload**, **Exit**.
- **Auto-opens at champ select** and **fills in live** as picks lock — your team on the
  left, your full rune page + build (and skill order) on the right (enemies are hidden in
  champ select). At the loading screen / in-game it transitions to the full scoreboard,
  matchups, gank tags, the player scout, and duo markers — all updating in the same window.
- **Profile auto-opens after game end** so recent-game review is immediately visible.
- **The floating item widget auto-opens in-game** (or **Ctrl+Alt+B** / tray → *Item widget*):
  drag it anywhere, it remembers the spot, and it closes itself after the game.
- **Dragon spawn reminder** — plays a system sound about 30 seconds before the next elemental
  dragon spawns while you're in-game.
- **Click a champ icon** to open that player's **u.gg** profile in your browser.
- **Ctrl+Alt+X** opens the board manually (global). **Left-drag** moves it; **right-click or Esc**
  closes it; it **auto-closes** ~1.5 min after the match ends so the next game is fresh.
- **Updates**: startup auto-apply attempt + periodic background checks; tray notifies when a
  newer release exists.
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
- **Profile: games to load** — how many games profile loads at once (and per Load more click).
- **Auto-open at champ select** — same toggle as the tray menu.
- **Open profile/home on startup** — toggle startup landing behavior.
- **Auto-accept queue** — optional ready-check auto-accept.
- **Live game intel** — the widget's win read + objective timers + spike alert (toggle off for a
  bare item helper).
- **Dodge alerts** — the champ-select "consider dodging" banner.
- **Flash key preference** — slider: left = Flash on D, right = Flash on F (applied on import).
- **Start with Windows** — adds/removes a registry Run key so the tray launches at login.

Saved to `~/.claude/smiteless_settings.json` (plain JSON you can also hand-edit).

## The gank score (transparent, tunable)

The champ-vs-champ matchup is the **base** (dominant). Enemy recent form is a ~30%
modifier that **compounds** with the length of their win/loss streak, and an *extreme*
(near-0%/100% last-10 or a long streak) **overrides** the matchup entirely:

```
score =  your_champ_kit                                     # YOUR CC/engage: Maokai +6 … Nidalee -1
       + 1.0  * (your_lane_winrate - 50)                    # matchup edge (the base)
       + 0.15 * (50 - enemy_last10_winrate) * streak_comp   # enemy form, compounding w/ streak
       + 0.10 * (50 - enemy_champ_winrate)                  # comfort on this champ (>=3 games)
       + 4.0   if the enemy is off their champ
       ± 16    if the enemy is extreme (<=15% / >=85% last-10, or a 7+ streak) -> overrides
where  streak_comp = 1 + 0.18 * max(0, streak_len - 2)      # each game past 2-in-a-row amplifies form
score >= +6  -> gank      |  score <= -6  -> tough  |  else even
```

So a tilted enemy on a long loss streak reads as a clear gank no matter the matchup,
a smurf/heater reads as tough even into a "winning" lane, and your own champion shifts
every lane up or down — the same enemy is a gank on Maokai and even on Nidalee. Weights/
threshold and the per-champ kit table live at the top of `smitecard.py` (`GANK_W_*`,
`GANK_STREAK_COMP`, `GANK_EXTREME`, `GANK_T`, `GANK_KIT`).

## Floating item widget

A separate compact window (`smitewidget.py`) — always-on-top, never steals focus, draggable,
and it **remembers where you drop it**. It auto-opens in-game (or **Ctrl+Alt+B** / tray →
*Item widget*) and closes itself ~1.5 min after the game ends. Leave it in a corner and glance
at it on each back.

It is **not** generic. The item pool is op.gg's real, per-champ build for your champ+role (the
same source as the build card), so the suggestions are always champ-correct. The **live game**
then drives them, so they're genuinely dynamic:

- **Next item** — the first item in your champ's standard op.gg sequence you don't already own.
  It advances every time you complete an item.
- **Defensive swap** — surfaced only when the game calls for it: it reads the enemy's *actual
  built* AD vs AP (from their live items, not their class) and who's **fed** (live KDA), then
  pulls the matching resist/anti-heal/stasis item **from your champ's own pool** (e.g. Zhonya's
  vs a fed Zed, an MR item vs a magic comp, a Grievous-Wounds item vs a healer). The moment you
  buy it, it drops off.
- **Boots cue** — Mercury's Treads over your standard boots when they're stacking CC or magic.

If your champ simply doesn't itemize against a threat (e.g. a burst mage vs magic damage), it
says so rather than inventing a fake item — it shows the threat readout and your next core.

The threat/recommendation logic is all in `lolitems.py` (`live_state` → `recommend`).

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
   `pythonw tools/smiteless_tray.py` instead — `pip install pystray` first.)*

> **Heads-up:** Windows hides new tray icons in the **overflow** (the **^** chevron by the
> clock). If you don't see the gold "S", click the chevron and drag it onto the taskbar to
> pin it. The **Ctrl+Alt+X** hotkey works either way.

Verify everything works: `python tools/selftest.py` — checks Pillow, Data Dragon, op.gg,
your Riot key, the claude CLI, and the live client. Run it after a dev-key rotation or a patch.

Render a card standalone (writes a PNG): `python core/smitecard.py --out card.png`

## Layout

```
smiteless.ahk    the tray app + global hotkeys (the launcher; stays at the root)
core/            data + render engine — imported, not run directly
ui/              the windows you launch — overlay, item widget, settings
tools/           standalone CLIs + helpers — selftest, coach, phase check, pystray tray
assets/          icon
```

The modules use flat imports (`import lolbuild`); each launchable script has a tiny
bootstrap at the top that adds `core/`, `ui/`, and `tools/` to `sys.path`, so nothing else
had to change when the files moved into folders.

## Components

**`core/`** — data + rendering engine
- `core/lolgame.py` — resolves the current game (your champ/role + both teams **with roles**)
  from whichever source is live: champ-select session -> Live Client API -> gameflow.
- `core/lolbuild.py` — op.gg build card + per-lane matchup win rates (**paired strictly by
  role slot**) + cached, self-healing Data Dragon decode (champ names, icons, items, runes).
- `core/lolscout.py` — Riot API per-player recent form (last-10 W/L + current-champ record),
  rank, mastery, and the recent **match IDs** that drive duo detection; rate-limit aware,
  permanent (capped) match caching.
- `core/lolitems.py` — in-game item logic: pulls your champ's real item pool from op.gg, reads
  the live game (your owned items, the enemy's *actual built* AD/AP, healing, CC, who's fed),
  and picks the next item + the right defensive piece from that pool. No AI, no generic tables.
- `core/lolprofile.py` — the home page: who you are (live client) + Riot-API rank, recent form,
  champ win rates, upgraded lobby-relative scoring (100+ possible), and role/champ-specific
  post-game review notes.
- `core/lolmatchup.py` — per-matchup lane tips: generated once per patch via `claude` with web
  search (current, not stale), cached to `~/.claude/cache/matchups/` as editable text.
- `core/claudecli.py` — thin shared wrapper around the logged-in `claude` CLI (no API key);
  used by the matchup tips and the standalone coach.
- `core/smitecard.py` — the renderer: builds each scoreboard frame as a PIL Image
  (`render_image`) and drives the resolve→render loop (`run()`, with the matchup tip generated
  in the background so it never blocks the scout). Also a PNG CLI (`--out`) for debugging.
- `core/smiteconfig.py` — tiny shared settings store (`~/.claude/smiteless_settings.json` +
  the auto-open marker); read live by the overlay's gank math.

**`ui/`** — the windows
- `ui/smiteoverlay.py` — the live overlay window (Tk + Pillow `ImageTk`). Runs `smitecard.run()`
  in a worker thread and updates the displayed image in place; topmost, no-focus-steal,
  second-monitor, single-instance, auto-close at game end.
- `ui/smitewidget.py` — the floating in-game **item widget** (Tk). Polls `lolitems.recommend()`,
  shows next-item + defensive suggestions, draggable + position-remembering, no-focus-steal,
  single-instance, auto-closes after the game.
- `ui/smitesettings.py` — the Tk settings window (the streak-influence dial, gank threshold,
  scout depth, auto-open).

**`tools/`** — standalone CLIs + helpers
- `tools/phasecheck.py` — tiny stdlib helper that prints the LCU gameflow phase; the AHK
  watcher polls it to auto-open at champ select.
- `tools/lolcoach.py` — standalone text coach (CLI): verified op.gg lane win rates + an AI
  tactical read for a quick console look. Not used by the overlay.
- `tools/smiteless_tray.py` — optional **pure-Python** tray (same role, `pip install pystray`):
  `pystray` icon + native Win32 hotkey + watcher + a "Start with Windows" registry toggle.
- `tools/selftest.py` — `python tools/selftest.py` health-checks every dependency (Pillow,
  Data Dragon, op.gg, Riot key, claude CLI, LCU) and tells you what's working at a glance.

**root**
- `smiteless.ahk` — the persistent **tray app** (AutoHotkey, default): tray icon + right-click
  menu, the **Ctrl+Alt+X** (overlay) / **Ctrl+Alt+B** (item widget) global hotkeys, and the
  watcher that auto-opens the board at champ select and the widget in-game. Launches the
  windows under `ui/`.

## Notes & roadmap

- **In-game only** for the full board — roles + player scout require the live game (the
  loading screen only exposes placeholder IDs). Pre-game it shows your build + a heads-up.
- **Rate limits:** with a dev key the 10-player scout is ~110 calls ≈ ~2 min cold, then
  instant from cache. A production key makes it fast.
- Config points still hardcoded for the author's setup (League drive, Python path, NA
  region) — moving these to a config file is on the list.
