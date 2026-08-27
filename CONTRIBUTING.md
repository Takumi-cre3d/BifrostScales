# Contributing

This project is in pre-1.0 development. Please open an issue before a large change so behavior, Maya/Bifrost compatibility, and determinism requirements can be agreed first.

## Required checks

1. Run the Python source tests.
2. Build the native core with warnings enabled.
3. Run `ctest` for the native deterministic/parity suite.
4. For Maya host changes, complete the checks in `docs/MAYA_HOST_TEST_JA.md`.

Final geometry and Stable Cell IDs use the CPU-exact production contract. Settled look-development may use documented deterministic CPU approximations; Interactive GPU work must have an explicit off switch and automatic CPU fallback, and neither path may silently alter Final/Bake output.

Do not submit commercial Houdini assets, extracted HDA scripts, demo scenes, third-party meshes without redistribution permission, Maya/Bifrost SDK binaries, or generated release installers.
