#pragma once

#include "bifrost_scales/core.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace bifrost_scales {

inline constexpr const char* kInteractiveCandidateBatchSchema =
    "bifrost-scales/interactive-candidate-batch/1";
inline constexpr std::size_t kInteractiveCandidateRandomStride = 6U;

// GPU-transfer-friendly stochastic surface candidates for Interactive
// Distribution. Boundary and authored Guide anchors intentionally remain in
// the exact CPU path. Candidate conflict arbitration is a separate milestone.
// Calling this API never mutates the Stage Cache or changes settled output.
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

// The counter-based stream gives a strict prefix property: generating N
// candidates and then M>N candidates produces identical first N entries.
// This allows the Interactive budget to grow without invalidating an existing
// device prefix. The batch is Preview-only and is not the CPU exact Poisson
// sequence used by distribute().
InteractiveCandidateBatch build_interactive_candidate_batch(
    const Mesh& mesh,
    const Settings& settings,
    std::uint32_t candidate_count);

}  // namespace bifrost_scales
