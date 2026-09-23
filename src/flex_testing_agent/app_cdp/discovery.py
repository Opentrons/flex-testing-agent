"""Locate the installed Opentrons desktop app executable."""

from __future__ import annotations

import os
import platform
import re
from collections.abc import Iterator
from pathlib import Path

_MAC_APP_BUNDLE_RE = re.compile(r"^Opentrons(?:[ ._-].+)?\.app$", re.IGNORECASE)
_MAC_EXECUTABLE_RE = re.compile(r"^Opentrons$", re.IGNORECASE)
_WIN_EXECUTABLE_RE = re.compile(r"^Opentrons(?:[ ._-].+)?\.exe$", re.IGNORECASE)
_WIN_INSTALL_DIR_RE = re.compile(r"^Opentrons", re.IGNORECASE)
_WIN_SKIP_EXE_RE = re.compile(r"(?i)(uninstall|setup|installer|update)")
_LINUX_EXECUTABLE_RE = re.compile(r"^opentrons$", re.IGNORECASE)


def _iter_dir_entries(root: Path, *, max_depth: int) -> Iterator[Path]:
    if max_depth < 0 or not root.is_dir():
        return
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        yield entry
        if max_depth > 0 and entry.is_dir() and not entry.is_symlink():
            yield from _iter_dir_entries(entry, max_depth=max_depth - 1)


def _prefer_exact_name(path: Path, exact: str) -> tuple[int, str]:
    return (0 if path.name.lower() == exact.lower() else 1, path.name.lower())


def _macos_search_roots() -> list[Path]:
    return [Path("/Applications"), Path.home() / "Applications"]


def _windows_search_roots() -> list[Path]:
    roots: list[Path] = []
    for env_key, default in (
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        roots.append(Path(os.environ.get(env_key) or default))
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        roots.append(Path(local_app) / "Programs")
    return roots


def _linux_search_roots() -> list[Path]:
    return [Path("/usr/bin"), Path("/usr/local/bin"), Path.home() / ".local" / "bin"]


def _find_macos_executable() -> Path | None:
    matches: list[Path] = []
    for root in _macos_search_roots():
        for entry in _iter_dir_entries(root, max_depth=0):
            if not entry.is_dir() or not _MAC_APP_BUNDLE_RE.match(entry.name):
                continue
            macos_dir = entry / "Contents" / "MacOS"
            for binary in _iter_dir_entries(macos_dir, max_depth=0):
                if binary.is_file() and _MAC_EXECUTABLE_RE.match(binary.name):
                    matches.append(binary)
    if not matches:
        return None
    matches.sort(
        key=lambda p: _prefer_exact_name(p.parent.parent.parent, "Opentrons.app")
    )
    return matches[0]


def _is_windows_app_exe(path: Path) -> bool:
    return (
        path.is_file()
        and bool(_WIN_EXECUTABLE_RE.match(path.name))
        and not _WIN_SKIP_EXE_RE.search(path.name)
    )


def _find_windows_executable() -> Path | None:
    matches: list[Path] = []
    for root in _windows_search_roots():
        for entry in _iter_dir_entries(root, max_depth=0):
            if _is_windows_app_exe(entry):
                matches.append(entry)
            elif entry.is_dir() and _WIN_INSTALL_DIR_RE.match(entry.name):
                for nested in _iter_dir_entries(entry, max_depth=2):
                    if _is_windows_app_exe(nested):
                        matches.append(nested)
    if not matches:
        return None
    matches.sort(key=lambda p: _prefer_exact_name(p, "Opentrons.exe"))
    return matches[0]


def _find_linux_executable() -> Path | None:
    matches: list[Path] = []
    for root in _linux_search_roots():
        for entry in _iter_dir_entries(root, max_depth=0):
            if entry.is_file() and _LINUX_EXECUTABLE_RE.match(entry.name):
                matches.append(entry)
    if not matches:
        return None
    matches.sort(key=lambda p: _prefer_exact_name(p, "opentrons"))
    return matches[0]


def _searched_locations(current_os: str) -> str:
    if current_os == "darwin":
        roots = _macos_search_roots()
        pattern = "Opentrons*.app/Contents/MacOS/Opentrons"
    elif current_os == "windows":
        roots = _windows_search_roots()
        pattern = "Opentrons*.exe"
    elif current_os == "linux":
        roots = _linux_search_roots()
        pattern = "opentrons"
    else:
        return current_os
    listed = "\n".join(f"  {root}" for root in roots)
    return f"{listed}\n(pattern: {pattern})"


def get_opentrons_app_path() -> Path:
    """Return the Opentrons desktop app executable for this OS.

    Prefers ``OPENTRONS_APP_PATH`` when set, then searches standard install
    locations (versioned bundles like ``Opentrons 8.5.0.app`` still match).
    """
    override = os.environ.get("OPENTRONS_APP_PATH", "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            msg = f"OPENTRONS_APP_PATH={path} is not a file"
            raise FileNotFoundError(msg)
        return path

    current_os = platform.system().lower()
    found: Path | None
    if current_os == "windows":
        found = _find_windows_executable()
    elif current_os == "darwin":
        found = _find_macos_executable()
    elif current_os == "linux":
        found = _find_linux_executable()
    else:
        msg = f"Unsupported operating system: {platform.system()}"
        raise OSError(msg)

    if found is None:
        msg = (
            "Could not find the Opentrons desktop app. Searched:\n"
            f"{_searched_locations(current_os)}\n"
            "Install the app or set OPENTRONS_APP_PATH to the executable."
        )
        raise FileNotFoundError(msg)
    return found.resolve()
