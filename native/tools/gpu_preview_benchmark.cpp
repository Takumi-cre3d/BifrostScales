#include "bifrost_scales/core.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
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

std::vector<bifrost_scales::Guide> make_guides() {
    std::vector<bifrost_scales::Guide> guides;
    for (std::uint32_t index = 0U; index < 6U; ++index) {
        const double offset = -7.5 + static_cast<double>(index) * 3.0;
        bifrost_scales::Guide guide;
        guide.id = "gpu-curve-" + std::to_string(index);
        guide.kind = bifrost_scales::GuideKind::DirectionCurve;
        guide.points = {
            {-9.0, 0.0, offset - 0.7},
            {-3.0, 0.0, offset + 0.8},
            {3.0, 0.0, offset - 0.5},
            {9.0, 0.0, offset + 0.6},
        };
        guide.radius = 3.25;
        guide.falloff = 1.0;
        guide.strength = 0.8;
        guide.angle_degrees = static_cast<double>(index) * 2.0;
        guide.use_density = false;
        guide.use_size = false;
        guide.use_direction = true;
        guides.push_back(std::move(guide));
    }
    return guides;
}

double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    return values[values.size() / 2U];
}

struct Measurement {
    bifrost_scales::GenerationResult result;
    double distribution_ms{0.0};
    double orientation_ms{0.0};
    double total_ms{0.0};
};

Measurement measure(
    const bifrost_scales::Mesh& mesh,
    const bifrost_scales::Settings& settings,
    const std::vector<bifrost_scales::Guide>& guides,
    const char* policy) {
    set_environment("BIFROST_SCALES_GPU", policy);
    bifrost_scales::clear_native_stage_cache();
    bifrost_scales::GenerationResult result = bifrost_scales::generate(
        mesh,
        settings,
        bifrost_scales::PreviewMode::Interactive,
        guides);
    const double distribution_ms = result.profile.distribution_ms;
    const double orientation_ms = result.profile.orientation_ms;
    const double total_ms = result.profile.total_ms;
    return {
        std::move(result),
        distribution_ms,
        orientation_ms,
        total_ms,
    };
}

}  // namespace

int main(int argc, char** argv) {
    const std::uint32_t requested = argc > 1
        ? static_cast<std::uint32_t>(std::max(1, std::atoi(argv[1])))
        : 10000U;
    const bifrost_scales::Mesh mesh = make_grid(40U, 20.0);
    const std::vector<bifrost_scales::Guide> guides = make_guides();
    bifrost_scales::Settings settings;
    settings.target_count = requested;
    settings.interactive_budget = requested;
    settings.settled_budget = requested;
    settings.seed = 104U;
    settings.cell_mode = bifrost_scales::GeometryMode::Cards;
    settings.relax_iterations = 0U;
    settings.direction_relax_iterations = 0U;
    set_environment("BIFROST_SCALES_CPU_THREADS", "8");

    std::vector<double> cpu_distribution_times;
    std::vector<double> gpu_distribution_times;
    std::vector<double> cpu_orientation_times;
    std::vector<double> gpu_orientation_times;
    std::vector<double> cpu_total_times;
    std::vector<double> gpu_total_times;
    Measurement cpu;
    Measurement gpu;
    for (std::uint32_t iteration = 0U; iteration < 5U; ++iteration) {
        cpu = measure(mesh, settings, guides, "off");
        cpu_distribution_times.push_back(cpu.distribution_ms);
        cpu_orientation_times.push_back(cpu.orientation_ms);
        cpu_total_times.push_back(cpu.total_ms);
    }
    // The first forced request creates the OpenCL context and builds the
    // program. Exclude that one-time warm-up from steady-state timing.
    gpu = measure(mesh, settings, guides, "force");
    for (std::uint32_t iteration = 0U; iteration < 5U; ++iteration) {
        gpu = measure(mesh, settings, guides, "force");
        gpu_distribution_times.push_back(gpu.distribution_ms);
        gpu_orientation_times.push_back(gpu.orientation_ms);
        gpu_total_times.push_back(gpu.total_ms);
    }

    set_environment("BIFROST_SCALES_GPU", "off");
    bifrost_scales::clear_native_stage_cache();
    const auto settled_cpu = bifrost_scales::generate(
        mesh, settings, bifrost_scales::PreviewMode::Settled, guides);
    set_environment("BIFROST_SCALES_GPU", "force");
    bifrost_scales::clear_native_stage_cache();
    const auto settled_force = bifrost_scales::generate(
        mesh, settings, bifrost_scales::PreviewMode::Settled, guides);
    const bool settled_deterministic =
        settled_cpu.mesh.vertices == settled_force.mesh.vertices &&
        settled_cpu.mesh.faces == settled_force.mesh.faces &&
        settled_cpu.mesh.cell_ids == settled_force.mesh.cell_ids;

    const double cpu_distribution_median = median(cpu_distribution_times);
    const double gpu_distribution_median = median(gpu_distribution_times);
    const double cpu_orientation_median = median(cpu_orientation_times);
    const double gpu_orientation_median = median(gpu_orientation_times);
    const double cpu_total_median = median(cpu_total_times);
    const double gpu_total_median = median(gpu_total_times);
    std::cout.imbue(std::locale::classic());
    std::cout << std::fixed << std::setprecision(6)
              << "{\"schema\":\"bifrost-scales/gpu-preview-benchmark/3\""
              << ",\"requested\":" << requested
              << ",\"accepted\":" << gpu.result.report.accepted_count
              << ",\"gpu_requested\":"
              << (gpu.result.profile.gpu_compute_requested ? "true" : "false")
              << ",\"gpu_available\":"
              << (gpu.result.profile.gpu_compute_available ? "true" : "false")
              << ",\"gpu_used\":"
              << (gpu.result.profile.gpu_compute_used ? "true" : "false")
              << ",\"cpu_distribution_ms\":" << cpu_distribution_median
              << ",\"gpu_distribution_ms\":" << gpu_distribution_median
              << ",\"cpu_orientation_ms\":" << cpu_orientation_median
              << ",\"gpu_orientation_ms\":" << gpu_orientation_median
              << ",\"cpu_total_ms\":" << cpu_total_median
              << ",\"gpu_total_ms\":" << gpu_total_median
              << ",\"gpu_backend\":\""
              << gpu.result.profile.gpu_compute_backend << "\""
              << ",\"gpu_upload_ms\":" << gpu.result.profile.gpu_upload_ms
              << ",\"gpu_kernel_ms\":" << gpu.result.profile.gpu_kernel_ms
              << ",\"gpu_readback_ms\":" << gpu.result.profile.gpu_readback_ms
              << ",\"settled_cpu_deterministic\":"
              << (settled_deterministic ? "true" : "false")
              << ",\"device\":\"" << gpu.result.profile.gpu_device << "\""
              << ",\"fallback_reason\":\""
              << gpu.result.profile.gpu_fallback_reason << "\"}\n";
    set_environment("BIFROST_SCALES_GPU", "auto");
    return settled_deterministic ? 0 : 1;
}
