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

- Density, size, direction, flow, and mask guides with surface-connected distance, Range as the outer limit, and normalized 0-1 Falloff width
- Masks preserve completed Cell placement and shape, then control mesh emission deterministically from Stable Cell IDs
- Guide groups and symmetry authoring
- Multiple scale types with guide-linked selection
- Stable 64-bit cell identity and mesh-free picker metadata
- Deterministic multicore CPU distribution, cells, and shape generation
- Process-shared bounded stage cache
- Reusable target-mesh topology, boundary, and surface-guide acceleration data across edits
- OpenCL interactive orientation with automatic CPU fallback
- Published Bifrost graph v4 and native-only production runtime

## Maya workflow

1. Open Bifrost Scales from the Maya Python API with `import bifrost_scales; bifrost_scales.show()`.
2. Select a polygon mesh and create a Bifrost Scales system.
3. Add and edit guides to control density, size, direction, flow, and masking.
4. Use Interactive preview while authoring and Settled preview for deterministic CPU-exact output.
5. Save the Maya scene; systems, guides, guide groups, scale types, and native graph connections are stored in the scene.

## Execution model

Settled output keeps the deterministic CPU-exact path. Interactive Distribution evaluates compact, deterministic, prefix-stable surface candidates in parallel and arbitrates spatial conflicts with OpenCL. It falls back automatically to the same-priority CPU reference when GPU execution is unavailable. CPU-authored open-boundary and Guide-curve anchors, surface-connected Guide fields, Stable Cell IDs, and post-Cell Mask filtering remain intact.

- `bifrost-scales/interactive-candidate-batch/1`: production Interactive surface candidates
- `bifrost-scales/interactive-conflict-reference/1`: deterministic CPU fallback
- `bifrost-scales/interactive-conflict-gpu/1`: exact-priority parallel OpenCL arbitration

GPU conflict arbitration uses an 8,192-candidate automatic crossover by default; `BIFROST_SCALES_GPU_MIN_CANDIDATES` overrides it.

## Current limitations

- Final and Bake controls remain hidden until their native contracts are complete.
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
- [GPU conflict arbitration](docs/INTERACTIVE_DISTRIBUTION_GPU_CONFLICT_JA.md)
- [Maya host validation](docs/MAYA_HOST_TEST_JA.md)
- [Native validation](docs/NATIVE_VALIDATION_JA.md)
