# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for HECTOR Desktop."""

import sys
import tomllib
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

block_cipher = None
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

ROOT = Path(SPECPATH)
PKG  = ROOT / "hector_desktop"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

HECTOR_SRC = (ROOT / ".." / "hector_package").resolve()

ICON = str(PKG / "resources" / ("hector.icns" if IS_MAC else "hector.ico"))

datas = [
    (str(PKG / "resources" / "Logo.png"),    "hector_desktop/resources"),
    (str(PKG / "resources" / "hector.icns"), "hector_desktop/resources"),
    (str(PKG / "resources" / "hector.ico"),  "hector_desktop/resources"),
    (str(PKG / "resources" / "chevron-down.svg"), "hector_desktop/resources"),
    (str(ROOT / "pyproject.toml"), "."),
]

FONT_DIR = PKG / "resources" / "fonts"
if FONT_DIR.is_dir():
    datas.append((str(FONT_DIR), "hector_desktop/resources/fonts"))

if IS_MAC:
    datas += collect_data_files("mlx", include_py_files=False)
else:
    datas += collect_data_files("tensorflow", include_py_files=False)
    datas += collect_data_files("google.protobuf")
datas += collect_data_files("hector", include_py_files=False)
datas += collect_data_files("h5py")

_metadata_pkgs = [
    "scikit-learn", "scipy", "numpy", "pandas", "anndata",
    "scanpy", "h5py", "matplotlib", "tqdm", "networkx", "huggingface_hub",
    "numcodecs", "zarr",
]
if not IS_MAC:
    _metadata_pkgs.append("tensorflow")
for _pkg in _metadata_pkgs:
    datas += copy_metadata(_pkg)

hiddenimports = [
    "PySide6.QtSvg",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "hector",
    *collect_submodules("hector"),
    "hector_desktop",
    *collect_submodules("hector_desktop"),
    "anndata",
    "scipy.sparse",
    "scipy.sparse.csgraph",
    "scipy.special",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors._typedefs",
    "h5py",
    "h5py.defs",
    "h5py.utils",
    "h5py.h5ac",
    "h5py._proxy",
    "huggingface_hub",
    *(collect_submodules("mlx") if IS_MAC else [
        "tensorflow",
        "tensorflow.python",
        "tensorflow.python.eager",
        "tensorflow.keras",
        "tensorflow.keras.layers",
        "tensorflow.lite.python.lite",
    ]),
    "pyqtgraph.graphicsItems.ViewBox.axisCtrlTemplate_pyside6",
    "pyqtgraph.graphicsItems.PlotItem.plotConfigTemplate_pyside6",
    "pyqtgraph.imageview.ImageViewTemplate_pyside6",
]

excludes = [
    "PySide6.QtNetwork",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "wx",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "sphinx",
    "docutils",
    "tensorboard",
    # macOS: TF is replaced by MLX — exclude to avoid accidental bundling
    *(["tensorflow", "tensorflow_metal", "google.protobuf"] if IS_MAC else []),
    # Not used by the desktop app (purely transitive)
    "torch",
    "torchaudio",
    "torchvision",
    "botocore",
    "boto3",
    "s3transfer",
    "zmq",
    "aiohttp",
    # Only used by hector trajectory modules (lazy-loaded,
    # never invoked from the desktop app)
    "plotly",
    "statsmodels",
    # Present in the build env but never imported by hector or the desktop
    # app — verified by blocking the import and loading every runtime module.
    "onnx",
]

module_collection_mode = {
    "scanpy": "pyz+py",
}

a = Analysis(
    [str(PKG / "__main__.py")],
    pathex=[str(ROOT), str(HECTOR_SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
    cipher=block_cipher,
    module_collection_mode=module_collection_mode,
)

if not IS_MAC:
    def _is_tf_devcruft(dest: str) -> bool:
        norm = dest.replace("\\", "/")
        return norm.startswith("tensorflow/include/") or norm.endswith(".if.lib")

    a.datas = [entry for entry in a.datas if not _is_tf_devcruft(entry[0])]
    a.binaries = [entry for entry in a.binaries if not _is_tf_devcruft(entry[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HECTOR Desktop",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)

if IS_MAC:
    app = BUNDLE(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        name="HECTOR Desktop.app",
        icon=ICON,
        bundle_identifier="com.hector.desktop",
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleName": "HECTOR Desktop",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "15.0",
        },
    )
else:
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        name="HECTOR Desktop",
    )
