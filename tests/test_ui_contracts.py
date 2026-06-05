from __future__ import annotations


def test_ui_import_root_and_boundary_contract_are_stable() -> None:
    import sophiagraph.ui as ui

    boundary = ui.build_default_ui_boundary()
    assert boundary.owner_import_root == "sophiagraph.ui"
    assert boundary.runtime_package == "sophiagraph-server"
    assert boundary.transport == "rest"
    assert boundary.transport_status == "designed_not_implemented"
    assert boundary.imports_openminion is False
    assert boundary.imports_runtime_package is False


def test_ui_screen_manifest_covers_mvp_and_secondary_routes() -> None:
    from sophiagraph.ui import build_ui_screen_manifest

    screens = build_ui_screen_manifest()
    assert [screen.screen_id for screen in screens] == [
        "explore",
        "record_detail",
        "graph",
        "operations",
        "repair",
        "community",
        "timeline",
        "schema",
    ]
    assert [screen.screen_id for screen in screens if screen.mvp] == [
        "explore",
        "record_detail",
        "graph",
        "operations",
        "repair",
    ]
