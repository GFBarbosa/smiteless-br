# Smiteless UI — "Duskfall" design system (v1.0)

A from-scratch redesign of every Smiteless surface. The previous pass (Council
v0.9.1) unified a drifted palette but kept the same colors, type, and layout —
so it read as identical. Duskfall changes the things the eye actually keys on:
**hue of the ground, temperature of the accent, the typeface of numbers and
headers, and the shape language of cards.**

Implementation constraints this spec respects:

- Tk windows (settings, notes, profile chrome, widget) + PIL-rendered boards
  (smitecard). No web tech, no images-as-chrome, Windows-bundled fonts only.
- Everything themable flows from `core/smiteskin.py`. **No surface may declare
  a hex or a font family locally.**
- Behavior, hitmaps, and layout *logic* are untouched — this is a reskin with
  stronger bones, not a rewrite of interaction code.

---

## 1. Identity

| | Old (v0.9.1) | Duskfall |
|---|---|---|
| Ground | blue-grey near-black `#11131a` | **violet ink** `#0c0a13` |
| Accent | muted League gold `#c8aa6e` | **ember** `#ffb454` — hotter, brighter |
| Live/data accent | (none — gold did everything) | **arcane cyan** `#5ad1dc` |
| Display type | Segoe UI 8–13pt everywhere | **Bahnschrift** headers + numerals |
| Cards | flat `#171a24` rectangles | surfaces with **3px ember/state rails**, radius 10 |
| Brand mark | tiny gold `◆` | **✦ spark** + letterspaced BAHNSCHRIFT wordmark |

The one-line brief: *League client at dusk, lit by an ember.* Warm light on a
cold violet ground. Amber is identity and action; cyan is live telemetry; the
two never fight because they're used for different jobs.

## 2. Color tokens (canonical in `smiteskin.py`)

### Ground ramp (violet-ink, warm-shadowed)

| Token | Hex | Use |
|---|---|---|
| `VOID` | `#0c0a13` | window ground, board background |
| `SURFACE` | `#15121f` | cards, strips, panels |
| `RAISED` | `#1e1930` | buttons at rest, raised chips, expanded rows |
| `HOVER` | `#2a2342` | button hover/active, selection |
| `SUNKEN` | `#07060b` | entry wells, troughs, scrollbar channels |
| `LINE` | `#2b2444` | strong hairlines, card outlines |
| `LINE_SOFT` | `#1c1730` | subtle seams inside cards |

### Ink

| Token | Hex | Use |
|---|---|---|
| `TXT` | `#e8e3f4` | body text (cool white-violet) |
| `MUTED` | `#9a92b4` | secondary text |
| `FAINT` | `#5e5678` | tertiary/disabled, rules-with-labels |

### Accent + status

| Token | Hex | Use |
|---|---|---|
| `EMBER` | `#ffb454` | THE accent: brand, section headers, primary buttons, "me" markers |
| `EMBER_DEEP` | `#c77f2e` | ember's pressed/ured shade, large fills, rails on quiet cards |
| `ARC` | `#5ad1dc` | live telemetry: timers, tempo, win-prob, sparklines, "live" dots |
| `GOOD` | `#5fe0a0` | wins, TAKE verdicts, saved-ok |
| `BAD` | `#ff6478` | losses, danger, GIVE verdicts, dodge flags |
| `WARN` | `#ffd166` | caution, 50-50 verdicts, expiring key |
| `INFO` | `#8fa9ef` | links, neutral highlights, bullet dots |
| `MYSTIC` | `#b98bf5` | antiheal/utility tags, duo markers |

Rules:
- Ember ≠ wallpaper. It marks *identity and action* (brand row, section
  headers, the accent button, "you" in a lobby). Everything informational that
  updates live is `ARC`. Verdicts/states use `GOOD/BAD/WARN`.
- Never place `ARC` text on `EMBER` fills or vice-versa. On `EMBER` fills the
  ink is `VOID`.
- Win-rate coloring keeps its semantic ramp but re-anchored: <46% `BAD`,
  46–52% `MUTED`, 52–56% `GOOD`, >56% `ARC` (exceptional).

## 3. Typography

| Role | Family (Tk name / PIL file) | Notes |
|---|---|---|
| Display / headers / all numerals | `Bahnschrift` / `bahnschrift.ttf` | DIN-style, condensed-capable, ships Win10+. Letterspace headers by spacing chars is NOT required in Tk — size+weight carries it |
| Body / labels | `Segoe UI` / `segoeui.ttf`, bold `seguisb.ttf` | unchanged workhorse |
| Mono (keys, riot ids) | `Consolas` | unchanged |
| Symbols/CJK | Segoe UI Symbol / msyh etc. | keep the existing fallback logic |

Scale (pt for Tk, px for PIL roughly 1.33×):

- `H1` 16 Bahnschrift — window titles ("SMITELESS")
- `H2` 12 Bahnschrift — section headers, ALL-CAPS, `EMBER`
- `BODY` 10 Segoe UI — standard text (was 8–9: **body text gets bigger**)
- `SMALL` 9 Segoe UI — descriptions, `MUTED`
- `NUM` Bahnschrift at context size — every score, timer, win-rate, KDA

Graceful fallback: if Bahnschrift is missing (old Win10 LTSB), fall back to
"Segoe UI Semibold". `smiteskin.display()` / `smitecard.font()` own this.

## 4. Shape & space

- Radius: cards `R_CARD = 10`, chips are pills (`R_PILL = 999`), buttons `8`.
- **State rail**: cards carry a 3px left rail — `EMBER_DEEP` for identity
  cards, `ARC` for live cards, `GOOD/BAD/WARN` for verdict cards, `LINE` when
  quiet. This is the Duskfall signature; in Tk approximate with a 3px Frame
  packed on the card's left edge, in PIL draw it inside the rounded rect.
- Spacing tokens: `PAD = 14` (card inner), `GAP = 10` (between cards),
  `PAD_WIN = 18` (window gutters). Sections separated by labeled rules:
  `H2 header — hairline to the right edge` instead of floating gold labels.
- Buttons: flat `RAISED` fill, `TXT` ink, radius 8, hover `HOVER`; the ONE
  primary action per window is `EMBER` fill with `VOID` ink.
- Brand row (every window/board top-left): `✦` in `EMBER` + `SMITELESS` in
  Bahnschrift `TXT` + surface-specific suffix in `MUTED` (e.g. `✦ SMITELESS
  TEMPO`, `✦ SMITELESS SETTINGS`).

## 5. Per-surface specs

### 5.1 Champ-select panel (smitecard `render_cs_vertical`, docked by client)

- Ground `VOID`; the panel reads as a stack of railed `SURFACE` cards with
  `GAP` between them, not one continuous sheet.
- Top: brand row + phase chip (pill, `ARC` outline, e.g. `BAN PHASE`).
- Your champ card: ember rail, splash art kept, champ name in Bahnschrift 20,
  role chip pill next to it.
- Bans/draft band: its own card, `BAD` rail; recommended bans keep slash icons
  but numbers/percents move to Bahnschrift.
- Runes/build card: quiet rail; the import button is THE primary action —
  ember pill, `VOID` ink, `⇩ IMPORT RUNES + SUMMS`. AUTO chips become pills:
  on = `GOOD` outline + dot, off = `FAINT` outline.
- Scout rows: grade chips (S–F) become filled pills colored by grade
  (S/A `ARC`, B `GOOD`, C `MUTED`, D/F `BAD`); dodge read, when present, is a
  `WARN`/`BAD` railed card at the bottom, never inline text.

### 5.2 In-game board (smitecard `render_image`)

- Same information architecture; re-grounded on `VOID` with team columns as
  two railed cards: ally rail `ARC`, enemy rail `BAD`.
- All numerals (KDA, wr%, gold) → Bahnschrift; names keep Segoe/CJK logic.
- "Me" row: ember rail segment + name in `EMBER`.
- Win-prob / verdict strip: full-width card, rail + big Bahnschrift verdict
  (`TAKE` `GOOD` / `GIVE` `BAD` / `50-50` `WARN`), reasoning line in `MUTED`.

### 5.3 Tempo widget (smitewidget.py)

- Header strip: `✦ SMITELESS TEMPO` brand row on `SURFACE`, controls (♪, ?, ✕)
  as `MUTED`→`TXT` hover glyphs, `ARC` live-dot when a game is being read.
- Body on `VOID`; item rows keep kind-coloring but remapped: core `TXT`,
  insert `EMBER`, counter `BAD`, antiheal `MYSTIC`, boots `INFO`.
- Objective timers and countdowns in Bahnschrift `ARC` — the widget's numbers
  are its whole point, so they get the display face at +2pt.
- Verdict chip (TAKE/GIVE/50-50) as a filled pill in its status color.

### 5.4 Profile / home (smitecard `render_profile` + smiteprofile.py chrome)

- Header art stays; overlay a `VOID`→transparent gradient so the rank block
  sits on solid ground; rank + LP in Bahnschrift 24/16.
- Games list: each game a railed card (`GOOD`/`BAD` by result) with `GAP`
  between, replacing the flat zebra rows. Scores (0–100) in Bahnschrift pills.
- Sparklines/LP trend in `ARC`.
- Bottom chrome (Tk): search entry in `SUNKEN` well with pill radius illusion
  (flat is fine), `Search`/`Load more`/`Save card` as standard buttons,
  `⟳ Refresh` stays but as ember-ink text button; status line `MUTED` SMALL.

### 5.5 Settings (smitesettings.py)

- Window ground `VOID`, gutters `PAD_WIN`.
- Title: brand row (`✦ SMITELESS SETTINGS` H1) + version chip pill (`MUTED`).
- Every section header → labeled rule (H2 `EMBER` + `LINE_SOFT` hairline).
- Sliders: trough `SUNKEN`, active `EMBER`, value readout in Bahnschrift
  `ARC` (it's a number).
- Checkboxes: `selectcolor=SUNKEN`, text `BODY` 10 (bigger than the old 9).
- The two feature columns stay; each column becomes a `SURFACE` card with a
  quiet rail so the wall of checkboxes gets structure.
- `Save` = the primary ember button; `Reset`/`Close` standard.

### 5.6 Patch notes (smitenotes.py)

- Brand row header; body text card on `SURFACE` with quiet rail.
- Version headings (`## x.y.z`) in Bahnschrift `EMBER` 13 with a `LINE_SOFT`
  rule; bullets: dot `INFO`, body `BODY` 10, bold runs `TXT` semibold.

### 5.7 Overlay key bar (smiteoverlay.py)

- `SURFACE` strip with `WARN` rail (it only appears when the key needs work).
- `RIOT KEY` label → H2 treatment; key state chip: `GOOD` pill `…abcd set` /
  `BAD` pill `not set`. Buttons per §4; entry in `SUNKEN` Consolas.

### 5.8 Queue call (smitequeue.py)

- Borderless `SURFACE` card, 400px, docked off the League client's right edge; the
  left rail carries the verdict color (`GOOD` GO / `WARN` LAST ONE + WAIT / `BAD` STOP).
- Verdict word: Bahnschrift 21 bold in the verdict color. Instruction under it:
  Bahnschrift 13 `TXT`. The "why" wraps at `SMALL` in `MUTED`.
- Evidence rows are `· `-led at `SMALL`, colored by tone (`BAD` proven / `WARN` a
  lean / `GOOD` a good window). The basis line closes in `FAINT` 8.
- No-activate + topmost: it appears next to a client the user is clicking, and must
  never take the focus off it.

## 6. Legacy alias map (during migration)

`smiteskin.py` keeps the old names as aliases so untouched call-sites still
work: `BG→VOID`, `PANEL→SURFACE`, `SEP→LINE_SOFT`, `GOLD→EMBER`, `RED→BAD`,
`GREEN→GOOD`, `TEAL→ARC`, `BLUE→INFO`, `PURPLE→MYSTIC`, `BTN→RAISED`,
`BTN_HOVER→HOVER`, `ENTRY→SUNKEN`. New code should use the new names.

## 7. What "done" looks like

Open any window next to a v0.9.1 screenshot: the ground is visibly violet,
the accent visibly hotter, every number is in the DIN face, and cards have
rails and breathing room. If a surface still looks like the screenshot, it
isn't done.
