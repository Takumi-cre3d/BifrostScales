"""Versioned settings model shared by UI, scene nodes, and engines."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Mapping, Sequence

from .stable_ids import cell_id_hex, parse_cell_id
from .version import SCHEMA_VERSION


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "off", "no"}:
            return False
        if normalized in {"1", "true", "on", "yes"}:
            return True
    return bool(value)


def _clamp(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    return max(float(minimum), min(float(maximum), numeric))


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = int(default)
    return max(int(minimum), min(int(maximum), numeric))


def _inherit_int(value: Any, minimum: int, maximum: int) -> int:
    """Clamp an integer override while reserving zero for "inherit"."""

    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 0
    if numeric <= 0:
        return 0
    return max(int(minimum), min(int(maximum), numeric))


def _safe_identifier(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    return "".join(character for character in text if character.isalnum() or character in "_-.")[:80] or fallback


def _vec3(value: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        return default
    try:
        result = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        return default
    return result if all(component == component and abs(component) != float("inf") for component in result) else default


def _cell_mode(value: Any, default: str = "auto") -> str:
    normalized = str(value or default).strip().lower()
    aliases = {
        "card": "cards",
        "cards": "cards",
        "cell": "cells",
        "cells": "cells",
        "auto": "auto",
    }
    return aliases.get(normalized, default)


UNIQUE_OVERRIDE_SCHEMA = "bifrost-scales/unique-overrides/1"


@dataclass(frozen=True)
class UniqueScaleOverride:
    """Artist-authored per-cell values stored against a Stable Cell ID.

    0.10.0 deliberately separates authoring persistence from Native mesh
    application.  These values survive scene save/load, Undo/Redo, rebind, and
    multi-selection editing.  The following Native stage consumes the same
    canonical mapping without changing the authoring contract.

    ``offset_u`` and ``offset_v`` are local tangent-frame offsets expressed in
    multiples of the registered cell spacing. ``offset_normal`` uses the same
    normalized unit. ``sides`` and ``divisions`` use zero as "inherit".
    """

    schema: str = UNIQUE_OVERRIDE_SCHEMA
    enabled: bool = False
    offset_u: float = 0.0
    offset_v: float = 0.0
    offset_normal: float = 0.0
    rotation_degrees: float = 0.0
    size_multiplier: float = 1.0
    width_multiplier: float = 1.0
    length_multiplier: float = 1.0
    sides: int = 0
    divisions: int = 0

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any] | None,
    ) -> "UniqueScaleOverride":
        values = values or {}
        return cls(
            schema=UNIQUE_OVERRIDE_SCHEMA,
            enabled=_as_bool(values.get("enabled"), False),
            offset_u=_clamp(values.get("offset_u"), -2.0, 2.0, 0.0),
            offset_v=_clamp(values.get("offset_v"), -2.0, 2.0, 0.0),
            offset_normal=_clamp(
                values.get("offset_normal"), -2.0, 2.0, 0.0
            ),
            rotation_degrees=_clamp(
                values.get("rotation_degrees"), -180.0, 180.0, 0.0
            ),
            size_multiplier=_clamp(
                values.get("size_multiplier"), 0.05, 8.0, 1.0
            ),
            width_multiplier=_clamp(
                values.get("width_multiplier"), 0.05, 8.0, 1.0
            ),
            length_multiplier=_clamp(
                values.get("length_multiplier"), 0.05, 8.0, 1.0
            ),
            sides=_inherit_int(values.get("sides"), 3, 64),
            divisions=_inherit_int(values.get("divisions"), 1, 6),
        )

    def is_authored(self) -> bool:
        return bool(
            self.enabled
            or abs(self.offset_u) > 1.0e-12
            or abs(self.offset_v) > 1.0e-12
            or abs(self.offset_normal) > 1.0e-12
            or abs(self.rotation_degrees) > 1.0e-12
            or abs(self.size_multiplier - 1.0) > 1.0e-12
            or abs(self.width_multiplier - 1.0) > 1.0e-12
            or abs(self.length_multiplier - 1.0) > 1.0e-12
            or self.sides > 0
            or self.divisions > 0
        )


@dataclass(frozen=True)
class UniqueScaleRegistration:
    """Persistent identity snapshot for one artist-registered generated cell."""

    cell_id: str = ""
    name: str = "Unique Scale"
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    normal: tuple[float, float, float] = (0.0, 1.0, 0.0)
    triangle_index: int = 0
    barycentric: tuple[float, float, float] = (1.0, 0.0, 0.0)
    boundary_signature: str = "0000000000000000"
    topology_hash: str = "0000000000000000"
    seed: int = 1
    override: UniqueScaleOverride = field(default_factory=UniqueScaleOverride)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> "UniqueScaleRegistration | None":
        if not isinstance(values, Mapping):
            return None
        try:
            normalized_id = cell_id_hex(parse_cell_id(values.get("cell_id", "")))
        except ValueError:
            return None

        def normalized_hex(name: str) -> str:
            raw = str(values.get(name, "") or "").strip().lower()
            if raw.startswith("0x"):
                raw = raw[2:]
            try:
                return "{:016x}".format(int(raw or "0", 16) & ((1 << 64) - 1))
            except ValueError:
                return "0000000000000000"

        override_values = values.get("override")
        if not isinstance(override_values, Mapping):
            # Accept the short-lived flat prototype keys if a scene was saved
            # with an internal development build.  They are immediately
            # normalized to the public nested schema on the next save.
            override_values = {
                key: values.get(key)
                for key in (
                    "enabled",
                    "offset_u",
                    "offset_v",
                    "offset_normal",
                    "rotation_degrees",
                    "size_multiplier",
                    "width_multiplier",
                    "length_multiplier",
                    "sides",
                    "divisions",
                )
                if key in values
            }

        return cls(
            cell_id=normalized_id,
            name=str(values.get("name", "Unique Scale"))[:64] or "Unique Scale",
            position=_vec3(values.get("position"), (0.0, 0.0, 0.0)),
            normal=_vec3(values.get("normal"), (0.0, 1.0, 0.0)),
            triangle_index=max(0, int(values.get("triangle_index", 0) or 0)),
            barycentric=_vec3(values.get("barycentric"), (1.0, 0.0, 0.0)),
            boundary_signature=normalized_hex("boundary_signature"),
            topology_hash=normalized_hex("topology_hash"),
            seed=_clamp_int(values.get("seed"), -2147483647, 2147483647, 1),
            override=UniqueScaleOverride.from_mapping(override_values),
        )


@dataclass(frozen=True)
class ScaleTypeSettings:
    """One deterministic scale-type slot.

    All types share the active preview topology. Type selection therefore
    changes point positions and colors without changing connectivity whenever
    the scale count and card/cell resolution are unchanged.
    """

    type_id: str = "classic"
    name: str = "Classic"
    enabled: bool = True

    size_multiplier: float = 1.0
    width_multiplier: float = 1.0
    length_multiplier: float = 1.0
    curvature_multiplier: float = 1.0

    offset: float = 0.0
    random_offset: float = 0.0
    tip_offset: float = 0.0

    guide_id: str = ""

    use_custom_color: bool = False
    color_r: float = 0.34
    color_g: float = 0.58
    color_b: float = 0.82

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any] | None,
        fallback: "ScaleTypeSettings | None" = None,
        fallback_id: str = "type",
    ) -> "ScaleTypeSettings":
        values = values or {}
        defaults = fallback or cls(type_id=fallback_id)
        return cls(
            type_id=_safe_identifier(values.get("type_id"), defaults.type_id or fallback_id),
            name=str(values.get("name", defaults.name))[:64] or defaults.name,
            enabled=_as_bool(values.get("enabled"), defaults.enabled),
            size_multiplier=_clamp(
                values.get("size_multiplier"), 0.05, 8.0, defaults.size_multiplier
            ),
            width_multiplier=_clamp(
                values.get("width_multiplier"), 0.05, 8.0, defaults.width_multiplier
            ),
            length_multiplier=_clamp(
                values.get("length_multiplier"), 0.05, 8.0, defaults.length_multiplier
            ),
            curvature_multiplier=_clamp(
                values.get("curvature_multiplier"),
                -4.0,
                4.0,
                defaults.curvature_multiplier,
            ),
            offset=_clamp(values.get("offset"), -4.0, 4.0, defaults.offset),
            random_offset=_clamp(
                values.get("random_offset"), 0.0, 1.0, defaults.random_offset
            ),
            tip_offset=_clamp(values.get("tip_offset"), -1.0, 1.0, defaults.tip_offset),
            guide_id=_safe_identifier(values.get("guide_id"), ""),
            use_custom_color=_as_bool(
                values.get("use_custom_color"), defaults.use_custom_color
            ),
            color_r=_clamp(values.get("color_r"), 0.0, 1.0, defaults.color_r),
            color_g=_clamp(values.get("color_g"), 0.0, 1.0, defaults.color_g),
            color_b=_clamp(values.get("color_b"), 0.0, 1.0, defaults.color_b),
        )

    def color(self, fallback: tuple[float, float, float]) -> tuple[float, float, float, float]:
        if self.use_custom_color:
            return (self.color_r, self.color_g, self.color_b, 1.0)
        return (float(fallback[0]), float(fallback[1]), float(fallback[2]), 1.0)


def default_scale_types() -> tuple[ScaleTypeSettings, ...]:
    return (
        ScaleTypeSettings(type_id="classic", name="Classic", enabled=True),
        ScaleTypeSettings(
            type_id="wide",
            name="Wide",
            enabled=False,
            width_multiplier=1.35,
            length_multiplier=0.85,
            curvature_multiplier=0.8,
            use_custom_color=True,
            color_r=0.28,
            color_g=0.68,
            color_b=0.44,
        ),
        ScaleTypeSettings(
            type_id="sharp",
            name="Sharp",
            enabled=False,
            size_multiplier=0.92,
            width_multiplier=0.82,
            length_multiplier=1.18,
            curvature_multiplier=1.15,
            use_custom_color=True,
            color_r=0.76,
            color_g=0.39,
            color_b=0.24,
        ),
    )


@dataclass(frozen=True)
class ScaleSettings:
    target_count: int = 512
    seed: int = 1
    spacing_factor: float = 0.82
    relax_iterations: int = 0
    relax_strength: float = 0.45

    size: float = 0.1
    lift: float = 0.002
    curvature: float = 0.22
    direction_degrees: float = 0.0
    direction_relax_iterations: int = 0
    direction_relax_strength: float = 0.35
    random_size: float = 0.12
    random_rotation_degrees: float = 8.0

    inset: float = 0.0
    squash: float = 0.0
    expand: float = 0.0
    tip_roundness: float = 0.15
    tip_offset: float = 0.0
    forward_offset: float = 0.0

    # Native preview uses cards while interacting and exact local cells when settled.
    cell_mode: str = "auto"
    cell_growth: float = 0.85
    cell_gap: float = 0.06
    cell_collision_margin: float = 0.02
    cell_radius_multiplier: float = 1.65
    # Number of corresponding interior rings between the unique cell outline
    # and its averaged center.  Shape parameters deform these rings instead
    # of replacing the cell with a shared silhouette.
    cell_shape_divisions: int = 2
    cell_interactive_resolution: int = 6
    cell_settled_resolution: int = 10
    cell_projection_rings: int = 2
    cell_project_to_surface: bool = True

    scale_types: tuple[ScaleTypeSettings, ...] = field(default_factory=default_scale_types)
    unique_scales: tuple[UniqueScaleRegistration, ...] = ()

    interactive_budget: int = 128
    settled_budget: int = 512
    interactive_delay_ms: int = 50
    settled_delay_ms: int = 180
    visible: bool = True
    color_r: float = 0.34
    color_g: float = 0.58
    color_b: float = 0.82

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> "ScaleSettings":
        values = values or {}
        defaults = cls()
        interactive_budget = _clamp_int(
            values.get("interactive_budget"), 1, 50000, defaults.interactive_budget
        )
        scale_types = cls._parse_scale_types(values.get("scale_types"), defaults.scale_types)
        unique_scales = cls._parse_unique_scales(values.get("unique_scales"))
        return cls(
            target_count=_clamp_int(values.get("target_count"), 1, 50000, defaults.target_count),
            seed=_clamp_int(values.get("seed"), -2147483647, 2147483647, defaults.seed),
            spacing_factor=_clamp(
                values.get("spacing_factor"), 0.15, 2.5, defaults.spacing_factor
            ),
            relax_iterations=_clamp_int(
                values.get("relax_iterations"), 0, 64, defaults.relax_iterations
            ),
            relax_strength=_clamp(
                values.get("relax_strength"), 0.0, 1.0, defaults.relax_strength
            ),
            size=_clamp(values.get("size"), 1.0e-6, 1.0e6, defaults.size),
            lift=_clamp(values.get("lift"), -1.0e6, 1.0e6, defaults.lift),
            curvature=_clamp(values.get("curvature"), -4.0, 4.0, defaults.curvature),
            direction_degrees=float(values.get("direction_degrees", defaults.direction_degrees)),
            direction_relax_iterations=_clamp_int(
                values.get("direction_relax_iterations"),
                0,
                64,
                defaults.direction_relax_iterations,
            ),
            direction_relax_strength=_clamp(
                values.get("direction_relax_strength"),
                0.0,
                1.0,
                defaults.direction_relax_strength,
            ),
            random_size=_clamp(values.get("random_size"), 0.0, 0.95, defaults.random_size),
            random_rotation_degrees=_clamp(
                values.get("random_rotation_degrees"),
                0.0,
                180.0,
                defaults.random_rotation_degrees,
            ),
            inset=_clamp(values.get("inset"), 0.0, 0.9, defaults.inset),
            squash=_clamp(values.get("squash"), -0.9, 0.9, defaults.squash),
            expand=_clamp(values.get("expand"), -0.75, 2.0, defaults.expand),
            tip_roundness=_clamp(
                values.get("tip_roundness"), 0.0, 1.0, defaults.tip_roundness
            ),
            tip_offset=_clamp(values.get("tip_offset"), -1.0, 1.0, defaults.tip_offset),
            forward_offset=_clamp(
                values.get("forward_offset"), -2.0, 2.0, defaults.forward_offset
            ),
            cell_mode=_cell_mode(values.get("cell_mode"), defaults.cell_mode),
            cell_growth=_clamp(
                values.get("cell_growth"), 0.0, 1.0, defaults.cell_growth
            ),
            cell_gap=_clamp(values.get("cell_gap"), 0.0, 0.49, defaults.cell_gap),
            cell_collision_margin=_clamp(
                values.get("cell_collision_margin"),
                0.0,
                0.49,
                defaults.cell_collision_margin,
            ),
            cell_radius_multiplier=_clamp(
                values.get("cell_radius_multiplier"),
                0.35,
                6.0,
                defaults.cell_radius_multiplier,
            ),
            cell_shape_divisions=_clamp_int(
                values.get("cell_shape_divisions"),
                1,
                6,
                defaults.cell_shape_divisions,
            ),
            cell_interactive_resolution=_clamp_int(
                values.get("cell_interactive_resolution"),
                4,
                16,
                defaults.cell_interactive_resolution,
            ),
            cell_settled_resolution=_clamp_int(
                values.get("cell_settled_resolution"),
                4,
                32,
                defaults.cell_settled_resolution,
            ),
            cell_projection_rings=_clamp_int(
                values.get("cell_projection_rings"),
                0,
                16,
                defaults.cell_projection_rings,
            ),
            cell_project_to_surface=_as_bool(
                values.get("cell_project_to_surface"),
                defaults.cell_project_to_surface,
            ),
            scale_types=scale_types,
            unique_scales=unique_scales,
            interactive_budget=interactive_budget,
            settled_budget=_clamp_int(
                values.get("settled_budget"), 1, 50000, defaults.settled_budget
            ),
            interactive_delay_ms=_clamp_int(
                values.get("interactive_delay_ms"), 0, 1000, defaults.interactive_delay_ms
            ),
            settled_delay_ms=_clamp_int(
                values.get("settled_delay_ms"), 25, 3000, defaults.settled_delay_ms
            ),
            visible=_as_bool(values.get("visible"), defaults.visible),
            color_r=_clamp(values.get("color_r"), 0.0, 1.0, defaults.color_r),
            color_g=_clamp(values.get("color_g"), 0.0, 1.0, defaults.color_g),
            color_b=_clamp(values.get("color_b"), 0.0, 1.0, defaults.color_b),
        )

    @staticmethod
    def _parse_unique_scales(raw: Any) -> tuple[UniqueScaleRegistration, ...]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return ()
        result: list[UniqueScaleRegistration] = []
        seen: set[str] = set()
        for item in raw[:4096]:
            parsed = UniqueScaleRegistration.from_mapping(item if isinstance(item, Mapping) else None)
            if parsed is None or parsed.cell_id in seen:
                continue
            seen.add(parsed.cell_id)
            result.append(parsed)
        return tuple(result)

    @staticmethod
    def _parse_scale_types(
        raw: Any,
        defaults: tuple[ScaleTypeSettings, ...],
    ) -> tuple[ScaleTypeSettings, ...]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return defaults
        parsed: list[ScaleTypeSettings] = []
        used_ids: set[str] = set()
        for index, item in enumerate(raw[:16]):
            if not isinstance(item, Mapping):
                continue
            fallback = (
                defaults[index]
                if index < len(defaults)
                else ScaleTypeSettings(
                    type_id="type_{}".format(index + 1),
                    name="Type {}".format(index + 1),
                    enabled=False,
                )
            )
            parsed_item = ScaleTypeSettings.from_mapping(
                item,
                fallback=fallback,
                fallback_id="type_{}".format(index + 1),
            )
            candidate_id = parsed_item.type_id
            if candidate_id in used_ids:
                suffix = 2
                while "{}_{}".format(candidate_id, suffix) in used_ids:
                    suffix += 1
                parsed_item = replace(
                    parsed_item,
                    type_id="{}_{}".format(candidate_id, suffix),
                )
            used_ids.add(parsed_item.type_id)
            parsed.append(parsed_item)
        if not parsed:
            return defaults
        if not any(item.enabled for item in parsed):
            first = parsed[0]
            parsed[0] = replace(first, enabled=True)
        return tuple(parsed)

    def effective_count(self, mode: str) -> int:
        mode_name = str(mode).lower()
        if mode_name == "interactive":
            return min(self.target_count, self.interactive_budget)
        if mode_name == "final":
            return self.target_count
        return min(self.target_count, self.settled_budget)

    def effective_relax_iterations(self, mode: str) -> int:
        mode_name = str(mode).lower()
        if mode_name == "interactive":
            return min(self.relax_iterations, 2)
        if mode_name == "settled":
            return min(self.relax_iterations, 16)
        return self.relax_iterations

    def effective_direction_relax_iterations(self, mode: str) -> int:
        mode_name = str(mode).lower()
        if mode_name == "interactive":
            return min(self.direction_relax_iterations, 1)
        if mode_name == "settled":
            return min(self.direction_relax_iterations, 16)
        return self.direction_relax_iterations

    def geometry_kind(self, mode: str) -> str:
        mode_name = str(mode).lower()
        if self.cell_mode == "cards":
            return "card"
        if self.cell_mode == "cells":
            return "cell"
        return "card" if mode_name == "interactive" else "cell"

    def effective_cell_resolution(self, mode: str) -> int:
        mode_name = str(mode).lower()
        if mode_name == "interactive":
            return self.cell_interactive_resolution
        if mode_name == "final":
            return min(64, max(self.cell_settled_resolution, self.cell_settled_resolution + 4))
        return self.cell_settled_resolution

    def effective_cell_projection_rings(self, mode: str) -> int:
        mode_name = str(mode).lower()
        if mode_name == "interactive":
            return min(self.cell_projection_rings, 1)
        if mode_name == "final":
            return min(16, self.cell_projection_rings + 1)
        return self.cell_projection_rings

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        payload = {"schema": SCHEMA_VERSION, "settings": self.to_mapping()}
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str | None) -> "ScaleSettings":
        if not text:
            return cls()
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return cls()
        if isinstance(payload, dict) and isinstance(payload.get("settings"), dict):
            return cls.from_mapping(payload["settings"])
        if isinstance(payload, dict):
            return cls.from_mapping(payload)
        return cls()
