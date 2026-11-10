"""Repository sources the Arco Bridge freezes into its executable.

The Bridge runs this frozen copy rather than the working tree, so an edit to any
of these roots does not reach a running ResQ import until the Bridge is rebuilt.
Two consumers need to agree on the list: ``build_exe.py`` bundles these roots,
and the build manager reports the Bridge as stale when one of them is newer than
the deployed executable. Both read this module so the list cannot drift.

Keep this module free of side effects and of imports outside the standard
library; the build manager imports it without preparing a build environment.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_BRIDGE_DIR = Path(__file__).resolve().parent
# .../ArcRho/server-components/src/arcrho_bridge -> .../ArcRho
REPO_ROOT = _BRIDGE_DIR.parents[2]

BUNDLE_DIR_NAME = "resq_importer"

# Standalone canonical modules the Bridge imports directly rather than through
# the staged migration bundle. ``resq_import_runner`` takes its reserving-class
# import lease from ``arcrho_engine_job_lease``, so that module must reach the
# frozen import graph, not only the data bundle.
CANONICAL_MODULE_ROOT = REPO_ROOT / "python-api" / "src"
CANONICAL_HIDDEN_IMPORTS: tuple[str, ...] = ("arcrho_engine_job_lease",)


@dataclass(frozen=True)
class BundledSource:
    """One repository tree copied into a frozen ArcRho executable.

    ``is_package`` distinguishes a directory that *is* an importable package from
    one that merely *contains* packages. It decides which directory has to be on
    ``sys.path`` for the tree's modules to import. ``bundle_dir`` is the frozen
    bundle's top-level folder; the Bridge default is shared by consumers that
    reuse this recipe (the Engine passes its own).
    """

    source: Path
    relative_target: Path
    is_package: bool = False
    bundle_dir: str = BUNDLE_DIR_NAME

    @property
    def target(self) -> str:
        """The PyInstaller ``--add-data`` destination inside the bundle."""
        return str(Path(self.bundle_dir) / self.relative_target)

    @property
    def import_root(self) -> Path:
        """The repository directory to put on ``sys.path`` for this tree."""
        if self.source.is_file():
            return self.source.parent
        return self.source.parent if self.is_package else self.source


BUNDLED_SOURCES: tuple[BundledSource, ...] = (
    BundledSource(REPO_ROOT / "python-api" / "migration", Path("python-api") / "migration"),
    BundledSource(REPO_ROOT / "python-api" / "src", Path("python-api") / "src"),
    BundledSource(
        REPO_ROOT / "frontend" / "app_server",
        Path("frontend") / "app_server",
        is_package=True,
    ),
    # The reserving-class synchronization session drives ResQ through the same
    # exporter the Export macro uses. Only that one macro file is frozen, and
    # it lands beside the migration folder so the bundle reproduces the layout
    # the shared support release publishes for Client PCs.
    BundledSource(
        REPO_ROOT / "python-api" / "macros" / "export_reserving_class_to_resq.py",
        Path("python-api") / "macros",
    ),
)

BUNDLED_SOURCE_ROOTS: tuple[Path, ...] = tuple(item.source for item in BUNDLED_SOURCES)
