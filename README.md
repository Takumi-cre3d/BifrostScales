# Bifrost Scales

Bifrost Scales is a procedural scale-generation tool for Autodesk Maya 2026 and Bifrost. It combines a Maya authoring UI, guide-based art direction, a native C++ Bifrost operator, deterministic CPU-exact settled output, and optional OpenCL acceleration for interactive orientation.

[日本語](README_JA.md)

## Requirements and status

- Autodesk Maya 2026
- Autodesk Bifrost for Maya 2026
- Maya C++ toolchain and Bifrost SDK for native source builds
- Runtime baseline: 0.10.6
- Development status: pre-1.0; no packaged public release is available yet

## Features

- Density, size, direction, flow, and mask guides
- Guide groups and symmetry authoring
- Multiple scale types with guide-linked selection
- Stable 64-bit cell identity and per-cell override authoring
- Deterministic multicore CPU distribution, cells, and shape generation
- Process-shared bounded stage cache
- OpenCL interactive orientation with automatic CPU fallback
- Published Bifrost graph v4 and native-only production runtime

## Maya workflow

1. Open Bifrost Scales from the Maya Python API with `import bifrost_scales; bifrost_scales.show()`.
2. Select a polygon mesh and create a Bifrost Scales system.
3. Add and edit guides to control density, size, direction, flow, and masking.
4. Use Interactive preview while authoring and Settled preview for deterministic CPU-exact output.
5. Save the Maya scene; systems, guides, guide groups, scale types, and native graph connections are stored in the scene.

## Execution model

Settled output uses the deterministic CPU-exact path. Interactive orientation can use OpenCL when the workload crosses the configured threshold and falls back to multicore CPU automatically.

The interactive distribution foundation contains two host-independent contracts:

- `bifrost-scales/interactive-candidate-batch/1`: compact, deterministic, prefix-stable surface candidates
- `bifrost-scales/interactive-conflict-reference/1`: deterministic CPU reference for density/mask gates and spatial conflict arbitration

These contracts are not connected to the Maya runtime yet. They cannot modify settled geometry, the Stage Cache, or Stable Cell IDs.

## Current limitations

- Per-cell override values are stored by Maya but are not yet applied by the native shape stage.
- Final and Bake controls remain hidden until their native contracts are complete.
- Interactive distribution conflict arbitration is currently a host-independent CPU reference, not a GPU runtime stage.
- Source builds require the Maya 2026 and Bifrost SDK development environment.

## Build and test

```powershell
cmake -S native -B native/build -DBUILD_TESTING=ON
cmake --build native/build --config Release
ctest --test-dir native/build -C Release --output-on-failure
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Building the Maya/Bifrost operator additionally requires `BIFROST_LOCATION`. See [native build notes](docs/NATIVE_BUILD_JA.md).

## Documentation

- [Architecture](docs/ARCHITECTURE_JA.md)
- [Roadmap](docs/ROADMAP_JA.md)
- [Interactive distribution candidate batch](docs/INTERACTIVE_DISTRIBUTION_CANDIDATE_BATCH_JA.md)
- [Maya host validation](docs/MAYA_HOST_TEST_JA.md)
- [Native validation](docs/NATIVE_VALIDATION_JA.md)
