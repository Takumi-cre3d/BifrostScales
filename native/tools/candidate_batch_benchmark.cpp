#include "bifrost_scales/preview_distribution.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <locale>

namespace {

bifrost_scales::Mesh make_grid(std::uint32_t divisions, double extent) {
    bifrost_scales::Mesh mesh;
    const std::uint32_t row = divisions + 1U;
    for (std::uint32_t z = 0U; z <= divisions; ++z) {
        const double tz = static_cast<double>(z) / divisions;
        for (std::uint32_t x = 0U; x <= divisions; ++x) {
            const double tx = static_cast<double>(x) / divisions;
            mesh.vertices.push_back({
                (tx - 0.5) * extent,
                0.0,
                (tz - 0.5) * extent,
            });
        }
    }
    for (std::uint32_t z = 0U; z < divisions; ++z) {
        for (std::uint32_t x = 0U; x < divisions; ++x) {
            const std::uint32_t a = z * row + x;
            const std::uint32_t b = a + 1U;
            const std::uint32_t d = (z + 1U) * row + x;
            const std::uint32_t c = d + 1U;
            mesh.triangles.push_back({a, c, b});
            mesh.triangles.push_back({a, d, c});
        }
    }
    return mesh;
}

}  // namespace

int main(int argc, char** argv) {
    const std::uint32_t count = argc > 1
        ? static_cast<std::uint32_t>(std::max(1, std::atoi(argv[1])))
        : 40000U;
    const std::uint32_t accepted_limit = std::min(count, 10000U);
    const bifrost_scales::Mesh mesh = make_grid(80U, 20.0);
    bifrost_scales::Settings settings;
    settings.seed = 106U;

    const auto generation_started = std::chrono::steady_clock::now();
    const auto batch = bifrost_scales::build_interactive_candidate_batch(
        mesh,
        settings,
        count);
    const double generation_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - generation_started).count();

    const auto arbitration_started = std::chrono::steady_clock::now();
    const auto arbitration =
        bifrost_scales::arbitrate_interactive_candidates(
            batch,
            settings,
            accepted_limit);
    const double arbitration_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - arbitration_started).count();

    std::cout.imbue(std::locale::classic());
    std::cout << std::fixed << std::setprecision(3)
              << "candidate_count,triangle_count,upload_bytes,generation_ms,"
                 "accepted_count,considered_count,rejected_conflict,"
                 "arbitration_ms\n"
              << batch.candidate_count << ',' << mesh.triangles.size() << ','
              << batch.upload_bytes() << ',' << generation_ms << ','
              << arbitration.accepted_count << ','
              << arbitration.considered_count << ','
              << arbitration.rejected_conflict << ','
              << arbitration_ms << '\n';
    return batch.has_consistent_sizes() &&
            arbitration.has_consistent_sizes()
        ? 0
        : 1;
}
