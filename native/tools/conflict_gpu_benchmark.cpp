#include "bifrost_scales/preview_distribution.hpp"

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

void set_gpu_override(const char* value) {
#ifdef _WIN32
    _putenv_s("BIFROST_SCALES_GPU", value);
#else
    setenv("BIFROST_SCALES_GPU", value, 1);
#endif
}

double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    return values[values.size() / 2U];
}

bool same_result(
    const bifrost_scales::InteractiveConflictResult& left,
    const bifrost_scales::InteractiveConflictResult& right) {
    return left.considered_count == right.considered_count &&
           left.accepted_count == right.accepted_count &&
           left.rejected_density == right.rejected_density &&
           left.rejected_mask == right.rejected_mask &&
           left.rejected_conflict == right.rejected_conflict &&
           left.default_spacing == right.default_spacing &&
           left.accepted_candidate_indices ==
               right.accepted_candidate_indices &&
           left.accepted_candidate_keys ==
               right.accepted_candidate_keys;
}

std::string json_escape(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size());
    for (const char character : value) {
        switch (character) {
            case '\\':
                escaped += "\\\\";
                break;
            case '"':
                escaped += "\\\"";
                break;
            case '\n':
                escaped += "\\n";
                break;
            case '\r':
                escaped += "\\r";
                break;
            case '\t':
                escaped += "\\t";
                break;
            default:
                escaped += character;
                break;
        }
    }
    return escaped;
}

}  // namespace

int main(int argc, char** argv) {
    const std::uint32_t count = argc > 1
        ? static_cast<std::uint32_t>(std::max(1, std::atoi(argv[1])))
        : 40000U;
    const std::uint32_t accepted_limit = std::min(count, 10000U);
    const auto mesh = make_grid(80U, 20.0);
    bifrost_scales::Settings settings;
    settings.seed = 106U;

    const auto generation_started = std::chrono::steady_clock::now();
    const auto batch =
        bifrost_scales::build_interactive_candidate_batch(
            mesh,
            settings,
            count);
    const double generation_ms =
        std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() -
            generation_started).count();

    std::vector<double> cpu_times;
    bifrost_scales::InteractiveConflictResult cpu_reference;
    for (std::uint32_t iteration = 0U; iteration < 5U; ++iteration) {
        const auto started = std::chrono::steady_clock::now();
        cpu_reference =
            bifrost_scales::arbitrate_interactive_candidates(
                batch,
                settings,
                accepted_limit);
        cpu_times.push_back(
            std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - started).count());
    }

    set_gpu_override("force");
    bifrost_scales::gpu::ExecutionInfo gpu_info;
    (void)bifrost_scales::arbitrate_interactive_candidates_accelerated(
        batch,
        settings,
        accepted_limit,
        gpu_info);
    std::vector<double> accelerated_times;
    bool parity = true;
    bifrost_scales::InteractiveConflictResult accelerated;
    for (std::uint32_t iteration = 0U; iteration < 5U; ++iteration) {
        const auto started = std::chrono::steady_clock::now();
        accelerated =
            bifrost_scales::arbitrate_interactive_candidates_accelerated(
                batch,
                settings,
                accepted_limit,
                gpu_info);
        accelerated_times.push_back(
            std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - started).count());
        parity = parity && same_result(accelerated, cpu_reference);
    }
    set_gpu_override("auto");

    std::cout.imbue(std::locale::classic());
    std::cout << std::fixed << std::setprecision(6)
              << "{\"schema\":\"bifrost-scales/gpu-conflict-benchmark/1\""
              << ",\"candidate_count\":" << count
              << ",\"accepted_count\":" << accelerated.accepted_count
              << ",\"upload_bytes\":" << batch.upload_bytes()
              << ",\"generation_ms\":" << generation_ms
              << ",\"cpu_arbitration_ms\":" << median(cpu_times)
              << ",\"accelerated_wall_ms\":"
              << median(accelerated_times)
              << ",\"gpu_requested\":"
              << (gpu_info.requested ? "true" : "false")
              << ",\"gpu_available\":"
              << (gpu_info.available ? "true" : "false")
              << ",\"gpu_used\":"
              << (gpu_info.used ? "true" : "false")
              << ",\"gpu_upload_ms\":" << gpu_info.upload_ms
              << ",\"gpu_kernel_ms\":" << gpu_info.kernel_ms
              << ",\"gpu_readback_ms\":" << gpu_info.readback_ms
              << ",\"gpu_iterations\":" << gpu_info.iteration_count
              << ",\"parity\":" << (parity ? "true" : "false")
              << ",\"device\":\"" << json_escape(gpu_info.device) << "\""
              << ",\"fallback_reason\":\""
              << json_escape(gpu_info.fallback_reason) << "\"}\n";
    return parity ? 0 : 1;
}
