from cadfix.smoke import run


def test_geometry_stack_round_trip():
    r = run()
    assert r.brep_valid
    assert r.manifold_status.endswith("NoError"), r.manifold_status
    assert r.n_triangles > 0
    assert r.brep_volume < r.box_volume  # the fillet really removed material
    assert r.rel_diff < 0.001, f"B-rep {r.brep_volume} vs mesh {r.mesh_volume}"
