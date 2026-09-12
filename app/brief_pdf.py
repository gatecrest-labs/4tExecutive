"""Real PDF generation for the weekly Executive Brief, by shelling out to a
headless Chrome/Chromium binary.

**Deviation from the design doc, documented deliberately**: the original
design doc modeled this on 4thealth-plus's "pdf" report format, describing
it as headless-Chrome conversion. It is not -- 4thealth-plus's "pdf" format
is actually just a styled HTML attachment; there is no Chrome invocation
anywhere in that codebase. This module implements the *real* thing: it
shells out to an actual headless Chrome/Chromium binary via `subprocess` to
render a genuine PDF, with a graceful fallback (log a warning, return
False, never raise) when no such binary is available on the host --
callers (app.brief_send.send_weekly_brief) must treat a False return as
"skip the PDF attachment, still send the HTML", not as an error.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Bare names are resolved with shutil.which (must be on PATH); absolute
# paths are checked with Path.exists() -- covers Linux package names plus
# the macOS .app bundle layout for dev machines.
_FALLBACK_BINARIES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

CHROME_BINARY_ENV_VAR = "CHROME_BINARY"


def find_chrome_binary() -> str | None:
    """Locate a Chrome/Chromium binary: $CHROME_BINARY env var first, else
    the fixed fallback search list. Returns None (never raises) if nothing
    is found."""
    import os

    env_binary = os.environ.get(CHROME_BINARY_ENV_VAR)
    if env_binary:
        if env_binary.startswith("/"):
            return env_binary if Path(env_binary).exists() else None
        return shutil.which(env_binary)

    for candidate in _FALLBACK_BINARIES:
        if candidate.startswith("/"):
            if Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def render_pdf(html_path_or_url: str, out_path: Path, timeout: int = 30) -> bool:
    """Render `html_path_or_url` (a local file path or a URL) to a PDF at
    `out_path` using headless Chrome/Chromium.

    Returns True iff a binary was found, the subprocess exited 0, and
    out_path exists and is non-empty. Never raises -- every failure mode
    (no binary, non-zero exit, timeout, missing binary crashing mid-render)
    is logged and reported as False so callers can degrade gracefully
    (skip the PDF attachment, still send the HTML).
    """
    binary = find_chrome_binary()
    if binary is None:
        logger.warning(
            "No Chrome/Chromium binary found (checked $%s and %s); skipping PDF generation.",
            CHROME_BINARY_ENV_VAR,
            _FALLBACK_BINARIES,
        )
        return False

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                binary,
                "--headless=new",
                "--disable-gpu",
                f"--print-to-pdf={out_path}",
                html_path_or_url,
            ],
            timeout=timeout,
            capture_output=True,
            check=False,
        )
    except Exception:
        logger.exception("Failed to run headless Chrome (%s) for PDF generation", binary)
        return False

    if result.returncode != 0:
        logger.warning(
            "Headless Chrome exited %s generating PDF: %s",
            result.returncode,
            result.stderr.decode(errors="replace") if result.stderr else "",
        )
        return False

    if not out_path.exists() or out_path.stat().st_size == 0:
        logger.warning("Headless Chrome exited 0 but produced no/empty PDF at %s", out_path)
        return False

    return True
