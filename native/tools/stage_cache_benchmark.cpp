#include "bifrost_scales/core.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <locale>
#include <thread>

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

struct Measurement {
    bifrost_scales::GenerationResult result;
    double wall_ms{0.0};
};

Measurement measure_on_new_worker(
    const bifrost_scales::Mesh& mesh,
    const bifrost_scales::Settings& settings,
    const bifrost_scales::GenerationOptions& options) {
    Measurement measurement;
    std::thread worker([&]() {
        const auto started = std::chrono::steady_clock::now();
        measurement.result = bifrost_scales::generate(
            mesh,
            settings,
            bifrost_scales::PreviewMode::Settled,
            {},
            options);
        measurement.wall_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - started).count();
    });
    worker.join();
    return measurement;
}

}  // namespace

int main(int argc, char** argv) {
    const std::uint32_t requested = argc > 1
        ? static_cast<std::uint32_t>(std::max(1, std::atoi(argv[1])))
        : 10000U;
    const bifrost_scales::Mesh mesh = make_grid(80U, 10.0);
    bifrost_scales::Settings settings;
    settings.target_count = requested;
    settings.settled_budget = requested;
    settings.seed = 105U;
    settings.cell_mode = bifrost_scales::GeometryMode::Cells;
    settings.relax_iterations = 1U;
    settings.direction_relax_iterations = 0U;
    settings.cell_settled_resolution = 12U;
    bifrost_scales::GenerationOptions options;
    options.include_uvs = false;
    options.include_colors = false;
    options.include_scale_type_ids = false;
    options.materialize_faces = false;
    options.include_flat_topology = true;

    bifrost_scales::clear_native_stage_cache();
    const Measurement cold = measure_on_new_worker(mesh, settings, options);
    const Measurement migrated = measure_on_new_worker(mesh, settings, options);
    const bool exact =
        cold.result.mesh.vertices == migrated.result.mesh.vertices &&
        cold.result.mesh.face_offsets == migrated.result.mesh.face_offsets &&
        cold.result.mesh.face_vertices == migrated.result.mesh.face_vertices &&
        cold.result.mesh.cell_ids == migrated.result.mesh.cell_ids;

    std::cout.imbue(std::locale::classic());
    std::cout << std::fixed << std::setprecision(3)
              << "{\"schema\":\"bifrost-scales/stage-cache-benchmark/1\""
              << ",\"requested\":" << requested
              << ",\"accepted\":" << cold.result.report.accepted_count
              << ",\"cache_scope\":\""
              << migrated.result.profile.stage_cache_scope << "\""
              << ",\"cache_capacity\":"
              << migrated.result.profile.stage_cache_capacity
              << ",\"cold_wall_ms\":" << cold.wall_ms
              << ",\"migrated_wall_ms\":" << migrated.wall_ms
              << ",\"distribution_hit\":"
              << (migrated.result.profile.distribution_cache_hit ? "true" : "false")
              << ",\"orientation_hit\":"
              << (migrated.result.profile.orientation_cache_hit ? "true" : "false")
              << ",\"cell_hit\":"
              << (migrated.result.profile.cell_cache_hit ? "true" : "false")
              << ",\"exact\":" << (exact ? "true" : "false")
              << "}\n";
    return exact &&
        migrated.result.profile.distribution_cache_hit &&
        migrated.result.profile.orientation_cache_hit &&
        migrated.result.profile.cell_cache_hit
        ? 0
        : 1;
}
