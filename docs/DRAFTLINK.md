# The Live Draft Link 🔗

In champ select, Smiteless posts **one URL into the lobby chat**. Anyone who clicks it —
including the four random teammates who will never install anything — lands on a live web
board of the current draft: both teams, bans, and per-seat **champion suggestions with
runes** for this exact game. They tap **"This is me"** on their seat and get pick + rune
cards that keep updating as the draft evolves. No app, no account, no refresh.

**Total monthly cost: $0.** The page is static hosting (GitHub Pages), the live data
channel is Firebase's free Spark tier, and all art/names load from Riot's public ddragon
CDN in the viewer's browser. Smiteless only uploads a few KB of champion/rune IDs per
champ select.

```
you (Smiteless) ──publishes draft──▶ Firebase RTDB (free) ──streams──▶ teammates' browsers
        └──posts ONE link in champ-select chat──▶ https://…github.io/smiteless/draft/#d=…
```

## One-time setup (~5 minutes)

The feature stays dormant until you give Smiteless a database to publish to.

### 1. Create a free Firebase Realtime Database

1. Go to [console.firebase.google.com](https://console.firebase.google.com) → **Create a
   project** (any name, e.g. `smiteless-draft`). Analytics off is fine.
2. In the left menu: **Build → Realtime Database → Create Database**. Pick the US region,
   start in **locked mode**.
3. Open the **Rules** tab and replace the rules with:

   ```json
   {
     "rules": {
       "drafts": {
         "$draft": {
           ".read": true,
           ".write": true,
           ".validate": "newData.hasChild('v') || newData.val() == null"
         }
       }
     }
   }
   ```

   Draft IDs are random and unguessable, the data is just champion IDs (nothing personal),
   and every draft is retired when champ select ends — open write on this one path is the
   price of running with zero servers and zero logins. Don't store anything else in this
   database.
4. Copy the database URL shown above the data tree — it looks like
   `https://smiteless-draft-default-rtdb.firebaseio.com`.

### 2. Paste it into Smiteless

Tray → **Settings** → **LIVE DRAFT LINK** → paste the URL → **Save + test**. The test
publishes a fake draft and opens the resulting page in your browser — if you see the demo
board go live, the whole pipeline works. The "Live draft link" checkbox under FEATURES
turns the chat post on/off.

### 3. (Repo owners only) hosting the page

The page itself is [`docs/draft/index.html`](draft/index.html), served by GitHub Pages:
repo **Settings → Pages → Deploy from a branch → `main` / `docs`**. If you fork this and
host your own copy, point the `draft_page` key in `~/.claude/smiteless_settings.json` at
your Pages URL.

## How it behaves

- Publishing starts when champ select opens and stops the moment it ends; the draft node
  is marked ended and deleted at the next lobby. Nothing runs between games.
- The link is posted **once** per champ select, after the first successful publish.
- Suggestions are the overlay's own pick brain (op.gg counters + comp fit) run for every
  seat — with **no mastery gate**, because these are for teammates whose champion pools
  are unknown. Your own overlay panel still applies your 12k-mastery climb guard.
- The viewer's browser streams changes over Firebase's SSE endpoint and falls back to
  7-second polling if streaming is blocked.
- Manual test any time: `python core\loldraft.py test`.

## Privacy

The published draft contains champion/rune/item IDs and role tags only — **no summoner
names, no PUUIDs, no ranks**. Enemy picks appear exactly as Riot exposes them in champ
select (locked champions only; Riot anonymizes enemy players there anyway).
