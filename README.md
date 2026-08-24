# Bifrost Scales

Bifrost Scales is a procedural scale-generation tool for Autodesk Maya 2026 and Bifrost. It combines a Maya authoring UI, guide-based art direction, a native C++ Bifrost operator, deterministic CPU-exact settled output, and an optional OpenCL interactive-orientation path.

> Development status: pre-1.0. The current runtime baseline is 0.10.6. Source builds require Maya 2026 and the Bifrost SDK. A packaged public release has not been published yet.

[日本語](README_JA.md)

## Current capabilities

- Density, size, direction, flow, and mask guides
- Guide groups and symmetry authoring
- Multiple scale types with guide-linked selection
- Stable 64-bit cell identity and per-cell override authoring
- Deterministic multicore CPU distribution, cells, and shape generation
- Process-shared bounded stage cache
- OpenCL interactive orientation with automatic CPU fallback
- Published Bifrost graph v4 and native-only production runtime

Per-cell override values are stored by the Maya host but are not yet applied by the native shape stage. Final and Bake UI are also intentionally withheld until their native contracts are complete.

## Development restart

The first post-0.10.6 milestone adds `bifrost-scales/interactive-candidate-batch/1`: a compact, deterministic, prefix-stable surface-candidate stream for future GPU distribution conflict arbitration. It is isolated from the current exact distribution path, so calling it cannot change settled geometry or Stable Cell IDs.

## Build and test the native core

```powershell
cmake -S native -B native/build -DBUILD_TESTING=ON
cmake --build native/build --config Release
ctest --test-dir native/build -C Release --output-on-failure
```

Building the Maya/Bifrost operator additionally requires `BIFROST_LOCATION`; see [native build notes](docs/NATIVE_BUILD_JA.md).

## Python tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The installer tests require a generated release artifact and are excluded from source-only CI.

## Repository policy

This repository starts from the current source state. Historical installers, generated audits, local benchmarks, Houdini reference assets, demo scenes, and the test FBX are intentionally excluded. Release artifacts will be generated from tagged source and attached to GitHub Releases.

The attached Houdini asset was used only for feature-boundary comparison. Its implementation, scripts, encrypted contents, and demo assets are not redistributed or copied into this project.

## License

No open-source license has been selected yet. The source is publicly visible, but all rights are reserved unless a file states otherwise. A distribution license must be chosen before the first public binary release.
