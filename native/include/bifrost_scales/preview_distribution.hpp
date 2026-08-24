#pragma once

#include "bifrost_scales/core.hpp"
#include "bifrost_scales/gpu_compute.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace bifrost_scales {

inline constexpr const char* kInteractiveCandidateBatchSchema =
    "bifrost-scales/interactive-candidate-batch/1";
inline constexpr const char* kInteractiveConflictReferenceSchema =
    "bifrost-scales/interactive-conflict-reference/1";
inline constexpr const char* kInteractiveConflictGpuSchema =
    "bifrost-scales/interactive-conflict-gpu/1";
inline constexpr std::size_t kInteractiveCandidateRandomStride = 6U;

// GPU-transfer-friendly stochastic surface candidates for Interactive
// Distribution. Boundary and authored Guide anchors intentionally remain in
// the exact CPU path. Calling this API never mutates the Stage Cache or changes
// settled output.
struct InteractiveCandidateBatch {
    std::uint64_t seed{0U};
    std::uint32_t candidate_count{0U};
    double surface_area{0.0};
    std::vector<float> positions_xyz;
    std::vector<float> normals_xyz;
    std::vector<float> barycentric;
    std::vector<float> random_values;
    std::vector<std::uint32_t> triangle_indices;
    std::vector<std::uint64_t> candidate_keys;

    [[nodiscard]] std::size_t upload_bytes() const noexcept;
    [[nodiscard]] bool has_consistent_sizes() const noexcept;
};

// Per-candidate Guide Field results consumed by conflict arbitration. Empty
// arrays select uniform defaults: acceptance=1 and nominal local spacing.
struct InteractiveCandidateFields {
    std::vector<float> density_acceptance;
    std::vector<float> mask_acceptance;
    std::vector<float> local_spacing;

    [[nodiscard]] bool has_consistent_sizes(
        std::size_t candidate_count) const noexcept;
};

// Deterministic CPU reference for the future GPU conflict pass. Candidate
// ordinal is the priority order; accepted indices therefore remain a prefix-
// stable decision stream when candidate_count grows.
struct InteractiveConflictResult {
    std::uint32_t considered_count{0U};
    std::uint32_t accepted_count{0U};
    std::uint32_t rejected_density{0U};
    std::uint32_t rejected_mask{0U};
    std::uint32_t rejected_conflict{0U};
    float default_spacing{0.0F};
    std::vector<std::uint32_t> accepted_candidate_indices;
    std::vector<std::uint64_t> accepted_candidate_keys;

    [[nodiscard]] bool has_consistent_sizes() const noexcept;
};

// The counter-based stream gives a strict prefix property: generating N
// candidates and then M>N candidates produces identical first N entries.
// This allows the Interactive budget to grow without invalidating an existing
// device prefix. The batch is Preview-only and is not the CPU exact Poisson
// sequence used by distribute().
InteractiveCandidateBatch build_interactive_candidate_batch(
    const Mesh& mesh,
    const Settings& settings,
    std::uint32_t candidate_count);

// Applies density/mask stochastic gates, then deterministic spatial conflict
// arbitration. Processing stops after max_accepted candidates have won.
// This reference is Preview-only and never calls or mutates distribute().
InteractiveConflictResult arbitrate_interactive_candidates(
    const InteractiveCandidateBatch& batch,
    const Settings& settings,
    std::uint32_t max_accepted,
    const InteractiveCandidateFields& fields = {});

// Attempts the OpenCL conflict kernel under BIFROST_SCALES_GPU policy and
// falls back to the CPU reference on every unavailable or invalid GPU result.
// The current correctness kernel preserves ordinal priority exactly and is
// intentionally isolated from the Maya runtime.
InteractiveConflictResult arbitrate_interactive_candidates_accelerated(
    const InteractiveCandidateBatch& batch,
    const Settings& settings,
    std::uint32_t max_accepted,
    gpu::ExecutionInfo& execution,
    const InteractiveCandidateFields& fields = {});

}  // namespace bifrost_scales
