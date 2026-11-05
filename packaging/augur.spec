# PyInstaller recipe: pyinstaller packaging/augur.spec
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
datas = [
    (str(ROOT / "augur" / "web"), "augur/web"),
    (str(ROOT / "augur" / "removed_hexes.json"), "augur"),
    (str(ROOT / "data" / "gamedata.json"), "data"),
]
for folder in ("icons", "ocr"):  # hex icons + Korean/Japanese OCR models (download with: python -m augur update)
    if (ROOT / "data" / folder).is_dir():
        datas.append((str(ROOT / "data" / folder), f"data/{folder}"))
datas += collect_data_files("rapidocr_onnxruntime")  # OCR models and config
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    [str(ROOT / "packaging" / "augur_app.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=["augur.__main__", "augur.collect", "augur.lcu", "augur.opgg", "augur.model", "augur.gaps", "augur.arammayhem", "augur.screen", "PIL.ImageGrab"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
icon = str(ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.png"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Augur", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="Augur")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Augur.app", icon=icon, bundle_identifier="io.github.augur",
                 info_plist={"NSHighResolutionCapable": True,
                             "NSScreenCaptureUsageDescription": "Augur reads the hex cards on your screen to grade them."})
