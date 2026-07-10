# Smiteless — Patch Notes

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
