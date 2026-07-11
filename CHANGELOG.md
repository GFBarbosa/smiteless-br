# Smiteless — Patch Notes

## v0.2.88
- **THE disappearing-widget bug, actually found.** Right-click anywhere on the widget was bound to *close it* — in a game where right-click is the move command. Any move-click that drifted onto the widget silently killed it, which is why it "randomly" vanished for months no matter how the game-over detection was tuned. Right-click (and Escape) no longer close the widget — only the ✕ button does.
- **Three more layers so it can never come back:** (1) while the actual game process (League of Legends.exe) is running the widget is **immortal** — it ignores client-API blips entirely; (2) it re-asserts its always-on-top status every few seconds so the game window can't bury it; (3) every close now writes its reason to a log (`~/.claude/cache/smiteless_widget.log`) — if it ever disappears again, we'll know exactly why instead of guessing.
- **Bans are now ranked by expected value, ending the "always ban Zac" loop.** A ban's worth = how hard the champ counters your team **×** how likely you are to actually face them (their live pick rate in that role). A brutal-but-niche 4%-pick counter now ranks below a popular counter you'll meet every third game. Multi-lane threats still stack, and everything else (fallbacks, auto-ban) rides the same list.

## v0.2.87
- **Fixed the in-game widget randomly disappearing mid-game.** The "is the game over?" check counted poll ticks but was tuned as if ticks were 5s when they're ~1s — so a **4-second** client hiccup (a teamfight lagging the client and the live-data port at once) could close the widget mid-game. It's now wall-clock based: ~25s of confirmed non-game (or 3 min of unreachable client) before it even considers closing, and it always asks the live game directly first — if the game answers, the widget stays.
- **Fixed the voice callouts being completely silent in the installed app.** The speech renderer worked in development but died instantly in the shipped (windowed) build due to a Windows process-handle quirk — so no WAVs were ever created. Now fixed and verified under the same condition.
- **"Tempo online."** — the widget now says a short hello when it first picks up your game, so you know immediately that audio is working instead of discovering silence at first drake.

## v0.2.86
- **The Tempo engine now talks.** Short spoken callouts fire exactly when a window opens: **"Base now."**, **"Rotate to dragon."** (per-objective), **"Take it — you win this fight."**, **"Give it — trade elsewhere."**, **"Fifty fifty — only with vision."**, **"Force now — numbers advantage."** Voiced by Windows' built-in speech engine — free, offline, rendered once to WAV and cached, played at your existing widget volume. It only speaks on a *phase change* (never repeats, 6s global cooldown, anti-flap guard), the in-game ♪ mute button silences it along with the drake chime, and there's a separate "Tempo voice callouts" toggle in Settings.

## v0.2.85
- **Ban suggestions now consider the whole team's hovers, not just yours.** GOOD BANS aggregates the counters of every champ your team is hovering or has locked (including you) and ranks enemy champs by total threat to the draft — a champ that beats two of your lanes now outranks one that only edges yours, so the ban adapts as teammates hover instead of always showing your champ's #1 counter. The shown % is the most-countered teammate's win rate into that champ. Falls back to your champ's counters, then to the meta ban list, if there's nothing to aggregate. (Auto-ban uses the same improved list.)

## v0.2.84
- **THE TEMPO ENGINE.** The in-game widget now runs a live objective-setup director — the single highest-leverage macro system in the game, built on real research (8M-game Diamond+ study: 1 drake at even gold = +8% win rate, 2 = +16.9%, full grubs = +11%, and the dragon-soul team wins ~85–90% of games). Games are decided in the ~90 seconds *before* each objective, and now that window is scheduled for you:
  - **FARM window** — how long you can safely farm, with your exact recall-by and arrive-by deadlines counted down, walked back from the next spawn using your **live movement speed**, recall time and homeguard.
  - **BASE window** — the last moment to recall so you arrive 30s early with items.
  - **ROTATE** — when to start walking, and what setup to do (pit ward + river control).
  - **TAKE / GIVE / 50-50 verdict at the spawn** — computed from **death timers** (the real per-level respawn formula, including whether a dead enemy respawns *and walks back* in time to fight), **item gold** and **XP-as-gold** for all ten players. If you win the fight, it says take; if you don't, it names the trade to make instead. It never lets you coinflip blind.
  - **FORCE windows** — the moment an enemy dies with a long respawn, it tells you the numbers (5v4 for 23s) and to cash the advantage.
  - **SOUL POINT escalation** — at 3 drakes either side, the next drake is flagged as the ~85–90% game-decider it is.
  - **Elder tracking** — the objective timers now roll over to Elder after the 4th elemental (6:00 spawn/respawn), which they previously just dropped.
  - Toggle in Settings ("Tempo coach"). Every game constant verified against the wiki this week: baron 20:00, grubs 8:00 one-spawn, herald 15:00–19:45, drake 5:00/5:00, elder 6:00, the full death-timer table, recall 8.5s, homeguard 80%→150%.

## v0.2.83
- **"Play more / ease off" champ advice now uses real statistics.** It no longer crowns a 3-0 champ your best pick. Champs are ranked by a **Wilson score** — a confidence-adjusted win rate that discounts small samples so a wide 3-0 can't beat a tight 40-25 — blended with **how well you actually play the champ** (your average game score on it), and a champ needs a real sample (5+ games) before it can drive advice. So a proven main beats a lucky streak; "ease off" only fires when it's statistically confident a non-main is a loser (never off a 4-game fluke); and a champ you *main* on a rough patch is still flagged as a slump, not a pick problem. Each suggestion now shows the games it rests on (e.g. "play more Graves 61% (40g)"). The season-wide version also factors in your performance now, not just W/L.

## v0.2.82
- **Pick-order swap now has a simple "Accept any" mode.** In **Settings → Auto pick-order swap**, pick **Accept any** to just auto-accept every incoming pick-order swap request — no direction, no asking. (First pick / Last pick are still there if you want Smiteless to actively work toward an end of the order.)

## v0.2.81
- **Auto pick-order swap (counter-pick automation).** New in **Settings → Auto pick-order swap**: choose **Last pick** and Smiteless works your spot in the pick order as late as possible so you can counter-pick — it accepts a teammate's swap offer that moves you later, and requests one otherwise. **First pick** does the opposite (swap early to lock a contested champ). Off by default. (This is the pick-order swap; the v0.2.80 role swap is a separate setting.)

## v0.2.80
- **Auto-accept role swaps.** New in **Settings → Auto-accept role swap**: check the role(s) you're happy to play. When a teammate offers a role (position) swap in champ select that would put you on one of them, Smiteless accepts it for you. It **only ever moves you ONTO a checked role, never off one** — so a jungle main who got autofilled support auto-takes the jungle swap, but never gets swapped off jungle. None checked = off. (This is the assigned-lane swap, not a champion trade.)

## v0.2.79
- **The player grade now reads how you actually PLAY, not your win/loss.** It scores each of your recent games against your role's benchmarks — CS/min, kill participation, damage share, deaths, vision (the same engine as your post-game review) — and averages them. Win rate is only a light tie-breaker now.
- **Why this matters:** if you're a strong player grinding on a low/off-role account, or just lost a few playing off-champs, your fundamentals still show through — you'll grade a solid **B**, not a bogus **F**, even mid-losing-streak. It figures out your skill from your gameplay, not from your account. Meanwhile someone who's genuinely inting (bad CS, no participation, feeding) still grades low even if they got carried to a win.
- (No account-peeking — the grade is read purely from the games in front of it. Detailed per-game stats build up as your recent matches get scanned; until then it falls back to the old win-rate + KDA read.)

## v0.2.78
- **Ban ideas (before you pick) are now live op.gg data**, not a hardcoded list — the highest win-rate champs in YOUR role this patch. No more banning off-meta champs.
- **Player grade is now a real-stats skill read.** It's driven by win rate (your season ranked W/L when available — a big sample), with KDA and current form as supporting factors. Rank tier is ignored, so a Silver on a 65% climb grades higher than a Diamond who's feeding.
- **New GOOD PLAYER tag** on any player graded S or A — spot the carries (and carry threats) at a glance.
- **Gank ratings are now purely champ-vs-champ matchup** (plus your kit and live game state). Player form/skill no longer muddies the lane read — that's what the grade + GOOD PLAYER tag are for now.

## v0.2.77
- **Auto-ban.** New **AUTO** toggle next to GOOD BANS in champ select (also in Settings). When on, it locks the top recommended ban on your ban turn — and never bans an already-banned champ or one a teammate is hovering.
- **Ban ideas now show during the ban phase.** Since you ban before you pick, GOOD BANS now shows high-priority solo-queue bans when you don't have a champ yet (instead of "hover your champ for ban ideas"); once you hover, it switches to your champ's hardest counters.
- **QoL:** the current version number now shows in the Settings header.

## v0.2.76
- **"Good this game" now populates the moment champ select opens** — you no longer have to hover a champ (or wait for enemies to lock) to see it. It shows your mastery-5+ champs for your assigned role right away, and refines as enemies lock in.

## v0.2.75
- **The scout now loads everyone at once.** All 10 players are scouted in parallel instead of one at a time, so the board fills in roughly as fast as a single player used to take (~10× quicker) instead of trickling in. (Allies are also prioritized first.)

## v0.2.74
- **Rune sets now switch instantly.** Clicking one of the 3 rune-set tabs in champ select used to lag up to ~2 seconds before it updated — now it's immediate.
- **Each rune set carries its own summoners.** Picking a set now also shows (and imports) the summoner spells that go with it, not just the runes.

## v0.2.73
- **Removed the gank-tuning dials.** The "streak influence", "gank decisiveness (threshold)", and "champ kit in gank rating" settings are gone — they caused more confusion than help. The gank ratings now always use the tuned defaults, and any custom values you'd set are reset back to default.

## v0.2.72
- **Favourite picks now use a dropdown.** In Settings, pick a champ from a searchable dropdown (type to filter), choose a role (or "any"), and hit **+ Add** — no more typing names by hand. Your list shows below with **Remove** and **↑/↓** to set priority order.

## v0.2.71
- **Game plan now shows in champ select too.** As soon as the enemy team locks in (draft), the docked champ-select panel shows the same GAME PLAN box — read their comp and plan your win condition before the game even starts.
- **Player grades in the queue read.** The in-game winners/losers-queue chip now also shows each team's average letter grade (e.g. "WINNERS QUEUE 80% vs 30% · grades S vs F") — a KDA/form-based second opinion next to the win-rate read.

## v0.2.70
- **Post-game review on your latest game.** Your most recent game now gets a short, data-driven review pulled from Riot's match timeline: where you fell behind vs your laner (gold@10/@14), your CS at 10:00 vs benchmark, and your worst death window. It's rule-based — no AI, no tokens, no waiting — and shows up with that game's tips in your profile.

## v0.2.69
- **Auto game-plan card.** The in-game board now shows a "GAME PLAN" box: 2-3 blunt win conditions read from both comps — the enemy's damage split (rush armor/MR), whether they lack a frontline (dive their carries), and how much engage each side has (respect all-ins vs play for picks).
- **First scuttle timer.** The in-game widget's objective timers now include the first Rift Scuttler (2:55) — the early jungle tempo anchor, with the usual soon/urgent cues.

## v0.2.68
- **Recall / power-spike coach.** The in-game widget now reads your live gold + items and tells you when to back for your next spike: **"BACK now → finish Trinity (spike)"** when you can afford it, **"wait ~200g → …"** when you're close, or how far off you are otherwise. It subtracts components you already hold, so it's the real cost to *finish* the item — no more backing for a longsword when 8 seconds of farm gets you a whole item.

## v0.2.67
- **"Good this game" now only suggests champs you're mastery 5+ on** (mastery 7+ first). It won't recommend a champ you've barely touched — if none of the role-appropriate picks are ones you're M5+ on, it just says so instead of guessing. Pooled across all your accounts, same as before. (If the client can't report your mastery, it falls back to the old meta suggestions rather than showing nothing.)

## v0.2.66
- **Mute the drake chime mid-game.** The in-game widget now has a **♪** button in its header — click it to silence the 45/30/15s drake cues for the rest of the game (e.g. when your jungler is never going to contest it). It shows a struck-through red note while muted; click again to turn it back on. Resets each game, and Settings still has the permanent on/off.

## v0.2.65
- **Fixed the lane tip showing a raw "401 authentication" error.** A transient auth blip from the AI tip generator was being treated as the tip text and cached, so it showed every game. Those errors are now detected and never shown or cached, poisoned cached tips self-heal, and a bad tip just quietly regenerates next game.

## v0.2.64
- **Player rating is now about how you're *playing*, not your rank.** The S–F grade is driven by your recent win rate, KDA (are you carrying or inting), and hot/cold streak — rank is ignored entirely. A Silver stomping 20/0 game after game shows up as a gold **S** God-Mode player; a Diamond who's been feeding is a black-hole **F**.

## v0.2.63
- **Player rating is clearer.** The S–F grade now sits right next to each player's name (so it's obvious it's rating the player), the bottom legend spells out what it means, and it no longer collides with the duo/premade dot.

## v0.2.62
- **Player ratings on the in-game board.** Every player now gets a grade (S–F) from their rank, recent form, and comfort on their champ. A smurf/sicko lights up with a **gold glowing banner and an S**; someone tanking or way out of their depth goes **dark red with an F** — spot the carry and the griefer at a glance, on both teams.
- **Fixed the Flash key reverting to D.** Settings are now saved by merging onto the existing file, so changing one setting can never quietly reset another (Flash-on-F now sticks).

## v0.2.61
- **The champ-select panel now appears as soon as champ select opens** — it used to stay hidden until you hovered a champion. Right away it shows your assigned role, your team's roles, bans, and suggested picks; runes/build fill in once you hover.

## v0.2.60
- **"Good this game" now pools familiarity across all your accounts.** It remembers each account you log into and combines your champion mastery across your main and smurfs, so a champ you main on one account counts as familiar on the others. Manage the list in **Settings → Your accounts** (add smurfs you haven't logged into recently by Riot ID).

## v0.2.59
- **"Good this game" now factors in champs you actually play.** It reads your champion mastery from the client and surfaces picks you're familiar with first, so it won't tell you to first-time some champ you've never touched. If you have too few known picks for the role, it still fills in with strong meta options.

## v0.2.58
- **Click a "Good this game" face to hover it** in champ select. It selects (hovers) the champ for you — it never locks — and the panel updates to that champ's runes and build. Handy for trying suggestions quickly.

## v0.2.57
- **This page.** Added a **Patch notes** window (right-click the tray → Patch notes) so you can see what changed each update. It shows the notes for your installed version and pulls the very latest from GitHub when you're online.

## v0.2.56
- Fixed the **Deeplol** right-click link. It was using the wrong region code, so Deeplol said the account didn't exist. Now it opens the profile correctly, like the other sites.

## v0.2.55
- **Rune-set picker in champ select.** op.gg often lists more than one good rune page — the panel now shows small tabs (e.g. `1 · 54%  2 · 49%`). Click one to switch which runes are shown, and Import / auto-import writes that set.
- **Favourite picks.** Set an ordered list of your go-to champs in Settings → Favourite Picks (add a role like `Kha'Zix, jungle` to limit it to that role). In champ select the panel shows your top still-open picks in priority order. Recommend-only — it never hovers or locks for you.
- **Fixed the ⬜ square symbols** on the overlay (the `★ gank` chip, the dodge banner, the coach lines, and the ✓ marks) — they render properly now.
- **Better duo detection.** If the first player scan misses someone (a rate-limit hiccup), it now re-checks a little later and fills in any duo/premade markers it missed.
- **Profile window closes on its own** when you enter champ select, so the champ-select panel and in-game overlay take over cleanly.

## v0.2.54
- **Refresh button on your profile** — force a fresh pull when a just-finished game hasn't shown up yet.
- **Right-click any player's face** for a menu: open them on u.gg, op.gg, League of Graphs, Deeplol, or Porofessor (their live game), or copy their name. Left-click still opens their Smiteless profile.

## v0.2.53
- **Auto-import toggle** sits right next to the runes/summoners, so you can flip it in champ select.
- **Live gank sides.** Someone's always tagged the strong side and someone the weak side, and it shifts as the game goes on (deaths, level leads).

## v0.2.52
- No more blank "claude" terminal flashing on the loading screen.
- Champ banners now auto-focus the champion's face instead of a random slice of the splash art.
- More reliable jungle tracker.

## v0.2.51
- Rebuilt the jungle tracker so it reports a state every tick instead of going blank between events.
