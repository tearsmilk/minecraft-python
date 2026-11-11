# PyInstaller spec for Honoka.app (macOS 11+, Intel and Apple Silicon).
# Built by .github/workflows/build-mac.yml with python.org's universal2 Python, whose binaries run on
# macOS 10.13+, so the app does too; LSMinimumSystemVersion says 11.0, Honoka's floor.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
VERSION = os.environ.get("HONOKA_VERSION", "0.1.0")

a = Analysis(
    [os.path.join(ROOT, "packaging", "honoka_app.py")],
    pathex=[ROOT],
    hiddenimports=["honoka.gui"],
    excludes=["unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Honoka",
    console=False,
    target_arch=os.environ.get("HONOKA_ARCH", "universal2"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Honoka")
app = BUNDLE(
    coll,
    name="Honoka.app",
    icon=os.environ.get("HONOKA_ICON"),
    bundle_identifier="ink.hoka.honoka",
    version=VERSION,
    info_plist={
        "CFBundleName": "Honoka",
        "CFBundleDisplayName": "Honoka",
        "CFBundleShortVersionString": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.games",
    },
)
