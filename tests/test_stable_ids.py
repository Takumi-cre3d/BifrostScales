import json

import pytest

from bifrost_scales.cell_identity import CellMetadata
from bifrost_scales.native_payload import NATIVE_PAYLOAD_SCHEMA, build_native_payload
from bifrost_scales.settings import ScaleSettings, UniqueScaleRegistration
from bifrost_scales.stable_ids import (
    ROLE_CURVE_CENTER,
    ROLE_OPEN_BOUNDARY,
    ROLE_SURFACE_CANDIDATE,
    cell_id_hex,
    mesh_topology_hash,
    parse_cell_id,
    sample_id,
)


PLANE_TRIANGLES = ((0, 1, 2), (0, 2, 3))


def test_topology_hash_uses_connectivity_not_positions():
    first = mesh_topology_hash(4, PLANE_TRIANGLES)
    repeated = mesh_topology_hash(4, PLANE_TRIANGLES)
    changed = mesh_topology_hash(4, ((0, 1, 3), (1, 2, 3)))

    assert first == repeated
    assert first != changed


def test_stable_sample_ids_are_deterministic_nonzero_and_role_scoped():
    topology = mesh_topology_hash(4, PLANE_TRIANGLES)
    values = {
        sample_id(topology, 17, ROLE_OPEN_BOUNDARY, 0, 1, 8),
        sample_id(topology, 17, ROLE_CURVE_CENTER, 42, 1, 8),
        sample_id(topology, 17, ROLE_SURFACE_CANDIDATE, 0, 19),
    }
    assert len(values) == 3
    assert 0 not in values
    assert sample_id(topology, 17, ROLE_SURFACE_CANDIDATE, 0, 19) == sample_id(
        topology, 17, ROLE_SURFACE_CANDIDATE, 0, 19
    )
    assert sample_id(topology, 18, ROLE_SURFACE_CANDIDATE, 0, 19) not in values


def test_cell_metadata_is_a_lightweight_native_query_contract():
    item = CellMetadata(
        cell_id=0xAB,
        scale_index=7,
        position=(1.0, 2.0, 3.0),
        normal=(0.0, 1.0, 0.0),
        triangle_index=2,
        barycentric=(0.2, 0.3, 0.5),
        boundary_signature=0xCD,
    )
    assert item.cell_id_hex == "00000000000000ab"
    assert item.scale_index == 7


def test_unique_scale_settings_roundtrip_and_runtime_payload_separation():
    registration = UniqueScaleRegistration(
        cell_id="00000000000000ab",
        name="Landmark",
        position=(1.0, 2.0, 3.0),
        topology_hash="00000000000000cd",
        seed=19,
    )
    settings = ScaleSettings(unique_scales=(registration,))
    roundtrip = ScaleSettings.from_mapping(settings.to_mapping())
    assert roundtrip.unique_scales == (registration,)

    payload = json.loads(
        build_native_payload(
            settings,
            mode="settled",
            cell_metadata_indices=(3, 3, 1),
            resolve_cell_ids=("0xab", "00000000000000ab"),
        )
    )
    assert payload["schema"] == NATIVE_PAYLOAD_SCHEMA
    assert "unique_scales" not in payload["settings"]
    assert payload["cell_metadata_indices"] == [1, 3]
    assert payload["resolve_cell_ids"] == ["00000000000000ab"]


def test_cell_id_text_validation():
    assert parse_cell_id("0x1a") == 0x1A
    assert cell_id_hex(0x1A) == "000000000000001a"
    with pytest.raises(ValueError):
        parse_cell_id("0")
    with pytest.raises(ValueError):
        parse_cell_id("not-hex")
