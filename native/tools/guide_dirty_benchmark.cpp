#include "bifrost_scales/core.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <locale>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;

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

double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    const std::size_t middle = values.size() / 2U;
    return values.size() % 2U == 0U
        ? (values[middle - 1U] + values[middle]) * 0.5
        : values[middle];
}

struct Row {
    std::uint32_t requested{0U};
    std::uint32_t accepted{0U};
    double orientation_ms{0.0};
    double cells_ms{0.0};
    double shape_ms{0.0};
    double core_total_ms{0.0};
    double wall_ms{0.0};
    std::uint32_t dirty_sample_count{0U};
    double dirty_sample_ratio{0.0};
};

Row run_case(
    const bifrost_scales::Mesh& mesh,
    std::uint32_t requested,
    std::uint32_t repeats) {
    bifrost_scales::Settings settings;
    settings.target_count = requested;
    settings.settled_budget = requested;
    settings.seed = 171U;
    settings.size = 0.055;
    settings.spacing_factor = 0.82;
    settings.relax_iterations = 1U;
    settings.direction_relax_iterations = 2U;
    settings.direction_relax_strength = 0.35;
    settings.cell_mode = bifrost_scales::GeometryMode::Cells;
    settings.cell_settled_resolution = 10U;
    settings.cell_shape_divisions = 2U;
    settings.cell_project_to_surface = true;

    bifrost_scales::Guide point;
    point.id = "guide-dirty-benchmark";
    point.kind = bifrost_scales::GuideKind::DirectionPoint;
    point.points = {{-2.5, 0.0, -1.5}};
    point.radius = 0.45;
    point.falloff = 1.0;
    point.strength = 0.85;
    point.use_density = false;
    point.use_size = false;
    point.use_direction = true;

    bifrost_scales::GenerationOptions options;
    options.include_uvs = false;
    options.include_colors = false;
    options.include_scale_type_ids = false;
    options.materialize_faces = false;
    options.include_flat_topology = true;
    options.include_cell_ids = false;

    std::vector<double> orientation;
    std::vector<double> cells;
    std::vector<double> shape;
    std::vector<double> core_total;
    std::vector<double> wall;
    std::uint32_t accepted = 0U;
    std::uint32_t dirty_sample_count = 0U;
    double dirty_sample_ratio = 0.0;
    for (std::uint32_t repeat = 0U; repeat < repeats; ++repeat) {
        bifrost_scales::clear_native_stage_cache();
        (void)bifrost_scales::generate(
            mesh,
            settings,
            bifrost_scales::PreviewMode::Settled,
            {point},
            options);
        bifrost_scales::Guide moved = point;
        moved.points.front().x += 0.12;
        const auto started = Clock::now();
        const bifrost_scales::GenerationResult warm = bifrost_scales::generate(
            mesh,
            settings,
            bifrost_scales::PreviewMode::Settled,
            {moved},
            options);
        const double elapsed = std::chrono::duration<double, std::milli>(
            Clock::now() - started).count();
        if (!warm.profile.distribution_cache_hit ||
            warm.profile.orientation_cache_hit ||
            !warm.profile.cell_cache_hit) {
            throw std::runtime_error("local Guide edit cache contract failed");
        }
        bifrost_scales::clear_native_stage_cache();
        const bifrost_scales::GenerationResult cold = bifrost_scales::generate(
            mesh,
            settings,
            bifrost_scales::PreviewMode::Settled,
            {moved},
            options);
        if (warm.mesh.vertices != cold.mesh.vertices ||
            warm.mesh.face_offsets != cold.mesh.face_offsets ||
            warm.mesh.face_vertices != cold.mesh.face_vertices) {
            throw std::runtime_error("local Guide edit differs from cold output");
        }
        accepted = warm.report.accepted_count;
#if defined(BIFROST_SCALES_NATIVE_PROFILE_SCHEMA_VERSION) && \
    BIFROST_SCALES_NATIVE_PROFILE_SCHEMA_VERSION >= 7
        if (!warm.profile.orientation_dirty_region_used) {
            throw std::runtime_error("Guide dirty region was not used");
        }
        dirty_sample_count = warm.profile.orientation_dirty_sample_count;
        dirty_sample_ratio = warm.profile.orientation_dirty_sample_ratio;
#endif
        orientation.push_back(warm.profile.orientation_ms);
        cells.push_back(warm.profile.cells_ms);
        shape.push_back(warm.profile.shape_ms);
        core_total.push_back(warm.profile.total_ms);
        wall.push_back(elapsed);
    }
    return {
        requested,
        accepted,
        median(orientation),
        median(cells),
        median(shape),
        median(core_total),
        median(wall),
        dirty_sample_count,
        dirty_sample_ratio,
    };
}

}  // namespace

int main(int argc, char** argv) {
    try {
        std::string output_path;
        std::uint32_t repeats = 3U;
        std::vector<std::uint32_t> counts{10000U, 30000U};
        for (int index = 1; index < argc; ++index) {
            const std::string argument = argv[index];
            if (argument == "--output" && index + 1 < argc) {
                output_path = argv[++index];
            } else if (argument == "--repeats" && index + 1 < argc) {
                repeats = std::max<std::uint32_t>(
                    1U,
                    static_cast<std::uint32_t>(std::stoul(argv[++index])));
            } else {
                throw std::runtime_error("unknown or incomplete argument: " + argument);
            }
        }
        const bifrost_scales::Mesh mesh = make_grid(100U, 10.0);
        std::ofstream file;
        std::ostream* output = &std::cout;
        if (!output_path.empty()) {
            file.open(output_path, std::ios::binary | std::ios::trunc);
            if (!file) {
                throw std::runtime_error("cannot open output file: " + output_path);
            }
            output = &file;
        }
        output->imbue(std::locale::classic());
        *output << std::fixed << std::setprecision(3);
        *output << "requested_count,accepted_count,orientation_ms,cells_ms,"
                   "shape_ms,core_total_ms,wall_ms,dirty_sample_count,"
                   "dirty_sample_ratio\n";
        for (const std::uint32_t count : counts) {
            const Row row = run_case(mesh, count, repeats);
            *output << row.requested << ',' << row.accepted << ','
                    << row.orientation_ms << ',' << row.cells_ms << ','
                    << row.shape_ms << ',' << row.core_total_ms << ','
                    << row.wall_ms << ',' << row.dirty_sample_count << ','
                    << row.dirty_sample_ratio << '\n';
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "bifrost_scales_guide_dirty_benchmark: "
                  << error.what() << '\n';
        return 1;
    }
}
