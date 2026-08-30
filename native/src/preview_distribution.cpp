#include "bifrost_scales/preview_distribution.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <vector>

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


struct GridCell {
    std::int64_t x{0};
    std::int64_t y{0};
    std::int64_t z{0};

    bool operator==(const GridCell& other) const noexcept {
        return x == other.x && y == other.y && z == other.z;
    }
};

struct GridCellHash {
    std::size_t operator()(const GridCell& cell) const noexcept {
        auto mix = [](std::uint64_t value) noexcept {
            value ^= value >> 30U;
            value *= 0xBF58476D1CE4E5B9ULL;
            value ^= value >> 27U;
            value *= 0x94D049BB133111EBULL;
            return value ^ (value >> 31U);
        };
        const std::uint64_t hx = mix(static_cast<std::uint64_t>(cell.x));
        const std::uint64_t hy = mix(static_cast<std::uint64_t>(cell.y));
        const std::uint64_t hz = mix(static_cast<std::uint64_t>(cell.z));
        return static_cast<std::size_t>(
            hx ^ (hy + 0x9E3779B97F4A7C15ULL + (hx << 6U) + (hx >> 2U)) ^
            (hz + 0x517CC1B727220A95ULL));
    }
};

std::int64_t grid_coordinate(float value, float cell_size) {
    const double coordinate = std::floor(
        static_cast<double>(value) / static_cast<double>(cell_size));
    constexpr double minimum = static_cast<double>(
        std::numeric_limits<std::int64_t>::min() + 1);
    constexpr double maximum = static_cast<double>(
        std::numeric_limits<std::int64_t>::max() - 1);
    if (!std::isfinite(coordinate) ||
        coordinate < minimum ||
        coordinate > maximum) {
        throw std::invalid_argument(
            "interactive candidate position is outside the grid range");
    }
    return static_cast<std::int64_t>(coordinate);
}

void append_vec3(std::vector<float>& output, const Vec3& value) {
    output.push_back(static_cast<float>(value.x));
    output.push_back(static_cast<float>(value.y));
    output.push_back(static_cast<float>(value.z));
}

struct InteractiveSurfaceSamplingData {
    std::vector<std::uint32_t> triangles;
    std::vector<double> cumulative_areas;
    std::vector<Vec3> normals;
    double total_area{0.0};
};

std::uint64_t interactive_mesh_hash(const Mesh& mesh) noexcept {
    constexpr std::uint64_t offset = 14695981039346656037ULL;
    constexpr std::uint64_t prime = 1099511628211ULL;
    std::uint64_t result = offset;
    const auto bytes = [&](const void* data, std::size_t size) {
        const auto* values = static_cast<const unsigned char*>(data);
        for (std::size_t index = 0U; index < size; ++index) {
            result ^= static_cast<std::uint64_t>(values[index]);
            result *= prime;
        }
    };
    const std::uint64_t vertex_count = mesh.vertices.size();
    bytes(&vertex_count, sizeof(vertex_count));
    for (const Vec3& point : mesh.vertices) {
        bytes(&point.x, sizeof(point.x));
        bytes(&point.y, sizeof(point.y));
        bytes(&point.z, sizeof(point.z));
    }
    const std::uint64_t triangle_count = mesh.triangles.size();
    bytes(&triangle_count, sizeof(triangle_count));
    for (const Triangle& triangle : mesh.triangles) {
        bytes(&triangle.a, sizeof(triangle.a));
        bytes(&triangle.b, sizeof(triangle.b));
        bytes(&triangle.c, sizeof(triangle.c));
    }
    return result == 0U ? 1U : result;
}

std::shared_ptr<const InteractiveSurfaceSamplingData>
build_interactive_surface_sampling_data(const Mesh& mesh) {
    auto data = std::make_shared<InteractiveSurfaceSamplingData>();
    data->normals.resize(mesh.triangles.size());
    data->triangles.reserve(mesh.triangles.size());
    data->cumulative_areas.reserve(mesh.triangles.size());
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
        data->total_area += 0.5 * doubled_area;
        data->triangles.push_back(index);
        data->cumulative_areas.push_back(data->total_area);
        data->normals[index] = {
            area_vector.x / doubled_area,
            area_vector.y / doubled_area,
            area_vector.z / doubled_area,
        };
    }
    if (data->total_area <= 1.0e-14 || data->triangles.empty()) {
        throw std::invalid_argument(
            "interactive candidate mesh has no non-degenerate surface area");
    }
    return data;
}

struct InteractiveSurfaceCacheEntry {
    std::uint64_t geometry_hash{0U};
    std::size_t vertex_count{0U};
    std::size_t triangle_count{0U};
    std::shared_ptr<const InteractiveSurfaceSamplingData> data;
    std::uint64_t access_stamp{0U};
};

struct InteractiveSurfaceCache {
    std::mutex mutex;
    std::uint64_t access_clock{0U};
    std::vector<InteractiveSurfaceCacheEntry> entries;
};

InteractiveSurfaceCache& interactive_surface_cache() {
    static InteractiveSurfaceCache cache;
    return cache;
}

std::shared_ptr<const InteractiveSurfaceSamplingData>
shared_interactive_surface_sampling_data(const Mesh& mesh, bool* cache_hit) {
    const std::uint64_t geometry_hash = interactive_mesh_hash(mesh);
    InteractiveSurfaceCache& cache = interactive_surface_cache();
    {
        std::lock_guard<std::mutex> lock(cache.mutex);
        for (InteractiveSurfaceCacheEntry& entry : cache.entries) {
            if (entry.geometry_hash == geometry_hash &&
                entry.vertex_count == mesh.vertices.size() &&
                entry.triangle_count == mesh.triangles.size()) {
                entry.access_stamp = ++cache.access_clock;
                *cache_hit = true;
                return entry.data;
            }
        }
    }
    auto built = build_interactive_surface_sampling_data(mesh);
    std::lock_guard<std::mutex> lock(cache.mutex);
    constexpr std::size_t capacity = 2U;
    if (cache.entries.size() >= capacity) {
        const auto oldest = std::min_element(
            cache.entries.begin(),
            cache.entries.end(),
            [](const InteractiveSurfaceCacheEntry& left,
               const InteractiveSurfaceCacheEntry& right) {
                return left.access_stamp < right.access_stamp;
            });
        cache.entries.erase(oldest);
    }
    cache.entries.push_back({
        geometry_hash,
        mesh.vertices.size(),
        mesh.triangles.size(),
        std::move(built),
        ++cache.access_clock,
    });
    *cache_hit = false;
    return cache.entries.back().data;
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
    bool surface_cache_hit = false;
    const auto surface = shared_interactive_surface_sampling_data(
        mesh,
        &surface_cache_hit);

    InteractiveCandidateBatch batch;
    batch.seed = settings.seed;
    batch.candidate_count = candidate_count;
    batch.surface_area = surface->total_area;
    batch.surface_cache_hit = surface_cache_hit;
    const std::size_t count = candidate_count;
    batch.positions_xyz.reserve(count * 3U);
    batch.normals_xyz.reserve(count * 3U);
    batch.barycentric.reserve(count * 3U);
    batch.random_values.reserve(count * kInteractiveCandidateRandomStride);
    batch.triangle_indices.reserve(count);
    batch.candidate_keys.reserve(count);

    for (std::uint64_t ordinal = 0U; ordinal < candidate_count; ++ordinal) {
        const double weighted = candidate_random(settings.seed, ordinal, 0U) *
            surface->total_area;
        const auto found = std::lower_bound(
            surface->cumulative_areas.begin(),
            surface->cumulative_areas.end(),
            weighted);
        const std::size_t area_index = std::min<std::size_t>(
            static_cast<std::size_t>(found - surface->cumulative_areas.begin()),
            surface->triangles.size() - 1U);
        const std::uint32_t triangle_index = surface->triangles[area_index];
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
        append_vec3(batch.normals_xyz, surface->normals[triangle_index]);
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

void clear_interactive_candidate_cache() {
    InteractiveSurfaceCache& cache = interactive_surface_cache();
    std::lock_guard<std::mutex> lock(cache.mutex);
    cache.entries.clear();
    cache.access_clock = 0U;
}


bool InteractiveCandidateFields::has_consistent_sizes(
    std::size_t candidate_count) const noexcept {
    const auto valid = [candidate_count](const std::vector<float>& values) {
        return values.empty() || values.size() == candidate_count;
    };
    return valid(density_acceptance) &&
           valid(mask_acceptance) &&
           valid(local_spacing);
}

bool InteractiveConflictResult::has_consistent_sizes() const noexcept {
    return accepted_candidate_indices.size() == accepted_count &&
           accepted_candidate_keys.size() == accepted_count &&
           accepted_count <= considered_count &&
           accepted_count + rejected_density + rejected_mask +
               rejected_conflict == considered_count;
}

InteractiveConflictResult arbitrate_interactive_candidates(
    const InteractiveCandidateBatch& batch,
    const Settings& settings,
    std::uint32_t max_accepted,
    const InteractiveCandidateFields& fields) {
    if (!batch.has_consistent_sizes()) {
        throw std::invalid_argument(
            "interactive candidate batch has inconsistent buffer sizes");
    }
    if (!fields.has_consistent_sizes(batch.candidate_count)) {
        throw std::invalid_argument(
            "interactive candidate fields have inconsistent buffer sizes");
    }
    if (!std::isfinite(batch.surface_area) || batch.surface_area <= 0.0) {
        throw std::invalid_argument(
            "interactive candidate batch has invalid surface area");
    }

    const double nominal_count = static_cast<double>(
        std::max<std::uint32_t>(max_accepted, 1U));
    const double spacing_factor = std::clamp(
        settings.spacing_factor,
        0.15,
        2.5);
    const float default_spacing = static_cast<float>(
        std::sqrt(batch.surface_area / nominal_count) * spacing_factor);
    if (!std::isfinite(default_spacing) || default_spacing <= 0.0F) {
        throw std::invalid_argument(
            "interactive conflict reference has invalid default spacing");
    }

    InteractiveConflictResult result;
    result.default_spacing = default_spacing;
    if (max_accepted == 0U || batch.candidate_count == 0U) {
        return result;
    }
    result.accepted_candidate_indices.reserve(std::min<std::size_t>(
        batch.candidate_count,
        max_accepted));
    result.accepted_candidate_keys.reserve(std::min<std::size_t>(
        batch.candidate_count,
        max_accepted));

    float maximum_spacing = default_spacing;
    if (!fields.local_spacing.empty()) {
        for (const float spacing : fields.local_spacing) {
            if (!std::isfinite(spacing) || spacing <= 0.0F) {
                throw std::invalid_argument(
                    "interactive local spacing must be finite and positive");
            }
            maximum_spacing = std::max(maximum_spacing, spacing);
        }
    }
    const auto acceptance_at = [](const std::vector<float>& values,
                                  std::size_t index) {
        if (values.empty()) {
            return 1.0F;
        }
        const float value = values[index];
        if (!std::isfinite(value)) {
            throw std::invalid_argument(
                "interactive acceptance must be finite");
        }
        return std::clamp(value, 0.0F, 1.0F);
    };
    const auto spacing_at = [&fields, default_spacing](std::size_t index) {
        return fields.local_spacing.empty()
            ? default_spacing
            : fields.local_spacing[index];
    };

    std::unordered_map<GridCell, std::vector<std::uint32_t>, GridCellHash>
        accepted_buckets;
    accepted_buckets.reserve(std::min<std::size_t>(
        batch.candidate_count,
        max_accepted));
    std::vector<float> accepted_spacings;
    accepted_spacings.reserve(std::min<std::size_t>(
        batch.candidate_count,
        max_accepted));

    for (std::uint32_t candidate_index = 0U;
         candidate_index < batch.candidate_count &&
             result.accepted_count < max_accepted;
         ++candidate_index) {
        ++result.considered_count;
        const std::size_t random_offset =
            static_cast<std::size_t>(candidate_index) *
            kInteractiveCandidateRandomStride;
        if (batch.random_values[random_offset] >=
            acceptance_at(fields.density_acceptance, candidate_index)) {
            ++result.rejected_density;
            continue;
        }
        if (batch.random_values[random_offset + 1U] >=
            acceptance_at(fields.mask_acceptance, candidate_index)) {
            ++result.rejected_mask;
            continue;
        }

        const std::size_t position_offset =
            static_cast<std::size_t>(candidate_index) * 3U;
        const float px = batch.positions_xyz[position_offset];
        const float py = batch.positions_xyz[position_offset + 1U];
        const float pz = batch.positions_xyz[position_offset + 2U];
        const GridCell cell{
            grid_coordinate(px, maximum_spacing),
            grid_coordinate(py, maximum_spacing),
            grid_coordinate(pz, maximum_spacing),
        };
        const float candidate_spacing = spacing_at(candidate_index);
        bool conflicts = false;
        for (int dz = -1; dz <= 1 && !conflicts; ++dz) {
            for (int dy = -1; dy <= 1 && !conflicts; ++dy) {
                for (int dx = -1; dx <= 1 && !conflicts; ++dx) {
                    const GridCell neighbor{
                        cell.x + dx,
                        cell.y + dy,
                        cell.z + dz,
                    };
                    const auto found = accepted_buckets.find(neighbor);
                    if (found == accepted_buckets.end()) {
                        continue;
                    }
                    for (const std::uint32_t accepted_slot : found->second) {
                        const std::uint32_t accepted_index =
                            result.accepted_candidate_indices[accepted_slot];
                        const std::size_t accepted_offset =
                            static_cast<std::size_t>(accepted_index) * 3U;
                        const float delta_x =
                            px - batch.positions_xyz[accepted_offset];
                        const float delta_y =
                            py - batch.positions_xyz[accepted_offset + 1U];
                        const float delta_z =
                            pz - batch.positions_xyz[accepted_offset + 2U];
                        const float minimum_distance = std::max(
                            candidate_spacing,
                            accepted_spacings[accepted_slot]);
                        const float distance_squared =
                            delta_x * delta_x +
                            delta_y * delta_y +
                            delta_z * delta_z;
                        if (distance_squared <
                            minimum_distance * minimum_distance) {
                            conflicts = true;
                            break;
                        }
                    }
                }
            }
        }
        if (conflicts) {
            ++result.rejected_conflict;
            continue;
        }

        const std::uint32_t accepted_slot = result.accepted_count;
        result.accepted_candidate_indices.push_back(candidate_index);
        result.accepted_candidate_keys.push_back(
            batch.candidate_keys[candidate_index]);
        accepted_spacings.push_back(candidate_spacing);
        accepted_buckets[cell].push_back(accepted_slot);
        ++result.accepted_count;
    }
    return result;
}


InteractiveConflictResult arbitrate_interactive_candidates_accelerated(
    const InteractiveCandidateBatch& batch,
    const Settings& settings,
    std::uint32_t max_accepted,
    gpu::ExecutionInfo& execution,
    const InteractiveCandidateFields& fields) {
    execution = gpu::ExecutionInfo{};
    auto cpu_fallback = [&]() {
        execution.used = false;
        execution.backend = "cpu-conflict-reference";
        return arbitrate_interactive_candidates(
            batch,
            settings,
            max_accepted,
            fields);
    };
    if (max_accepted == 0U) {
        execution.fallback_reason =
            "conflict accepted limit is zero";
        return cpu_fallback();
    }
    if (!gpu::should_attempt_conflict(
            batch.candidate_count,
            execution)) {
        return cpu_fallback();
    }
    if (!batch.has_consistent_sizes()) {
        throw std::invalid_argument(
            "interactive candidate batch has inconsistent buffer sizes");
    }
    if (!fields.has_consistent_sizes(batch.candidate_count)) {
        throw std::invalid_argument(
            "interactive candidate fields have inconsistent buffer sizes");
    }
    if (!std::isfinite(batch.surface_area) || batch.surface_area <= 0.0) {
        throw std::invalid_argument(
            "interactive candidate batch has invalid surface area");
    }

    const double nominal_count = static_cast<double>(
        std::max<std::uint32_t>(max_accepted, 1U));
    const double spacing_factor = std::clamp(
        settings.spacing_factor,
        0.15,
        2.5);
    const float default_spacing = static_cast<float>(
        std::sqrt(batch.surface_area / nominal_count) * spacing_factor);
    if (!std::isfinite(default_spacing) || default_spacing <= 0.0F) {
        throw std::invalid_argument(
            "interactive conflict GPU path has invalid default spacing");
    }

    float maximum_spacing = default_spacing;
    if (!fields.local_spacing.empty()) {
        for (const float spacing : fields.local_spacing) {
            if (!std::isfinite(spacing) || spacing <= 0.0F) {
                throw std::invalid_argument(
                    "interactive local spacing must be finite and positive");
            }
            maximum_spacing = std::max(maximum_spacing, spacing);
        }
    }
    const auto acceptance_at = [](const std::vector<float>& values,
                                  std::size_t index) {
        if (values.empty()) {
            return 1.0F;
        }
        const float value = values[index];
        if (!std::isfinite(value)) {
            throw std::invalid_argument(
                "interactive acceptance must be finite");
        }
        return std::clamp(value, 0.0F, 1.0F);
    };
    const auto spacing_at = [&fields, default_spacing](std::size_t index) {
        return fields.local_spacing.empty()
            ? default_spacing
            : fields.local_spacing[index];
    };

    std::vector<gpu::ConflictInput> inputs;
    inputs.reserve(batch.candidate_count);
    constexpr std::int64_t minimum_cell =
        static_cast<std::int64_t>(
            std::numeric_limits<std::int32_t>::min()) + 1;
    constexpr std::int64_t maximum_cell =
        static_cast<std::int64_t>(
            std::numeric_limits<std::int32_t>::max()) - 1;
    for (std::size_t index = 0U;
         index < batch.candidate_count;
         ++index) {
        const std::size_t position_offset = index * 3U;
        const std::size_t random_offset =
            index * kInteractiveCandidateRandomStride;
        const std::int64_t cell_x = grid_coordinate(
            batch.positions_xyz[position_offset],
            maximum_spacing);
        const std::int64_t cell_y = grid_coordinate(
            batch.positions_xyz[position_offset + 1U],
            maximum_spacing);
        const std::int64_t cell_z = grid_coordinate(
            batch.positions_xyz[position_offset + 2U],
            maximum_spacing);
        if (cell_x < minimum_cell || cell_x > maximum_cell ||
            cell_y < minimum_cell || cell_y > maximum_cell ||
            cell_z < minimum_cell || cell_z > maximum_cell) {
            execution.fallback_reason =
                "candidate grid coordinate exceeds OpenCL int32 range";
            return cpu_fallback();
        }

        gpu::ConflictInput input;
        input.position = {
            batch.positions_xyz[position_offset],
            batch.positions_xyz[position_offset + 1U],
            batch.positions_xyz[position_offset + 2U],
            0.0F,
        };
        input.gates = {
            batch.random_values[random_offset],
            batch.random_values[random_offset + 1U],
            acceptance_at(fields.density_acceptance, index),
            acceptance_at(fields.mask_acceptance, index),
        };
        input.local_spacing = spacing_at(index);
        input.cell_x = static_cast<std::int32_t>(cell_x);
        input.cell_y = static_cast<std::int32_t>(cell_y);
        input.cell_z = static_cast<std::int32_t>(cell_z);
        inputs.push_back(input);
    }

    std::vector<std::uint32_t> accepted_indices;
    gpu::ConflictCounters counters;
    if (!gpu::try_arbitrate_conflicts(
            inputs,
            max_accepted,
            accepted_indices,
            counters,
            execution)) {
        return cpu_fallback();
    }

    InteractiveConflictResult result;
    result.considered_count = counters.considered_count;
    result.accepted_count = counters.accepted_count;
    result.rejected_density = counters.rejected_density;
    result.rejected_mask = counters.rejected_mask;
    result.rejected_conflict = counters.rejected_conflict;
    result.default_spacing = default_spacing;
    result.accepted_candidate_indices = std::move(accepted_indices);
    result.accepted_candidate_keys.reserve(result.accepted_count);
    bool valid_indices = true;
    std::uint32_t previous_index = 0U;
    for (std::size_t slot = 0U;
         slot < result.accepted_candidate_indices.size();
         ++slot) {
        const std::uint32_t index =
            result.accepted_candidate_indices[slot];
        if (index >= batch.candidate_count ||
            (slot > 0U && index <= previous_index)) {
            valid_indices = false;
            break;
        }
        result.accepted_candidate_keys.push_back(
            batch.candidate_keys[index]);
        previous_index = index;
    }
    if (!valid_indices || !result.has_consistent_sizes()) {
        execution.used = false;
        execution.backend = "cpu-conflict-reference";
        execution.fallback_reason =
            "OpenCL conflict output failed validation";
        return cpu_fallback();
    }
    return result;
}



}  // namespace bifrost_scales
