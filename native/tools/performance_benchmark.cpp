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
    mesh.vertices.reserve(static_cast<std::size_t>(row) * row);
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
    mesh.triangles.reserve(static_cast<std::size_t>(divisions) * divisions * 2U);
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

bifrost_scales::Mesh make_closed_box(double extent) {
    const double half = extent * 0.5;
    bifrost_scales::Mesh mesh;
    mesh.vertices = {
        {-half, -half, -half}, {half, -half, -half},
        {half, half, -half}, {-half, half, -half},
        {-half, -half, half}, {half, -half, half},
        {half, half, half}, {-half, half, half},
    };
    mesh.triangles = {
        {0U, 2U, 1U}, {0U, 3U, 2U},
        {4U, 5U, 6U}, {4U, 6U, 7U},
        {0U, 1U, 5U}, {0U, 5U, 4U},
        {3U, 7U, 6U}, {3U, 6U, 2U},
        {0U, 4U, 7U}, {0U, 7U, 3U},
        {1U, 2U, 6U}, {1U, 6U, 5U},
    };
    return mesh;
}

double median(std::vector<double> values) {
    if (values.empty()) {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    const std::size_t middle = values.size() / 2U;
    if (values.size() % 2U == 0U) {
        return (values[middle - 1U] + values[middle]) * 0.5;
    }
    return values[middle];
}

struct Measurement {
    bifrost_scales::GenerationResult result;
    double wall_ms{0.0};
};

Measurement measure(
    const bifrost_scales::Mesh& mesh,
    const bifrost_scales::Settings& settings,
    const std::vector<bifrost_scales::Guide>& guides,
    const bifrost_scales::GenerationOptions& options) {
    const auto started = Clock::now();
    bifrost_scales::GenerationResult result = bifrost_scales::generate(
        mesh,
        settings,
        bifrost_scales::PreviewMode::Settled,
        guides,
        options);
    const double elapsed = std::chrono::duration<double, std::milli>(
        Clock::now() - started).count();
    if (result.mesh.face_offsets.empty() || !result.mesh.faces.empty()) {
        throw std::runtime_error("optimized flat topology contract failed");
    }
    if (!result.mesh.uvs.empty() || !result.mesh.colors.empty() ||
        !result.mesh.scale_type_ids.empty()) {
        throw std::runtime_error("optimized auxiliary output contract failed");
    }
    return {std::move(result), elapsed};
}

struct Row {
    std::uint32_t requested{0U};
    std::uint32_t accepted{0U};
    std::size_t points{0U};
    std::size_t faces{0U};
    double cold_distribution_ms{0.0};
    double cold_orientation_ms{0.0};
    double cold_cells_ms{0.0};
    double cold_shape_ms{0.0};
    double cold_core_total_ms{0.0};
    double cold_wall_ms{0.0};
    double shape_warm_shape_ms{0.0};
    double shape_warm_wall_ms{0.0};
    double cell_warm_cells_ms{0.0};
    double cell_warm_shape_ms{0.0};
    double cell_warm_wall_ms{0.0};
    double direction_warm_orientation_ms{0.0};
    double direction_warm_cells_ms{0.0};
    double direction_warm_shape_ms{0.0};
    double direction_warm_wall_ms{0.0};
    double cold_cell_setup_ms{0.0};
    double cold_cell_neighbors_ms{0.0};
    double cold_cell_boundaries_ms{0.0};
    double cold_cell_boundary_query_ms{0.0};
    double cold_cell_boundary_rays_ms{0.0};
    double cold_cell_projection_ms{0.0};
    double cell_warm_setup_ms{0.0};
    double cell_warm_neighbors_ms{0.0};
    double cell_warm_boundaries_ms{0.0};
    double cell_warm_boundary_query_ms{0.0};
    double cell_warm_boundary_rays_ms{0.0};
    double cell_warm_projection_ms{0.0};
};

Row run_case(
    const bifrost_scales::Mesh& mesh,
    std::uint32_t count,
    std::uint32_t repeats,
    double density_multiplier,
    double cell_radius_multiplier,
    double cell_direction_anisotropy,
    std::uint32_t cell_resolution) {
    bifrost_scales::Settings settings;
    settings.target_count = count;
    settings.settled_budget = count;
    settings.seed = 171U;
    settings.size = 0.055;
    settings.spacing_factor = 0.82;
    settings.relax_iterations = 1U;
    settings.direction_relax_iterations = 2U;
    settings.direction_relax_strength = 0.35;
    settings.cell_mode = bifrost_scales::GeometryMode::Cells;
    settings.cell_settled_resolution = cell_resolution;
    settings.cell_shape_divisions = 2U;
    settings.cell_project_to_surface = true;
    settings.cell_radius_multiplier = cell_radius_multiplier;
    settings.cell_direction_anisotropy = cell_direction_anisotropy;

    bifrost_scales::Guide curve;
    curve.id = "benchmark-curve";
    curve.kind = bifrost_scales::GuideKind::DirectionCurve;
    curve.points = {{-4.0, 0.0, 0.0}, {0.0, 0.0, 0.75}, {4.0, 0.0, 0.0}};
    curve.radius = 2.5;
    curve.falloff = 1.0;
    curve.strength = 1.0;
    curve.use_density = false;
    curve.use_size = false;
    curve.use_direction = true;

    bifrost_scales::Guide point;
    point.id = "benchmark-point";
    point.kind = bifrost_scales::GuideKind::DirectionPoint;
    point.points = {{0.0, 0.0, 2.0}};
    point.radius = 2.0;
    point.falloff = 1.0;
    point.strength = 0.8;
    point.use_density = false;
    point.use_size = false;
    point.use_direction = true;

    std::vector<bifrost_scales::Guide> guides{curve, point};
    if (density_multiplier > 0.0) {
        bifrost_scales::Guide density;
        density.id = "benchmark-density";
        density.kind = bifrost_scales::GuideKind::DensityPoint;
        density.points = {{0.0, 0.0, 0.0}};
        density.radius = 2.5;
        density.falloff = 1.0;
        density.density_multiplier = density_multiplier;
        density.use_density = true;
        density.use_size = false;
        density.use_direction = false;
        guides.push_back(std::move(density));
    }

    bifrost_scales::GenerationOptions options;
    options.include_uvs = false;
    options.include_colors = false;
    options.include_scale_type_ids = false;
    options.materialize_faces = false;
    options.include_flat_topology = true;
    options.include_cell_ids = false;

    std::vector<double> cold_distribution;
    std::vector<double> cold_orientation;
    std::vector<double> cold_cells;
    std::vector<double> cold_shape;
    std::vector<double> cold_core_total;
    std::vector<double> cold_wall;
    std::vector<double> shape_warm_shape;
    std::vector<double> shape_warm_wall;
    std::vector<double> cell_warm_cells;
    std::vector<double> cell_warm_shape;
    std::vector<double> cell_warm_wall;
    std::vector<double> direction_warm_orientation;
    std::vector<double> direction_warm_cells;
    std::vector<double> direction_warm_shape;
    std::vector<double> direction_warm_wall;
    std::vector<double> cold_cell_setup;
    std::vector<double> cold_cell_neighbors;
    std::vector<double> cold_cell_boundaries;
    std::vector<double> cold_cell_boundary_query;
    std::vector<double> cold_cell_boundary_rays;
    std::vector<double> cold_cell_projection;
    std::vector<double> cell_warm_setup;
    std::vector<double> cell_warm_neighbors;
    std::vector<double> cell_warm_boundaries;
    std::vector<double> cell_warm_boundary_query;
    std::vector<double> cell_warm_boundary_rays;
    std::vector<double> cell_warm_projection;

    bifrost_scales::GenerationResult latest;
    for (std::uint32_t repeat = 0U; repeat < repeats; ++repeat) {
        bifrost_scales::clear_native_stage_cache();
        Measurement cold = measure(mesh, settings, guides, options);
        if (cold.result.profile.distribution_cache_hit ||
            cold.result.profile.orientation_cache_hit ||
            cold.result.profile.cell_cache_hit) {
            throw std::runtime_error("cold benchmark unexpectedly hit a stage cache");
        }
        latest = cold.result;
        cold_distribution.push_back(cold.result.profile.distribution_ms);
        cold_orientation.push_back(cold.result.profile.orientation_ms);
        cold_cells.push_back(cold.result.profile.cells_ms);
        cold_cell_setup.push_back(cold.result.profile.cell_setup_ms);
        cold_cell_neighbors.push_back(cold.result.profile.cell_neighbors_ms);
        cold_cell_boundaries.push_back(cold.result.profile.cell_boundaries_ms);
        cold_cell_boundary_query.push_back(
            cold.result.profile.cell_boundary_query_ms);
        cold_cell_boundary_rays.push_back(
            cold.result.profile.cell_boundary_rays_ms);
        cold_cell_projection.push_back(cold.result.profile.cell_projection_ms);
        cold_shape.push_back(cold.result.profile.shape_ms);
        cold_core_total.push_back(cold.result.profile.total_ms);
        cold_wall.push_back(cold.wall_ms);

        bifrost_scales::Settings shape_settings = settings;
        shape_settings.inset = 0.18;
        Measurement shape_edit = measure(mesh, shape_settings, guides, options);
        if (!shape_edit.result.profile.distribution_cache_hit ||
            !shape_edit.result.profile.orientation_cache_hit ||
            !shape_edit.result.profile.cell_cache_hit) {
            throw std::runtime_error("shape-only edit did not reuse all upstream stages");
        }
        shape_warm_shape.push_back(shape_edit.result.profile.shape_ms);
        shape_warm_wall.push_back(shape_edit.wall_ms);

        bifrost_scales::Settings direction_settings = shape_settings;
        direction_settings.direction_degrees = settings.direction_degrees + 7.5;
        Measurement direction_edit = measure(
            mesh,
            direction_settings,
            guides,
            options);
        const bool expected_direction_cell_hit =
            cell_direction_anisotropy <= 1.0e-12;
        if (!direction_edit.result.profile.distribution_cache_hit ||
            direction_edit.result.profile.orientation_cache_hit ||
            direction_edit.result.profile.cell_cache_hit !=
                expected_direction_cell_hit ||
            direction_edit.result.profile.cell_cache_reused_after_orientation_change !=
                expected_direction_cell_hit) {
            throw std::runtime_error("direction edit cache boundary is invalid");
        }
        direction_warm_orientation.push_back(
            direction_edit.result.profile.orientation_ms);
        direction_warm_cells.push_back(direction_edit.result.profile.cells_ms);
        direction_warm_shape.push_back(direction_edit.result.profile.shape_ms);
        direction_warm_wall.push_back(direction_edit.wall_ms);

        bifrost_scales::Settings cell_settings = direction_settings;
        cell_settings.cell_gap = settings.cell_gap + 0.015;
        Measurement cell_edit = measure(mesh, cell_settings, guides, options);
        if (!cell_edit.result.profile.distribution_cache_hit ||
            !cell_edit.result.profile.orientation_cache_hit ||
            cell_edit.result.profile.cell_cache_hit) {
            throw std::runtime_error("cell edit cache boundary is invalid");
        }
        cell_warm_cells.push_back(cell_edit.result.profile.cells_ms);
        cell_warm_setup.push_back(cell_edit.result.profile.cell_setup_ms);
        cell_warm_neighbors.push_back(cell_edit.result.profile.cell_neighbors_ms);
        cell_warm_boundaries.push_back(cell_edit.result.profile.cell_boundaries_ms);
        cell_warm_boundary_query.push_back(
            cell_edit.result.profile.cell_boundary_query_ms);
        cell_warm_boundary_rays.push_back(
            cell_edit.result.profile.cell_boundary_rays_ms);
        cell_warm_projection.push_back(cell_edit.result.profile.cell_projection_ms);
        cell_warm_shape.push_back(cell_edit.result.profile.shape_ms);
        cell_warm_wall.push_back(cell_edit.wall_ms);
    }

    return {
        count,
        latest.report.accepted_count,
        latest.mesh.vertices.size(),
        latest.mesh.face_count(),
        median(cold_distribution),
        median(cold_orientation),
        median(cold_cells),
        median(cold_shape),
        median(cold_core_total),
        median(cold_wall),
        median(shape_warm_shape),
        median(shape_warm_wall),
        median(cell_warm_cells),
        median(cell_warm_shape),
        median(cell_warm_wall),
        median(direction_warm_orientation),
        median(direction_warm_cells),
        median(direction_warm_shape),
        median(direction_warm_wall),
        median(cold_cell_setup),
        median(cold_cell_neighbors),
        median(cold_cell_boundaries),
        median(cold_cell_boundary_query),
        median(cold_cell_boundary_rays),
        median(cold_cell_projection),
        median(cell_warm_setup),
        median(cell_warm_neighbors),
        median(cell_warm_boundaries),
        median(cell_warm_boundary_query),
        median(cell_warm_boundary_rays),
        median(cell_warm_projection),
    };
}

}  // namespace

int main(int argc, char** argv) {
    try {
        std::string output_path;
        std::uint32_t repeats = 3U;
        std::uint32_t mesh_divisions = 100U;
        double density_multiplier = 0.0;
        double cell_radius_multiplier = 1.65;
        double cell_direction_anisotropy = 0.0;
        std::uint32_t cell_resolution = 10U;
        bool closed_mesh = false;
        std::vector<std::uint32_t> counts{
            512U,
            2000U,
            5000U,
            10000U,
            30000U,
        };
        for (int index = 1; index < argc; ++index) {
            const std::string argument = argv[index];
            if (argument == "--output" && index + 1 < argc) {
                output_path = argv[++index];
            } else if (argument == "--repeats" && index + 1 < argc) {
                repeats = static_cast<std::uint32_t>(std::stoul(argv[++index]));
                repeats = std::max<std::uint32_t>(1U, repeats);
            } else if (argument == "--mesh-divisions" && index + 1 < argc) {
                mesh_divisions = static_cast<std::uint32_t>(
                    std::stoul(argv[++index]));
                if (mesh_divisions == 0U) {
                    throw std::runtime_error(
                        "--mesh-divisions must be greater than zero");
                }
            } else if (argument == "--density-multiplier" && index + 1 < argc) {
                density_multiplier = std::stod(argv[++index]);
                if (density_multiplier <= 0.0) {
                    throw std::runtime_error(
                        "--density-multiplier must be greater than zero");
                }
            } else if (argument == "--cell-radius-multiplier" && index + 1 < argc) {
                cell_radius_multiplier = std::stod(argv[++index]);
                if (cell_radius_multiplier < 0.35 ||
                    cell_radius_multiplier > 6.0) {
                    throw std::runtime_error(
                        "--cell-radius-multiplier must be in [0.35, 6.0]");
                }
            } else if (argument == "--cell-direction-anisotropy" &&
                       index + 1 < argc) {
                cell_direction_anisotropy = std::stod(argv[++index]);
                if (cell_direction_anisotropy < 0.0 ||
                    cell_direction_anisotropy > 1.0) {
                    throw std::runtime_error(
                        "--cell-direction-anisotropy must be in [0, 1]");
                }
            } else if (argument == "--cell-resolution" && index + 1 < argc) {
                cell_resolution = static_cast<std::uint32_t>(
                    std::stoul(argv[++index]));
                if (cell_resolution < 3U || cell_resolution > 64U) {
                    throw std::runtime_error(
                        "--cell-resolution must be in [3, 64]");
                }
            } else if (argument == "--closed-mesh") {
                closed_mesh = true;
            } else if (argument == "--counts" && index + 1 < argc) {
                counts.clear();
                const std::string encoded = argv[++index];
                std::size_t start = 0U;
                while (start <= encoded.size()) {
                    const std::size_t separator = encoded.find(',', start);
                    const std::string token = encoded.substr(
                        start,
                        separator == std::string::npos
                            ? std::string::npos
                            : separator - start);
                    if (!token.empty()) {
                        const std::uint32_t count = static_cast<std::uint32_t>(
                            std::stoul(token));
                        if (count == 0U) {
                            throw std::runtime_error(
                                "benchmark counts must be greater than zero");
                        }
                        counts.push_back(count);
                    }
                    if (separator == std::string::npos) {
                        break;
                    }
                    start = separator + 1U;
                }
                if (counts.empty()) {
                    throw std::runtime_error("--counts requires a comma-separated list");
                }
            } else {
                throw std::runtime_error("unknown or incomplete argument: " + argument);
            }
        }

        const bifrost_scales::Mesh mesh = closed_mesh
            ? make_closed_box(10.0)
            : make_grid(mesh_divisions, 10.0);
        std::vector<Row> rows;
        rows.reserve(counts.size());
        for (const std::uint32_t count : counts) {
            rows.push_back(run_case(
                mesh,
                count,
                repeats,
                density_multiplier,
                cell_radius_multiplier,
                cell_direction_anisotropy,
                cell_resolution));
        }

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
        *output
            << "requested_count,accepted_count,point_count,face_count,"
               "cold_distribution_ms,cold_orientation_ms,cold_cells_ms,"
               "cold_shape_ms,cold_core_total_ms,cold_wall_ms,"
               "shape_warm_shape_ms,shape_warm_wall_ms,"
               "cell_warm_cells_ms,cell_warm_shape_ms,cell_warm_wall_ms,"
               "direction_warm_orientation_ms,direction_warm_cells_ms,"
               "direction_warm_shape_ms,direction_warm_wall_ms,"
               "cold_cell_setup_ms,cold_cell_neighbors_ms,"
               "cold_cell_boundaries_ms,cold_cell_boundary_query_ms,"
               "cold_cell_boundary_rays_ms,cold_cell_projection_ms,"
               "cell_warm_setup_ms,cell_warm_neighbors_ms,"
               "cell_warm_boundaries_ms,cell_warm_boundary_query_ms,"
               "cell_warm_boundary_rays_ms,cell_warm_projection_ms\n";
        for (const Row& row : rows) {
            *output
                << row.requested << ','
                << row.accepted << ','
                << row.points << ','
                << row.faces << ','
                << row.cold_distribution_ms << ','
                << row.cold_orientation_ms << ','
                << row.cold_cells_ms << ','
                << row.cold_shape_ms << ','
                << row.cold_core_total_ms << ','
                << row.cold_wall_ms << ','
                << row.shape_warm_shape_ms << ','
                << row.shape_warm_wall_ms << ','
                << row.cell_warm_cells_ms << ','
                << row.cell_warm_shape_ms << ','
                << row.cell_warm_wall_ms << ','
                << row.direction_warm_orientation_ms << ','
                << row.direction_warm_cells_ms << ','
                << row.direction_warm_shape_ms << ','
                << row.direction_warm_wall_ms << ','
                << row.cold_cell_setup_ms << ','
                << row.cold_cell_neighbors_ms << ','
                << row.cold_cell_boundaries_ms << ','
                << row.cold_cell_boundary_query_ms << ','
                << row.cold_cell_boundary_rays_ms << ','
                << row.cold_cell_projection_ms << ','
                << row.cell_warm_setup_ms << ','
                << row.cell_warm_neighbors_ms << ','
                << row.cell_warm_boundaries_ms << ','
                << row.cell_warm_boundary_query_ms << ','
                << row.cell_warm_boundary_rays_ms << ','
                << row.cell_warm_projection_ms << '\n';
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "bifrost_scales_performance_benchmark: " << error.what() << '\n';
        return 1;
    }
}
