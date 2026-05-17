"""
RWAGenie launcher.

Bootstrap order:

1. Try to ``import core.models`` directly. In a Nuitka-packaged build
   the AG engine is baked into the binary and is importable as soon as
   the binary starts — no path manipulation needed. This is also the
   fastest no-op check for dev mode if AG happens to already be on
   sys.path.

2. Dev fallback — locate the sibling Aiccounting/ repo and put it on
   sys.path. ACCGENIE_PATH env var overrides for CI / non-standard
   checkouts.

Any unhandled exception during launch is written to
``%APPDATA%\\AccGenie\\rwagenie_startup.log`` AND surfaced via a
MessageBox if PySide6 is importable, so a failed launch is never
silent. ``--windows-console-mode=disable`` removes the console, so
``stderr`` writes would otherwise vanish.
"""
from __future__ import annotations

import ctypes
import os
import sys
import traceback
from pathlib import Path


def _bootstrap_paths() -> None:
    """Make `core`, `ui`, `ai` importable. No-op if already importable."""
    # 1. Already importable? Nuitka-packaged builds hit this branch.
    try:
        import core.models  # noqa: F401
        return
    except ImportError:
        pass

    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))

    # 2. Sibling-folder layout (default dev setup).
    sibling = here.parent / "Aiccounting"
    if sibling.is_dir() and (sibling / "core" / "models.py").is_file():
        sys.path.insert(0, str(sibling))
        return

    # 3. Env-var override (CI or non-standard layouts).
    env_path = os.environ.get("ACCGENIE_PATH")
    if env_path and Path(env_path).is_dir():
        sys.path.insert(0, env_path)
        return

    raise RuntimeError(
        "RWAGenie cannot find the AccGenie engine.\n"
        f"  Expected sibling folder at: {sibling}\n"
        "  Or set the ACCGENIE_PATH env var to the AG repo's root.\n"
        "  Or run from the packaged installer (which bundles AG)."
    )


def _log_path() -> Path:
    """%APPDATA%\\AccGenie\\rwagenie_startup.log (created on demand)."""
    appdata = os.environ.get("APPDATA") or str(Path.home())
    log_dir = Path(appdata) / "AccGenie"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "rwagenie_startup.log"


def _report_crash(exc: BaseException) -> None:
    """Persist crash to log file + show a MessageBox so the user sees it."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    msg = f"RWAGenie failed to launch.\n\n{exc}\n\n{tb}"

    try:
        with _log_path().open("a", encoding="utf-8") as fh:
            fh.write("=" * 72 + "\n")
            fh.write(msg)
            fh.write("\n")
    except Exception:
        pass

    # MessageBox: works even without a console. MB_ICONERROR = 0x10.
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            (f"{exc}\n\nDetails written to:\n{_log_path()}"),
            "RWAGenie — startup failed",
            0x10,
        )
    except Exception:
        pass


def main() -> int:
    try:
        _bootstrap_paths()
        from app.main import main as app_main
        return app_main() or 0
    except BaseException as exc:
        _report_crash(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
