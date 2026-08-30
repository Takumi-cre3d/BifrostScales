#include "bifrost_scales/core.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <locale>
#include <string>
#include <vector>

namespace {

void set_environment(const char* name, const char* value) {
#if defined(_WIN32)
    _putenv_s(name, value);
#else
    setenv(name, value, 1);
#endif
}

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

std::vector<bifrost_scales::Guide> make_guides(std::uint32_t guide_count) {
    std::vector<bifrost_scales::Guide> guides;
    guides.reserve(guide_count);
    for (std::uint32_t index = 0U; index < guide_count; ++index) {
        const double offset = -7.5 + static_cast<double>(index);
        bifrost_scales::Guide guide;
        guide.id = "distribution-guide-" + std::to_string(index);
        guide.kind = index < 14U
            ? bifrost_scales::GuideKind::FlowCurve
            : bifrost_scales::GuideKind::DensityCurve;
        guide.points = {
            {-9.0, 0.0, offset - 0.4},
            {-4.5, 0.0, offset + 0.5},
            {0.0, 0.0, offset - 0.3},
            {4.5, 0.0, offset + 0.4},
            {9.0, 0.0, offset},
        };
        guide.radius = 1.45;
        guide.falloff = 1.0;
        guide.strength = 0.85;
        guide.density_multiplier = 0.72 + 0.035 * index;
        guide.size_multiplier = 0.85 + 0.02 * index;
        guide.use_density = true;
        guide.use_size = index >= 14U;
        guide.use_direction = index < 14U;
        guides.push_back(std::move(guide));
    }
    return guides;
}

double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    return values[values.size() / 2U];
}

}  // namespace

int main(int argc, char** argv) {
    const std::uint32_t requested = argc > 1
        ? static_cast<std::uint32_t>(std::max(1, std::atoi(argv[1])))
        : 10000U;
    const std::uint32_t repeats = argc > 2
        ? static_cast<std::uint32_t>(std::max(1, std::atoi(argv[2])))
        : 5U;
    const std::string mode_name = argc > 3 ? std::string(argv[3]) : "interactive";
    const bifrost_scales::PreviewMode preview_mode = mode_name == "settled"
        ? bifrost_scales::PreviewMode::Settled
        : (mode_name == "final"
            ? bifrost_scales::PreviewMode::Final
            : bifrost_scales::PreviewMode::Interactive);
    const std::uint32_t guide_count = argc > 4
        ? static_cast<std::uint32_t>(std::max(1, std::atoi(argv[4])))
        : 16U;
    set_environment("BIFROST_SCALES_CPU_THREADS", "8");
    set_environment("BIFROST_SCALES_GPU", "off");
    const bifrost_scales::Mesh mesh = make_grid(80U, 20.0);
    const std::vector<bifrost_scales::Guide> guides = make_guides(guide_count);
    bifrost_scales::Settings settings;
    settings.target_count = requested;
    settings.interactive_budget = requested;
    settings.settled_budget = requested;
    settings.seed = 105U;
    settings.cell_mode = bifrost_scales::GeometryMode::Cards;
    settings.relax_iterations = 1U;
    settings.direction_relax_iterations = 0U;

    std::vector<double> cold_guide_surface_times;
    std::vector<double> distribution_times;
    std::vector<double> total_times;
    std::vector<double> reused_guide_surface_times;
    std::vector<double> reused_distribution_times;
    std::vector<double> reused_total_times;
    std::uint32_t accepted = 0U;
    std::uint64_t attempts = 0U;
    double final_spacing = 0.0;
    for (std::uint32_t repeat = 0U; repeat < repeats; ++repeat) {
        bifrost_scales::clear_native_stage_cache();
        const auto result = bifrost_scales::generate(
            mesh,
            settings,
            preview_mode,
            guides);
        accepted = result.report.accepted_count;
        attempts = result.report.attempts;
        final_spacing = result.report.final_spacing;
        cold_guide_surface_times.push_back(result.profile.guide_surface_ms);
        distribution_times.push_back(result.profile.distribution_ms);
        total_times.push_back(result.profile.total_ms);

        bifrost_scales::Settings seed_edit = settings;
        seed_edit.seed += repeat + 1U;
        const auto reused = bifrost_scales::generate(
            mesh,
            seed_edit,
            preview_mode,
            guides);
        if (reused.profile.distribution_cache_hit ||
            reused.profile.guide_surface_cache_hits != guides.size() ||
            reused.profile.guide_surface_cache_misses != 0U) {
            throw std::runtime_error(
                "surface Guide field cache did not survive a Distribution miss");
        }
        reused_guide_surface_times.push_back(reused.profile.guide_surface_ms);
        reused_distribution_times.push_back(reused.profile.distribution_ms);
        reused_total_times.push_back(reused.profile.total_ms);
    }
    std::cout.imbue(std::locale::classic());
    std::cout << std::fixed << std::setprecision(3)
              << "mode,requested_count,accepted_count,guide_count,attempts,final_spacing,"
                 "cold_guide_surface_ms,distribution_ms,total_ms,"
                 "reused_guide_surface_ms,reused_distribution_ms,reused_total_ms\n"
              << mode_name << ','
              << requested << ',' << accepted << ',' << guides.size() << ','
              << attempts << ',' << final_spacing << ','
              << median(cold_guide_surface_times) << ','
              << median(distribution_times) << ',' << median(total_times) << ','
              << median(reused_guide_surface_times) << ','
              << median(reused_distribution_times) << ','
              << median(reused_total_times) << '\n';
    return 0;
}
