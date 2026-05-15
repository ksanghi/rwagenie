"""
RWAGenie launcher.

Adds the sibling AccGenie repo to PYTHONPATH so `from core.*` and
`from ui.*` imports resolve to the AG engine. Then defers to
app.main.main().

Layout assumed (sibling-folder convention):

    C:\\Users\\ksang\\eclipse-workspace\\
        ├── Aiccounting\\          <- AccGenie engine
        └── rwagenie\\             <- this repo
                main.py            <- this file

When packaged via Nuitka, both repos' Python source gets baked into
the same installer — the customer machine doesn't need AccGenie
installed separately. The sys.path manipulation below is only for
dev-mode launches.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap_paths() -> None:
    """Locate the AccGenie engine and put it on sys.path."""
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))

    # 1. Sibling-folder layout (default dev setup).
    sibling = here.parent / "Aiccounting"
    if sibling.is_dir() and (sibling / "core" / "models.py").is_file():
        sys.path.insert(0, str(sibling))
        return

    # 2. Env-var override (CI or non-standard layouts).
    env_path = os.environ.get("ACCGENIE_PATH")
    if env_path and Path(env_path).is_dir():
        sys.path.insert(0, env_path)
        return

    # 3. Bundled (Nuitka frozen) — `core` and `ui` are already importable
    #    because Nuitka baked them into the binary.
    if getattr(sys, "frozen", False):
        return

    # Couldn't locate AG. Show a friendly message instead of an opaque
    # ImportError downstream.
    sys.stderr.write(
        "RWAGenie cannot find the AccGenie engine.\n"
        f"  Expected at: {sibling}\n"
        "  Or set the ACCGENIE_PATH env var to the AG repo's root.\n"
        "  Or run from the packaged installer (which bundles AG).\n"
    )
    sys.exit(1)


def main() -> int:
    _bootstrap_paths()
    from app.main import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main() or 0)
