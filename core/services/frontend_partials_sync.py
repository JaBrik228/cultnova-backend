from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

TARGET_PARTIALS_DIR = Path("templates") / "partials"
DEFAULT_FRONTEND_EXPORT_DIR = Path("deploy_artifacts") / "backend-partials"
EXPORT_MANIFEST_FILENAME = "manifest.json"
ROOT_PLACEHOLDER_PATTERN = re.compile(r"{{\s*ROOT\s*}}")


@dataclass(frozen=True)
class _PartialDefinition:
    source_relative_path: str
    target_name: str


@dataclass(frozen=True)
class _PreparedPartial:
    source_description: str
    target_name: str
    content: str
    synced_at: str
    freshness: datetime


@dataclass(frozen=True)
class _PreparedBundle:
    kind: str
    root: Path
    freshness: datetime
    files: tuple[_PreparedPartial, ...]


@dataclass(frozen=True)
class FrontendPartialSyncResult:
    source_kind: str
    source_root: Path
    written_files: tuple[Path, ...]
    unchanged_files: tuple[Path, ...]


PARTIAL_DEFINITIONS = (
    _PartialDefinition(source_relative_path="src/partials/header.html", target_name="header.html"),
    _PartialDefinition(source_relative_path="src/partials/footer.html", target_name="footer.html"),
    _PartialDefinition(source_relative_path="src/partials/popup.html", target_name="popup.html"),
    _PartialDefinition(source_relative_path="src/partials/call-back.html", target_name="callback_popup.html"),
)


def sync_frontend_partials(
    backend_base_dir: str | os.PathLike[str],
    frontend_repo_path: str | os.PathLike[str] | None = None,
    frontend_export_dir: str | os.PathLike[str] | None = None,
    *,
    strict: bool = False,
) -> FrontendPartialSyncResult | None:
    backend_root = Path(backend_base_dir).resolve()
    bundle = _resolve_source_bundle(
        backend_root=backend_root,
        frontend_repo_path=frontend_repo_path,
        frontend_export_dir=frontend_export_dir,
    )
    if bundle is None:
        if strict:
            raise FileNotFoundError(
                "Frontend partial sources were not found. Configure FRONTEND_REPO_PATH or FRONTEND_PARTIALS_EXPORT_DIR."
            )
        return None

    target_root = backend_root / TARGET_PARTIALS_DIR
    target_root.mkdir(parents=True, exist_ok=True)

    written_files: list[Path] = []
    unchanged_files: list[Path] = []

    for partial in bundle.files:
        target_path = target_root / partial.target_name
        rendered_content = _render_backend_partial(partial)
        if _write_text_if_changed(target_path, rendered_content):
            written_files.append(target_path)
        else:
            unchanged_files.append(target_path)

    return FrontendPartialSyncResult(
        source_kind=bundle.kind,
        source_root=bundle.root,
        written_files=tuple(written_files),
        unchanged_files=tuple(unchanged_files),
    )


def _resolve_source_bundle(
    backend_root: Path,
    frontend_repo_path: str | os.PathLike[str] | None,
    frontend_export_dir: str | os.PathLike[str] | None,
) -> _PreparedBundle | None:
    repo_root = _normalize_optional_path(frontend_repo_path, base_dir=backend_root)
    explicit_export_root = _normalize_optional_path(frontend_export_dir, base_dir=backend_root)

    export_candidates = []
    if explicit_export_root is not None:
        export_candidates.append(explicit_export_root)
    if repo_root is not None:
        export_candidates.append(repo_root / DEFAULT_FRONTEND_EXPORT_DIR)

    export_bundle = None
    for export_root in export_candidates:
        export_bundle = _build_export_bundle(export_root)
        if export_bundle is not None:
            break

    repo_bundle = _build_repo_bundle(repo_root) if repo_root is not None else None

    if export_bundle and repo_bundle:
        if export_bundle.freshness >= repo_bundle.freshness:
            return export_bundle
        return repo_bundle

    return export_bundle or repo_bundle


def _build_export_bundle(export_root: Path) -> _PreparedBundle | None:
    manifest_path = export_root / EXPORT_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    files = manifest.get("files")
    if manifest.get("version") != 1 or not isinstance(files, list):
        return None

    generated_at = _parse_timestamp(manifest.get("generatedAt"), fallback_path=manifest_path)
    prepared_files: list[_PreparedPartial] = []

    for entry in files:
        if not isinstance(entry, dict):
            return None

        target_name = _clean_relative_value(entry.get("target"))
        source_description = _clean_relative_value(entry.get("source")) or target_name
        if not target_name:
            return None

        partial_path = export_root / target_name
        if not partial_path.is_file():
            return None

        prepared_files.append(
            _PreparedPartial(
                source_description=source_description,
                target_name=target_name,
                content=partial_path.read_text(encoding="utf-8"),
                synced_at=_format_timestamp(generated_at),
                freshness=generated_at,
            )
        )

    if not prepared_files:
        return None

    return _PreparedBundle(
        kind="export",
        root=export_root,
        freshness=generated_at,
        files=tuple(prepared_files),
    )


def _build_repo_bundle(repo_root: Path) -> _PreparedBundle | None:
    if not repo_root.is_dir():
        return None

    prepared_files: list[_PreparedPartial] = []

    for definition in PARTIAL_DEFINITIONS:
        source_path = repo_root / definition.source_relative_path
        if not source_path.is_file():
            return None

        freshness = datetime.fromtimestamp(source_path.stat().st_mtime, tz=timezone.utc)
        prepared_files.append(
            _PreparedPartial(
                source_description=definition.source_relative_path.replace("\\", "/"),
                target_name=definition.target_name,
                content=source_path.read_text(encoding="utf-8"),
                synced_at=_format_timestamp(freshness),
                freshness=freshness,
            )
        )

    return _PreparedBundle(
        kind="repo",
        root=repo_root,
        freshness=max(file.freshness for file in prepared_files),
        files=tuple(prepared_files),
    )


def _render_backend_partial(partial: _PreparedPartial) -> str:
    normalized_content = _normalize_partial_content(partial.content)
    return f"<!-- source: {partial.source_description}; synced: {partial.synced_at} -->\n{normalized_content}\n"


def _normalize_partial_content(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = ROOT_PLACEHOLDER_PATTERN.sub("/", normalized)
    return normalized.strip()


def _write_text_if_changed(target_path: Path, content: str) -> bool:
    if target_path.exists() and target_path.read_text(encoding="utf-8") == content:
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target_path.parent, delete=False) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)

    temp_path.replace(target_path)
    os.chmod(target_path, 0o644)
    return True


def _normalize_optional_path(raw_value: str | os.PathLike[str] | None, *, base_dir: Path) -> Path | None:
    if raw_value is None:
        return None

    value = str(raw_value).strip()
    if not value:
        return None

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _clean_relative_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().replace("\\", "/")


def _parse_timestamp(raw_value: object, *, fallback_path: Path) -> datetime:
    if isinstance(raw_value, str) and raw_value.strip():
        normalized = raw_value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

    return datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
