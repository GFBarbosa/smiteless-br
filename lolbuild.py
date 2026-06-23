#!/usr/bin/env python3
"""lolbuild.py — fast per-game LoL build card (op.gg data, decoded via ddragon).

Speed: ddragon static data is cached locally per-patch, so after the first run a
build card prints in ~1-2s.

Usage:
  python lolbuild.py                         # AUTO: read champ select from the running League client (LCU)
  python lolbuild.py Qiyana                  # manual champ, default role jungle
  python lolbuild.py Qiyana jungle           # manual champ + role
  python lolbuild.py Qiyana jungle Rengar    # + enemy jungler -> matchup note
  python lolbuild.py "Kha'Zix" jungle --tier gold
Roles: top jungle mid adc support
"""
import sys, os, json, time, ssl, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CACHE = os.path.expanduser("~/.claude/cache/ddragon")
LOCKFILES = [
    r"F:\Riot Games\League of Legends\lockfile",
    r"C:\Riot Games\League of Legends\lockfile",
    r"C:\Program Files\Riot Games\League of Legends\lockfile",
    r"D:\Riot Games\League of Legends\lockfile",
    os.path.expanduser(r"~/Riot Games/League of Legends/lockfile"),
]
ROLE = {"top":"top","jungle":"jungle","jg":"jungle","mid":"mid","middle":"mid",
        "adc":"adc","bot":"adc","bottom":"adc","sup":"support","support":"support","utility":"support"}

def http(url, headers=None, timeout=8, insecure=False, data=None):
    ctx = ssl._create_unverified_context() if insecure else None
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA}, data=data)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.load(r)


def _atomic_json(fp, data):
    """Write JSON atomically so an interrupted run can't leave a corrupt cache file."""
    tmp = f"{fp}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, fp)


def _ddragon_version():
    """Latest patch, cached ~6h so we skip the network call on every run, and fall
    back to the newest locally cached patch if we're offline."""
    vf = os.path.join(CACHE, "_version.json")
    try:
        c = json.load(open(vf, encoding="utf-8"))
        if time.time() - c.get("ts", 0) < 21600 and c.get("ver"):
            return c["ver"]
    except Exception:
        pass
    try:
        ver = http("https://ddragon.leagueoflegends.com/api/versions.json")[0]
        try:
            _atomic_json(vf, {"ver": ver, "ts": time.time()})
        except Exception:
            pass
        return ver
    except Exception:
        # offline: reuse the newest patch we've already cached
        cached = sorted(f[:-len("_champion.json")] for f in os.listdir(CACHE)
                        if f.endswith("_champion.json")) if os.path.isdir(CACHE) else []
        if cached:
            return cached[-1]
        raise

# ---------- ddragon (cached per patch) ----------
def ddragon():
    os.makedirs(CACHE, exist_ok=True)
    ver = _ddragon_version()
    def load(name):
        fp = os.path.join(CACHE, f"{ver}_{name}.json")
        if os.path.exists(fp):
            try:
                return json.load(open(fp, encoding="utf-8"))
            except Exception:
                pass  # corrupt cache file -> re-fetch below
        d = http(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/{name}.json")
        try:
            _atomic_json(fp, d)
        except Exception:
            pass
        return d
    items = {int(k): v["name"] for k, v in load("item")["data"].items()}
    rr = load("runesReforged"); runes = {}; trees = {}
    for s in rr:
        trees[s["id"]] = s["name"]
        for slot in s["slots"]:
            for r in slot["runes"]: runes[r["id"]] = r["name"]
    spells = {int(v["key"]): v["name"] for v in load("summoner")["data"].values()}
    champ = load("champion")["data"]
    def norm(x): return "".join(c for c in x.lower() if c.isalnum())
    name2id = {}; id2name = {}; id2key = {}; id2tags = {}
    for c in champ.values():
        cid = int(c["key"]); id2name[cid] = c["name"]; id2key[cid] = c["id"]
        id2tags[cid] = c.get("tags", [])
        name2id[norm(c["name"])] = cid; name2id[norm(c["id"])] = cid
    return dict(ver=ver, items=items, runes=runes, trees=trees, spells=spells,
                name2id=name2id, id2name=id2name, id2key=id2key, id2tags=id2tags, norm=norm)

# ---------- op.gg ----------
def opgg(cid, role, tier=None):
    url = f"https://lol-api-champion.op.gg/api/na/champions/ranked/{cid}/{role}"
    if tier: url += f"?tier={tier}"
    return http(url, headers={"User-Agent": UA, "Accept": "application/json"}).get("data", {})

# ---------- format ----------
def card(dd, cid, role, tier, enemy_cid=None):
    role = ROLE.get(role.lower(), role.lower())
    d = opgg(cid, role, tier)
    if not d or "summary" not in d:
        return f"No op.gg data for {dd['id2name'].get(cid, cid)} {role}."
    av = d["summary"]["average_stats"]
    name = dd["id2name"].get(cid, str(cid))
    tiername = {1:"S",2:"A",3:"B",4:"C",5:"D"}.get(av.get("tier"), av.get("tier"))
    out = []
    out.append(f"{name.upper()} - {role.upper()}   (op.gg {tier or 'Emerald+'}, patch {dd['ver']}"
               f" | WR {av['win_rate']*100:.1f}% | pick {av['pick_rate']*100:.1f}% | {tiername}-tier | {av['play']}g)")
    rp = max(d["runes"], key=lambda r: r["play"])
    pr, sr = rp["primary_rune_ids"], rp["secondary_rune_ids"]
    out.append(f"RUNES  {dd['trees'].get(rp['primary_page_id'])}: "
               + " / ".join(dd['runes'].get(x, x) for x in pr))
    shard = {5008:"Adaptive",5005:"AtkSpd",5007:"Haste",5011:"Health",5001:"HP-scale",5010:"MoveSpd",5013:"Tenacity"}
    out.append(f"       {dd['trees'].get(rp['secondary_page_id'])}: " + " / ".join(dd['runes'].get(x, x) for x in sr)
               + "   |  Shards: " + " / ".join(shard.get(x, str(x)) for x in rp["stat_mod_ids"]))
    ss = max(d["summoner_spells"], key=lambda x: x["play"])
    stt = max(d["starter_items"], key=lambda x: x["play"])
    out.append(f"SUMS   {' + '.join(dd['spells'].get(i) for i in ss['ids'])}"
               f"     START  {', '.join(dd['items'].get(i, str(i)) for i in stt['ids'])}")
    sk = max(d["skills"], key=lambda x: x["play"])
    sm = max(d["skill_masteries"], key=lambda x: x["play"])
    out.append(f"SKILL  max {' > '.join(sm['ids'])}   (lvl: {','.join(sk['order'][:6])})")
    core = max(d["core_items"], key=lambda x: x["play"])
    boots = max(d["boots"], key=lambda x: x["play"])
    out.append(f"CORE   {' > '.join(dd['items'].get(i, str(i)) for i in core['ids'])}   ({core['win']/core['play']*100:.0f}%)")
    out.append(f"BOOTS  {dd['items'].get(boots['ids'][0], boots['ids'][0])}")
    situ = sorted((x for x in d["last_items"] if x["play"] >= 150), key=lambda x: -x["win"]/x["play"])[:4]
    out.append("SITU   " + " / ".join(f"{dd['items'].get(s['ids'][0], s['ids'][0])} ({s['win']/s['play']*100:.0f}%)" for s in situ))
    if enemy_cid:
        cm = next((c for c in d.get("counters", []) if c["champion_id"] == enemy_cid), None)
        en = dd["id2name"].get(enemy_cid, enemy_cid)
        if cm and cm["play"] >= 20:
            wr = cm["win"]/cm["play"]*100
            tag = "FAVORED" if wr >= 51 else ("EVEN" if wr >= 49 else "UNFAVORED")
            out.append(f"VS {en.upper()}: {wr:.1f}% ({cm['play']}g) — {tag}")
        else:
            out.append(f"VS {en.upper()}: not enough matchup data on op.gg (play it standard).")
    return "\n".join(out)

def main():
    t0 = time.time()
    args = [a for a in sys.argv[1:]]
    tier = None
    if "--tier" in args:
        i = args.index("--tier"); tier = args[i+1]; del args[i:i+2]
    dd = ddragon()
    enemy_cid = None
    if not args:  # AUTO: champ select / loading screen / in-game
        import lolgame as lg
        info, err = lg.resolve(dd)
        if err:
            print(err); return
        cid, role = info["my"], info["pos"]
        src = info.get("source", "auto")
        enemies = ", ".join(dd["id2name"].get(c, c) for c, _ in info["enemies"]) or "none yet"
        if not role:  # loading screen with no cached role
            print(f"[{src}] you: {dd['id2name'].get(cid)} - role not cached "
                  f"(press Win+B during champ select to cache it; it's auto-detected in-game).\n"
                  f"enemies: {enemies}\nBuild card needs a role; the coach analysis below infers it.")
            return
        print(f"[{src}] you: {dd['id2name'].get(cid)} ({role}); enemies: {enemies}\n")
        print(card(dd, cid, role, tier))
    else:
        cid = dd["name2id"].get(dd["norm"](args[0]))
        if not cid:
            print(f"Unknown champ '{args[0]}'."); return
        role = args[1] if len(args) > 1 else "jungle"
        if len(args) > 2:
            enemy_cid = dd["name2id"].get(dd["norm"](args[2]))
        print(card(dd, cid, role, tier, enemy_cid))
    print(f"\n(pulled in {time.time()-t0:.1f}s)")

if __name__ == "__main__":
    main()
