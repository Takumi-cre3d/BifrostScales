"""Native-only Bifrost Scales package for Maya 2026."""

from .version import PRODUCT_NAME, SCHEMA_VERSION, VERSION

__version__ = VERSION


def show():
    """Open the Bifrost Scales Maya UI."""

    from .ui import show as _show

    return _show()


def probe_native_backend():
    """Return a read-only report for the native Bifrost pack."""

    from .native_backend import probe_native_backend as _probe

    return _probe()


def run_native_smoke_test(
    settings_node=None,
    evaluate=False,
    cleanup_graph=False,
    auto_create_system=True,
    cleanup_test_system=None,
):
    """Probe or evaluate the production Native Published Graph in Maya."""

    from .native_smoke import run

    return run(
        settings_node=settings_node,
        evaluate=evaluate,
        cleanup_graph=cleanup_graph,
        auto_create_system=auto_create_system,
        cleanup_test_system=cleanup_test_system,
    )


def enable_cell_picker():
    from .cell_picker_maya import enable_cell_picker as _enable
    return _enable()


def disable_cell_picker():
    from .cell_picker_maya import disable_cell_picker as _disable
    return _disable()


def rebuild_cell_picker_cache():
    from .cell_picker_maya import rebuild_cell_picker_cache as _rebuild
    return _rebuild()


def get_cell_picker_selection():
    from .cell_picker_maya import current_selection_records
    return current_selection_records()


def get_cell_picker_debug_snapshot():
    from .cell_picker_maya import cell_picker_debug_snapshot
    return cell_picker_debug_snapshot()


__all__ = [
    "PRODUCT_NAME",
    "SCHEMA_VERSION",
    "VERSION",
    "__version__",
    "show",
    "probe_native_backend",
    "run_native_smoke_test",
    "enable_cell_picker",
    "disable_cell_picker",
    "rebuild_cell_picker_cache",
    "get_cell_picker_selection",
    "get_cell_picker_debug_snapshot",
]


