#!/usr/bin/env python3
"""lolcreds.py - saved Riot logins with one-click autofill (the password path).

The session-swap switcher (lolaccounts.py) breaks the moment you click "Sign out" in the
client - Riot revokes the token server-side, so the saved cookie is a corpse. This is the
other approach: store username+password (DPAPI-encrypted, user-scoped, same as the sessions)
and, on one click, bring up the Riot login window and put the credentials straight into its
fields. A fresh login can still hit a Riot captcha / MFA email that NOTHING can auto-skip -
that's Riot's risk engine, not us - but on a stable home machine it's usually clean.

Fields are located and focused via UI Automation (the Riot login is a Chromium page - UIA
reads its tree); the text is injected as keystrokes (Chromium blocks programmatic SetValue on
password inputs). If UIA isn't available it falls back to a blind fill of the focused field.
No clipboard is used, so nothing leaks there. We never tick "Stay signed in" for you.
"""
import os, sys, json, time, ctypes, subprocess
from ctypes import wintypes

STORE = os.path.expanduser("~/.claude/smiteless_logins.bin")
INSTALLS = r"C:\ProgramData\Riot Games\RiotClientInstalls.json"
CREATE_NO_WINDOW = 0x08000000
LEAGUE_UX = ("LeagueClientUx.exe", "LeagueClient.exe", "League of Legends.exe")


# ---------- DPAPI (user-scoped, stdlib ctypes) ----------
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, encrypt):
    buf = ctypes.create_string_buffer(data, len(data))
    inb, out = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# ---------- the store: one encrypted blob = [{name, username, password}] ----------
def _read():
    try:
        return json.loads(_dpapi(open(STORE, "rb").read(), False).decode("utf-8"))
    except Exception:
        return []


def _write(items):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    blob = _dpapi(json.dumps(items).encode("utf-8"), True)
    tmp = f"{STORE}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, STORE)


def names():
    """Just the account labels (for menus) - no secrets decrypted into anyone's hands."""
    return [i.get("name", "") for i in _read() if i.get("name")]


def get(name):
    for i in _read():
        if i.get("name", "").lower() == (name or "").lower():
            return i
    return None


def upsert(name, username, password):
    name = (name or "").strip()
    if not name or not (username or "").strip() or not password:
        raise RuntimeError("Name, username and password are all required.")
    items = [i for i in _read() if i.get("name", "").lower() != name.lower()]
    items.append({"name": name, "username": username.strip(), "password": password})
    _write(items)


def remove(name):
    _write([i for i in _read() if i.get("name", "").lower() != (name or "").lower()])


# ---------- keystroke injection (SendInput, unicode) ----------
_PUL = ctypes.POINTER(ctypes.c_ulong)


class _KBD(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _PUL)]


class _MOUSE(ctypes.Structure):                # only here so the union is the true INPUT size
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", _PUL)]


class _IU(ctypes.Union):
    _fields_ = [("ki", _KBD), ("mi", _MOUSE)]   # sizeof must match Win32 INPUT (40 on x64)


class _INP(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _IU)]


_KEYUP, _UNICODE, _KBDINPUT = 0x0002, 0x0004, 1
VK_TAB, VK_RET, VK_CTRL, VK_A = 0x09, 0x0D, 0x11, 0x41


def _send(items):
    arr = (_INP * len(items))(*items)
    ctypes.windll.user32.SendInput(len(items), arr, ctypes.sizeof(_INP))


def _ki(vk=0, scan=0, flags=0):
    return _INP(_KBDINPUT, _IU(ki=_KBD(vk, scan, flags, 0, None)))


def _type(text):
    ins = []
    for ch in text:
        c = ord(ch)
        ins += [_ki(0, c, _UNICODE), _ki(0, c, _UNICODE | _KEYUP)]
    if ins:
        _send(ins)


def _tap(vk):
    _send([_ki(vk), _ki(vk, flags=_KEYUP)])


def _clear_field():
    _send([_ki(VK_CTRL), _ki(VK_A), _ki(VK_A, flags=_KEYUP), _ki(VK_CTRL, flags=_KEYUP)])


# ---------- windows / processes ----------
_u32 = ctypes.windll.user32


def _running(names_):
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW, timeout=15).stdout.lower()
    except Exception:
        return set()
    return {n for n in names_ if n.lower() in out}


def _find_window(pred):
    hits = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _l):
        if not _u32.IsWindowVisible(hwnd):
            return True
        ln = _u32.GetWindowTextLengthW(hwnd)
        tb = ctypes.create_unicode_buffer(ln + 1)
        _u32.GetWindowTextW(hwnd, tb, ln + 1)
        cb2 = ctypes.create_unicode_buffer(256)
        _u32.GetClassNameW(hwnd, cb2, 256)
        if pred(tb.value, cb2.value):
            hits.append(hwnd)
        return True
    _u32.EnumWindows(proc(cb), 0)
    return hits[0] if hits else 0


def _riot_login_hwnd():
    # the Riot Client shell (login AND the post-login home are both "Riot Client"/Chromium;
    # UIA later confirms a password field is actually present before we type anything)
    return _find_window(lambda t, c: t == "Riot Client" and c == "Chrome_WidgetWin_1")


def _foreground(hwnd):
    _u32.ShowWindow(hwnd, 9)                    # SW_RESTORE
    fg = _u32.GetForegroundWindow()
    t1 = _u32.GetWindowThreadProcessId(fg, None)
    t2 = _u32.GetWindowThreadProcessId(hwnd, None)
    cur = ctypes.windll.kernel32.GetCurrentThreadId()
    _u32.AttachThreadInput(cur, t1, True)
    _u32.AttachThreadInput(cur, t2, True)
    _u32.SetForegroundWindow(hwnd)
    _u32.BringWindowToTop(hwnd)
    _u32.AttachThreadInput(cur, t1, False)
    _u32.AttachThreadInput(cur, t2, False)


def _riot_exe():
    try:
        d = json.load(open(INSTALLS, encoding="utf-8"))
        for k in ("rc_default", "rc_live"):
            if d.get(k) and os.path.exists(d[k]):
                return d[k]
        for p in (d.get("associated_client") or {}).values():
            if p and os.path.exists(p):
                return p
    except Exception:
        pass
    for drv in "CDEFGH":
        p = f"{drv}:\\Riot Games\\Riot Client\\RiotClientServices.exe"
        if os.path.exists(p):
            return p
    raise RuntimeError("Riot Client not found.")


# ---------- UI Automation: locate + focus the login fields ----------
_IS_PASSWORD, _CT_EDIT = 30057, 50004
_PROP_CONTROL_TYPE = 30003
_SCOPE_DESCENDANTS = 4


def _uia():
    import comtypes.client as cc
    mod = cc.GetModule("UIAutomationCore.dll")
    return cc.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=mod.IUIAutomation)


def _login_edits(hwnd, uia=None):
    """[(element, is_password)] for the Edit fields inside the Riot window, or None if UIA
    is unavailable. Empty-with-UIA-working means 'no login form here (yet)'. Uses ONE native
    FindAll (the search runs inside UIAutomationCore) instead of the old Python tree walk —
    the walk made thousands of COM round-trips through the Chromium tree and took seconds
    per poll, which is exactly why the fill took forever to notice a waiting login form."""
    try:
        uia = uia or _uia()
    except Exception:
        return None                            # UIA not available -> caller does a blind fill
    try:
        root = uia.ElementFromHandle(hwnd)
        cond = uia.CreatePropertyCondition(_PROP_CONTROL_TYPE, _CT_EDIT)
        found = root.FindAll(_SCOPE_DESCENDANTS, cond)
        edits = []
        for i in range(found.Length):
            el = found.GetElement(i)
            try:
                is_pw = bool(el.GetCurrentPropertyValue(_IS_PASSWORD))
            except Exception:
                is_pw = False
            edits.append((el, is_pw))
        return edits
    except Exception:
        return []                              # tree not materialized yet -> poll again


def _is_login_form(edits):
    """A login form = a password-flagged edit, or at least two text fields (Chromium doesn't
    always expose IsPassword). edits is None when UIA is unavailable -> we can't tell, so we
    optimistically say yes and let the blind fill handle it."""
    if edits is None:
        return True
    return any(pw for _e, pw in edits) or len(edits) >= 2


def _pick_fields(edits):
    """(username_el, password_el) from the located edits, or (None, None) if UIA gave nothing."""
    if not edits:
        return None, None
    pw = next((e for e, is_pw in edits if is_pw), None)
    if pw is not None:
        user = next((e for e, is_pw in edits if not is_pw), None)
        return (user or edits[0][0]), pw
    if len(edits) >= 2:                        # no IsPassword flag -> assume [user, pass] order
        return edits[0][0], edits[1][0]
    return edits[0][0], None


def _wait_for_login_window(timeout=35):
    """Poll (fast — 0.35s, one shared UIA object, native FindAll) for a Riot window that
    actually shows a password field, else just any Riot window after the grace period
    (UIA missing / tree never materialized)."""
    try:
        uia = _uia()
    except Exception:
        uia = None
    end = time.time() + timeout
    while time.time() < end:
        h = _riot_login_hwnd()
        if h:
            if uia is None:                    # no UIA -> can't verify; accept the window
                return h, None
            edits = _login_edits(h, uia)
            # a password-flagged edit OR two fields = the form (Chromium doesn't always
            # expose IsPassword — waiting for the flag alone rode out the whole timeout)
            if edits and (any(pw for _el, pw in edits) or len(edits) >= 2):
                return h, edits
        time.sleep(0.35)
    h = _riot_login_hwnd()
    return (h, _login_edits(h, uia)) if h else (0, None)


# ---------- the one verb ----------
def fill(name, submit=True, on_status=None):
    say = on_status or (lambda s: None)
    cred = get(name)
    if not cred:
        raise RuntimeError(f'No saved login called "{name}".')
    if _running(LEAGUE_UX):
        raise RuntimeError("You're already logged in - close the client first to switch.")

    hwnd = _riot_login_hwnd()
    edits = _login_edits(hwnd) if hwnd else None
    if not (bool(hwnd) and _is_login_form(edits)):
        if not hwnd:
            say("opening Riot Client…")
            subprocess.Popen([_riot_exe(), "--launch-product=league_of_legends",
                              "--launch-patchline=live"], creationflags=CREATE_NO_WINDOW)
            hwnd, edits = _wait_for_login_window()
        else:
            # the window is ALREADY up — the form just isn't readable yet (Chromium builds
            # its accessibility tree lazily). Never relaunch the client for this; just poll
            # until the password field shows (or conclude it's the signed-in home screen).
            say("login window found — waiting for the form…")
            hwnd, edits = _wait_for_login_window(timeout=12)
        if not hwnd:
            raise RuntimeError("Riot login window never appeared - open it and try again.")
    # UIA present but clearly not a login form (e.g. already on the client home) -> don't type
    if edits is not None and not _is_login_form(edits):
        raise RuntimeError("No Riot login screen found (already signed in?).")

    say("filling login…")
    _foreground(hwnd)
    time.sleep(0.5)

    user_el, pw_el = _pick_fields(edits)       # None,None when UIA unavailable
    if user_el is not None:                    # UIA path: focus each field precisely
        user_el.SetFocus(); time.sleep(0.12)
        _clear_field(); _type(cred["username"])
        if pw_el is not None:
            pw_el.SetFocus(); time.sleep(0.12)
        else:
            _tap(VK_TAB)                        # 2nd field not resolvable -> tab to it
        _clear_field(); _type(cred["password"])
    else:                                      # blind fallback: Riot auto-focuses username
        _clear_field(); _type(cred["username"])
        _tap(VK_TAB); _type(cred["password"])
    if submit:
        time.sleep(0.15); _tap(VK_RET)
    say(f"submitted {name} — watch for a captcha/MFA prompt")


# ---------- CLI (SmitelessApp.exe login2 <name> / logins ...) ----------
def _msgbox(text):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, "Smiteless", 0x10 | 0x40000)
    except Exception:
        pass


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = (args[0].lower() if args else "list")
    rest = " ".join(args[1:]).strip().strip('"')
    try:
        if cmd == "fill":
            fill(rest)
        elif cmd == "remove":
            remove(rest)
        else:
            for n in names():
                print(n)
    except Exception as e:
        _msgbox(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
