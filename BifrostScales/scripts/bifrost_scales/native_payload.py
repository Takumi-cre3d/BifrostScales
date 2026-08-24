"""Deterministic JSON contract consumed by the native Bifrost operator."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .guides import GuideSet
from .settings import ScaleSettings
from .stable_ids import cell_id_hex, parse_cell_id

NATIVE_PAYLOAD_SCHEMA = "bifrost-scales/native-payload/10"
NATIVE_PAYLOAD_MODES = frozenset({"interactive", "settled", "final"})
_MAX_METADATA_REQUESTS = 4096


def _metadata_indices(values: Sequence[int] | None) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values or ():
        index = int(value)
        if index < 0 or index in seen:
            continue
        seen.add(index)
        result.append(index)
        if len(result) >= _MAX_METADATA_REQUESTS:
            break
    return sorted(result)


def _resolve_ids(values: Sequence[str | int] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        try:
            normalized = cell_id_hex(parse_cell_id(value))
        except ValueError:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= _MAX_METADATA_REQUESTS:
            break
    return sorted(result)


def native_payload_mapping(
    settings: ScaleSettings | Mapping[str, Any],
    guides: GuideSet | None = None,
    mode: str = "settled",
    *,
    cell_metadata_indices: Sequence[int] | None = None,
    resolve_cell_ids: Sequence[str | int] | None = None,
) -> dict[str, Any]:
    """Return the canonical native payload mapping.

    UV seam data was removed from the runtime contract in 0.9.0. Unique Scale
    metadata is opt-in so ordinary preview payloads remain compact.
    """

    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in NATIVE_PAYLOAD_MODES:
        raise ValueError("Unsupported native preview mode: {!r}".format(mode))
    normalized_settings = (
        settings
        if isinstance(settings, ScaleSettings)
        else ScaleSettings.from_mapping(settings)
    )
    normalized_guides = guides if guides is not None else GuideSet()
    settings_mapping = normalized_settings.to_mapping()
    # Registrations are a Maya authoring concern until pinned-site evaluation
    # lands. Do not resend them on every ordinary native preview update.
    settings_mapping.pop("unique_scales", None)
    return {
        "schema": NATIVE_PAYLOAD_SCHEMA,
        "mode": normalized_mode,
        "settings": settings_mapping,
        "guides": normalized_guides.to_mappings(),
        "symmetry_planes": [
            {"origin": list(origin), "normal": list(normal)}
            for origin, normal in normalized_guides.symmetry_planes
        ],
        "cell_metadata_indices": _metadata_indices(cell_metadata_indices),
        "resolve_cell_ids": _resolve_ids(resolve_cell_ids),
    }


def build_native_payload(
    settings: ScaleSettings | Mapping[str, Any],
    guides: GuideSet | None = None,
    mode: str = "settled",
    *,
    cell_metadata_indices: Sequence[int] | None = None,
    resolve_cell_ids: Sequence[str | int] | None = None,
) -> str:
    """Serialize a stable, compact payload for a Bifrost string port."""

    return json.dumps(
        native_payload_mapping(
            settings,
            guides=guides,
            mode=mode,
            cell_metadata_indices=cell_metadata_indices,
            resolve_cell_ids=resolve_cell_ids,
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def validate_native_payload(text: str) -> dict[str, Any]:
    """Validate the Python-side envelope used by host tests and diagnostics."""

    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("Native payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Native payload root must be an object")
    if payload.get("schema") != NATIVE_PAYLOAD_SCHEMA:
        raise ValueError("Unsupported native payload schema")
    if payload.get("mode") not in NATIVE_PAYLOAD_MODES:
        raise ValueError("Native payload mode is invalid")
    if not isinstance(payload.get("settings"), dict):
        raise ValueError("Native payload settings must be an object")
    if not isinstance(payload.get("guides"), list):
        raise ValueError("Native payload guides must be an array")
    if not isinstance(payload.get("symmetry_planes", []), list):
        raise ValueError("Native payload symmetry planes must be an array")
    indices = payload.get("cell_metadata_indices", [])
    if (
        not isinstance(indices, list)
        or len(indices) > _MAX_METADATA_REQUESTS
        or not all(isinstance(value, int) and value >= 0 for value in indices)
    ):
        raise ValueError("Native payload cell metadata indices are invalid")
    ids = payload.get("resolve_cell_ids", [])
    if not isinstance(ids, list) or len(ids) > _MAX_METADATA_REQUESTS:
        raise ValueError("Native payload resolve cell ids are invalid")
    for value in ids:
        if not isinstance(value, str):
            raise ValueError("Native payload resolve cell ids must be strings")
        try:
            parse_cell_id(value)
        except ValueError as exc:
            raise ValueError("Native payload resolve cell id is invalid") from exc
    if "uv_boundary_edges" in payload:
        raise ValueError("UV boundary payload data is no longer supported")
    return payload
