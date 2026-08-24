from bifrost_scales.cell_picker_core import (
    CellPickRecord, SpatialCellIndex,
    find_metadata_list, find_scale_count, revision_from_payload, set_query_indices,
    approximate_voronoi_outline,
)

def test_metadata_discovery_and_count():
    profile = {"profile": {"scale_count": 2, "cell_metadata": [
        {"cell_id": "1", "scale_index": 0, "center": [0,0,0], "normal": [0,1,0]},
        {"cell_id": "2", "scale_index": 1, "center": [1,0,0], "normal": [0,1,0]},
    ]}}
    assert find_scale_count(profile) == 2
    assert len(find_metadata_list(profile)) == 2

def test_query_indices_updates_existing_nested_key():
    payload = {"query": {"cell_metadata_indices": []}}
    set_query_indices(payload, [3, 1, 3])
    assert payload["query"]["cell_metadata_indices"] == [1, 3]

def test_revision_ignores_transient_query():
    a = {"seed": 5, "cell_metadata_indices": [1]}
    b = {"seed": 5, "cell_metadata_indices": [999]}
    assert revision_from_payload(a) == revision_from_payload(b)

def test_spatial_pick_selects_nearest_surface_cell():
    records = [
        CellPickRecord("0000000000000001", 0, (0,0,0), (0,1,0), 1.0),
        CellPickRecord("0000000000000002", 1, (4,0,0), (0,1,0), 1.0),
    ]
    index = SpatialCellIndex.build(records)
    hit = index.pick((0.2,0,0.1), (0,10,0), (0,-1,0))
    assert hit is not None and hit.scale_index == 0


def test_approximate_voronoi_outline_is_closed():
    center = CellPickRecord("a", 0, (0,0,0), (0,1,0), 1.0)
    neighbors = [
        CellPickRecord("b", 1, (2,0,0), (0,1,0), 1.0),
        CellPickRecord("c", 2, (-2,0,0), (0,1,0), 1.0),
        CellPickRecord("d", 3, (0,0,2), (0,1,0), 1.0),
        CellPickRecord("e", 4, (0,0,-2), (0,1,0), 1.0),
    ]
    outline = approximate_voronoi_outline(center, neighbors, 1.0)
    assert len(outline) >= 4
    assert outline[0] == outline[-1]
