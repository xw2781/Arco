"""Repository sources the Arco Engine freezes into its executable.

The Engine runs dependent propagation through the canonical
``frontend/app_server`` services, loaded from this frozen copy rather than the
working tree, so an edit to these roots does not reach a running Engine until
it is rebuilt. ``build_exe.py`` bundles these roots and the dependent
propagation runtime resolves its ``sys.path`` from the same list, so the two
cannot drift. The mechanism (``BundledSource``) is owned by the Bridge's
bundle recipe, which this build reuses.

Keep this module free of side effects and of imports outside the standard
library plus ``arcrho_bridge.bundled_sources``.
"""
from __future__ import annotations

from pathlib import Path

from arcrho_bridge.bundled_sources import REPO_ROOT, BundledSource

BUNDLE_DIR_NAME = "arcrho_canonical"

ENGINE_BUNDLED_SOURCES: tuple[BundledSource, ...] = (
    BundledSource(
        REPO_ROOT / "python-api" / "src",
        Path("python-api") / "src",
        bundle_dir=BUNDLE_DIR_NAME,
    ),
    BundledSource(
        REPO_ROOT / "frontend" / "app_server",
        Path("frontend") / "app_server",
        is_package=True,
        bundle_dir=BUNDLE_DIR_NAME,
    ),
)
