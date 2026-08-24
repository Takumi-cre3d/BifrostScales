#include "bifrost_scales/preview_distribution.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace bifrost_scales {
namespace {

constexpr std::uint64_t kCandidateStream = 0xA0761D6478BD642FULL;
constexpr std::uint64_t kCandidateStep = 0xE7037ED1A0B428DBULL;
constexpr std::uint64_t kLaneStep = 0x8EBC6AF09C88C6E3ULL;

std::uint64_t splitmix64(std::uint64_t value) noexcept {
    value += 0x9E3779B97F4A7C15ULL;
    value = (value ^ (value >> 30U)) * 0xBF58476D1CE4E5B9ULL;
    value = (value ^ (value >> 27U)) * 0x94D049BB133111EBULL;
    return value ^ (value >> 31U);
}

double candidate_random(
    std::uint64_t seed,
    std::uint64_t candidate,
    std::uint64_t lane) noexcept {
    const std::uint64_t bits = splitmix64(
        seed ^ kCandidateStream ^ candidate * kCandidateStep ^ lane * kLaneStep);
    return static_cast<double>(bits >> 11U) * 0x1.0p-53;
}

Vec3 subtract(const Vec3& left, const Vec3& right) noexcept {
    return {left.x - right.x, left.y - right.y, left.z - right.z};
}

Vec3 cross(const Vec3& left, const Vec3& right) noexcept {
    return {
        left.y * right.z - left.z * right.y,
        left.z * right.x - left.x * right.z,
        left.x * right.y - left.y * right.x,
    };
}

double length(const Vec3& value) noexcept {
    return std::sqrt(value.x * value.x + value.y * value.y + value.z * value.z);
}

void append_vec3(std::vector<float>& output, const Vec3& value) {
    output.push_back(static_cast<float>(value.x));
    output.push_back(static_cast<float>(value.y));
    output.push_back(static_cast<float>(value.z));
}

}  // namespace

std::size_t InteractiveCandidateBatch::upload_bytes() const noexcept {
    return positions_xyz.size() * sizeof(float) +
           normals_xyz.size() * sizeof(float) +
           barycentric.size() * sizeof(float) +
           random_values.size() * sizeof(float) +
           triangle_indices.size() * sizeof(std::uint32_t) +
           candidate_keys.size() * sizeof(std::uint64_t);
}

bool InteractiveCandidateBatch::has_consistent_sizes() const noexcept {
    const std::size_t count = candidate_count;
    return positions_xyz.size() == count * 3U &&
           normals_xyz.size() == count * 3U &&
           barycentric.size() == count * 3U &&
           random_values.size() == count * kInteractiveCandidateRandomStride &&
           triangle_indices.size() == count &&
           candidate_keys.size() == count;
}

InteractiveCandidateBatch build_interactive_candidate_batch(
    const Mesh& mesh,
    const Settings& settings,
    std::uint32_t candidate_count) {
    std::vector<std::uint32_t> triangles;
    std::vector<double> cumulative_areas;
    std::vector<Vec3> normals(mesh.triangles.size());
    triangles.reserve(mesh.triangles.size());
    cumulative_areas.reserve(mesh.triangles.size());

    double total_area = 0.0;
    for (std::uint32_t index = 0U; index < mesh.triangles.size(); ++index) {
        const Triangle& triangle = mesh.triangles[index];
        if (triangle.a >= mesh.vertices.size() ||
            triangle.b >= mesh.vertices.size() ||
            triangle.c >= mesh.vertices.size()) {
            throw std::invalid_argument(
                "interactive candidate mesh contains an invalid triangle index");
        }
        const Vec3& a = mesh.vertices[triangle.a];
        const Vec3& b = mesh.vertices[triangle.b];
        const Vec3& c = mesh.vertices[triangle.c];
        const Vec3 area_vector = cross(subtract(b, a), subtract(c, a));
        const double doubled_area = length(area_vector);
        if (doubled_area <= 2.0e-14) {
            continue;
        }
        total_area += 0.5 * doubled_area;
        triangles.push_back(index);
        cumulative_areas.push_back(total_area);
        normals[index] = {
            area_vector.x / doubled_area,
            area_vector.y / doubled_area,
            area_vector.z / doubled_area,
        };
    }
    if (total_area <= 1.0e-14 || triangles.empty()) {
        throw std::invalid_argument(
            "interactive candidate mesh has no non-degenerate surface area");
    }

    InteractiveCandidateBatch batch;
    batch.seed = settings.seed;
    batch.candidate_count = candidate_count;
    batch.surface_area = total_area;
    const std::size_t count = candidate_count;
    batch.positions_xyz.reserve(count * 3U);
    batch.normals_xyz.reserve(count * 3U);
    batch.barycentric.reserve(count * 3U);
    batch.random_values.reserve(count * kInteractiveCandidateRandomStride);
    batch.triangle_indices.reserve(count);
    batch.candidate_keys.reserve(count);

    for (std::uint64_t ordinal = 0U; ordinal < candidate_count; ++ordinal) {
        const double weighted = candidate_random(settings.seed, ordinal, 0U) *
            total_area;
        const auto found = std::lower_bound(
            cumulative_areas.begin(), cumulative_areas.end(), weighted);
        const std::size_t area_index = std::min<std::size_t>(
            static_cast<std::size_t>(found - cumulative_areas.begin()),
            triangles.size() - 1U);
        const std::uint32_t triangle_index = triangles[area_index];
        const Triangle& triangle = mesh.triangles[triangle_index];
        const double root = std::sqrt(candidate_random(settings.seed, ordinal, 1U));
        const double second = candidate_random(settings.seed, ordinal, 2U);
        const std::array<double, 3> weights{
            1.0 - root,
            root * (1.0 - second),
            root * second,
        };
        const Vec3& a = mesh.vertices[triangle.a];
        const Vec3& b = mesh.vertices[triangle.b];
        const Vec3& c = mesh.vertices[triangle.c];
        const Vec3 position{
            a.x * weights[0] + b.x * weights[1] + c.x * weights[2],
            a.y * weights[0] + b.y * weights[1] + c.y * weights[2],
            a.z * weights[0] + b.z * weights[1] + c.z * weights[2],
        };

        append_vec3(batch.positions_xyz, position);
        append_vec3(batch.normals_xyz, normals[triangle_index]);
        for (const double weight : weights) {
            batch.barycentric.push_back(static_cast<float>(weight));
        }
        // density acceptance, mask acceptance, size, rotation, type, shape
        for (std::uint64_t lane = 3U;
             lane < 3U + kInteractiveCandidateRandomStride;
             ++lane) {
            batch.random_values.push_back(static_cast<float>(
                candidate_random(settings.seed, ordinal, lane)));
        }
        batch.triangle_indices.push_back(triangle_index);
        // Addition by ordinal is bijective modulo 2^64, so keys are unique
        // within a batch while remaining seed-specific and prefix-stable.
        batch.candidate_keys.push_back(
            splitmix64(settings.seed ^ kCandidateStream) + ordinal);
    }
    return batch;
}

}  // namespace bifrost_scales
