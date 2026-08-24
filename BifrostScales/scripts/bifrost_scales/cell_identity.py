"""Stable cell identity contracts shared by the native host and authoring UI."""

from __future__ import annotations

from dataclasses import dataclass

from .stable_ids import cell_id_hex

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class CellMetadata:
    """Selection/registration metadata returned by the native operator."""

    cell_id: int
    scale_index: int
    position: Vec3
    normal: Vec3
    triangle_index: int
    barycentric: tuple[float, float, float]
    boundary_signature: int = 0

    @property
    def cell_id_hex(self) -> str:
        return cell_id_hex(self.cell_id)
