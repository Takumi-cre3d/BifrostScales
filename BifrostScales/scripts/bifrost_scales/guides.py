"""Host-independent guide contracts for density, size, and direction fields.

A guide's geometry and roles are intentionally independent.  A single curve
can therefore affect density, scale size, and stroke-directed orientation at
the same time, matching the original HDA's direction-guide behavior while
keeping stage fingerprints precise for cache invalidation.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass, replace
from enum import Enum
from functools import cached_property
from typing import Iterable, Mapping, Sequence

from .stable_ids import hash_text, hash_u64

from .math3d import (
    Vec3,
    add,
    dot,
    length,
    length_squared,
    mul,
    normalize,
    project_on_plane,
    rotate_around_axis,
    sub,
    vec3,
)


SYMMETRY_AXES = frozenset({"x", "y", "z"})
SYMMETRY_SPACES = frozenset({"world", "target_local"})
MASK_CORE_INFLUENCE = 0.5


def _mask_core_fraction(falloff: float) -> float:
    """Return the normalized distance of the stable no-scale core.

    Mask density now fades according to the existing Guide Falloff control.
    Cells are clipped only at the 50% influence contour, preserving an empty
    center without turning the whole Guide radius into a hard cutout.
    """

    exponent = max(0.1, min(8.0, float(falloff)))
    target_smooth = math.pow(MASK_CORE_INFLUENCE, 1.0 / exponent)
    lower = 0.0
    upper = 1.0
    for _iteration in range(48):
        middle = 0.5 * (lower + upper)
        smooth = 1.0 - middle * middle * (3.0 - 2.0 * middle)
        if smooth > target_smooth:
            lower = middle
        else:
            upper = middle
    return 0.5 * (lower + upper)


def _symmetry_axis(value: object) -> str:
    normalized = str(value).strip().lower()
    return normalized if normalized in SYMMETRY_AXES else "x"


def _symmetry_space(value: object) -> str:
    normalized = str(value).strip().lower().replace(" ", "_")
    if normalized in {"target", "local", "targetlocal"}:
        normalized = "target_local"
    return normalized if normalized in SYMMETRY_SPACES else "world"


def _axis_vector(axis: str) -> Vec3:
    normalized = _symmetry_axis(axis)
    if normalized == "y":
        return (0.0, 1.0, 0.0)
    if normalized == "z":
        return (0.0, 0.0, 1.0)
    return (1.0, 0.0, 0.0)


def _reflect_point(point: Vec3, origin: Vec3, normal: Vec3) -> Vec3:
    offset = sub(point, origin)
    return sub(point, mul(normal, 2.0 * dot(offset, normal)))


def _reflect_vector(value: Vec3, normal: Vec3) -> Vec3:
    return sub(value, mul(normal, 2.0 * dot(value, normal)))


def _points_match(
    left: Sequence[Vec3],
    right: Sequence[Vec3],
    tolerance: float,
) -> bool:
    if len(left) != len(right):
        return False
    threshold_squared = max(1.0e-24, float(tolerance) ** 2)
    return all(
        length_squared(sub(a, b)) <= threshold_squared
        for a, b in zip(left, right)
    )


class GuideKind(str, Enum):
    DENSITY_POINT = "density_point"
    DENSITY_CURVE = "density_curve"
    DIRECTION_POINT = "direction_point"
    DIRECTION_CURVE = "direction_curve"
    FLOW_CURVE = "flow_curve"

    @property
    def stage(self) -> str:
        if self == GuideKind.FLOW_CURVE:
            return "combined"
        return "density" if self.value.startswith("density_") else "direction"

    @property
    def is_curve(self) -> bool:
        return self.value.endswith("_curve")

    @property
    def default_use_density(self) -> bool:
        return self in {
            GuideKind.DENSITY_POINT,
            GuideKind.DENSITY_CURVE,
            GuideKind.FLOW_CURVE,
        }

    @property
    def default_use_size(self) -> bool:
        return self in {
            GuideKind.DENSITY_POINT,
            GuideKind.DENSITY_CURVE,
        }

    @property
    def default_use_direction(self) -> bool:
        return self in {
            GuideKind.DIRECTION_POINT,
            GuideKind.DIRECTION_CURVE,
            GuideKind.FLOW_CURVE,
        }


@dataclass(frozen=True)
class GuideGroupData:
    """Logical group whose values are composed with member guides at read time.

    Authored guide values are never overwritten by group edits.  This keeps
    individual editing fully available while allowing a group to provide
    aggregate range, falloff, density, size, and direction controls.
    """

    group_id: str
    name: str
    enabled: bool = True
    order: int = 0
    radius_multiplier: float = 1.0
    falloff_multiplier: float = 1.0
    density_strength: float = 1.0
    size_strength: float = 1.0
    direction_strength: float = 1.0
    angle_offset_degrees: float = 0.0
    symmetry_enabled: bool = False
    symmetry_axis: str = "x"
    symmetry_space: str = "world"

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "GuideGroupData":
        return cls(
            group_id=str(values.get("group_id", "group"))[:96] or "group",
            name=str(values.get("name", "Guide Group"))[:96] or "Guide Group",
            enabled=bool(values.get("enabled", True)),
            order=int(values.get("order", 0)),
            radius_multiplier=float(values.get("radius_multiplier", 1.0)),
            falloff_multiplier=float(values.get("falloff_multiplier", 1.0)),
            density_strength=float(values.get("density_strength", 1.0)),
            size_strength=float(values.get("size_strength", 1.0)),
            direction_strength=float(values.get("direction_strength", 1.0)),
            angle_offset_degrees=float(values.get("angle_offset_degrees", 0.0)),
            symmetry_enabled=bool(values.get("symmetry_enabled", False)),
            symmetry_axis=_symmetry_axis(values.get("symmetry_axis", "x")),
            symmetry_space=_symmetry_space(
                values.get("symmetry_space", "world")
            ),
        ).normalized()

    def normalized(self) -> "GuideGroupData":
        return GuideGroupData(
            group_id=str(self.group_id).strip()[:96] or "group",
            name=str(self.name).strip()[:96] or "Guide Group",
            enabled=bool(self.enabled),
            order=max(0, int(self.order)),
            radius_multiplier=max(0.05, min(20.0, float(self.radius_multiplier))),
            falloff_multiplier=max(0.125, min(8.0, float(self.falloff_multiplier))),
            density_strength=max(0.0, min(4.0, float(self.density_strength))),
            size_strength=max(0.0, min(4.0, float(self.size_strength))),
            direction_strength=max(0.0, min(1.0, float(self.direction_strength))),
            angle_offset_degrees=max(
                -360.0, min(360.0, float(self.angle_offset_degrees))
            ),
            symmetry_enabled=bool(self.symmetry_enabled),
            symmetry_axis=_symmetry_axis(self.symmetry_axis),
            symmetry_space=_symmetry_space(self.symmetry_space),
        )

    def apply(self, guide: "GuideData") -> "GuideData":
        """Return effective values without mutating the authored guide."""

        group = self.normalized()
        authored = guide.normalized()
        return replace(
            authored,
            group_id=group.group_id,
            enabled=authored.enabled and group.enabled,
            radius=authored.radius * group.radius_multiplier,
            falloff=authored.falloff * group.falloff_multiplier,
            density_multiplier=(
                1.0
                + (authored.density_multiplier - 1.0) * group.density_strength
            ),
            size_multiplier=(
                1.0 + (authored.size_multiplier - 1.0) * group.size_strength
            ),
            strength=authored.strength * group.direction_strength,
            angle_degrees=authored.angle_degrees + group.angle_offset_degrees,
            symmetry_enabled=(
                authored.symmetry_enabled or group.symmetry_enabled
            ),
            symmetry_axis=(
                group.symmetry_axis
                if group.symmetry_enabled
                else authored.symmetry_axis
            ),
            symmetry_space=(
                group.symmetry_space
                if group.symmetry_enabled
                else authored.symmetry_space
            ),
        ).normalized()


@dataclass(frozen=True)
class GuideData:
    guide_id: str
    name: str
    kind: GuideKind
    points: tuple[Vec3, ...]
    order: int = 0
    group_id: str = ""
    symmetry_enabled: bool = False
    symmetry_axis: str = "x"
    symmetry_space: str = "world"
    symmetry_origin: Vec3 = (0.0, 0.0, 0.0)
    symmetry_normal: Vec3 = (1.0, 0.0, 0.0)
    direction: Vec3 = (0.0, 1.0, 0.0)
    enabled: bool = True
    radius: float = 1.0
    falloff: float = 2.0
    density_multiplier: float = 1.0
    size_multiplier: float = 1.0
    strength: float = 1.0
    angle_degrees: float = 0.0
    closed: bool = False
    use_density: bool | None = None
    use_size: bool | None = None
    use_direction: bool | None = None
    use_mask: bool | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "GuideData":
        raw_kind = str(values.get("kind", GuideKind.DENSITY_POINT.value))
        try:
            kind = GuideKind(raw_kind)
        except ValueError:
            kind = GuideKind.DENSITY_POINT
        raw_points = values.get("points", ())
        points: list[Vec3] = []
        if isinstance(raw_points, Sequence) and not isinstance(raw_points, (str, bytes)):
            for item in raw_points:
                try:
                    points.append(vec3(item))  # type: ignore[arg-type]
                except Exception:
                    continue
        if not points:
            points = [(0.0, 0.0, 0.0)]
        try:
            direction = vec3(values.get("direction", (0.0, 1.0, 0.0)))  # type: ignore[arg-type]
        except Exception:
            direction = (0.0, 1.0, 0.0)
        try:
            symmetry_origin = vec3(
                values.get("symmetry_origin", (0.0, 0.0, 0.0))  # type: ignore[arg-type]
            )
        except Exception:
            symmetry_origin = (0.0, 0.0, 0.0)
        symmetry_axis = _symmetry_axis(values.get("symmetry_axis", "x"))
        try:
            symmetry_normal = vec3(
                values.get("symmetry_normal", _axis_vector(symmetry_axis))  # type: ignore[arg-type]
            )
        except Exception:
            symmetry_normal = _axis_vector(symmetry_axis)

        def optional_bool(key: str) -> bool | None:
            return bool(values[key]) if key in values else None

        return cls(
            guide_id=str(values.get("guide_id", "guide"))[:96] or "guide",
            name=str(values.get("name", "Guide"))[:96] or "Guide",
            kind=kind,
            points=tuple(points),
            order=max(
                -2147483647,
                min(2147483647, int(values.get("order", 0))),
            ),
            group_id=str(values.get("group_id", ""))[:96],
            symmetry_enabled=bool(values.get("symmetry_enabled", False)),
            symmetry_axis=symmetry_axis,
            symmetry_space=_symmetry_space(
                values.get("symmetry_space", "world")
            ),
            symmetry_origin=symmetry_origin,
            symmetry_normal=symmetry_normal,
            direction=direction,
            enabled=bool(values.get("enabled", True)),
            radius=max(1.0e-6, float(values.get("radius", 1.0))),
            falloff=max(0.1, min(8.0, float(values.get("falloff", 2.0)))),
            density_multiplier=max(
                0.0,
                min(16.0, float(values.get("density_multiplier", 1.0))),
            ),
            size_multiplier=max(
                0.05,
                min(8.0, float(values.get("size_multiplier", 1.0))),
            ),
            strength=max(0.0, min(1.0, float(values.get("strength", 1.0)))),
            angle_degrees=float(values.get("angle_degrees", 0.0)),
            closed=bool(values.get("closed", False)),
            use_density=optional_bool("use_density"),
            use_size=optional_bool("use_size"),
            use_direction=optional_bool("use_direction"),
            use_mask=optional_bool("use_mask"),
        ).normalized()

    def _resolved_role(self, value: bool | None, default: bool) -> bool:
        return bool(default if value is None else value)

    @property
    def affects_density(self) -> bool:
        return self._resolved_role(self.use_density, self.kind.default_use_density)

    @property
    def affects_size(self) -> bool:
        return self._resolved_role(self.use_size, self.kind.default_use_size)

    @property
    def affects_direction(self) -> bool:
        return self._resolved_role(self.use_direction, self.kind.default_use_direction)

    @property
    def affects_mask(self) -> bool:
        """Whether this guide creates a hard no-scale region."""

        return bool(False if self.use_mask is None else self.use_mask)

    def normalized(self) -> "GuideData":
        points = tuple(vec3(point) for point in self.points) or ((0.0, 0.0, 0.0),)
        kind = GuideKind(self.kind)
        return GuideData(
            guide_id=str(self.guide_id)[:96] or "guide",
            name=str(self.name).strip()[:96] or "Guide",
            kind=kind,
            points=points,
            order=max(-2147483647, min(2147483647, int(self.order))),
            group_id=str(self.group_id).strip()[:96],
            symmetry_enabled=bool(self.symmetry_enabled),
            symmetry_axis=_symmetry_axis(self.symmetry_axis),
            symmetry_space=_symmetry_space(self.symmetry_space),
            symmetry_origin=vec3(self.symmetry_origin),
            symmetry_normal=normalize(
                vec3(self.symmetry_normal),
                _axis_vector(self.symmetry_axis),
            ),
            direction=normalize(vec3(self.direction), (0.0, 1.0, 0.0)),
            enabled=bool(self.enabled),
            radius=max(1.0e-6, float(self.radius)),
            falloff=max(0.1, min(8.0, float(self.falloff))),
            density_multiplier=max(0.0, min(16.0, float(self.density_multiplier))),
            size_multiplier=max(0.05, min(8.0, float(self.size_multiplier))),
            strength=max(0.0, min(1.0, float(self.strength))),
            angle_degrees=float(self.angle_degrees),
            closed=bool(self.closed),
            use_density=self._resolved_role(
                self.use_density,
                kind.default_use_density,
            ),
            use_size=self._resolved_role(
                self.use_size,
                kind.default_use_size,
            ),
            use_direction=self._resolved_role(
                self.use_direction,
                kind.default_use_direction,
            ),
            use_mask=bool(False if self.use_mask is None else self.use_mask),
        )

    @property
    def position(self) -> Vec3:
        return self.points[0]

    def with_symmetry_frame(
        self,
        origin: Vec3,
        normal: Vec3,
    ) -> "GuideData":
        """Return the authored guide with a resolved world-space mirror plane."""

        normalized = self.normalized()
        return replace(
            normalized,
            symmetry_origin=vec3(origin),
            symmetry_normal=normalize(
                vec3(normal),
                _axis_vector(normalized.symmetry_axis),
            ),
        ).normalized()

    def mirrored(self) -> "GuideData | None":
        """Return one non-authored mirror evaluation guide when required.

        The source Guide keeps its ID so Scale Type Guide Links address the
        original and mirrored influence as one logical authoring control.  A
        guide on the mirror plane is not duplicated, preventing doubled
        density or competing direction fields at the symmetry center.
        """

        guide = self.normalized()
        if not guide.symmetry_enabled:
            return None
        normal = normalize(
            guide.symmetry_normal,
            _axis_vector(guide.symmetry_axis),
        )
        mirrored_points = tuple(
            _reflect_point(point, guide.symmetry_origin, normal)
            for point in guide.points
        )
        tolerance = max(1.0e-8, guide.radius * 1.0e-6)
        matches_forward = _points_match(guide.points, mirrored_points, tolerance)
        matches_reverse = (
            guide.kind.is_curve
            and _points_match(
                guide.points,
                tuple(reversed(mirrored_points)),
                tolerance,
            )
        )
        if matches_forward or matches_reverse:
            return None
        return replace(
            guide,
            points=mirrored_points,
            direction=normalize(
                _reflect_vector(guide.direction, normal),
                guide.direction,
            ),
            # Reflection reverses handedness. Negating the authored angular
            # offset preserves a visually symmetric tangent field.
            angle_degrees=-guide.angle_degrees,
            symmetry_enabled=False,
        ).normalized()

    def _nearest_normalized(self, position: Vec3) -> tuple[float, Vec3, Vec3]:
        if not self.kind.is_curve or len(self.points) < 2:
            return (
                length(sub(position, self.position)),
                self.position,
                self.direction,
            )
        best_distance_sq = float("inf")
        best_point = self.points[0]
        best_tangent = normalize(sub(self.points[1], self.points[0]), self.direction)
        segment_count = len(self.points) if self.closed else len(self.points) - 1
        for index in range(segment_count):
            a = self.points[index]
            b = self.points[(index + 1) % len(self.points)]
            segment = sub(b, a)
            denominator = length_squared(segment)
            if denominator <= 1.0e-16:
                continue
            amount = max(0.0, min(1.0, dot(sub(position, a), segment) / denominator))
            closest = add(a, mul(segment, amount))
            distance_sq = length_squared(sub(position, closest))
            if distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
                best_point = closest
                best_tangent = normalize(segment, best_tangent)
        return math.sqrt(best_distance_sq), best_point, best_tangent

    def nearest(self, position: Vec3) -> tuple[float, Vec3, Vec3]:
        return self.normalized()._nearest_normalized(position)

    def _influence_normalized(
        self,
        position: Vec3,
        radius_override: float = 0.0,
    ) -> float:
        if not self.enabled:
            return 0.0
        radius = max(
            1.0e-6,
            float(radius_override) if radius_override > 0.0 else self.radius,
        )
        distance, _nearest, _tangent = self._nearest_normalized(position)
        if distance >= radius:
            return 0.0
        normalized_distance = max(0.0, min(1.0, distance / radius))
        smooth = (
            1.0
            - normalized_distance
            * normalized_distance
            * (3.0 - 2.0 * normalized_distance)
        )
        return math.pow(max(0.0, smooth), self.falloff)

    def influence(self, position: Vec3, radius_override: float = 0.0) -> float:
        return self.normalized()._influence_normalized(
            position,
            radius_override=radius_override,
        )


@dataclass(frozen=True)
class PointGuide:
    """Backward-compatible point-guide helper used by tests and scripts."""

    kind: GuideKind | str
    position: Vec3
    direction: Vec3 = (0.0, 1.0, 0.0)
    radius: float = 1.0
    strength: float = 1.0
    falloff: float = 2.0
    enabled: bool = True
    name: str = ""

    def to_guide(self) -> GuideData:
        raw_kind = self.kind
        if str(raw_kind) in {"density", "GuideKind.DENSITY"}:
            kind = GuideKind.DENSITY_POINT
        elif str(raw_kind) in {"direction", "GuideKind.DIRECTION"}:
            kind = GuideKind.DIRECTION_POINT
        else:
            kind = GuideKind(raw_kind)
        if kind.default_use_density:
            density_multiplier = max(0.0, 1.0 + float(self.strength))
            strength = 1.0
        else:
            density_multiplier = 1.0
            strength = max(0.0, min(1.0, float(self.strength)))
        return GuideData(
            guide_id=self.name or "point_guide",
            name=self.name or "Point Guide",
            kind=kind,
            points=(vec3(self.position),),
            direction=vec3(self.direction),
            enabled=self.enabled,
            radius=self.radius,
            falloff=self.falloff,
            density_multiplier=density_multiplier,
            strength=strength,
        ).normalized()

    def influence(self, position: Vec3) -> float:
        return self.to_guide().influence(position)


def _blend_oriented_direction(
    current: Vec3,
    desired: Vec3,
    normal: Vec3,
    amount: float,
) -> Vec3:
    """Blend directions without losing a deliberate 180-degree reversal."""

    t = max(0.0, min(1.0, float(amount)))
    start = normalize(project_on_plane(current, normal), current)
    target = normalize(project_on_plane(desired, normal), desired)
    if t <= 0.0:
        return start
    if t >= 1.0:
        return target
    cosine = max(-1.0, min(1.0, dot(start, target)))
    if cosine <= -0.999999:
        return normalize(
            rotate_around_axis(start, normal, math.pi * t),
            target,
        )
    return normalize(
        add(mul(start, 1.0 - t), mul(target, t)),
        target,
    )


@dataclass(frozen=True)
class CurveCenterAnchor:
    position: Vec3
    guide_key: int
    ordinal: int
    count: int


@dataclass(frozen=True)
class GuideSet:
    guides: tuple[GuideData, ...] = ()

    @classmethod
    def from_iterable(
        cls,
        guides: Iterable[GuideData | PointGuide] | None,
    ) -> "GuideSet":
        if guides is None:
            return cls()
        normalized: list[GuideData] = []
        for guide in guides:
            value = guide.to_guide() if isinstance(guide, PointGuide) else guide
            normalized.append(value.normalized())
        normalized.sort(key=lambda item: (item.order, item.guide_id))
        return cls(tuple(normalized))

    @cached_property
    def evaluated_guides(self) -> tuple[GuideData, ...]:
        """Return authored guides followed by their transient mirror guides."""

        result: list[GuideData] = []
        for guide in self.guides:
            normalized = guide.normalized()
            result.append(normalized)
            mirrored = normalized.mirrored()
            if mirrored is not None:
                result.append(mirrored)
        return tuple(result)

    def by_stage(self, stage: str) -> tuple[GuideData, ...]:
        normalized = str(stage).strip().lower()
        if normalized == "density":
            return tuple(
                guide
                for guide in self.evaluated_guides
                if guide.enabled and (guide.affects_density or guide.affects_size)
            )
        if normalized == "direction":
            return tuple(
                guide
                for guide in self.evaluated_guides
                if guide.enabled and guide.affects_direction
            )
        return tuple(guide for guide in self.evaluated_guides if guide.enabled)

    @cached_property
    def density(self) -> tuple[GuideData, ...]:
        return self.by_stage("density")

    @cached_property
    def direction(self) -> tuple[GuideData, ...]:
        return self.by_stage("direction")

    @cached_property
    def mask(self) -> tuple[GuideData, ...]:
        """Enabled feathered mask guides evaluated by Distribution and Cells."""

        return tuple(
            guide
            for guide in self.evaluated_guides
            if guide.enabled and guide.affects_mask
        )

    @cached_property
    def symmetry_planes(self) -> tuple[tuple[Vec3, Vec3], ...]:
        """Unique resolved mirror planes used for inexpensive seam stabilization."""

        result: list[tuple[Vec3, Vec3]] = []
        for guide in self.guides:
            normalized = guide.normalized()
            if (
                not normalized.enabled
                or not normalized.symmetry_enabled
                or not (
                    normalized.affects_density
                    or normalized.affects_size
                    or normalized.affects_direction
                    or normalized.affects_mask
                )
            ):
                continue
            origin = normalized.symmetry_origin
            normal = normalize(
                normalized.symmetry_normal,
                _axis_vector(normalized.symmetry_axis),
            )
            duplicate = False
            for existing_origin, existing_normal in result:
                same_normal = abs(dot(existing_normal, normal)) >= 1.0 - 1.0e-9
                same_plane = abs(dot(sub(origin, existing_origin), existing_normal)) <= max(
                    1.0e-8,
                    normalized.radius * 1.0e-7,
                )
                if same_normal and same_plane:
                    duplicate = True
                    break
            if not duplicate:
                result.append((origin, normal))
        return tuple(result)

    def fingerprint(self, stage: str | None = None) -> str:
        """Return a stage-specific cache and change-detection fingerprint.

        ``links`` covers the geometry and membership used by Scale Type Guide
        Links, including guides whose Density/Size/Direction effects are off.
        ``distribution`` covers Density/Size fields plus the Direction Curve
        centerline-anchor contract.  Names remain presentation-only.
        """

        normalized_stage = None if stage is None else str(stage).strip().lower()
        if normalized_stage == "distribution":
            selected = tuple(
                guide
                for guide in self.evaluated_guides
                if guide.enabled
                and (
                    guide.affects_density
                    or guide.affects_size
                    or (guide.kind.is_curve and guide.affects_direction)
                    or guide.affects_mask
                )
            )
            digest = hashlib.blake2b(digest_size=16)
            for guide in selected:
                digest.update(guide.guide_id.encode("utf-8"))
                digest.update(guide.kind.value.encode("ascii"))
                digest.update(struct.pack("<i", guide.order))
                digest.update(struct.pack("<?", guide.enabled))
                digest.update(struct.pack("<I", len(guide.points)))
                for point in guide.points:
                    digest.update(struct.pack("<ddd", *point))
                digest.update(struct.pack("<?", guide.closed))
                density_or_size = guide.affects_density or guide.affects_size
                curve_centerline = (
                    guide.kind.is_curve
                    and guide.affects_direction
                    and guide.strength > 1.0e-12
                )
                digest.update(
                    struct.pack(
                        "<????",
                        density_or_size,
                        guide.affects_density,
                        guide.affects_size,
                        curve_centerline,
                    )
                )
                if density_or_size:
                    digest.update(struct.pack("<dd", guide.radius, guide.falloff))
                    digest.update(
                        struct.pack(
                            "<dd",
                            guide.density_multiplier,
                            guide.size_multiplier,
                        )
                    )
                if curve_centerline:
                    # A positive Direction Strength enables the center row, but
                    # its magnitude affects orientation only. Density and
                    # Poisson spacing decide how many centers survive.
                    digest.update(struct.pack("<?", True))
                digest.update(struct.pack("<?", guide.affects_mask))
                if guide.affects_mask:
                    digest.update(struct.pack("<dd", guide.radius, guide.falloff))
            return digest.hexdigest()

        if normalized_stage == "symmetry":
            digest = hashlib.blake2b(digest_size=16)
            for origin, normal in self.symmetry_planes:
                digest.update(struct.pack("<ddd", *origin))
                digest.update(struct.pack("<ddd", *normal))
            return digest.hexdigest()

        if normalized_stage == "links":
            selected = self.evaluated_guides
        else:
            selected = (
                self.evaluated_guides
                if normalized_stage is None
                else self.by_stage(normalized_stage)
            )
        digest = hashlib.blake2b(digest_size=16)
        if normalized_stage is None:
            # Authored symmetry settings are presentation/editing state even
            # when the guide lies exactly on the plane and produces no clone.
            for authored in self.guides:
                digest.update(authored.guide_id.encode("utf-8"))
                digest.update(authored.name.encode("utf-8"))
                digest.update(struct.pack("<?", authored.symmetry_enabled))
                digest.update(authored.symmetry_axis.encode("ascii"))
                digest.update(authored.symmetry_space.encode("ascii"))
                digest.update(struct.pack("<ddd", *authored.symmetry_origin))
                digest.update(struct.pack("<ddd", *authored.symmetry_normal))
        for guide in selected:
            digest.update(guide.guide_id.encode("utf-8"))
            digest.update(guide.kind.value.encode("ascii"))
            if normalized_stage in {None, "density", "direction"}:
                digest.update(struct.pack("<i", guide.order))
            if normalized_stage is None:
                digest.update(guide.name.encode("utf-8"))
            if normalized_stage in {None, "links"}:
                digest.update(guide.group_id.encode("utf-8"))
            digest.update(struct.pack("<?", guide.enabled))
            digest.update(struct.pack("<I", len(guide.points)))
            for point in guide.points:
                digest.update(struct.pack("<ddd", *point))
            digest.update(struct.pack("<dd?", guide.radius, guide.falloff, guide.closed))
            if normalized_stage in {None, "density"}:
                digest.update(
                    struct.pack(
                        "<??dd",
                        guide.affects_density,
                        guide.affects_size,
                        guide.density_multiplier,
                        guide.size_multiplier,
                    )
                )
            if normalized_stage in {None, "direction"}:
                digest.update(struct.pack("<?", guide.affects_direction))
                if normalized_stage is None:
                    digest.update(struct.pack("<ddd", *guide.direction))
                digest.update(struct.pack("<dd", guide.strength, guide.angle_degrees))
            if normalized_stage is None:
                digest.update(struct.pack("<?", guide.affects_mask))
        return digest.hexdigest()

    def density_factors(self, position: Vec3) -> tuple[float, float]:
        density = 1.0
        size = 1.0
        for guide in self.density:
            influence = guide._influence_normalized(position)
            if guide.affects_density:
                density *= 1.0 + (guide.density_multiplier - 1.0) * influence
            if guide.affects_size:
                size *= 1.0 + (guide.size_multiplier - 1.0) * influence
        return (
            max(0.02, min(16.0, density)),
            max(0.05, min(8.0, size)),
        )

    @cached_property
    def _maximum_density_factor(self) -> float:
        maximum = 1.0
        for guide in self.density:
            if guide.affects_density:
                maximum *= max(1.0, guide.density_multiplier)
        return max(1.0, min(256.0, maximum))

    def maximum_density_factor(self) -> float:
        return self._maximum_density_factor

    def density_acceptance_probability(self, position: Vec3) -> float:
        density, _size = self.density_factors(position)
        return max(0.002, min(1.0, density / self._maximum_density_factor))

    def direction_solution(
        self,
        position: Vec3,
        normal: Vec3,
        fallback: Vec3,
    ) -> tuple[Vec3, float]:
        """Return the guided tangent and aggregate orientation influence.

        Direction Points aim from each sample toward the point position.
        Direction Curves preserve CV[0] -> CV[n] for tangent orientation.
        Cell pairing is intentionally computed separately from Point Guides so
        a drawn curve can pass through cell centers instead of becoming a cell
        boundary.
        """

        guides = self.direction
        base = normalize(project_on_plane(fallback, normal), fallback)
        if not guides:
            return base, 0.0
        accumulated = base
        remaining = 1.0
        for guide in guides:
            weight = max(
                0.0,
                min(1.0, guide.strength * guide._influence_normalized(position)),
            )
            if weight <= 0.0:
                continue
            _distance, nearest, tangent = guide._nearest_normalized(position)
            desired = (
                tangent
                if guide.kind.is_curve
                else sub(nearest, position)
            )
            desired = normalize(project_on_plane(desired, normal), accumulated)
            if abs(guide.angle_degrees) > 1.0e-12:
                desired = normalize(
                    rotate_around_axis(
                        desired,
                        normal,
                        math.radians(guide.angle_degrees),
                    ),
                    accumulated,
                )
            accumulated = _blend_oriented_direction(
                accumulated,
                desired,
                normal,
                weight,
            )
            remaining *= 1.0 - weight
        return normalize(accumulated, base), max(0.0, min(1.0, 1.0 - remaining))

    def guided_direction(self, position: Vec3, normal: Vec3, fallback: Vec3) -> Vec3:
        return self.direction_solution(position, normal, fallback)[0]

    def direction_influence(self, position: Vec3, normal: Vec3, fallback: Vec3) -> float:
        return self.direction_solution(position, normal, fallback)[1]

    def point_direction_influence(self, position: Vec3) -> float:
        """Return the aggregate Direction Point weight used by Cell pairing.

        Curve guides now define a centerline for scale placement.  Keeping
        their influence out of the paired-site Cell stage prevents the drawn
        curve from becoming a Voronoi boundary.  Point guides retain the
        paired-site shaping behavior so cells can still stretch toward the
        point attractor when the global Cell controls request it.
        """

        remaining = 1.0
        for guide in self.direction:
            if guide.kind.is_curve:
                continue
            weight = max(
                0.0,
                min(1.0, guide.strength * guide._influence_normalized(position)),
            )
            remaining *= 1.0 - weight
        return max(0.0, min(1.0, 1.0 - remaining))

    @cached_property
    def curve_center_guides(self) -> tuple[GuideData, ...]:
        """Direction curves whose positive strength enables a center row."""

        return tuple(
            guide
            for guide in self.direction
            if guide.kind.is_curve and guide.strength > 1.0e-12
        )

    def curve_center_anchors(
        self,
        spacing: float,
        limit: int,
    ) -> tuple[CurveCenterAnchor, ...]:
        """Return deterministic Direction-curve center candidates with IDs."""

        remaining = max(0, int(limit))
        base_spacing = max(1.0e-12, float(spacing))
        anchors: list[CurveCenterAnchor] = []
        guide_occurrences: dict[str, int] = {}
        for guide in self.curve_center_guides:
            if remaining <= 0:
                break
            points = guide.points
            segments: list[tuple[Vec3, Vec3, float]] = []
            for start, end in zip(points, points[1:]):
                segment_length = length(sub(end, start))
                if segment_length > 1.0e-12:
                    segments.append((start, end, segment_length))
            if guide.closed and len(points) > 2:
                segment_length = length(sub(points[0], points[-1]))
                if segment_length > 1.0e-12:
                    segments.append((points[-1], points[0], segment_length))
            total_length = sum(segment[2] for segment in segments)
            if total_length <= 1.0e-12:
                continue
            requested = int(math.floor(total_length / base_spacing))
            count = min(remaining, max(1, requested))
            occurrence = guide_occurrences.get(guide.guide_id, 0)
            guide_occurrences[guide.guide_id] = occurrence + 1
            guide_key = hash_u64(
                (
                    hash_text(guide.guide_id, tag="bifrost-scales/curve-guide/1"),
                    occurrence,
                ),
                tag="bifrost-scales/curve-guide-evaluation/1",
            )
            for index in range(count):
                if guide.closed:
                    distance = total_length * float(index) / float(count)
                else:
                    distance = total_length * (float(index) + 0.5) / float(count)
                cursor = 0.0
                for segment_index, (start, end, segment_length) in enumerate(segments):
                    next_cursor = cursor + segment_length
                    if distance <= next_cursor or segment_index == len(segments) - 1:
                        amount = max(
                            0.0,
                            min(1.0, (distance - cursor) / segment_length),
                        )
                        anchors.append(
                            CurveCenterAnchor(
                                position=add(start, mul(sub(end, start), amount)),
                                guide_key=guide_key,
                                ordinal=index,
                                count=count,
                            )
                        )
                        break
                    cursor = next_cursor
            remaining -= count
        return tuple(anchors)

    def curve_center_anchor_positions(
        self,
        spacing: float,
        limit: int,
    ) -> tuple[Vec3, ...]:
        """Backward-compatible position-only view of curve center anchors."""

        return tuple(
            anchor.position
            for anchor in self.curve_center_anchors(spacing, limit)
        )

    def mask_influence(self, position: Vec3) -> float:
        """Return combined stochastic exclusion strength in ``[0, 1]``."""

        remaining = 1.0
        for guide in self.mask:
            influence = max(0.0, min(1.0, guide._influence_normalized(position)))
            remaining *= 1.0 - influence
        return max(0.0, min(1.0, 1.0 - remaining))

    def mask_acceptance_probability(self, position: Vec3) -> float:
        """Probability that a distribution candidate survives Mask Falloff.

        Influence at or above the 50% contour is a deterministic empty core.
        The outer half of the Guide radius feathers smoothly from no scales to
        the unmasked density.
        """

        exclusion = min(1.0, self.mask_influence(position) / MASK_CORE_INFLUENCE)
        return max(0.0, min(1.0, 1.0 - exclusion))

    def is_masked(self, position: Vec3) -> bool:
        """Return True inside the stable 50% no-scale core."""

        return self.mask_influence(position) >= MASK_CORE_INFLUENCE

    @staticmethod
    def _ray_sphere_entry(
        origin: Vec3,
        direction: Vec3,
        center: Vec3,
        radius: float,
        maximum: float,
    ) -> float:
        limit = max(0.0, float(maximum))
        offset = sub(origin, center)
        a = max(1.0e-20, dot(direction, direction))
        b = dot(offset, direction)
        c = dot(offset, offset) - radius * radius
        discriminant = b * b - a * c
        if discriminant < 0.0:
            return limit
        entry = (-b - math.sqrt(max(0.0, discriminant))) / a
        if 0.0 <= entry < limit:
            return entry
        return limit

    @classmethod
    def _ray_capsule_entry(
        cls,
        origin: Vec3,
        direction: Vec3,
        start: Vec3,
        end: Vec3,
        radius: float,
        maximum: float,
    ) -> float:
        """Return exact first entry into a finite segment capsule."""

        limit = max(0.0, float(maximum))
        ray = normalize(direction, (1.0, 0.0, 0.0))
        axis = sub(end, start)
        axis_length_sq = dot(axis, axis)
        if axis_length_sq <= 1.0e-20:
            return cls._ray_sphere_entry(
                origin, ray, start, radius, limit
            )
        offset = sub(origin, start)
        axis_ray = dot(axis, ray)
        axis_offset = dot(axis, offset)
        ray_offset = dot(ray, offset)
        offset_sq = dot(offset, offset)
        coefficient_a = axis_length_sq - axis_ray * axis_ray
        coefficient_b = axis_length_sq * ray_offset - axis_offset * axis_ray
        coefficient_c = (
            axis_length_sq * offset_sq
            - axis_offset * axis_offset
            - radius * radius * axis_length_sq
        )
        best = limit
        if abs(coefficient_a) > 1.0e-20:
            discriminant = (
                coefficient_b * coefficient_b
                - coefficient_a * coefficient_c
            )
            if discriminant >= 0.0:
                entry = (
                    -coefficient_b
                    - math.sqrt(max(0.0, discriminant))
                ) / coefficient_a
                axial = axis_offset + entry * axis_ray
                if 0.0 <= entry < best and 0.0 < axial < axis_length_sq:
                    best = entry
        best = min(
            best,
            cls._ray_sphere_entry(origin, ray, start, radius, best),
            cls._ray_sphere_entry(origin, ray, end, radius, best),
        )
        return best

    def mask_entry_radius(
        self,
        origin: Vec3,
        direction: Vec3,
        maximum: float,
    ) -> float:
        """Return the exact first ray distance entering a Mask hard core.

        Falloff controls stochastic scale removal over the full Guide radius.
        Cell geometry is clipped only at the 50% influence contour, preventing
        outside cells from filling the center while keeping a visible feathered
        transition instead of a hard cut at the outer radius.
        """

        limit = max(0.0, float(maximum))
        if limit <= 1.0e-12 or not self.mask:
            return limit
        if self.is_masked(origin):
            return 0.0
        ray = normalize(direction, (1.0, 0.0, 0.0))
        best = limit
        for guide in self.mask:
            core_radius = guide.radius * _mask_core_fraction(guide.falloff)
            if core_radius <= 1.0e-12:
                continue
            points = guide.points
            if not guide.kind.is_curve or len(points) < 2:
                best = min(
                    best,
                    self._ray_sphere_entry(
                        origin, ray, points[0], core_radius, best
                    ),
                )
                continue
            segment_count = len(points) if guide.closed else len(points) - 1
            for index in range(segment_count):
                best = min(
                    best,
                    self._ray_capsule_entry(
                        origin,
                        ray,
                        points[index],
                        points[(index + 1) % len(points)],
                        core_radius,
                        best,
                    ),
                )
        return best

    def influence_for_id(
        self,
        guide_id: str,
        position: Vec3,
        radius_override: float = 0.0,
    ) -> float:
        """Resolve an exact guide ID first, then a group union.

        Group influence is the maximum enabled-member influence rather than a
        sum, so overlapping members cannot unintentionally amplify Scale Type
        selection bias.
        """

        if not guide_id:
            return 0.0
        exact = 0.0
        found_exact = False
        for guide in self.evaluated_guides:
            if guide.guide_id != guide_id or not guide.enabled:
                continue
            found_exact = True
            exact = max(
                exact,
                guide._influence_normalized(
                    position,
                    radius_override=radius_override,
                ),
            )
        if found_exact:
            return exact
        maximum = 0.0
        for guide in self.evaluated_guides:
            if guide.group_id != guide_id or not guide.enabled:
                continue
            maximum = max(
                maximum,
                guide._influence_normalized(
                    position,
                    radius_override=radius_override,
                ),
            )
        return maximum

    def to_mappings(self, *, evaluated: bool = True) -> list[dict[str, object]]:
        """Serialize concrete guides for the Python/Native operator boundary.

        Native receives the same transient mirror guides used by the Python
        Reference engine.  Symmetry remains authored once in Maya and never
        creates additional DAG nodes.
        """

        selected = self.evaluated_guides if evaluated else self.guides
        return [
            {
                "guide_id": guide.guide_id,
                "name": guide.name,
                "kind": guide.kind.value,
                "order": guide.order,
                "group_id": guide.group_id,
                "points": [list(point) for point in guide.points],
                "direction": list(guide.direction),
                "enabled": guide.enabled,
                "radius": guide.radius,
                "falloff": guide.falloff,
                "density_multiplier": guide.density_multiplier,
                "size_multiplier": guide.size_multiplier,
                "strength": guide.strength,
                "angle_degrees": guide.angle_degrees,
                "closed": guide.closed,
                "use_density": guide.affects_density,
                "use_size": guide.affects_size,
                "use_direction": guide.affects_direction,
                "use_mask": guide.affects_mask,
            }
            for guide in selected
        ]

    def authored_to_mappings(self) -> list[dict[str, object]]:
        """Serialize authored controls, including symmetry metadata."""

        result = self.to_mappings(evaluated=False)
        for mapping, guide in zip(result, self.guides):
            mapping.update(
                {
                    "symmetry_enabled": guide.symmetry_enabled,
                    "symmetry_axis": guide.symmetry_axis,
                    "symmetry_space": guide.symmetry_space,
                    "symmetry_origin": list(guide.symmetry_origin),
                    "symmetry_normal": list(guide.symmetry_normal),
                }
            )
        return result
