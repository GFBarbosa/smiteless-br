# Smiteless — Patch Notes

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
