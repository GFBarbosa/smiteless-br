# Smiteless — working notes for Claude

A League of Legends companion (build + coach + scout + in-game overlays + the DraftBoard
web page). Windows, Python, Tk overlays + PIL-rendered boards. Private repo; **multiple
Claude sessions (local and cloud) edit it in parallel — read this before reworking shared
surfaces so we stop stepping on each other.**

## Releases — READ THIS FIRST
- **Never ask permission to release.** Don't say "want me to update?" — just do it when a
  batch is ready. (He hates being asked.)
- **Batch. One release per coherent chunk of work — NOT per commit or per micro-fix.**
  Commit freely; hold the release until it's a meaningful, self-contained unit. Shipping a
  release per tiny tweak is noise and burns real compute (each `make-release` runs a full
  PyInstaller freeze + installer build, minutes each).
- **Web-only changes do NOT need an app release.** `docs/draft/index.html` (the DraftBoard
  page) deploys to GitHub Pages on push — just commit + push, no `make-release`. Only cut an
  app release when the bundled Python/exe actually changed. Dev-only changes (dev tray) skip
  releasing too — say so.
- **How to release — TWO paths. A cloud session can release on its own; never claim a release
  "needs his Windows machine".**
  - *On his box:* `powershell -ExecutionPolicy Bypass -File dist\make-release.ps1 -Version X.Y.Z -Notes "..."`
  - *Anywhere else (cloud sessions — this is the one you want):* dispatch
    `.github/workflows/release.yml` with `{"version": "X.Y.Z"}` and `ref` = your working
    branch (GitHub MCP: `actions_run_trigger`, method `run_workflow`). It builds
    SmitelessSetup.exe on a **Windows runner**, fast-forwards `main` to your branch, tags, and
    publishes — ~4 minutes, no local toolchain. **Don't touch VERSION**; the workflow sets and
    commits it. Release notes are grepped out of the `## vX.Y.Z` CHANGELOG section.
  Either way the in-app updater reads **only** `/releases/latest` — old releases are pure
  history, leave them.
- **Verify the release before you call it done:** `/releases/latest` must show the new tag
  **and** a `SmitelessSetup.exe` asset. A release published without that asset is worse than
  no release — `smiteupdate.latest_release()` returns None and installed copies stop being
  offered *any* update, including the previous version.
- **New `core/`/`ui/` module? Add it to the `$hidden` list in `dist\build.ps1`** before you
  release. Its siblings are all in there; left out, PyInstaller can ship an exe that crashes
  on import — a release missing the very feature it's named for.
- **Never build on top of a live game — LOCAL path only.** `make-release` is a multi-minute
  PyInstaller freeze + installer build; running it while `tools\phasecheck.py` says
  GameStart/InProgress/Reconnect costs him FPS in the ranked game this whole project exists to
  win. Poll the phase and cut the release when he's out. Don't ask — just wait, then ship.
  The **cloud workflow runs on GitHub's hardware and costs him nothing** — never delay it for
  a live game, and never make him wait for a release you could have shipped while he played.
- **Version numbering:** bump +0.0.1 (0.9.40 → 0.9.41). Never jump to 1.0 without his say-so.
- **CHANGELOG.md first:** add an entry (top of file) before you release — it feeds the
  in-app Patch Notes window. Each release needs ≥1 change the user can SEE in a minute;
  invisible-only correctness batches read as "paid for nothing."

## Verify before you ship
- Health: `python tools\selftest.py` (also runs the tag + glyph guards).
- Guards that must stay green: `tools\tagcheck.py` (player-tag spec, docs/TAGS.md) and
  `tools\glyphcheck.py` (tofu tripwire — no symbol glyph drawn through a text-blind font).
- UI changes: render with real data and LOOK at the PNG (a color swap alone reads as "no
  change"). Overlay changes go through the real window path + a proven Tk pattern (no novel
  Win32 painting); un-triggerable surfaces ship with a diagnostic log.
- Full how-to lives in the `verify` skill under `.claude/skills/verify`.

## Invariants that keep getting stomped — don't revert these
- **The DraftBoard in-game scoreboard is HORIZONTAL: the two teams sit side by side**
  (`.scoutcols` grid in `docs/draft/index.html`), collapsing to one column on phones. A
  prior session reverted this to a full-width top-down stack "so columns align" — the user
  explicitly wants side-by-side. Leave it.
- **Player grade = in-game performance only** (`lolprofile._grade_game` lineage). Never rank,
  W/L, or cross-account peeking.
- **Tags cite their evidence** (docs/TAGS.md): THIS-GAME reads separate from ACCOUNT reads;
  `smurf?` needs account-level evidence and renders as an inference. Don't let a Morgana
  one-trick playing Brand read as a smurf.
- **DraftBoard link is short** (`…/draft/#d=<id>`, no `&db=` blob): the page bakes in the DB
  host — `DEFAULT_DB` in `docs/draft/index.html` ⇄ `loldraft._DEFAULT_PAGE_DB`. Keep in sync.

## North star
Every change should speed the climb to Diamond. Cut anything that just "covers the game"
without shortening the climb. Quality over coverage — 6 things done right beats 12 half-done.
