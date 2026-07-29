"""Shared subprocess safety helpers for local LLM CLIs."""

import subprocess


NO_WINDOW = 0x08000000


def terminate_tree(process):
    """Best-effort termination of a CLI and every process it spawned."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True, creationflags=NO_WINDOW, timeout=10,
        )
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    try:
        process.communicate(timeout=5)
    except Exception:
        pass
