#include "bifrost_scales/core.hpp"

#include <array>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <locale>

int main() {
    bifrost_scales::Mesh mesh;
    mesh.vertices = {
        {-10.0, 0.0, -10.0},
        {10.0, 0.0, -10.0},
        {10.0, 0.0, 10.0},
        {-10.0, 0.0, 10.0},
    };
    mesh.triangles = {{0U, 1U, 2U}, {0U, 2U, 3U}};
    bifrost_scales::Settings settings;
    settings.target_count = 1000U;
    settings.settled_budget = 1000U;
    settings.seed = 104U;
    settings.cell_mode = bifrost_scales::GeometryMode::Cells;

    std::cout.imbue(std::locale::classic());
    std::cout << "density_multiplier,accepted_count,boundary_anchor_count,"
                 "initial_spacing,boundary_density_adapted\n";
    for (const double density : std::array<double, 4>{1.0, 0.5, 0.25, 0.1}) {
        bifrost_scales::Guide guide;
        guide.id = "boundary-density";
        guide.kind = bifrost_scales::GuideKind::DensityPoint;
        guide.points = {{0.0, 0.0, 0.0}};
        guide.radius = 10000.0;
        guide.falloff = 1.0;
        guide.density_multiplier = density;
        guide.use_density = true;
        guide.use_size = false;
        guide.use_direction = false;
        const auto result = bifrost_scales::distribute(
            mesh,
            settings,
            bifrost_scales::PreviewMode::Settled,
            {guide});
        std::cout << std::fixed << std::setprecision(6)
                  << density << ','
                  << result.report.accepted_count << ','
                  << result.report.boundary_anchor_count << ','
                  << result.report.initial_spacing << ','
                  << (result.report.boundary_density_adapted ? "true" : "false")
                  << '\n';
    }
    return 0;
}
