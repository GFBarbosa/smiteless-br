#!/usr/bin/env python3
"""lolaccounts.py - one-click Riot login (the account switcher) for Smiteless.

No passwords, ever. The Riot Client already keeps a "Stay signed in" session on disk
(Riot Client\\Data - the cookie yaml - plus Config\\RiotClientSettings.yaml); this module
snapshots that whole login state per account and swaps it back in on demand - the same
approach as TcNo-Acc-Switcher / RiotSwitcher. Password login through the client's local
API has been dead since Riot added captcha, so session-swapping is THE way this is done.
Snapshots are DPAPI-encrypted (CryptProtectData, user-scoped): the blobs in
~/.claude/smiteless_accounts are unreadable to anything but this Windows user.

Setup is once per account: log in with "Stay signed in" TICKED, then "Save current login".
"Log in" then: refuses if a game is running, closes the Riot/League clients (gracefully,
then hard), re-snapshots the account being left (Riot rotates session cookies every use,
so the stored blob would go stale otherwise), swaps the files, and relaunches League.
"""
import os, sys, io, json, time, ctypes, shutil, zipfile, subprocess
from ctypes import wintypes

_LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
RC_ROOT = os.path.join(_LOCAL, "Riot Games", "Riot Client")
DATA_DIR = os.path.join(RC_ROOT, "Data")
CONFIG_YAML = os.path.join(RC_ROOT, "Config", "RiotClientSettings.yaml")
INSTALLS = r"C:\ProgramData\Riot Games\RiotClientInstalls.json"
STORE = os.path.expanduser("~/.claude/smiteless_accounts")
INDEX = os.path.join(STORE, "index.json")

# What must die before the swap (TcNo's list + the League client + crash handlers).
KILL = ["RiotClientServices.exe", "RiotClientUx.exe", "RiotClientUxRender.exe",
        "Riot Client.exe", "LeagueClient.exe", "LeagueClientUx.exe",
        "LeagueClientUxRender.exe", "LeagueCrashHandler.exe", "RiotClientCrashHandler.exe"]
INGAME_EXE = "League of Legends.exe"
CREATE_NO_WINDOW = 0x08000000


# ---------- DPAPI (user-scoped encrypt/decrypt, stdlib ctypes) ----------
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, encrypt):
    buf = ctypes.create_string_buffer(data, len(data))
    inb, out = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI " + ("encrypt" if encrypt else "decrypt") + " failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# ---------- the index (names + which one is live) ----------
def _load_index():
    try:
        d = json.load(open(INDEX, encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("accounts"), list):
            return d
    except Exception:
        pass
    return {"active": "", "accounts": []}


def _save_index(idx):
    os.makedirs(STORE, exist_ok=True)
    tmp = f"{INDEX}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=2, ensure_ascii=False)  # AHK reads names verbatim (UTF-8)
    os.replace(tmp, INDEX)


def _slug(name):
    s = "".join(c if c.isalnum() else "_" for c in name.strip().lower()).strip("_")
    return s or "account"


def _blob_path(name):
    return os.path.join(STORE, _slug(name) + ".bin")


def list_accounts():
    """[{name, riot_id, saved, active}] in saved order."""
    idx = _load_index()
    return [{**a, "active": a.get("name") == idx.get("active")} for a in idx["accounts"]
            if os.path.exists(_blob_path(a.get("name", "")))]


# ---------- snapshot / restore of the client's login state ----------
def _snapshot_bytes():
    """Zip (in memory) of everything under Riot Client\\Data + Config\\RiotClientSettings.yaml,
    arcnames relative to the Riot Client root."""
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(DATA_DIR):
            for fn in files:
                p = os.path.join(root, fn)
                z.write(p, os.path.relpath(p, RC_ROOT).replace("\\", "/"))
        if os.path.exists(CONFIG_YAML):
            z.write(CONFIG_YAML, os.path.relpath(CONFIG_YAML, RC_ROOT).replace("\\", "/"))
    return bio.getvalue()


def _zip_has_session(zbytes):
    """True if the snapshot holds an actual persistent login (the ssid session cookie),
    not just a logged-out client's device id."""
    try:
        with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
            for n in z.namelist():
                if n.startswith("Data/") and n.lower().endswith("privatesettings.yaml"):
                    if b"ssid" in z.read(n):
                        return True
    except Exception:
        pass
    return False


def _restore(zbytes):
    # wipe Data\ then lay the snapshot back down (Config yaml overwrites in place)
    if os.path.isdir(DATA_DIR):
        for e in os.listdir(DATA_DIR):
            p = os.path.join(DATA_DIR, e)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        for n in z.namelist():
            parts = n.replace("\\", "/").split("/")
            if n.endswith("/") or any(p in ("", "..") for p in parts) or ":" in n:
                continue                       # zip-slip guard; our own zips are always clean
            dest = os.path.join(RC_ROOT, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(z.read(n))


# ---------- processes ----------
def _running(names):
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, creationflags=CREATE_NO_WINDOW, timeout=15).stdout
    except Exception:
        return set()
    low = {n.lower() for n in names}
    have = set()
    for ln in out.splitlines():
        exe = ln.split('","')[0].strip('"').lower()
        if exe in low:
            have.add(exe)
    return have


def _taskkill(names, force):
    for n in names:
        cmd = ["taskkill", "/IM", n] + (["/F"] if force else [])
        subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=15)


def _close_clients():
    """Ask nicely first (lets the client flush the freshest cookies to disk), then kill."""
    if not _running(KILL):
        return
    _taskkill(KILL, force=False)
    for _ in range(10):                        # up to ~5s graceful
        time.sleep(0.5)
        if not _running(KILL):
            return
    _taskkill(KILL, force=True)
    for _ in range(12):                        # up to ~6s forced
        time.sleep(0.5)
        if not _running(KILL):
            return
    raise RuntimeError("Couldn't close the Riot Client - close it manually and retry.")


def riot_client_exe():
    """RiotClientServices.exe, from Riot's own install registry (authoritative), else a scan."""
    try:
        d = json.load(open(INSTALLS, encoding="utf-8"))
        for k in ("rc_default", "rc_live", "rc_beta"):
            p = d.get(k)
            if p and os.path.exists(p):
                return p
        for p in (d.get("associated_client") or {}).values():
            if p and os.path.exists(p):
                return p
    except Exception:
        pass
    for drv in "CDEFGH":
        p = f"{drv}:\\Riot Games\\Riot Client\\RiotClientServices.exe"
        if os.path.exists(p):
            return p
    raise RuntimeError("Riot Client not found (RiotClientInstalls.json missing?).")


# ---------- the verbs ----------
def save_current(name):
    """Snapshot the CURRENT client login under `name`. Needs a 'Stay signed in' session."""
    name = (name or "").strip()
    if not name:
        raise RuntimeError("Give the account a name.")
    z = _snapshot_bytes()
    if not _zip_has_session(z):
        raise RuntimeError('No saved session found. In the Riot Client, log OUT, then log '
                           'back in with "Stay signed in" TICKED - then save again.')
    riot_id = ""
    try:                                       # best effort: tag with the logged-in Riot ID
        import lolgame
        cur = lolgame.current_account()
        if cur:
            riot_id = cur[1]
    except Exception:
        pass
    os.makedirs(STORE, exist_ok=True)
    with open(_blob_path(name), "wb") as f:
        f.write(_dpapi(z, encrypt=True))
    idx = _load_index()
    idx["accounts"] = [a for a in idx["accounts"] if _slug(a.get("name", "")) != _slug(name)]
    idx["accounts"].append({"name": name, "riot_id": riot_id, "saved": int(time.time())})
    idx["active"] = name
    _save_index(idx)
    if riot_id:
        try:                                   # pool this account's mastery like any other
            import lolscout as ls
            ls.save_accounts([a["riot_id"] for a in ls.load_accounts()] + [riot_id])
        except Exception:
            pass
    return riot_id


def remove(name):
    idx = _load_index()
    idx["accounts"] = [a for a in idx["accounts"] if _slug(a.get("name", "")) != _slug(name)]
    if _slug(idx.get("active", "")) == _slug(name):
        idx["active"] = ""
    _save_index(idx)
    try:
        os.remove(_blob_path(name))
    except FileNotFoundError:
        pass


def switch(name, on_status=None):
    """Close the clients, swap in `name`'s saved session, relaunch League."""
    say = on_status or (lambda s: None)
    idx = _load_index()
    match = [a for a in idx["accounts"] if _slug(a.get("name", "")) == _slug(name)]
    if not match or not os.path.exists(_blob_path(name)):
        raise RuntimeError(f'No saved login called "{name}".')
    blob = _dpapi(open(_blob_path(match[0]["name"]), "rb").read(), encrypt=False)
    if _running([INGAME_EXE]):
        raise RuntimeError("A game is running - finish it before switching accounts.")
    exe = riot_client_exe()
    say("closing Riot Client…")
    _close_clients()
    active = idx.get("active", "")
    if active and _slug(active) != _slug(name):
        try:                                   # cookies rotate every session: keep the account
            z = _snapshot_bytes()              # we're LEAVING fresh, or its blob goes stale
            if _zip_has_session(z):
                with open(_blob_path(active), "wb") as f:
                    f.write(_dpapi(z, encrypt=True))
                for a in idx["accounts"]:
                    if _slug(a.get("name", "")) == _slug(active):
                        a["saved"] = int(time.time())
        except Exception:
            pass
    say("swapping login…")
    _restore(blob)
    idx["active"] = match[0]["name"]
    _save_index(idx)
    say("launching League…")
    subprocess.Popen([exe, "--launch-product=league_of_legends", "--launch-patchline=live"],
                     creationflags=CREATE_NO_WINDOW)


# ---------- CLI (smiteless_main routes `login <name>` / `accounts ...` here) ----------
def _msgbox(text, flags=0x10):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, "Smiteless", flags | 0x40000)  # topmost
    except Exception:
        pass


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = (args[0].lower() if args else "list")
    rest = " ".join(args[1:]).strip().strip('"')
    try:
        if cmd in ("login", "switch"):
            switch(rest)
        elif cmd == "save":
            save_current(rest)
        elif cmd == "remove":
            remove(rest)
        else:
            for a in list_accounts():
                print(("* " if a["active"] else "  ") + a["name"] +
                      (f'  ({a.get("riot_id")})' if a.get("riot_id") else ""))
    except Exception as e:                     # tray runs this windowless -> surface it
        _msgbox(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
