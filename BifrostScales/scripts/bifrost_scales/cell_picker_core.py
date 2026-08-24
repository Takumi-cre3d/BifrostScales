from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import statistics
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Optional, Sequence

PICKER_SCHEMA = "bifrost-scales/cell-picker/1"
_QUERY_KEYS = {"cell_metadata_indices", "resolve_cell_ids", "pick_cache_enabled"}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _vec3(value: Any) -> Optional[tuple[float, float, float]]:
    if isinstance(value, Mapping):
        keys = (("x", "y", "z"), ("X", "Y", "Z"), ("r", "g", "b"))
        for names in keys:
            if all(name in value for name in names):
                return tuple(_as_float(value[name]) for name in names)  # type: ignore[return-value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 3:
        return (_as_float(value[0]), _as_float(value[1]), _as_float(value[2]))
    return None


def _first(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _normalize_cell_id(value: Any) -> str:
    if isinstance(value, int):
        return f"{value & 0xFFFFFFFFFFFFFFFF:016x}"
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    try:
        return f"{int(text, 16) & 0xFFFFFFFFFFFFFFFF:016x}"
    except ValueError:
        digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()
        return digest


@dataclass(frozen=True)
class CellPickRecord:
    cell_id: str
    scale_index: int
    center: tuple[float, float, float]
    normal: tuple[float, float, float]
    radius: float = 0.0
    outline: tuple[tuple[float, float, float], ...] = ()
    source_triangle: int = -1
    preview_revision: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, fallback_index: int = 0, revision: str = "") -> "CellPickRecord":
        cell_id = _normalize_cell_id(_first(data, ("cell_id", "stable_cell_id", "id", "cellId")))
        scale_index = _as_int(_first(data, ("scale_index", "cell_index", "index", "scaleIndex")), fallback_index)
        center = _vec3(_first(data, ("center", "position", "cell_center", "world_center", "sample_position"))) or (0.0, 0.0, 0.0)
        normal = _vec3(_first(data, ("normal", "cell_normal", "surface_normal", "sample_normal"))) or (0.0, 1.0, 0.0)
        length = math.sqrt(sum(v * v for v in normal))
        if length > 1.0e-12:
            normal = tuple(v / length for v in normal)  # type: ignore[assignment]
        radius = _as_float(_first(data, ("radius", "cell_radius", "local_spacing", "spacing", "sample_spacing")), 0.0)
        tri = _as_int(_first(data, ("source_triangle", "triangle_index", "triangle", "sourceTriangle")), -1)
        outline_value = _first(data, ("outline", "outer_ring", "outer_ring_points", "boundary", "boundary_points", "cell_boundary"))
        outline: list[tuple[float, float, float]] = []
        if isinstance(outline_value, Sequence) and not isinstance(outline_value, (str, bytes)):
            for item in outline_value:
                p = _vec3(item)
                if p is not None:
                    outline.append(p)
        return cls(cell_id, scale_index, center, normal, max(0.0, radius), tuple(outline), tri, revision)


def iter_mappings(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from iter_mappings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from iter_mappings(child)


def find_scale_count(profile: Any) -> int:
    best = 0
    for mapping in iter_mappings(profile):
        for key, value in mapping.items():
            if str(key).lower() in {"scale_count", "cell_count", "sample_count"}:
                best = max(best, _as_int(value, 0))
    return best


def find_metadata_list(profile: Any) -> list[Mapping[str, Any]]:
    candidates: list[list[Mapping[str, Any]]] = []
    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_l = str(key).lower()
                if isinstance(child, list) and child and all(isinstance(x, Mapping) for x in child):
                    sample = child[0]
                    sample_keys = {str(k).lower() for k in sample.keys()}
                    score = len(sample_keys.intersection({"cell_id", "stable_cell_id", "cell_index", "scale_index", "center", "position"}))
                    if "metadata" in key_l or score >= 2:
                        candidates.append(child)  # type: ignore[arg-type]
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(profile)
    if not candidates:
        return []
    return max(candidates, key=len)


def set_query_indices(payload: MutableMapping[str, Any], indices: Sequence[int]) -> None:
    normalized = sorted({max(0, int(i)) for i in indices})
    found = False
    def walk(mapping: MutableMapping[str, Any]) -> None:
        nonlocal found
        for key, value in list(mapping.items()):
            if str(key) == "cell_metadata_indices":
                mapping[key] = normalized
                found = True
            elif isinstance(value, MutableMapping):
                walk(value)
    walk(payload)
    if not found:
        payload["cell_metadata_indices"] = normalized


def clear_transient_queries(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): clear_transient_queries(v) for k, v in value.items() if str(k) not in _QUERY_KEYS}
    if isinstance(value, list):
        return [clear_transient_queries(v) for v in value]
    return value


def revision_from_payload(payload: Mapping[str, Any], profile: Any = None) -> str:
    profile_revision = None
    if profile is not None:
        for mapping in iter_mappings(profile):
            profile_revision = _first(mapping, ("preview_revision", "revision", "payload_hash"))
            if profile_revision not in (None, ""):
                break
    if profile_revision not in (None, ""):
        return str(profile_revision)
    canonical = json.dumps(clear_transient_queries(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.blake2b(canonical.encode("utf-8"), digest_size=12).hexdigest()


def _sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def _length_sq(v: Sequence[float]) -> float:
    return _dot(v, v)


def approximate_voronoi_outline(record: CellPickRecord, neighbors: Sequence[CellPickRecord], default_radius: float) -> list[tuple[float, float, float]]:
    """Build a lightweight display outline from neighboring stable cell centers.

    This is used only when an older native pack returns center/normal metadata
    without explicit boundary points.  It does not change the generated cells
    or the Stable Cell ID; it is a visual picking proxy.
    """
    n = record.normal
    helper = (0.0, 1.0, 0.0) if abs(n[1]) < 0.9 else (1.0, 0.0, 0.0)
    u = (n[1]*helper[2]-n[2]*helper[1], n[2]*helper[0]-n[0]*helper[2], n[0]*helper[1]-n[1]*helper[0])
    ul = math.sqrt(_length_sq(u)) or 1.0
    u = tuple(v/ul for v in u)
    v = (n[1]*u[2]-n[2]*u[1], n[2]*u[0]-n[0]*u[2], n[0]*u[1]-n[1]*u[0])
    radius = max(record.radius, default_radius, 1.0e-5)
    extent = radius * 2.25
    polygon: list[tuple[float,float]] = [(-extent,-extent),(extent,-extent),(extent,extent),(-extent,extent)]

    def clip(poly: list[tuple[float,float]], nx: float, ny: float, right: float) -> list[tuple[float,float]]:
        if not poly: return []
        result: list[tuple[float,float]] = []
        previous = poly[-1]
        prev_value = nx*previous[0] + ny*previous[1] - right
        prev_inside = prev_value <= 1.0e-9
        for current in poly:
            cur_value = nx*current[0] + ny*current[1] - right
            cur_inside = cur_value <= 1.0e-9
            if cur_inside != prev_inside:
                denom = prev_value - cur_value
                t = prev_value / denom if abs(denom) > 1.0e-12 else 0.0
                result.append((previous[0] + (current[0]-previous[0])*t, previous[1] + (current[1]-previous[1])*t))
            if cur_inside: result.append(current)
            previous, prev_value, prev_inside = current, cur_value, cur_inside
        return result

    ordered = []
    for other in neighbors:
        if other.cell_id == record.cell_id: continue
        d = _sub(other.center, record.center)
        dx, dy = _dot(d,u), _dot(d,v)
        dist2 = dx*dx + dy*dy
        if dist2 <= 1.0e-12 or dist2 > (extent*3.0)**2: continue
        ordered.append((dist2, other.scale_index, dx, dy))
    ordered.sort()
    for dist2, _, dx, dy in ordered[:32]:
        polygon = clip(polygon, dx, dy, 0.5*dist2)
        if len(polygon) < 3: break
    if len(polygon) < 3:
        polygon = []
        for i in range(24):
            a=2.0*math.pi*i/24.0; polygon.append((radius*math.cos(a),radius*math.sin(a)))
    points = [tuple(record.center[j] + x*u[j] + y*v[j] for j in range(3)) for x,y in polygon]
    if points: points.append(points[0])
    return points


@dataclass
class SpatialCellIndex:
    records: tuple[CellPickRecord, ...]
    cell_size: float = 1.0
    grid: dict[tuple[int, int, int], list[int]] = field(default_factory=dict)
    by_id: dict[str, int] = field(default_factory=dict)

    @classmethod
    def build(cls, records: Sequence[CellPickRecord]) -> "SpatialCellIndex":
        recs = list(records)
        if not recs:
            return cls(())
        explicit = [r.radius for r in recs if r.radius > 1.0e-9]
        xs = [r.center[0] for r in recs]; ys = [r.center[1] for r in recs]; zs = [r.center[2] for r in recs]
        diag = math.sqrt((max(xs)-min(xs))**2 + (max(ys)-min(ys))**2 + (max(zs)-min(zs))**2)
        estimated = diag / max(1.0, math.sqrt(float(len(recs))))
        base_radius = statistics.median(explicit) if explicit else max(estimated, 1.0e-4)
        normalized: list[CellPickRecord] = []
        for r in recs:
            radius = r.radius if r.radius > 1.0e-9 else base_radius * 0.65
            normalized.append(CellPickRecord(r.cell_id, r.scale_index, r.center, r.normal, radius, r.outline, r.source_triangle, r.preview_revision))
        cell_size = max(base_radius * 2.0, 1.0e-5)
        index = cls(tuple(normalized), cell_size)
        for i, record in enumerate(index.records):
            key = index.key(record.center)
            index.grid.setdefault(key, []).append(i)
            index.by_id[record.cell_id] = i
        return index

    def key(self, p: Sequence[float]) -> tuple[int, int, int]:
        s = self.cell_size
        return (math.floor(p[0]/s), math.floor(p[1]/s), math.floor(p[2]/s))

    def nearby_indices(self, p: Sequence[float], rings: int = 2) -> Iterator[int]:
        base = self.key(p)
        seen: set[int] = set()
        for dz in range(-rings, rings+1):
            for dy in range(-rings, rings+1):
                for dx in range(-rings, rings+1):
                    for idx in self.grid.get((base[0]+dx, base[1]+dy, base[2]+dz), ()):
                        if idx not in seen:
                            seen.add(idx)
                            yield idx

    def pick(self, surface_point: Sequence[float], ray_origin: Sequence[float], ray_direction: Sequence[float]) -> Optional[CellPickRecord]:
        best: Optional[CellPickRecord] = None
        best_score = float("inf")
        candidates = list(self.nearby_indices(surface_point, 2))
        if not candidates:
            candidates = list(self.nearby_indices(surface_point, 5))
        for idx in candidates:
            rec = self.records[idx]
            delta = _sub(surface_point, rec.center)
            normal_depth = abs(_dot(delta, rec.normal))
            tangent_sq = max(0.0, _length_sq(delta) - normal_depth*normal_depth)
            radius = max(rec.radius, self.cell_size*0.2, 1.0e-6)
            tangent = math.sqrt(tangent_sq)
            if tangent > radius * 1.8 and not rec.outline:
                continue
            ray_delta = _sub(rec.center, ray_origin)
            ray_t = max(0.0, _dot(ray_delta, ray_direction))
            closest = (ray_origin[0]+ray_direction[0]*ray_t, ray_origin[1]+ray_direction[1]*ray_t, ray_origin[2]+ray_direction[2]*ray_t)
            ray_distance = math.sqrt(_length_sq(_sub(rec.center, closest)))
            score = tangent/radius + 0.35*normal_depth/radius + 0.15*ray_distance/radius
            if score < best_score:
                best_score = score
                best = rec
        return best if best_score <= 2.75 else None

    def get(self, cell_id: str) -> Optional[CellPickRecord]:
        idx = self.by_id.get(_normalize_cell_id(cell_id))
        return self.records[idx] if idx is not None else None
