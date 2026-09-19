def _read_version() -> str:
    try:
        from importlib.metadata import version
        return version("hector-desktop")
    except Exception:
        pass
    try:
        import sys
        from pathlib import Path
        if getattr(sys, "frozen", False):
            toml_path = Path(sys._MEIPASS) / "pyproject.toml"
        else:
            toml_path = Path(__file__).parent.parent / "pyproject.toml"
        for line in toml_path.read_text().splitlines():
            if line.strip().startswith("version"):
                return line.split("=")[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.0.0"

__version__ = _read_version()
