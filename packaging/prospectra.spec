# 2026-07-14 (P6): PyInstaller spec — one spec for all three OSes.
#
# Run from the repo root:  uv run pyinstaller packaging/prospectra.spec --noconfirm
#
# Why the hidden imports: Prospectra's whole architecture is dynamic — connectors, flow nodes, LLM
# providers, and chart types are found through entry points and registries, so PyInstaller's static
# analysis cannot see them. Anything discovered at runtime has to be named here or the packaged app
# ships without it. That is also why the smoke test after a build matters more than the build
# succeeding: a build can succeed and still be missing a whole tier of connectors.
#
# QWebEngine is deliberately absent from this app (the plan avoided it precisely so packaging stays
# sane); matplotlib's Qt backend is the only GUI-adjacent native piece.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# 2026-07-14 (P6): entry-point plugins need their *distribution metadata*, not just their code.
# Proven, not assumed: the first build of this bundle launched fine, ran the whole stats engine —
# and reported "PLUGINS: (none)". `importlib.metadata.entry_points()` reads .dist-info, which
# PyInstaller does not ship by default, so every plugin silently vanished from the packaged app
# while working perfectly in the dev install. copy_metadata puts it back.
#
# Limitation, stated plainly: a frozen app can only carry the plugins bundled at build time. There
# is no pip inside a bundle, so a user cannot add a connector to the packaged build — they install
# from source for that. A drop-in plugin folder is future work (Deviations.md).
plugin_distributions = ["prospectra-jira"]

metadata = copy_metadata("prospectra")
for distribution in plugin_distributions:
    metadata += copy_metadata(distribution)

hiddenimports = [
    # The bundled plugins' own modules (their metadata alone is not enough — the code must be in).
    "prospectra_jira",
    "prospectra_jira.connector",
    # Discovered at runtime through registries / entry points — invisible to static analysis.
    *collect_submodules("prospectra.core.connectors"),
    *collect_submodules("prospectra.core.flow.nodes"),
    *collect_submodules("prospectra.core.llm.providers"),
    # Scientific stack pieces loaded lazily by their parents.
    "duckdb",
    "pandas",
    "pyarrow",
    "sklearn.utils._typedefs",
    "sklearn.utils._heap",
    "sklearn.utils._sorting",
    "sklearn.utils._vector_sentinel",
    "scipy._lib.array_api_compat.numpy.fft",
    "scipy.special._special_ufuncs",
    "statsmodels.tsa.statespace._filters",
    "matplotlib.backends.backend_qtagg",
    # keyring's backends are plugins too — without these the OS keychain silently disappears and
    # every API key "fails to save" in the packaged build.
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.chainer",
    "keyring.backends.fail",
]

datas = [
    *metadata,  # without this, entry-point plugins are invisible in the packaged app
    *collect_data_files("statsmodels"),
    *collect_data_files("duckdb"),
]

a = Analysis(
    ["../prospectra/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Trim the parts of the scientific stack that pull in a second GUI toolkit or a compiler.
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "jupyter", "notebook", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Prospectra",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX corrupts Qt frameworks on macOS and trips antivirus heuristics on Windows
    console=False,  # a GUI app; the CLI subcommands are for the dev install, not the bundle
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Prospectra",
)

# macOS: wrap the collected app in a proper .app bundle so it launches from Finder.
app = BUNDLE(
    coll,
    name="Prospectra.app",
    icon=None,  # branding is still an open decision in the plan
    bundle_identifier="org.prospectra.app",
    info_plist={
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
