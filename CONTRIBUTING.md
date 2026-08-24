# Contributing

This project is in pre-1.0 development. Please open an issue before a large change so behavior, Maya/Bifrost compatibility, and determinism requirements can be agreed first.

## Required checks

1. Run the Python source tests.
2. Build the native core with warnings enabled.
3. Run `ctest` for the native deterministic/parity suite.
4. For Maya host changes, complete the checks in `docs/MAYA_HOST_TEST_JA.md`.

Settled/Final geometry and Stable Cell IDs are CPU-exact contracts. Interactive GPU work must have an explicit off switch and automatic CPU fallback, and must not silently alter saved production output.

Do not submit commercial Houdini assets, extracted HDA scripts, demo scenes, third-party meshes without redistribution permission, Maya/Bifrost SDK binaries, or generated release installers.
