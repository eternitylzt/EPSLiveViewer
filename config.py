"""Application configuration and Ghostscript discovery utilities."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


APP_NAME = "EPS Live Viewer"
APP_VERSION = "1.2.0"
PROJECT_URL = "https://github.com/eternitylzt/EPSLiveViewer"
BACKGROUND_MODES = ("transparent", "white", "custom")
WHEEL_ACTIONS = ("zoom", "files", "pages")
LANGUAGES = ("zh_CN", "en")
MIN_REFRESH_INTERVAL = 100
MAX_REFRESH_INTERVAL = 10_000
MIN_EXPORT_DPI = 72
MAX_EXPORT_DPI = 600
SUPPORTED_SOURCE_SUFFIXES = (".eps", ".ps")
VIDEO_SOURCE_SUFFIXES = (".eps", ".ps", ".png", ".jpg", ".jpeg")


def filename_sort_key(path: Path) -> tuple[tuple[int, object], ...]:
    """Sort frame2 before frame10 while remaining case-insensitive."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", path.name)
    )


def _coerce_bool(value: Any, default: bool) -> bool:
    """Convert common JSON/user representations without treating junk as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        converted = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(converted, maximum))


def _normalize_color(value: Any, default: str = "#FFFFFF") -> str:
    """Return a canonical, opaque ``#RRGGBB`` color string."""
    text = str(value).strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.upper()
    return default


@dataclass
class AppConfig:
    """Persisted application settings with safe defaults.

    Preview resolution is deliberately absent: the viewer derives it from the
    current zoom level. ``export_dpi`` affects only explicit PNG exports.
    """

    ghostscript_path: str = ""
    auto_refresh: bool = True
    refresh_interval: int = 500
    background_mode: str = "transparent"
    background_color: str = "#FFFFFF"
    export_dpi: int = 300
    wheel_action: str = "zoom"
    language: str = "zh_CN"

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "AppConfig":
        """Build a validated configuration from an untrusted JSON mapping.

        Older releases stored preview/export resolution under ``dpi``. When
        ``export_dpi`` is absent that value is migrated automatically.
        """
        defaults = cls()
        mode = str(raw.get("background_mode", defaults.background_mode)).strip().lower()
        if mode not in BACKGROUND_MODES:
            mode = defaults.background_mode
        wheel_action = str(raw.get("wheel_action", defaults.wheel_action)).strip().lower()
        if wheel_action not in WHEEL_ACTIONS:
            wheel_action = defaults.wheel_action
        language = str(raw.get("language", defaults.language)).strip()
        if language not in LANGUAGES:
            language = defaults.language

        legacy_or_export_dpi = raw.get("export_dpi", raw.get("dpi", defaults.export_dpi))
        configured_path = raw.get("ghostscript_path", "")
        if configured_path is None:
            configured_path = ""
        return cls(
            ghostscript_path=str(configured_path).strip(),
            auto_refresh=_coerce_bool(raw.get("auto_refresh"), defaults.auto_refresh),
            refresh_interval=_bounded_int(
                raw.get("refresh_interval"),
                defaults.refresh_interval,
                MIN_REFRESH_INTERVAL,
                MAX_REFRESH_INTERVAL,
            ),
            background_mode=mode,
            background_color=_normalize_color(
                raw.get("background_color"), defaults.background_color
            ),
            export_dpi=_bounded_int(
                legacy_or_export_dpi,
                defaults.export_dpi,
                MIN_EXPORT_DPI,
                MAX_EXPORT_DPI,
            ),
            wheel_action=wheel_action,
            language=language,
        )


class ConfigManager:
    """Load and save ``config.json`` in a platform-appropriate location."""

    def __init__(self) -> None:
        self.base_dir = self._application_dir()
        self.path = self.base_dir / "config.json"

    @staticmethod
    def _application_dir() -> Path:
        # Preserve the established portable Windows behavior: config.json lives
        # beside the EXE. Unix application folders are commonly read-only, so
        # frozen Linux/macOS builds use the conventional per-user config area.
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            return Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False) and sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "EPSLiveViewer"
        if getattr(sys, "frozen", False):
            xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
            config_root = (
                Path(xdg_config_home).expanduser()
                if xdg_config_home
                else Path.home() / ".config"
            )
            return config_root / "EPSLiveViewer"
        return Path(__file__).resolve().parent

    def load(self) -> AppConfig:
        """Return defaults when the file is missing or contains invalid JSON."""
        try:
            with self.path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
            if not isinstance(raw, dict):
                return AppConfig()
            return AppConfig.from_mapping(raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        """Validate and atomically save user-editable settings.

        A unique temporary file in the destination directory prevents parallel
        launches from sharing one ``.tmp`` name. ``os.replace`` keeps the old
        configuration intact if writing the new one fails.
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
        validated = AppConfig.from_mapping(asdict(config))
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix="config_",
                suffix=".json.tmp",
                dir=self.base_dir,
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                json.dump(asdict(validated), file, ensure_ascii=False, indent=4)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.path)
        except Exception:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise


def find_ghostscript(configured_path: str = "") -> Path | None:
    """Find the Ghostscript command on Windows, Linux, or macOS."""
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_file():
            return candidate

    for environment_name in ("GSWIN64C", "GSWIN32C"):
        configured = os.environ.get(environment_name)
        candidate = Path(configured).expanduser() if configured else None
        if candidate and candidate.is_file():
            return candidate

    for executable in ("gswin64c.exe", "gswin32c.exe", "gs.exe", "gs"):
        located = shutil.which(executable)
        if located:
            return Path(located)

    if sys.platform != "win32":
        # Homebrew is not always present in the PATH of a Finder-launched app.
        for candidate in (
            Path("/opt/homebrew/bin/gs"),
            Path("/usr/local/bin/gs"),
            Path("/usr/bin/gs"),
        ):
            if candidate.is_file():
                return candidate
        return None

    candidates: list[Path] = []
    program_roots = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramW6432", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    for root in dict.fromkeys(program_roots):
        if not root:
            continue
        gs_root = Path(root) / "gs"
        for executable in ("gswin64c.exe", "gswin32c.exe"):
            candidates.extend(gs_root.glob(f"*/bin/{executable}"))

    existing = [candidate for candidate in candidates if candidate.is_file()]
    if not existing:
        return None

    def version_key(candidate: Path) -> tuple[int, ...]:
        version_name = candidate.parent.parent.name
        parts = re.findall(r"\d+", version_name)
        return tuple(int(part) for part in parts) or (0,)

    return max(existing, key=version_key)
