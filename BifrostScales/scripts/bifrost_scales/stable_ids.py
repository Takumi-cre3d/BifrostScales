"""Deterministic 64-bit identities for generated samples and cells.

The IDs deliberately depend on topology, seed, and the authored candidate key,
not on array position or thread scheduling.  A Maya system scopes the IDs, so
one numeric value can safely exist in two different Bifrost Scales systems.
"""

from __future__ import annotations

from typing import Iterable

FNV_OFFSET_BASIS_64 = 14695981039346656037
FNV_PRIME_64 = 1099511628211
UINT64_MASK = (1 << 64) - 1

ROLE_OPEN_BOUNDARY = 1
ROLE_CURVE_CENTER = 2
ROLE_SURFACE_CANDIDATE = 3


def _fnv_bytes(seed: int, values: bytes) -> int:
    result = int(seed) & UINT64_MASK
    for value in values:
        result ^= int(value)
        result = (result * FNV_PRIME_64) & UINT64_MASK
    return result


def hash_u64(values: Iterable[int], *, tag: str = "") -> int:
    result = FNV_OFFSET_BASIS_64
    if tag:
        result = _fnv_bytes(result, tag.encode("utf-8"))
        result = _fnv_bytes(result, b"\0")
    for value in values:
        result = _fnv_bytes(
            result,
            (int(value) & UINT64_MASK).to_bytes(8, "little", signed=False),
        )
    return result or 1


def hash_text(value: str, *, tag: str = "text") -> int:
    result = _fnv_bytes(FNV_OFFSET_BASIS_64, tag.encode("utf-8") + b"\0")
    result = _fnv_bytes(result, str(value).encode("utf-8"))
    return result or 1


def mesh_topology_hash(vertex_count: int, triangles: Iterable[Iterable[int]]) -> int:
    normalized = tuple(tuple(int(index) for index in triangle) for triangle in triangles)
    values: list[int] = [int(vertex_count), len(normalized)]
    for triangle in normalized:
        if len(triangle) != 3:
            raise ValueError("Stable topology hashing requires triangles")
        values.extend(triangle)
    return hash_u64(values, tag="bifrost-scales/topology/1")


def sample_id(
    topology_hash: int,
    distribution_seed: int,
    role: int,
    *role_values: int,
) -> int:
    return hash_u64(
        (
            int(topology_hash),
            int(distribution_seed),
            int(role),
            *(int(value) for value in role_values),
        ),
        tag="bifrost-scales/cell-id/1",
    )


def cell_id_hex(value: int) -> str:
    return "{:016x}".format(int(value) & UINT64_MASK)


def parse_cell_id(value: str | int) -> int:
    if isinstance(value, int):
        numeric = value
    else:
        text = str(value or "").strip().lower()
        if text.startswith("0x"):
            text = text[2:]
        if not text or len(text) > 16:
            raise ValueError("Cell ID must be a 1-16 digit hexadecimal value")
        try:
            numeric = int(text, 16)
        except ValueError as exc:
            raise ValueError("Cell ID is not hexadecimal") from exc
    numeric &= UINT64_MASK
    if numeric == 0:
        raise ValueError("Cell ID 0000000000000000 is reserved")
    return numeric
