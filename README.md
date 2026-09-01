# Bifrost Scales

Bifrost Scales is a procedural scale-generation tool for Autodesk Maya 2026 and Bifrost. It combines a Maya authoring UI, guide-based art direction, a native C++ Bifrost operator, deterministic CPU-exact settled output, and optional OpenCL acceleration for interactive orientation.

[日本語](README_JA.md)

## Requirements and status

- Autodesk Maya 2026
- Autodesk Bifrost for Maya 2026
- Maya C++ toolchain and Bifrost SDK for native source builds
- Runtime baseline: 0.10.9
- Release status: 0.10.9 Public Beta for evaluation; production UI/UX work continues separately

## Features

- Density, size, direction, flow, and mask guides with surface-connected distance, Range as the outer limit, and normalized 0-1 Falloff width
- Independently authored Direction orientation, Direction Curve center alignment, and bounded anisotropic Cell partitioning (`Direction Strength`, per-guide `Center Alignment`, per-guide `Cell Anisotropy`, plus global `Cell Direction Anisotropy`)
- Masks preserve completed Cell placement and shape, then control mesh emission deterministically from Stable Cell IDs
- Guide groups and symmetry authoring
- Multiple scale types with guide-linked selection
- Stable 64-bit cell identity and mesh-free picker metadata
- Deterministic multicore CPU distribution, cells, and shape generation
- Exact BVH-indexed Cell neighbor search for large radii and uneven density
- Owner-safe Collision Margin constraints that remain valid under strong local Density guides
- Curvature-following Cell interiors with selective exact surface reprojection on tight bends
- Exact BVH lookup for open-boundary candidates, with a closed-mesh fast path that skips traversal
- Process-shared bounded stage, per-guide geodesic-field, and Interactive surface-sampling caches
- Reusable target-mesh topology, boundary, area/normal sampling tables, and Surface Guide fields across edits
- Cell and Surface Guide setup, cache reuse, neighbor, boundary-query, boundary-ray, and surface-projection diagnostics in the Performance log
- OpenCL interactive orientation with automatic CPU fallback
- Published Bifrost graph v4 and native-only production runtime

## Installation bundle

The prebuilt Maya 2026 distribution ZIP is installed on another Windows PC by extracting it, closing Maya, and double-clicking `Install_BifrostScales.cmd`; no local build is required. The installer verifies every payload file, backs up an existing installation, registers the bundled Native Pack, and rolls back on failure. See [one-click installer details](docs/ONE_CLICK_INSTALLER_JA.md).

## Maya workflow

1. Open Bifrost Scales from the Maya Python API with `import bifrost_scales; bifrost_scales.show()`.
2. Select a polygon mesh and create a Bifrost Scales system.
3. Add and edit guides to control density, size, direction, flow, and masking. `Direction Strength` controls scale orientation, `Center Alignment` controls the fraction of curve-centered candidates, and per-guide `Cell Anisotropy` scales the global `Cell Direction Anisotropy`.
4. Use Interactive preview while authoring and Settled preview for deterministic CPU output.
5. Save the Maya scene; systems, guides, guide groups, scale types, and native graph connections are stored in the scene.

## Execution model

Cell partition constraints cap a fixed Gap or Collision Margin before it can cross the owning seed, preventing isolated oversized fallback Cells in high-density guide regions. Projected boundary midpoints provide a cached quadratic surface approximation for Shape edits; Cells whose sag or normal bend exceeds the safe threshold reproject their deformed inner rings and center exactly against the connected target surface. The exact path is selective, so planar and gently curved cached Cells retain the lightweight Shape path.

Settled output caches the surface-connected Guide field at visited triangle corners and interpolates deterministically inside each triangle, accelerating look-development redistribution. Orientation evaluates each sample's Direction Guide field once and reuses it for initial and final direction solving; multi-iteration Settled Direction Relax stores only distance-qualified neighbors in a bounded compact CSR array and reuses that graph across Direction-only edits while Distribution remains unchanged. The Native Performance log exposes Orientation as prepare / neighbors / relax / finalize timings plus the neighbor-cache state. Final keeps the previous per-candidate double-precision CPU-exact evaluation. Interactive Distribution evaluates compact, deterministic, prefix-stable surface candidates in parallel and arbitrates spatial conflicts with OpenCL. It falls back automatically to the same-priority CPU reference when GPU execution is unavailable. CPU-authored open-boundary and Guide-curve anchors, Stable Cell IDs, and post-Cell Mask filtering remain intact. Direction anisotropy changes only the pair-symmetric metric between neighboring Cells, without adding or removing centers. The global maximum uses a bounded 2.25 axis ratio, while each guide can reduce or disable its contribution independently.
For multi-iteration Settled previews above the GPU crossover, surface-connected Guide evaluation stays CPU-exact while compact-CSR Direction Relax runs on OpenCL. Any unavailable device, dense-neighborhood fallback, or GPU failure automatically keeps the existing CPU path.
GPU staging uses compact serial conversion for the typical 8k-15k settled sample range, avoiding temporary thread startup. The Native Profile log reports `relaxParts=pack/gpu-call/unpack` for diagnosis.


- `bifrost-scales/interactive-candidate-batch/1`: production Interactive surface candidates
- `bifrost-scales/interactive-conflict-reference/1`: deterministic CPU fallback
- `bifrost-scales/interactive-conflict-gpu/1`: exact-priority parallel OpenCL arbitration

GPU conflict arbitration uses a 65,536-candidate automatic crossover by default; `BIFROST_SCALES_GPU_MIN_CANDIDATES` overrides it.

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
