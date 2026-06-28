#!/usr/bin/env python3
"""lolautoaccept.py - auto-accept queue ready checks via local LCU API.

This uses the League client's local endpoint:
  POST /lol-matchmaking/v1/ready-check/accept
"""
import ssl
import urllib.request

import lolgame as lg
import smiteconfig as cfg


def _lcu(method, path, timeout=3):
    lc = lg._lcu()
    if not lc:
        return None
    port, hdr = lc
    req = urllib.request.Request(f"https://127.0.0.1:{port}{path}", headers=hdr, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as r:
        raw = r.read()
    return raw


def try_accept():
    """Accept the ready-check if it's currently waiting and auto-accept is enabled."""
    if not cfg.load().get("auto_accept", False):
        return False
    try:
        raw = _lcu("GET", "/lol-matchmaking/v1/ready-check")
        if not raw:
            return False
        txt = raw.decode("utf-8", "replace")
        if '"state":"InProgress"' not in txt and '"state": "InProgress"' not in txt:
            return False
        _lcu("POST", "/lol-matchmaking/v1/ready-check/accept")
        return True
    except Exception:
        return False


def main():
    try_accept()


if __name__ == "__main__":
    main()
