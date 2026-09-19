import multiprocessing
import os
import sys

# Keep streams usable in windowed builds and use UTF-8 when available.
def _ensure_safe_stream(name: str) -> None:
    stream = getattr(sys, name, None)
    if stream is None:
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        return
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


for _stream_name in ("stdout", "stderr"):
    _ensure_safe_stream(_stream_name)

# Make native libraries available in unactivated Windows environments.
if sys.platform == "win32":
    _prefix = os.environ.get("CONDA_PREFIX") or os.path.dirname(sys.executable)
    _lib_bin = os.path.join(_prefix, "Library", "bin")
    if os.path.isdir(_lib_bin):
        os.environ["PATH"] = _lib_bin + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(_lib_bin)

# Prevent child processes from flashing a console window on Windows.
if sys.platform == "win32":
    import subprocess as _subprocess

    _CREATE_NO_WINDOW = 0x08000000
    _orig_popen_init = _subprocess.Popen.__init__

    def _popen_no_window(self, *args, **kwargs):
        kwargs["creationflags"] = (kwargs.get("creationflags") or 0) | _CREATE_NO_WINDOW
        _orig_popen_init(self, *args, **kwargs)

    _subprocess.Popen.__init__ = _popen_no_window

# Configure Qt plugin paths before importing PySide6.
try:
    import PySide6 as _pyside6
    _qt_plugins = os.path.join(os.path.dirname(_pyside6.__file__), "Qt", "plugins")
    if os.path.isdir(_qt_plugins):
        os.environ.setdefault("QT_PLUGIN_PATH", _qt_plugins)
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH",
                              os.path.join(_qt_plugins, "platforms"))
except ImportError:
    pass

if __name__ == "__main__":
    multiprocessing.freeze_support()

    from hector_desktop.app import main
    sys.exit(main())
