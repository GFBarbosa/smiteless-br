# Smiteless ⚔️

**A League of Legends companion that plays the map with you.** It watches champ select and your live game, then tells you the one thing that matters right now — what to ban, when to back, whether that drake fight is winnable, and when to stop queuing.

![The in-game scoreboard](docs/board.png)

| Champ select (docks by the client) | Your profile |
|:---:|:---:|
| ![Champ select panel](docs/champselect.png) | ![Profile](docs/profile.png) |

**The loading-screen scout** — every account in the lobby read from its real match history, with profile tags (duo · smurf read · OTP · tilt risk · first-timer · off-role):

![Loading-screen scout](docs/preview_loading_ui.png)

**The Death Brief** — laid out around the game's own death HUD, center kept clear to watch the fight:

![Death brief](docs/preview_death_ui.png)

> ⚠️ **Small personal project — Windows + NA only, no warranty.** Not affiliated with or endorsed by Riot Games; respect the [Riot API terms](https://developer.riotgames.com/policies/general). The player scout needs your own free Riot API key.

## ⬇️ Install

**[Download SmitelessSetup.exe](https://github.com/bobbyroylee/smiteless/releases/latest)** → double-click → Install. No Python, no setup — everything's bundled. Windows 10/11, League in **Borderless** mode. Full walkthrough (including the free Riot-key setup): **[INSTALL.md](INSTALL.md)**.

It lives in your tray (gold **S**), opens itself at champ select and in-game, and keeps itself updated. Hotkeys: **Ctrl+Alt+X** overlay · **Ctrl+Alt+B** widget.

## What it does

### 🧠 In champ select
- **Scouts everyone live** — rank, form, player grades (S–F from how they actually *play*), duo detection, and a **dodge read** that flags tilted or struggling teammates *while you can still dodge*
- **Smart bans** — ranked by who threatens your whole team's hovers, weighted by pick rate, with optional **auto-ban** that waits until the last seconds for maximum hover intel
- **Real matchup tips** — written by actual guide authors for your exact matchup, not AI
- **The live draft link** — posts one URL into lobby chat; teammates who click it get a live web board of the draft with pick suggestions + runes for their seat, no install needed ([setup](docs/DRAFTLINK.md), $0 to run)
- **One-click (or automatic) runes + summoners import**, multiple rune sets, favourite picks
- **Climb guards** — warns when you hover a champ you barely play (sub-12k-mastery picks win ~44%, per a 1M-game study), and only suggests champs you actually main — pooled across all your accounts

### ⚡ In game
- **The Tempo engine** — a live director for the ~90 seconds before every objective: your farm window, exact recall deadline, when to rotate, and a **TAKE / GIVE / 50-50 verdict** from death timers, levels and gold (fog-of-war aware). With spoken callouts: *"Base now"*, *"Rotate to dragon"*, *"Give it, trade elsewhere"*
- **Enemy jungle tracker** — where they were seen, when they're dead, when to respect the gank
- **Win probability, objective timers with audio, power-spike alerts, item coaching** — one compact draggable HUD that fades when nothing needs you, and is fully click-through during a live game so it can never eat a click (hold **Ctrl+Alt** to touch it)
- **The Death Brief** — the moment you die, a see-through fullscreen overlay gives you the whole game at a glance: respawn clock, why you died, what to buy on respawn, the win read, the enemy to watch, next objectives, and the team boards. Laid out around the game's own death HUD (team boards top-center where TAB lives, nothing over the recap / chat / minimap), center stays clear + click-through so you keep watching the fight. Read-only — never touches your camera or inputs
- **The Loading-Screen Scout** — while the game loads, ten splash-art scoreboard rows read every ACCOUNT in the lobby: rank + LP + season record, last-10 form bars, KDA, mastery, record on the locked champ, a performance grade, and profile tags mined from their real history — `duo`, `SMURF READ`, `OTP · 612k pts`, `4L streak · tilt risk`, `first-time?`, `off-role`, `carries games`, `hardstuck`. Gone the instant the game starts

### 📈 Between games
- **Your profile** — per-game performance scores graded against your role's benchmarks (never the lobby), timeline review of your latest game, LP trend, session tracking
- **The climb system** — research-backed discipline: the 2-loss stop rule, champion-pool focus, and sample-aware "play more / ease off" coaching
- **Click any player** to scout their full profile; right-click for u.gg / op.gg / Porofessor
- **One-click Riot login, two ways** — *(a)* save each account's "Stay signed in" session and switch from the tray with no password stored, or *(b)* Profile → **⚡ Log in** to save a username+password (DPAPI-encrypted) and have Smiteless autofill the Riot login form for you. Both relaunch you straight into League; the password path survives logging out, the session path can't be captcha'd

Patch notes: tray → **Patch notes**, or [CHANGELOG.md](CHANGELOG.md).

## 🛠️ Building from source

```
git clone https://github.com/bobbyroylee/smiteless
pip install pillow pystray
python smiteless_main.py overlay      # or: widget / settings / profile
```

`dist\build.ps1` builds the frozen app; `dist\make-release.ps1 -Version X.Y.Z` cuts a release (PyInstaller + AHK-compiled tray/installer, Python 3.11+).
