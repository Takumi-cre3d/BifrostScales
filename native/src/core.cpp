#include "bifrost_scales/core.hpp"
#include "bifrost_scales/gpu_compute.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <exception>
#include <functional>
#include <limits>
#include <iterator>
#include <memory>
#include <mutex>
#include <numeric>
#include <queue>
#include <tuple>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace bifrost_scales {
namespace {

constexpr double kEpsilon = 1.0e-12;
constexpr double kPi = 3.1415926535897932384626433832795;
constexpr double kMaskHardCoreInfluence = 0.98;
constexpr double kFixedScaleAspect = 1.65;
constexpr std::array<double, 5> kRelaxationFactors{1.0, 0.86, 0.73, 0.61, 0.50};
constexpr std::uint64_t kFnvOffsetBasis64 = 14695981039346656037ULL;
constexpr std::uint64_t kFnvPrime64 = 1099511628211ULL;
constexpr std::uint64_t kRoleOpenBoundary = 1ULL;
constexpr std::uint64_t kRoleCurveCenter = 2ULL;
constexpr std::uint64_t kRoleSurfaceCandidate = 3ULL;
constexpr std::uint32_t kAutomaticWorkerCap = 32U;

std::uint32_t configured_worker_limit() {
    const char* encoded = std::getenv("BIFROST_SCALES_CPU_THREADS");
    if (encoded != nullptr && encoded[0] != '\0') {
        char* end = nullptr;
        const unsigned long parsed = std::strtoul(encoded, &end, 10);
        if (end != encoded && *end == '\0') {
            if (parsed == 0UL) {
                // Zero explicitly selects the automatic policy.
            } else {
                return static_cast<std::uint32_t>(std::clamp<unsigned long>(
                    parsed,
                    1UL,
                    64UL));
            }
        }
    }
    const std::uint32_t hardware = std::max<std::uint32_t>(
        1U,
        std::thread::hardware_concurrency());
    const std::uint32_t responsive = hardware > 4U ? hardware - 1U : hardware;
    return std::clamp<std::uint32_t>(responsive, 1U, kAutomaticWorkerCap);
}

std::uint32_t parallel_worker_count(
    std::size_t item_count,
    std::size_t minimum_items_per_worker) {
    if (item_count == 0U) {
        return 1U;
    }
    const std::size_t grain = std::max<std::size_t>(1U, minimum_items_per_worker);
    const std::size_t useful_workers =
        (item_count + grain - 1U) / grain;
    return static_cast<std::uint32_t>(std::max<std::size_t>(
        1U,
        std::min<std::size_t>(configured_worker_limit(), useful_workers)));
}

template <typename Function>
std::uint32_t parallel_for_chunks(
    std::size_t item_count,
    std::size_t minimum_items_per_worker,
    Function&& function) {
    const std::uint32_t worker_count = parallel_worker_count(
        item_count,
        minimum_items_per_worker);
    if (worker_count <= 1U) {
        function(0U, item_count, 0U);
        return 1U;
    }

    std::vector<std::thread> threads;
    threads.reserve(worker_count - 1U);
    std::vector<std::exception_ptr> errors(worker_count);

    auto invoke = [&](std::uint32_t worker_index) {
        const std::size_t begin =
            item_count * static_cast<std::size_t>(worker_index) / worker_count;
        const std::size_t end =
            item_count * static_cast<std::size_t>(worker_index + 1U) / worker_count;
        try {
            function(begin, end, worker_index);
        } catch (...) {
            errors[worker_index] = std::current_exception();
        }
    };

    for (std::uint32_t worker_index = 1U;
         worker_index < worker_count;
         ++worker_index) {
        threads.emplace_back(invoke, worker_index);
    }
    invoke(0U);
    for (std::thread& thread : threads) {
        thread.join();
    }
    for (const std::exception_ptr& error : errors) {
        if (error) {
            std::rethrow_exception(error);
        }
    }
    return worker_count;
}

std::uint64_t fnv_bytes(std::uint64_t seed, const unsigned char* values, std::size_t size) {
    std::uint64_t result = seed;
    for (std::size_t index = 0U; index < size; ++index) {
        result ^= static_cast<std::uint64_t>(values[index]);
        result *= kFnvPrime64;
    }
    return result;
}

std::uint64_t fnv_text(std::uint64_t seed, std::string_view value) {
    return fnv_bytes(
        seed,
        reinterpret_cast<const unsigned char*>(value.data()),
        value.size());
}

std::uint64_t fnv_u64(std::uint64_t seed, std::uint64_t value) {
    std::array<unsigned char, 8> bytes{};
    for (std::size_t index = 0U; index < bytes.size(); ++index) {
        bytes[index] = static_cast<unsigned char>((value >> (index * 8U)) & 0xffU);
    }
    return fnv_bytes(seed, bytes.data(), bytes.size());
}

std::uint64_t stable_hash_values(
    std::string_view tag,
    std::initializer_list<std::uint64_t> values) {
    std::uint64_t result = fnv_text(kFnvOffsetBasis64, tag);
    const unsigned char terminator = 0U;
    result = fnv_bytes(result, &terminator, 1U);
    for (const std::uint64_t value : values) {
        result = fnv_u64(result, value);
    }
    return result == 0U ? 1U : result;
}

std::uint64_t stable_hash_text(std::string_view tag, std::string_view value) {
    std::uint64_t result = fnv_text(kFnvOffsetBasis64, tag);
    const unsigned char terminator = 0U;
    result = fnv_bytes(result, &terminator, 1U);
    result = fnv_text(result, value);
    return result == 0U ? 1U : result;
}

std::uint64_t mesh_topology_hash(const Mesh& mesh) {
    std::uint64_t result = fnv_text(kFnvOffsetBasis64, "bifrost-scales/topology/1");
    const unsigned char terminator = 0U;
    result = fnv_bytes(result, &terminator, 1U);
    result = fnv_u64(result, static_cast<std::uint64_t>(mesh.vertices.size()));
    result = fnv_u64(result, static_cast<std::uint64_t>(mesh.triangles.size()));
    for (const Triangle& triangle : mesh.triangles) {
        result = fnv_u64(result, triangle.a);
        result = fnv_u64(result, triangle.b);
        result = fnv_u64(result, triangle.c);
    }
    return result == 0U ? 1U : result;
}

std::uint64_t sample_stable_id(
    std::uint64_t topology_hash,
    std::uint64_t distribution_seed,
    std::uint64_t role,
    std::initializer_list<std::uint64_t> role_values) {
    std::uint64_t result = fnv_text(
        kFnvOffsetBasis64,
        "bifrost-scales/cell-id/1");
    const unsigned char terminator = 0U;
    result = fnv_bytes(result, &terminator, 1U);
    result = fnv_u64(result, topology_hash);
    result = fnv_u64(result, distribution_seed);
    result = fnv_u64(result, role);
    for (const std::uint64_t value : role_values) {
        result = fnv_u64(result, value);
    }
    return result == 0U ? 1U : result;
}

std::uint64_t boundary_edge_key(std::uint32_t left, std::uint32_t right);

// Match CPython ``random.Random(int_seed).random()`` exactly.  Python is the
// reference backend, so sharing its MT19937 seeding and 53-bit float mapping
// keeps distribution order stable across the Python and Native cores.
class PythonRandom {
public:
    explicit PythonRandom(std::uint64_t seed) {
        const std::array<std::uint32_t, 2> words{
            static_cast<std::uint32_t>(seed & 0xffffffffULL),
            static_cast<std::uint32_t>(seed >> 32U),
        };
        init_by_array(words.data(), words[1] == 0U ? 1U : 2U);
    }

    double random() {
        const std::uint32_t upper = next_uint32() >> 5U;
        const std::uint32_t lower = next_uint32() >> 6U;
        return (static_cast<double>(upper) * 67108864.0 +
                static_cast<double>(lower)) *
               (1.0 / 9007199254740992.0);
    }

private:
    static constexpr std::size_t kStateSize = 624U;
    static constexpr std::size_t kMiddleWord = 397U;
    static constexpr std::uint32_t kMatrixA = 0x9908b0dfU;
    static constexpr std::uint32_t kUpperMask = 0x80000000U;
    static constexpr std::uint32_t kLowerMask = 0x7fffffffU;

    std::array<std::uint32_t, kStateSize> state_{};
    std::size_t index_{kStateSize};

    void init_genrand(std::uint32_t seed) {
        state_[0] = seed;
        for (std::size_t index = 1U; index < kStateSize; ++index) {
            const std::uint32_t previous = state_[index - 1U];
            state_[index] =
                1812433253U * (previous ^ (previous >> 30U)) +
                static_cast<std::uint32_t>(index);
        }
        index_ = kStateSize;
    }

    void init_by_array(const std::uint32_t* key, std::size_t key_length) {
        init_genrand(19650218U);
        std::size_t state_index = 1U;
        std::size_t key_index = 0U;
        std::size_t count = std::max(kStateSize, key_length);
        for (; count > 0U; --count) {
            const std::uint32_t previous = state_[state_index - 1U];
            state_[state_index] =
                (state_[state_index] ^
                 ((previous ^ (previous >> 30U)) * 1664525U)) +
                key[key_index] + static_cast<std::uint32_t>(key_index);
            ++state_index;
            ++key_index;
            if (state_index >= kStateSize) {
                state_[0] = state_[kStateSize - 1U];
                state_index = 1U;
            }
            if (key_index >= key_length) {
                key_index = 0U;
            }
        }
        for (count = kStateSize - 1U; count > 0U; --count) {
            const std::uint32_t previous = state_[state_index - 1U];
            state_[state_index] =
                (state_[state_index] ^
                 ((previous ^ (previous >> 30U)) * 1566083941U)) -
                static_cast<std::uint32_t>(state_index);
            ++state_index;
            if (state_index >= kStateSize) {
                state_[0] = state_[kStateSize - 1U];
                state_index = 1U;
            }
        }
        state_[0] = 0x80000000U;
        index_ = kStateSize;
    }

    void twist() {
        static constexpr std::array<std::uint32_t, 2> kMagic{0U, kMatrixA};
        std::size_t state_index = 0U;
        for (; state_index < kStateSize - kMiddleWord; ++state_index) {
            const std::uint32_t mixed =
                (state_[state_index] & kUpperMask) |
                (state_[state_index + 1U] & kLowerMask);
            state_[state_index] =
                state_[state_index + kMiddleWord] ^
                (mixed >> 1U) ^ kMagic[mixed & 1U];
        }
        for (; state_index < kStateSize - 1U; ++state_index) {
            const std::uint32_t mixed =
                (state_[state_index] & kUpperMask) |
                (state_[state_index + 1U] & kLowerMask);
            state_[state_index] =
                state_[state_index + kMiddleWord - kStateSize] ^
                (mixed >> 1U) ^ kMagic[mixed & 1U];
        }
        const std::uint32_t mixed =
            (state_[kStateSize - 1U] & kUpperMask) |
            (state_[0] & kLowerMask);
        state_[kStateSize - 1U] =
            state_[kMiddleWord - 1U] ^
            (mixed >> 1U) ^ kMagic[mixed & 1U];
        index_ = 0U;
    }

    std::uint32_t next_uint32() {
        if (index_ >= kStateSize) {
            twist();
        }
        std::uint32_t value = state_[index_++];
        value ^= value >> 11U;
        value ^= (value << 7U) & 0x9d2c5680U;
        value ^= (value << 15U) & 0xefc60000U;
        value ^= value >> 18U;
        return value;
    }
};

double clamp(double value, double minimum, double maximum) {
    return std::max(minimum, std::min(maximum, value));
}

double lerp_scalar(double left, double right, double amount) {
    return left + (right - left) * amount;
}

double combine_size_multipliers(
    double guide_multiplier,
    double type_multiplier) {
    const double guide = clamp(guide_multiplier, 0.05, 8.0);
    const double scale_type = clamp(type_multiplier, 0.05, 8.0);
    const double combined =
        1.0 + (guide - 1.0) + (scale_type - 1.0);
    return clamp(
        combined,
        std::min({1.0, guide, scale_type}),
        std::max({1.0, guide, scale_type}));
}

Vec3 add(const Vec3& a, const Vec3& b) {
    return {a.x + b.x, a.y + b.y, a.z + b.z};
}

Vec3 sub(const Vec3& a, const Vec3& b) {
    return {a.x - b.x, a.y - b.y, a.z - b.z};
}

Vec3 mul(const Vec3& value, double scalar) {
    return {value.x * scalar, value.y * scalar, value.z * scalar};
}

double dot(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

Vec3 cross(const Vec3& a, const Vec3& b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

double length_squared(const Vec3& value) {
    return dot(value, value);
}

double length(const Vec3& value) {
    return std::sqrt(length_squared(value));
}

Vec3 normalize(const Vec3& value, const Vec3& fallback = {0.0, 1.0, 0.0}) {
    const double magnitude = length(value);
    if (magnitude <= kEpsilon) {
        return fallback;
    }
    return mul(value, 1.0 / magnitude);
}

Vec3 project_on_plane(const Vec3& value, const Vec3& normal) {
    return sub(value, mul(normal, dot(value, normal)));
}

Vec3 orthonormal_tangent(const Vec3& normal) {
    const Vec3 unit_normal = normalize(normal);
    Vec3 tangent = project_on_plane({0.0, 1.0, 0.0}, unit_normal);
    if (length_squared(tangent) <= 1.0e-10) {
        tangent = project_on_plane({1.0, 0.0, 0.0}, unit_normal);
    }
    return normalize(tangent, {1.0, 0.0, 0.0});
}

Vec3 rotate_around_axis(const Vec3& value, const Vec3& axis, double radians) {
    const Vec3 unit_axis = normalize(axis);
    const double cosine = std::cos(radians);
    const double sine = std::sin(radians);
    return add(
        add(mul(value, cosine), mul(cross(unit_axis, value), sine)),
        mul(unit_axis, dot(unit_axis, value) * (1.0 - cosine)));
}

Vec3 blend_oriented_direction(
    const Vec3& current,
    const Vec3& desired,
    const Vec3& normal,
    double amount) {
    const double t = clamp(amount, 0.0, 1.0);
    const Vec3 start = normalize(project_on_plane(current, normal), current);
    const Vec3 target = normalize(project_on_plane(desired, normal), desired);
    if (t <= 0.0) {
        return start;
    }
    if (t >= 1.0) {
        return target;
    }
    const double cosine = clamp(dot(start, target), -1.0, 1.0);
    if (cosine <= -0.999999) {
        return normalize(
            rotate_around_axis(start, normal, kPi * t),
            target);
    }
    return normalize(
        add(mul(start, 1.0 - t), mul(target, t)),
        target);
}

std::pair<Vec3, double> normal_and_area(const Vec3& a, const Vec3& b, const Vec3& c) {
    const Vec3 twice_area = cross(sub(b, a), sub(c, a));
    const double magnitude = length(twice_area);
    if (magnitude <= kEpsilon) {
        return {{0.0, 1.0, 0.0}, 0.0};
    }
    return {mul(twice_area, 1.0 / magnitude), 0.5 * magnitude};
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
        const auto h1 = std::hash<std::int64_t>{}(cell.x);
        const auto h2 = std::hash<std::int64_t>{}(cell.y);
        const auto h3 = std::hash<std::int64_t>{}(cell.z);
        return h1 ^ (h2 << 1U) ^ (h3 << 7U);
    }
};

GridCell cell_for(const Vec3& position, double cell_size) {
    const double inverse = 1.0 / std::max(kEpsilon, cell_size);
    return {
        static_cast<std::int64_t>(std::floor(position.x * inverse)),
        static_cast<std::int64_t>(std::floor(position.y * inverse)),
        static_cast<std::int64_t>(std::floor(position.z * inverse)),
    };
}

std::uint32_t effective_count(const Settings& settings, PreviewMode mode) {
    switch (mode) {
        case PreviewMode::Interactive:
            return std::min(settings.target_count, settings.interactive_budget);
        case PreviewMode::Settled:
            return std::min(settings.target_count, settings.settled_budget);
        case PreviewMode::Final:
            return settings.target_count;
    }
    return settings.target_count;
}

std::uint32_t effective_relax_iterations(const Settings& settings, PreviewMode mode) {
    switch (mode) {
        case PreviewMode::Interactive:
            return std::min<std::uint32_t>(settings.relax_iterations, 2U);
        case PreviewMode::Settled:
            return std::min<std::uint32_t>(settings.relax_iterations, 16U);
        case PreviewMode::Final:
            return settings.relax_iterations;
    }
    return settings.relax_iterations;
}

std::uint32_t effective_direction_relax_iterations(
    const Settings& settings,
    PreviewMode mode) {
    switch (mode) {
        case PreviewMode::Interactive:
            return std::min<std::uint32_t>(settings.direction_relax_iterations, 1U);
        case PreviewMode::Settled:
            return std::min<std::uint32_t>(settings.direction_relax_iterations, 16U);
        case PreviewMode::Final:
            return settings.direction_relax_iterations;
    }
    return settings.direction_relax_iterations;
}

bool uses_cells(const Settings& settings, PreviewMode mode) {
    switch (settings.cell_mode) {
        case GeometryMode::Cards:
            return false;
        case GeometryMode::Cells:
            return true;
        case GeometryMode::Auto:
            return mode != PreviewMode::Interactive;
    }
    return mode != PreviewMode::Interactive;
}

std::uint32_t effective_cell_resolution(
    const Settings& settings,
    PreviewMode mode) {
    switch (mode) {
        case PreviewMode::Interactive:
            return std::clamp<std::uint32_t>(
                settings.cell_interactive_resolution,
                4U,
                64U);
        case PreviewMode::Settled:
            return std::clamp<std::uint32_t>(
                settings.cell_settled_resolution,
                4U,
                64U);
        case PreviewMode::Final:
            return settings.cell_settled_resolution >= 60U
                ? 64U
                : std::clamp<std::uint32_t>(
                      settings.cell_settled_resolution + 4U,
                      4U,
                      64U);
    }
    return 10U;
}

std::uint32_t effective_cell_projection_rings(
    const Settings& settings,
    PreviewMode mode) {
    switch (mode) {
        case PreviewMode::Interactive:
            return std::min<std::uint32_t>(settings.cell_projection_rings, 1U);
        case PreviewMode::Settled:
            return std::min<std::uint32_t>(settings.cell_projection_rings, 16U);
        case PreviewMode::Final:
            return settings.cell_projection_rings >= 16U
                ? 16U
                : settings.cell_projection_rings + 1U;
    }
    return 2U;
}

void validate_mesh(const Mesh& mesh) {
    if (mesh.vertices.empty() || mesh.triangles.empty()) {
        throw std::invalid_argument("mesh requires vertices and triangles");
    }
    for (const Triangle& triangle : mesh.triangles) {
        if (triangle.a >= mesh.vertices.size() || triangle.b >= mesh.vertices.size() ||
            triangle.c >= mesh.vertices.size()) {
            throw std::invalid_argument("triangle index is out of range");
        }
    }
}

bool default_use_density(GuideKind kind) {
    return kind == GuideKind::DensityPoint ||
           kind == GuideKind::DensityCurve ||
           kind == GuideKind::FlowCurve;
}

bool default_use_size(GuideKind kind) {
    return kind == GuideKind::DensityPoint ||
           kind == GuideKind::DensityCurve;
}

bool default_use_direction(GuideKind kind) {
    return kind == GuideKind::DirectionPoint ||
           kind == GuideKind::DirectionCurve ||
           kind == GuideKind::FlowCurve;
}

bool resolved_role(const std::optional<bool>& explicit_value, bool fallback) {
    return explicit_value.has_value() ? *explicit_value : fallback;
}

bool guide_uses_density(const Guide& guide) {
    return resolved_role(guide.use_density, default_use_density(guide.kind));
}

bool guide_uses_size(const Guide& guide) {
    return resolved_role(guide.use_size, default_use_size(guide.kind));
}

bool guide_uses_direction(const Guide& guide) {
    return resolved_role(guide.use_direction, default_use_direction(guide.kind));
}

bool guide_uses_mask(const Guide& guide) {
    return resolved_role(guide.use_mask, false);
}

bool is_curve(GuideKind kind) {
    return kind == GuideKind::DensityCurve ||
           kind == GuideKind::DirectionCurve ||
           kind == GuideKind::FlowCurve;
}

struct GuideNearest {
    double distance{0.0};
    Vec3 point{};
    Vec3 tangent{1.0, 0.0, 0.0};
};

struct PreparedCurveSegment {
    Vec3 start{};
    Vec3 end{};
    Vec3 delta{};
    Vec3 tangent{1.0, 0.0, 0.0};
    double denominator{0.0};
    double length{0.0};
};

struct SurfaceGuideSeed {
    std::uint32_t triangle_index{0U};
    Vec3 point{};
};

struct SurfaceGuideTopology {
    std::vector<Vec3> edge_midpoints;
    std::vector<std::array<std::uint32_t, 3>> triangle_edge_nodes;
};

struct PreparedGuide {
    const Guide* source{nullptr};
    bool curve{false};
    bool uses_density{false};
    bool uses_size{false};
    bool uses_direction{false};
    bool uses_mask{false};
    Vec3 fallback_point{};
    Vec3 fallback_tangent{1.0, 0.0, 0.0};
    Vec3 bounds_min{};
    Vec3 bounds_max{};
    double radius{1.0};
    double falloff{2.0};
    double total_length{0.0};
    std::size_t anchor_segment_count{0U};
    std::vector<PreparedCurveSegment> segments;
    std::shared_ptr<const SurfaceGuideTopology> surface_topology;
    std::vector<double> surface_node_distances;
    std::vector<SurfaceGuideSeed> surface_seeds;
};

using PreparedGuides = std::vector<PreparedGuide>;

PreparedGuides prepare_guides(const std::vector<Guide>& guides) {
    PreparedGuides result;
    result.reserve(guides.size());
    for (const Guide& guide : guides) {
        PreparedGuide prepared;
        prepared.source = &guide;
        prepared.curve = is_curve(guide.kind);
        prepared.uses_density = guide_uses_density(guide);
        prepared.uses_size = guide_uses_size(guide);
        prepared.uses_direction = guide_uses_direction(guide);
        prepared.uses_mask = guide_uses_mask(guide);
        prepared.fallback_point = guide.points.empty() ? Vec3{} : guide.points.front();
        prepared.fallback_tangent = normalize(guide.direction, {1.0, 0.0, 0.0});
        prepared.radius = std::max(1.0e-6, guide.radius);
        prepared.falloff = clamp(guide.falloff, 0.1, 8.0);
        if (guide.points.empty()) {
            prepared.bounds_min = prepared.fallback_point;
            prepared.bounds_max = prepared.fallback_point;
        } else {
            prepared.bounds_min = guide.points.front();
            prepared.bounds_max = guide.points.front();
            for (const Vec3& point : guide.points) {
                prepared.bounds_min.x = std::min(prepared.bounds_min.x, point.x);
                prepared.bounds_min.y = std::min(prepared.bounds_min.y, point.y);
                prepared.bounds_min.z = std::min(prepared.bounds_min.z, point.z);
                prepared.bounds_max.x = std::max(prepared.bounds_max.x, point.x);
                prepared.bounds_max.y = std::max(prepared.bounds_max.y, point.y);
                prepared.bounds_max.z = std::max(prepared.bounds_max.z, point.z);
            }
        }

        if (prepared.curve && guide.points.size() >= 2U) {
            const std::size_t segment_count =
                guide.closed ? guide.points.size() : guide.points.size() - 1U;
            prepared.segments.reserve(segment_count);
            for (std::size_t index = 0U; index < segment_count; ++index) {
                const Vec3& start = guide.points[index];
                const Vec3& end = guide.points[(index + 1U) % guide.points.size()];
                const Vec3 delta = sub(end, start);
                const double denominator = length_squared(delta);
                if (denominator <= kEpsilon) {
                    continue;
                }
                const double segment_length = std::sqrt(denominator);
                prepared.segments.push_back({
                    start,
                    end,
                    delta,
                    normalize(delta, prepared.fallback_tangent),
                    denominator,
                    segment_length,
                });
                const bool contributes_anchor_length =
                    index + 1U < guide.points.size() ||
                    (guide.closed && guide.points.size() > 2U);
                if (contributes_anchor_length) {
                    prepared.total_length += segment_length;
                    ++prepared.anchor_segment_count;
                }
            }
        }
        result.push_back(std::move(prepared));
    }
    return result;
}

bool outside_guide_bounds(
    const PreparedGuide& guide,
    const Vec3& position,
    double radius) {
    return position.x < guide.bounds_min.x - radius ||
           position.x > guide.bounds_max.x + radius ||
           position.y < guide.bounds_min.y - radius ||
           position.y > guide.bounds_max.y + radius ||
           position.z < guide.bounds_min.z - radius ||
           position.z > guide.bounds_max.z + radius;
}

GuideNearest nearest_on_guide(
    const PreparedGuide& guide,
    const Vec3& position) {
    if (!guide.curve || guide.segments.empty()) {
        return {
            length(sub(position, guide.fallback_point)),
            guide.fallback_point,
            guide.fallback_tangent,
        };
    }

    double best_distance_squared = std::numeric_limits<double>::infinity();
    Vec3 best_point = guide.fallback_point;
    Vec3 best_tangent = guide.fallback_tangent;
    for (const PreparedCurveSegment& segment : guide.segments) {
        const double amount = clamp(
            dot(sub(position, segment.start), segment.delta) /
                segment.denominator,
            0.0,
            1.0);
        const Vec3 closest = add(segment.start, mul(segment.delta, amount));
        const double distance_squared = length_squared(sub(position, closest));
        if (distance_squared < best_distance_squared) {
            best_distance_squared = distance_squared;
            best_point = closest;
            best_tangent = segment.tangent;
        }
    }
    return {std::sqrt(best_distance_squared), best_point, best_tangent};
}

double guide_distance(
    const PreparedGuide& guide,
    const Vec3& position,
    std::uint32_t triangle_index) {
    const GuideNearest nearest = nearest_on_guide(guide, position);
    if (guide.surface_topology == nullptr ||
        guide.surface_node_distances.size() !=
            guide.surface_topology->edge_midpoints.size() ||
        triangle_index >= guide.surface_topology->triangle_edge_nodes.size()) {
        return nearest.distance;
    }

    double best = std::numeric_limits<double>::infinity();
    const auto first = std::lower_bound(
        guide.surface_seeds.begin(),
        guide.surface_seeds.end(),
        triangle_index,
        [](const SurfaceGuideSeed& seed, std::uint32_t value) {
            return seed.triangle_index < value;
        });
    for (auto iterator = first;
         iterator != guide.surface_seeds.end() &&
         iterator->triangle_index == triangle_index;
         ++iterator) {
        best = std::min(best, length(sub(position, iterator->point)));
    }

    const auto& nodes =
        guide.surface_topology->triangle_edge_nodes[triangle_index];
    for (const std::uint32_t node : nodes) {
        const double distance = guide.surface_node_distances[node];
        if (std::isfinite(distance)) {
            best = std::min(
                best,
                distance + length(sub(
                    position,
                    guide.surface_topology->edge_midpoints[node])));
        }
    }
    return best;
}

double guide_influence_from_distance(
    const PreparedGuide& guide,
    double distance,
    double radius) {
    if (distance >= radius) {
        return 0.0;
    }
    const double normalized_distance = clamp(distance / radius, 0.0, 1.0);
    const double smooth = 1.0 - normalized_distance * normalized_distance *
                                    (3.0 - 2.0 * normalized_distance);
    return std::pow(std::max(0.0, smooth), guide.falloff);
}

double guide_influence(
    const PreparedGuide& guide,
    const Vec3& position,
    double radius_override = 0.0,
    std::uint32_t triangle_index = std::numeric_limits<std::uint32_t>::max()) {
    if (!guide.source || !guide.source->enabled) {
        return 0.0;
    }
    const double radius = std::max(
        1.0e-6,
        radius_override > 0.0 ? radius_override : guide.radius);
    if (outside_guide_bounds(guide, position, radius)) {
        return 0.0;
    }
    return guide_influence_from_distance(
        guide,
        guide_distance(guide, position, triangle_index),
        radius);
}

double mask_influence(
    const Vec3& position,
    const PreparedGuides& guides,
    std::uint32_t triangle_index = std::numeric_limits<std::uint32_t>::max()) {
    double remaining = 1.0;
    for (const PreparedGuide& guide : guides) {
        if (!guide.source || !guide.source->enabled || !guide.uses_mask) {
            continue;
        }
        const double influence = clamp(
            guide_influence(guide, position, 0.0, triangle_index),
            0.0,
            1.0);
        remaining *= 1.0 - influence;
    }
    return clamp(1.0 - remaining, 0.0, 1.0);
}

double mask_acceptance_probability(
    const Vec3& position,
    const PreparedGuides& guides,
    std::uint32_t triangle_index = std::numeric_limits<std::uint32_t>::max()) {
    const double influence =
        mask_influence(position, guides, triangle_index);
    if (influence >= kMaskHardCoreInfluence) {
        return 0.0;
    }
    return clamp(1.0 - influence, 0.0, 1.0);
}

std::uint32_t mask_guide_count(const PreparedGuides& guides) {
    return static_cast<std::uint32_t>(std::count_if(
        guides.begin(),
        guides.end(),
        [](const PreparedGuide& guide) {
            return guide.source && guide.source->enabled && guide.uses_mask;
        }));
}

std::pair<double, double> density_factors(
    const Vec3& position,
    const PreparedGuides& guides,
    std::uint32_t triangle_index = std::numeric_limits<std::uint32_t>::max()) {
    double density = 1.0;
    double size = 1.0;
    for (const PreparedGuide& guide : guides) {
        const Guide& source = *guide.source;
        if (!source.enabled || (!guide.uses_density && !guide.uses_size)) {
            continue;
        }
        const double influence =
            guide_influence(guide, position, 0.0, triangle_index);
        if (guide.uses_density) {
            density *= 1.0 +
                (clamp(source.density_multiplier, 0.0, 16.0) - 1.0) * influence;
        }
        if (guide.uses_size) {
            size *= 1.0 +
                (clamp(source.size_multiplier, 0.05, 8.0) - 1.0) * influence;
        }
    }
    return {clamp(density, 0.02, 16.0), clamp(size, 0.05, 8.0)};
}

double maximum_density_factor(const PreparedGuides& guides) {
    double maximum = 1.0;
    for (const PreparedGuide& guide : guides) {
        const Guide& source = *guide.source;
        if (source.enabled && guide.uses_density) {
            maximum *= std::max(
                1.0,
                clamp(source.density_multiplier, 0.0, 16.0));
        }
    }
    return clamp(maximum, 1.0, 256.0);
}

std::uint32_t guide_count(const PreparedGuides& guides, bool density) {
    return static_cast<std::uint32_t>(std::count_if(
        guides.begin(),
        guides.end(),
        [density](const PreparedGuide& guide) {
            return guide.source->enabled &&
                   (density ? (guide.uses_density || guide.uses_size)
                            : guide.uses_direction);
        }));
}

struct DirectionSolution {
    Vec3 tangent{1.0, 0.0, 0.0};
    double influence{0.0};
};

DirectionSolution guided_direction_solution(
    const Vec3& position,
    const Vec3& normal,
    const Vec3& fallback,
    std::uint32_t triangle_index,
    const PreparedGuides& guides) {
    const Vec3 base = normalize(project_on_plane(fallback, normal), fallback);
    Vec3 accumulated = base;
    double remaining = 1.0;
    for (const PreparedGuide& guide : guides) {
        const Guide& source = *guide.source;
        if (!source.enabled || !guide.uses_direction) {
            continue;
        }
        if (outside_guide_bounds(guide, position, guide.radius)) {
            continue;
        }
        const GuideNearest nearest = nearest_on_guide(guide, position);
        const double weight = clamp(
            clamp(source.strength, 0.0, 1.0) *
                guide_influence_from_distance(
                    guide,
                    guide_distance(guide, position, triangle_index),
                    guide.radius),
            0.0,
            1.0);
        if (weight <= 0.0) {
            continue;
        }
        Vec3 desired = guide.curve
            ? nearest.tangent
            : sub(nearest.point, position);
        desired = normalize(project_on_plane(desired, normal), accumulated);
        if (std::abs(source.angle_degrees) > kEpsilon) {
            desired = normalize(
                rotate_around_axis(
                    desired,
                    normal,
                    source.angle_degrees * kPi / 180.0),
                accumulated);
        }
        accumulated = blend_oriented_direction(
            accumulated,
            desired,
            normal,
            weight);
        remaining *= 1.0 - weight;
    }
    return {
        normalize(accumulated, base),
        clamp(1.0 - remaining, 0.0, 1.0),
    };
}

double point_direction_influence(
    const Vec3& position,
    std::uint32_t triangle_index,
    const PreparedGuides& guides) {
    double remaining = 1.0;
    for (const PreparedGuide& guide : guides) {
        const Guide& source = *guide.source;
        if (!source.enabled || guide.curve || !guide.uses_direction) {
            continue;
        }
        const double weight = clamp(
            clamp(source.strength, 0.0, 1.0) *
                guide_influence(guide, position, 0.0, triangle_index),
            0.0,
            1.0);
        remaining *= 1.0 - weight;
    }
    return clamp(1.0 - remaining, 0.0, 1.0);
}

struct CurveCenterAnchor {
    Vec3 position{};
    std::uint64_t guide_key{0U};
    std::uint32_t ordinal{0U};
    std::uint32_t count{1U};
};

std::vector<CurveCenterAnchor> curve_center_anchors(
    const PreparedGuides& guides,
    double spacing,
    std::uint32_t limit) {
    std::vector<CurveCenterAnchor> anchors;
    anchors.reserve(limit);
    std::uint32_t remaining = limit;
    const double base_spacing = std::max(1.0e-12, spacing);
    std::unordered_map<std::string, std::uint64_t> guide_occurrences;
    for (const PreparedGuide& guide : guides) {
        const Guide& source = *guide.source;
        if (remaining == 0U) {
            break;
        }
        if (!source.enabled ||
            !guide.curve ||
            !guide.uses_direction ||
            source.strength <= 0.0 ||
            guide.anchor_segment_count == 0U) {
            continue;
        }
        const double total_length = guide.total_length;
        if (total_length <= kEpsilon) {
            continue;
        }
        const double requested_value = std::floor(total_length / base_spacing);
        const std::uint32_t requested = std::max<std::uint32_t>(
            1U,
            requested_value <= 0.0
                ? 0U
                : static_cast<std::uint32_t>(requested_value));
        const std::uint32_t count = std::min(remaining, requested);
        if (count == 0U) {
            continue;
        }
        const std::uint64_t occurrence = guide_occurrences[source.id]++;
        const std::uint64_t guide_key = stable_hash_values(
            "bifrost-scales/curve-guide-evaluation/1",
            {
                stable_hash_text("bifrost-scales/curve-guide/1", source.id),
                occurrence,
            });
        for (std::uint32_t index = 0U; index < count; ++index) {
            const double distance = source.closed
                ? total_length * static_cast<double>(index) /
                    static_cast<double>(count)
                : total_length * (static_cast<double>(index) + 0.5) /
                    static_cast<double>(count);
            double cursor = 0.0;
            for (std::size_t segment_index = 0U;
                 segment_index < guide.anchor_segment_count;
                 ++segment_index) {
                const PreparedCurveSegment& segment = guide.segments[segment_index];
                const double next_cursor = cursor + segment.length;
                if (distance <= next_cursor ||
                    segment_index + 1U == guide.anchor_segment_count) {
                    const double amount = clamp(
                        (distance - cursor) / segment.length,
                        0.0,
                        1.0);
                    anchors.push_back({
                        add(segment.start, mul(segment.delta, amount)),
                        guide_key,
                        index,
                        count,
                    });
                    break;
                }
                cursor = next_cursor;
            }
        }
        remaining -= count;
    }
    return anchors;
}

double influence_for_id(
    const std::string& guide_id,
    const Vec3& position,
    double radius_override,
    std::uint32_t triangle_index,
    const PreparedGuides& guides) {
    if (guide_id.empty()) {
        return 0.0;
    }
    double exact = 0.0;
    bool found_exact = false;
    for (const PreparedGuide& guide : guides) {
        const Guide& source = *guide.source;
        if (source.enabled && source.id == guide_id) {
            found_exact = true;
            exact = std::max(
                exact,
                guide_influence(
                    guide,
                    position,
                    radius_override,
                    triangle_index));
        }
    }
    if (found_exact) {
        return exact;
    }
    double maximum = 0.0;
    for (const PreparedGuide& guide : guides) {
        const Guide& source = *guide.source;
        if (!source.enabled || source.group_id != guide_id) {
            continue;
        }
        maximum = std::max(
            maximum,
            guide_influence(
                    guide,
                    position,
                    radius_override,
                    triangle_index));
    }
    return maximum;
}

struct Projection {
    Vec3 point{};
    std::array<double, 3> barycentric{1.0, 0.0, 0.0};
};

struct SurfaceSampleProjection {
    Vec3 point{};
    Vec3 normal{0.0, 1.0, 0.0};
    std::uint32_t triangle_index{0U};
    std::array<double, 3> barycentric{1.0, 0.0, 0.0};
};

Projection closest_point_on_triangle(
    const Vec3& point,
    const Vec3& a,
    const Vec3& b,
    const Vec3& c) {
    const Vec3 ab = sub(b, a);
    const Vec3 ac = sub(c, a);
    const Vec3 ap = sub(point, a);
    const double d1 = dot(ab, ap);
    const double d2 = dot(ac, ap);
    if (d1 <= 0.0 && d2 <= 0.0) {
        return {a, {1.0, 0.0, 0.0}};
    }

    const Vec3 bp = sub(point, b);
    const double d3 = dot(ab, bp);
    const double d4 = dot(ac, bp);
    if (d3 >= 0.0 && d4 <= d3) {
        return {b, {0.0, 1.0, 0.0}};
    }

    const double vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0) {
        const double amount = d1 / (d1 - d3);
        return {add(a, mul(ab, amount)), {1.0 - amount, amount, 0.0}};
    }

    const Vec3 cp = sub(point, c);
    const double d5 = dot(ab, cp);
    const double d6 = dot(ac, cp);
    if (d6 >= 0.0 && d5 <= d6) {
        return {c, {0.0, 0.0, 1.0}};
    }

    const double vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0) {
        const double amount = d2 / (d2 - d6);
        return {add(a, mul(ac, amount)), {1.0 - amount, 0.0, amount}};
    }

    const double va = d3 * d6 - d5 * d4;
    if (va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0) {
        const Vec3 bc = sub(c, b);
        const double amount = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        return {add(b, mul(bc, amount)), {0.0, 1.0 - amount, amount}};
    }

    const double denominator = 1.0 / (va + vb + vc);
    const double v = vb * denominator;
    const double w = vc * denominator;
    const double u = 1.0 - v - w;
    return {add(add(mul(a, u), mul(b, v)), mul(c, w)), {u, v, w}};
}

struct Bounds3 {
    Vec3 minimum{
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
    };
    Vec3 maximum{
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
    };
};

void expand_bounds(Bounds3& bounds, const Vec3& point) {
    bounds.minimum.x = std::min(bounds.minimum.x, point.x);
    bounds.minimum.y = std::min(bounds.minimum.y, point.y);
    bounds.minimum.z = std::min(bounds.minimum.z, point.z);
    bounds.maximum.x = std::max(bounds.maximum.x, point.x);
    bounds.maximum.y = std::max(bounds.maximum.y, point.y);
    bounds.maximum.z = std::max(bounds.maximum.z, point.z);
}

void expand_bounds(Bounds3& destination, const Bounds3& source) {
    expand_bounds(destination, source.minimum);
    expand_bounds(destination, source.maximum);
}

double bounds_distance_squared(const Bounds3& bounds, const Vec3& point) {
    auto axis_distance = [](double value, double minimum, double maximum) {
        if (value < minimum) {
            return minimum - value;
        }
        if (value > maximum) {
            return value - maximum;
        }
        return 0.0;
    };
    const double x = axis_distance(point.x, bounds.minimum.x, bounds.maximum.x);
    const double y = axis_distance(point.y, bounds.minimum.y, bounds.maximum.y);
    const double z = axis_distance(point.z, bounds.minimum.z, bounds.maximum.z);
    return x * x + y * y + z * z;
}

class SurfaceProjector {
public:
    explicit SurfaceProjector(
        const Mesh& mesh,
        bool build_local_projection = true,
        bool build_global_projection = false)
        : mesh_(mesh) {
        if (build_local_projection) {
            adjacency_ = build_adjacency(mesh);
            components_ = build_components(adjacency_);
            vertex_stars_ = build_vertex_stars(mesh);
        }
        if (build_global_projection) {
            build_global_bvh();
        }
    }

    [[nodiscard]] std::uint32_t component(std::uint32_t triangle_index) const {
        if (components_.empty()) {
            return 0U;
        }
        return components_[clamped_triangle(triangle_index)];
    }

    [[nodiscard]] Vec3 project(
        const Vec3& point,
        std::uint32_t triangle_index,
        std::uint32_t rings) {
        const std::uint32_t source = clamped_triangle(triangle_index);
        const std::vector<std::uint32_t>& candidate_triangles = candidates(source, rings);
        double best_distance = std::numeric_limits<double>::infinity();
        Projection best_projection{point, {1.0, 0.0, 0.0}};
        std::uint32_t best_triangle = source;
        for (const std::uint32_t candidate : candidate_triangles) {
            update_local_projection(
                candidate,
                point,
                best_distance,
                best_projection,
                best_triangle);
        }
        if (rings > 0U) {
            expand_hit_feature_if_needed(
                source,
                rings,
                point,
                candidate_triangles,
                best_distance,
                best_projection,
                best_triangle);
        }
        return best_projection.point;
    }

    [[nodiscard]] SurfaceSampleProjection project_sample(
        const Vec3& point,
        std::uint32_t triangle_index,
        std::uint32_t rings) {
        const std::uint32_t source = clamped_triangle(triangle_index);
        const std::vector<std::uint32_t>& candidate_triangles = candidates(source, rings);
        double best_distance = std::numeric_limits<double>::infinity();
        Projection best_projection{point, {1.0, 0.0, 0.0}};
        std::uint32_t best_triangle = source;
        for (const std::uint32_t candidate : candidate_triangles) {
            update_local_projection(
                candidate,
                point,
                best_distance,
                best_projection,
                best_triangle);
        }
        if (rings > 0U) {
            expand_hit_feature_if_needed(
                source,
                rings,
                point,
                candidate_triangles,
                best_distance,
                best_projection,
                best_triangle);
        }
        const Triangle& triangle = mesh_.triangles[best_triangle];
        const auto normal_area = normal_and_area(
            mesh_.vertices[triangle.a],
            mesh_.vertices[triangle.b],
            mesh_.vertices[triangle.c]);
        return {
            best_projection.point,
            normal_area.first,
            best_triangle,
            best_projection.barycentric,
        };
    }

    void prepare_candidates(
        const std::vector<std::uint32_t>& triangle_indices,
        std::uint32_t rings) {
        if (adjacency_.empty()) {
            return;
        }
        std::vector<std::uint32_t> unique = triangle_indices;
        std::sort(unique.begin(), unique.end());
        unique.erase(std::unique(unique.begin(), unique.end()), unique.end());
        for (const std::uint32_t triangle_index : unique) {
            (void)candidates(clamped_triangle(triangle_index), rings);
        }
    }

    [[nodiscard]] Vec3 project_prepared(
        const Vec3& point,
        std::uint32_t triangle_index,
        std::uint32_t rings) const {
        const std::uint32_t source = clamped_triangle(triangle_index);
        const std::uint32_t ring_count = std::min<std::uint32_t>(rings, 16U);
        const std::uint64_t key =
            (static_cast<std::uint64_t>(source) << 32U) |
            static_cast<std::uint64_t>(ring_count);
        const auto found = candidate_cache_.find(key);
        if (found == candidate_cache_.end()) {
            throw std::logic_error(
                "SurfaceProjector candidates were not prepared before parallel projection");
        }
        const std::vector<std::uint32_t>& candidate_triangles = found->second;
        double best_distance = std::numeric_limits<double>::infinity();
        Projection best_projection{point, {1.0, 0.0, 0.0}};
        std::uint32_t best_triangle = source;
        for (const std::uint32_t candidate : candidate_triangles) {
            update_local_projection(
                candidate,
                point,
                best_distance,
                best_projection,
                best_triangle);
        }
        if (rings > 0U) {
            expand_hit_feature_if_needed(
                source,
                rings,
                point,
                candidate_triangles,
                best_distance,
                best_projection,
                best_triangle);
        }
        return best_projection.point;
    }

    [[nodiscard]] SurfaceSampleProjection project_sample_global(
        const Vec3& point) const {
        double best_distance = std::numeric_limits<double>::infinity();
        Projection best_projection{point, {1.0, 0.0, 0.0}};
        std::uint32_t best_triangle = std::numeric_limits<std::uint32_t>::max();
        if (!bvh_nodes_.empty()) {
            search_global_bvh(
                0U,
                point,
                best_distance,
                best_projection,
                best_triangle);
        } else {
            for (std::uint32_t candidate = 0U;
                 candidate < mesh_.triangles.size();
                 ++candidate) {
                update_global_projection(
                    candidate,
                    point,
                    best_distance,
                    best_projection,
                    best_triangle);
            }
        }
        if (best_triangle == std::numeric_limits<std::uint32_t>::max()) {
            best_triangle = 0U;
        }
        const Triangle& triangle = mesh_.triangles[best_triangle];
        const auto normal_area = normal_and_area(
            mesh_.vertices[triangle.a],
            mesh_.vertices[triangle.b],
            mesh_.vertices[triangle.c]);
        return {
            best_projection.point,
            normal_area.first,
            best_triangle,
            best_projection.barycentric,
        };
    }

private:
    struct BvhNode {
        Bounds3 bounds{};
        std::uint32_t begin{0U};
        std::uint32_t end{0U};
        std::uint32_t left{std::numeric_limits<std::uint32_t>::max()};
        std::uint32_t right{std::numeric_limits<std::uint32_t>::max()};
        std::uint32_t minimum_triangle{std::numeric_limits<std::uint32_t>::max()};

        [[nodiscard]] bool leaf() const noexcept {
            return left == std::numeric_limits<std::uint32_t>::max();
        }
    };

    const Mesh& mesh_;
    std::vector<std::vector<std::uint32_t>> adjacency_;
    std::vector<std::vector<std::uint32_t>> vertex_stars_;
    std::vector<std::uint32_t> components_;
    std::unordered_map<std::uint64_t, std::vector<std::uint32_t>> candidate_cache_;
    std::vector<std::uint32_t> bvh_triangles_;
    std::vector<BvhNode> bvh_nodes_;

    void update_local_projection(
        std::uint32_t candidate,
        const Vec3& point,
        double& best_distance,
        Projection& best_projection,
        std::uint32_t& best_triangle) const {
        const Triangle& triangle = mesh_.triangles[candidate];
        const Projection projected = closest_point_on_triangle(
            point,
            mesh_.vertices[triangle.a],
            mesh_.vertices[triangle.b],
            mesh_.vertices[triangle.c]);
        const double distance = length_squared(sub(projected.point, point));
        if (distance < best_distance) {
            best_distance = distance;
            best_projection = projected;
            best_triangle = candidate;
        }
    }

    void expand_hit_feature_if_needed(
        std::uint32_t source_triangle,
        std::uint32_t rings,
        const Vec3& point,
        const std::vector<std::uint32_t>& base_candidates,
        double& best_distance,
        Projection& best_projection,
        std::uint32_t& best_triangle) const {
        if (rings == 0U || best_distance <= 1.0e-20) {
            return;
        }

        std::array<std::size_t, 3> support_slots{};
        std::size_t support_count = 0U;
        for (std::size_t index = 0U;
             index < best_projection.barycentric.size();
             ++index) {
            if (best_projection.barycentric[index] > 1.0e-10) {
                support_slots[support_count++] = index;
            }
        }
        if (support_count >= 3U || support_count == 0U) {
            return;
        }

        const Triangle& hit_triangle = mesh_.triangles[best_triangle];
        const std::array<std::uint32_t, 3> vertices{
            hit_triangle.a,
            hit_triangle.b,
            hit_triangle.c,
        };
        const std::uint32_t component_id = components_[source_triangle];
        const auto consider = [&](std::uint32_t candidate) {
            if (components_[candidate] != component_id ||
                std::binary_search(
                    base_candidates.begin(),
                    base_candidates.end(),
                    candidate)) {
                return;
            }
            update_local_projection(
                candidate,
                point,
                best_distance,
                best_projection,
                best_triangle);
        };

        const auto& first = vertex_stars_[vertices[support_slots[0U]]];
        if (support_count == 1U) {
            for (const std::uint32_t candidate : first) {
                consider(candidate);
            }
            return;
        }

        // Vertex stars are built in ascending triangle order. Merge the two
        // hit-edge stars without allocating a temporary candidate vector;
        // this preserves Python's sorted-set tie order while keeping the
        // fallback cheap for large previews.
        const auto& second = vertex_stars_[vertices[support_slots[1U]]];
        std::size_t first_index = 0U;
        std::size_t second_index = 0U;
        while (first_index < first.size() || second_index < second.size()) {
            std::uint32_t candidate = 0U;
            if (second_index >= second.size() ||
                (first_index < first.size() &&
                 first[first_index] < second[second_index])) {
                candidate = first[first_index++];
            } else if (first_index >= first.size() ||
                       second[second_index] < first[first_index]) {
                candidate = second[second_index++];
            } else {
                candidate = first[first_index];
                ++first_index;
                ++second_index;
            }
            consider(candidate);
        }
    }

    [[nodiscard]] Bounds3 triangle_bounds(std::uint32_t triangle_index) const {
        Bounds3 bounds;
        const Triangle& triangle = mesh_.triangles[triangle_index];
        expand_bounds(bounds, mesh_.vertices[triangle.a]);
        expand_bounds(bounds, mesh_.vertices[triangle.b]);
        expand_bounds(bounds, mesh_.vertices[triangle.c]);
        return bounds;
    }

    [[nodiscard]] Vec3 triangle_centroid(std::uint32_t triangle_index) const {
        const Triangle& triangle = mesh_.triangles[triangle_index];
        return mul(
            add(
                add(mesh_.vertices[triangle.a], mesh_.vertices[triangle.b]),
                mesh_.vertices[triangle.c]),
            1.0 / 3.0);
    }

    void build_global_bvh() {
        bvh_triangles_.resize(mesh_.triangles.size());
        for (std::uint32_t index = 0U; index < mesh_.triangles.size(); ++index) {
            bvh_triangles_[index] = index;
        }
        bvh_nodes_.reserve(mesh_.triangles.size() * 2U);
        if (!bvh_triangles_.empty()) {
            build_global_bvh_node(
                0U,
                static_cast<std::uint32_t>(bvh_triangles_.size()));
        }
    }

    std::uint32_t build_global_bvh_node(
        std::uint32_t begin,
        std::uint32_t end) {
        BvhNode node;
        node.begin = begin;
        node.end = end;
        Bounds3 centroid_bounds;
        for (std::uint32_t offset = begin; offset < end; ++offset) {
            const std::uint32_t triangle_index = bvh_triangles_[offset];
            expand_bounds(node.bounds, triangle_bounds(triangle_index));
            expand_bounds(centroid_bounds, triangle_centroid(triangle_index));
            node.minimum_triangle = std::min(
                node.minimum_triangle,
                triangle_index);
        }
        const std::uint32_t node_index = static_cast<std::uint32_t>(
            bvh_nodes_.size());
        bvh_nodes_.push_back(node);
        if (end - begin <= 8U) {
            return node_index;
        }

        const Vec3 extent = sub(centroid_bounds.maximum, centroid_bounds.minimum);
        int axis = 0;
        if (extent.y > extent.x && extent.y >= extent.z) {
            axis = 1;
        } else if (extent.z > extent.x && extent.z > extent.y) {
            axis = 2;
        }
        auto axis_value = [this, axis](std::uint32_t triangle_index) {
            const Vec3 center = triangle_centroid(triangle_index);
            return axis == 0 ? center.x : axis == 1 ? center.y : center.z;
        };
        std::sort(
            bvh_triangles_.begin() + begin,
            bvh_triangles_.begin() + end,
            [&axis_value](std::uint32_t left, std::uint32_t right) {
                const double left_value = axis_value(left);
                const double right_value = axis_value(right);
                if (left_value != right_value) {
                    return left_value < right_value;
                }
                return left < right;
            });
        const std::uint32_t middle = begin + (end - begin) / 2U;
        const std::uint32_t left = build_global_bvh_node(begin, middle);
        const std::uint32_t right = build_global_bvh_node(middle, end);
        bvh_nodes_[node_index].left = left;
        bvh_nodes_[node_index].right = right;
        return node_index;
    }

    void update_global_projection(
        std::uint32_t candidate,
        const Vec3& point,
        double& best_distance,
        Projection& best_projection,
        std::uint32_t& best_triangle) const {
        const Triangle& triangle = mesh_.triangles[candidate];
        const Projection projected = closest_point_on_triangle(
            point,
            mesh_.vertices[triangle.a],
            mesh_.vertices[triangle.b],
            mesh_.vertices[triangle.c]);
        const double distance = length_squared(sub(projected.point, point));
        if (distance < best_distance ||
            (distance == best_distance && candidate < best_triangle)) {
            best_distance = distance;
            best_projection = projected;
            best_triangle = candidate;
        }
    }

    void search_global_bvh(
        std::uint32_t node_index,
        const Vec3& point,
        double& best_distance,
        Projection& best_projection,
        std::uint32_t& best_triangle) const {
        const BvhNode& node = bvh_nodes_[node_index];
        if (bounds_distance_squared(node.bounds, point) > best_distance) {
            return;
        }
        if (node.leaf()) {
            for (std::uint32_t offset = node.begin; offset < node.end; ++offset) {
                update_global_projection(
                    bvh_triangles_[offset],
                    point,
                    best_distance,
                    best_projection,
                    best_triangle);
            }
            return;
        }

        const BvhNode& left = bvh_nodes_[node.left];
        const BvhNode& right = bvh_nodes_[node.right];
        const double left_distance = bounds_distance_squared(left.bounds, point);
        const double right_distance = bounds_distance_squared(right.bounds, point);
        const bool left_first = left_distance < right_distance ||
            (left_distance == right_distance &&
             left.minimum_triangle <= right.minimum_triangle);
        const std::uint32_t first = left_first ? node.left : node.right;
        const std::uint32_t second = left_first ? node.right : node.left;
        search_global_bvh(
            first,
            point,
            best_distance,
            best_projection,
            best_triangle);
        search_global_bvh(
            second,
            point,
            best_distance,
            best_projection,
            best_triangle);
    }

    [[nodiscard]] std::uint32_t clamped_triangle(std::uint32_t triangle_index) const {
        return std::min<std::uint32_t>(
            triangle_index,
            static_cast<std::uint32_t>(mesh_.triangles.size() - 1U));
    }

    static std::vector<std::vector<std::uint32_t>> build_adjacency(
        const Mesh& mesh) {
        std::unordered_map<std::uint64_t, std::vector<std::uint32_t>> by_edge;
        by_edge.reserve(mesh.triangles.size() * 3U);
        for (std::uint32_t triangle_index = 0U;
             triangle_index < mesh.triangles.size();
             ++triangle_index) {
            const Triangle& triangle = mesh.triangles[triangle_index];
            for (const std::array<std::uint32_t, 2>& edge : {
                     std::array<std::uint32_t, 2>{triangle.a, triangle.b},
                     std::array<std::uint32_t, 2>{triangle.b, triangle.c},
                     std::array<std::uint32_t, 2>{triangle.c, triangle.a}}) {
                by_edge[boundary_edge_key(edge[0], edge[1])].push_back(triangle_index);
            }
        }
        std::vector<std::vector<std::uint32_t>> adjacency(mesh.triangles.size());
        for (std::uint32_t index = 0U; index < adjacency.size(); ++index) {
            adjacency[index].push_back(index);
        }
        for (const auto& entry : by_edge) {
            std::vector<std::uint32_t> triangles = entry.second;
            std::sort(triangles.begin(), triangles.end());
            triangles.erase(std::unique(triangles.begin(), triangles.end()), triangles.end());
            for (std::size_t left = 0U; left < triangles.size(); ++left) {
                for (std::size_t right = left + 1U; right < triangles.size(); ++right) {
                    adjacency[triangles[left]].push_back(triangles[right]);
                    adjacency[triangles[right]].push_back(triangles[left]);
                }
            }
        }
        for (std::vector<std::uint32_t>& neighbors : adjacency) {
            std::sort(neighbors.begin(), neighbors.end());
            neighbors.erase(std::unique(neighbors.begin(), neighbors.end()), neighbors.end());
        }
        return adjacency;
    }

    static std::vector<std::vector<std::uint32_t>> build_vertex_stars(
        const Mesh& mesh) {
        std::vector<std::vector<std::uint32_t>> by_vertex(mesh.vertices.size());
        for (std::uint32_t triangle_index = 0U;
             triangle_index < mesh.triangles.size();
             ++triangle_index) {
            const Triangle& triangle = mesh.triangles[triangle_index];
            by_vertex[triangle.a].push_back(triangle_index);
            by_vertex[triangle.b].push_back(triangle_index);
            by_vertex[triangle.c].push_back(triangle_index);
        }
        for (std::vector<std::uint32_t>& triangles : by_vertex) {
            std::sort(triangles.begin(), triangles.end());
            triangles.erase(
                std::unique(triangles.begin(), triangles.end()),
                triangles.end());
        }
        return by_vertex;
    }

    static std::vector<std::uint32_t> build_components(
        const std::vector<std::vector<std::uint32_t>>& adjacency) {
        const std::uint32_t unassigned = std::numeric_limits<std::uint32_t>::max();
        std::vector<std::uint32_t> components(adjacency.size(), unassigned);
        std::uint32_t component_id = 0U;
        for (std::uint32_t start = 0; start < adjacency.size(); ++start) {
            if (components[start] != unassigned) {
                continue;
            }
            std::vector<std::uint32_t> stack{start};
            components[start] = component_id;
            while (!stack.empty()) {
                const std::uint32_t current = stack.back();
                stack.pop_back();
                for (const std::uint32_t neighbor : adjacency[current]) {
                    if (components[neighbor] != unassigned) {
                        continue;
                    }
                    components[neighbor] = component_id;
                    stack.push_back(neighbor);
                }
            }
            ++component_id;
        }
        return components;
    }

    const std::vector<std::uint32_t>& candidates(
        std::uint32_t triangle_index,
        std::uint32_t rings) {
        const std::uint32_t ring_count = std::min<std::uint32_t>(rings, 16U);
        const std::uint64_t key =
            (static_cast<std::uint64_t>(triangle_index) << 32U) |
            static_cast<std::uint64_t>(ring_count);
        const auto found = candidate_cache_.find(key);
        if (found != candidate_cache_.end()) {
            return found->second;
        }

        std::vector<bool> visited(mesh_.triangles.size(), false);
        std::vector<std::uint32_t> frontier{triangle_index};
        std::vector<std::uint32_t> result{triangle_index};
        visited[triangle_index] = true;
        for (std::uint32_t ring = 0U; ring < ring_count && !frontier.empty(); ++ring) {
            std::vector<std::uint32_t> next;
            for (const std::uint32_t current : frontier) {
                for (const std::uint32_t neighbor : adjacency_[current]) {
                    if (visited[neighbor]) {
                        continue;
                    }
                    visited[neighbor] = true;
                    next.push_back(neighbor);
                    result.push_back(neighbor);
                }
            }
            frontier = std::move(next);
        }
        std::sort(result.begin(), result.end());
        return candidate_cache_.emplace(key, std::move(result)).first->second;
    }
};

struct SurfaceGraphEdge {
    std::uint32_t vertex{0U};
    double length{0.0};
};

void prepare_surface_guide_fields(
    const Mesh& mesh,
    PreparedGuides& guides) {
    if (mesh.vertices.empty() || mesh.triangles.empty() || guides.empty()) {
        return;
    }

    auto topology = std::make_shared<SurfaceGuideTopology>();
    topology->triangle_edge_nodes.reserve(mesh.triangles.size());
    std::unordered_map<std::uint64_t, std::uint32_t> edge_nodes;
    edge_nodes.reserve(mesh.triangles.size() * 2U);
    auto edge_node = [&](std::uint32_t first, std::uint32_t second) {
        const std::uint32_t lower = std::min(first, second);
        const std::uint32_t upper = std::max(first, second);
        const std::uint64_t key =
            (static_cast<std::uint64_t>(lower) << 32U) |
            static_cast<std::uint64_t>(upper);
        const auto found = edge_nodes.find(key);
        if (found != edge_nodes.end()) {
            return found->second;
        }
        const std::uint32_t node = static_cast<std::uint32_t>(
            topology->edge_midpoints.size());
        topology->edge_midpoints.push_back(mul(
            add(mesh.vertices[lower], mesh.vertices[upper]),
            0.5));
        edge_nodes.emplace(key, node);
        return node;
    };
    for (const Triangle& triangle : mesh.triangles) {
        topology->triangle_edge_nodes.push_back({
            edge_node(triangle.a, triangle.b),
            edge_node(triangle.b, triangle.c),
            edge_node(triangle.c, triangle.a),
        });
    }

    std::vector<std::vector<SurfaceGraphEdge>> graph(
        topology->edge_midpoints.size());
    double maximum_connection_length = 0.0;
    auto connect = [&](std::uint32_t first, std::uint32_t second) {
        if (first == second) {
            return;
        }
        const double connection_length = length(sub(
            topology->edge_midpoints[first],
            topology->edge_midpoints[second]));
        maximum_connection_length =
            std::max(maximum_connection_length, connection_length);
        graph[first].push_back({second, connection_length});
        graph[second].push_back({first, connection_length});
    };
    for (const auto& nodes : topology->triangle_edge_nodes) {
        connect(nodes[0], nodes[1]);
        connect(nodes[1], nodes[2]);
        connect(nodes[2], nodes[0]);
    }

    SurfaceProjector projector(mesh, false, true);
    using QueueItem = std::pair<double, std::uint32_t>;
    for (PreparedGuide& guide : guides) {
        if (guide.source == nullptr || !guide.source->enabled) {
            continue;
        }
        guide.surface_topology = topology;
        guide.surface_node_distances.assign(
            topology->edge_midpoints.size(),
            std::numeric_limits<double>::infinity());
        guide.surface_seeds.clear();

        std::vector<Vec3> source_points;
        if (!guide.curve || guide.segments.empty()) {
            source_points.push_back(guide.fallback_point);
        } else {
            constexpr std::uint32_t maximum_segment_samples = 256U;
            constexpr std::size_t maximum_guide_samples = 4096U;
            const double sample_spacing = std::max(1.0e-6, guide.radius * 0.25);
            for (const PreparedCurveSegment& segment : guide.segments) {
                const std::uint32_t steps = std::clamp<std::uint32_t>(
                    static_cast<std::uint32_t>(
                        std::ceil(segment.length / sample_spacing)),
                    1U,
                    maximum_segment_samples);
                for (std::uint32_t index = 0U;
                     index <= steps && source_points.size() < maximum_guide_samples;
                     ++index) {
                    source_points.push_back(add(
                        segment.start,
                        mul(segment.delta, static_cast<double>(index) /
                            static_cast<double>(steps))));
                }
                if (source_points.size() >= maximum_guide_samples) {
                    break;
                }
            }
        }

        std::priority_queue<
            QueueItem,
            std::vector<QueueItem>,
            std::greater<QueueItem>> queue;
        // One edge-midpoint connection beyond the authored radius keeps
        // coarse adjacent triangles queryable while bounding local traversal.
        const double search_limit =
            guide.radius + maximum_connection_length;
        for (const Vec3& source_point : source_points) {
            const SurfaceSampleProjection projected =
                projector.project_sample_global(source_point);
            guide.surface_seeds.push_back({
                projected.triangle_index,
                projected.point,
            });
            const auto& nodes =
                topology->triangle_edge_nodes[projected.triangle_index];
            for (const std::uint32_t node : nodes) {
                const double seed_distance = length(sub(
                    topology->edge_midpoints[node],
                    projected.point));
                if (seed_distance <= search_limit &&
                    seed_distance < guide.surface_node_distances[node]) {
                    guide.surface_node_distances[node] = seed_distance;
                    queue.push({seed_distance, node});
                }
            }
        }
        std::sort(
            guide.surface_seeds.begin(),
            guide.surface_seeds.end(),
            [](const SurfaceGuideSeed& left, const SurfaceGuideSeed& right) {
                return left.triangle_index < right.triangle_index;
            });

        while (!queue.empty()) {
            const auto [distance, node] = queue.top();
            queue.pop();
            if (distance > guide.surface_node_distances[node]) {
                continue;
            }
            if (distance > search_limit) {
                break;
            }
            for (const SurfaceGraphEdge& edge : graph[node]) {
                const double candidate = distance + edge.length;
                if (candidate <= search_limit &&
                    candidate < guide.surface_node_distances[edge.vertex]) {
                    guide.surface_node_distances[edge.vertex] = candidate;
                    queue.push({candidate, edge.vertex});
                }
            }
        }
    }
}

struct DistributionGuideField {
    double density{1.0};
    double size{1.0};
    double mask_acceptance{1.0};
};

// Candidate sampling can evaluate hundreds of thousands of rejected points.
// Query only guides whose influence AABBs contain the point, while sorting the
// resulting indices back to authored order so multiplication and therefore
// deterministic CPU output remain bit-for-bit stable.
class DistributionGuideIndex {
public:
    explicit DistributionGuideIndex(const PreparedGuides& guides)
        : guides_(guides) {
        items_.reserve(guides.size());
        for (std::uint32_t index = 0U; index < guides.size(); ++index) {
            const PreparedGuide& guide = guides[index];
            if (guide.source == nullptr ||
                !guide.source->enabled ||
                (!guide.uses_density && !guide.uses_size && !guide.uses_mask)) {
                continue;
            }
            const Vec3 radius{guide.radius, guide.radius, guide.radius};
            items_.push_back({
                index,
                sub(guide.bounds_min, radius),
                add(guide.bounds_max, radius),
            });
        }
        if (!items_.empty()) {
            nodes_.reserve(items_.size() * 2U);
            build_node(0U, items_.size());
        }
    }

    DistributionGuideField evaluate(
        const Vec3& position,
        std::uint32_t triangle_index,
        std::vector<std::uint32_t>& scratch) const {
        scratch.clear();
        if (!nodes_.empty()) {
            query_node(0U, position, scratch);
            std::sort(scratch.begin(), scratch.end());
        }
        double density = 1.0;
        double size = 1.0;
        double mask_remaining = 1.0;
        for (const std::uint32_t index : scratch) {
            const PreparedGuide& guide = guides_[index];
            const Guide& source = *guide.source;
            const double influence = guide_influence_from_distance(
                guide,
                guide_distance(guide, position, triangle_index),
                guide.radius);
            if (guide.uses_mask) {
                mask_remaining *= 1.0 - clamp(influence, 0.0, 1.0);
            }
            if (guide.uses_density) {
                density *= 1.0 +
                    (clamp(source.density_multiplier, 0.0, 16.0) - 1.0) *
                        influence;
            }
            if (guide.uses_size) {
                size *= 1.0 +
                    (clamp(source.size_multiplier, 0.05, 8.0) - 1.0) *
                        influence;
            }
        }
        const double exclusion = clamp(1.0 - mask_remaining, 0.0, 1.0);
        const double mask_acceptance = exclusion >= kMaskHardCoreInfluence
            ? 0.0
            : clamp(1.0 - exclusion, 0.0, 1.0);
        return {
            clamp(density, 0.02, 16.0),
            clamp(size, 0.05, 8.0),
            mask_acceptance,
        };
    }

private:
    struct Item {
        std::uint32_t guide_index{0U};
        Vec3 minimum{};
        Vec3 maximum{};
    };

    struct Node {
        Vec3 minimum{};
        Vec3 maximum{};
        std::size_t begin{0U};
        std::size_t end{0U};
        std::uint32_t left{std::numeric_limits<std::uint32_t>::max()};
        std::uint32_t right{std::numeric_limits<std::uint32_t>::max()};
    };

    static bool contains(
        const Vec3& minimum,
        const Vec3& maximum,
        const Vec3& point) {
        return point.x >= minimum.x && point.x <= maximum.x &&
               point.y >= minimum.y && point.y <= maximum.y &&
               point.z >= minimum.z && point.z <= maximum.z;
    }

    std::uint32_t build_node(std::size_t begin, std::size_t end) {
        Vec3 minimum{
            std::numeric_limits<double>::infinity(),
            std::numeric_limits<double>::infinity(),
            std::numeric_limits<double>::infinity(),
        };
        Vec3 maximum{
            -std::numeric_limits<double>::infinity(),
            -std::numeric_limits<double>::infinity(),
            -std::numeric_limits<double>::infinity(),
        };
        for (std::size_t index = begin; index < end; ++index) {
            minimum.x = std::min(minimum.x, items_[index].minimum.x);
            minimum.y = std::min(minimum.y, items_[index].minimum.y);
            minimum.z = std::min(minimum.z, items_[index].minimum.z);
            maximum.x = std::max(maximum.x, items_[index].maximum.x);
            maximum.y = std::max(maximum.y, items_[index].maximum.y);
            maximum.z = std::max(maximum.z, items_[index].maximum.z);
        }
        const std::uint32_t node_index = static_cast<std::uint32_t>(nodes_.size());
        nodes_.push_back({minimum, maximum, begin, end});
        if (end - begin <= 4U) {
            return node_index;
        }
        const Vec3 extent = sub(maximum, minimum);
        const int axis = extent.y > extent.x && extent.y >= extent.z
            ? 1
            : (extent.z > extent.x && extent.z > extent.y ? 2 : 0);
        auto center = [axis](const Item& item) {
            if (axis == 1) {
                return item.minimum.y + item.maximum.y;
            }
            if (axis == 2) {
                return item.minimum.z + item.maximum.z;
            }
            return item.minimum.x + item.maximum.x;
        };
        std::stable_sort(
            items_.begin() + static_cast<std::ptrdiff_t>(begin),
            items_.begin() + static_cast<std::ptrdiff_t>(end),
            [&](const Item& left, const Item& right) {
                const double left_center = center(left);
                const double right_center = center(right);
                return left_center == right_center
                    ? left.guide_index < right.guide_index
                    : left_center < right_center;
            });
        const std::size_t middle = begin + (end - begin) / 2U;
        const std::uint32_t left = build_node(begin, middle);
        const std::uint32_t right = build_node(middle, end);
        nodes_[node_index].left = left;
        nodes_[node_index].right = right;
        return node_index;
    }

    void query_node(
        std::uint32_t node_index,
        const Vec3& position,
        std::vector<std::uint32_t>& result) const {
        const Node& node = nodes_[node_index];
        if (!contains(node.minimum, node.maximum, position)) {
            return;
        }
        const std::uint32_t invalid = std::numeric_limits<std::uint32_t>::max();
        if (node.left == invalid) {
            for (std::size_t index = node.begin; index < node.end; ++index) {
                const Item& item = items_[index];
                if (contains(item.minimum, item.maximum, position)) {
                    result.push_back(item.guide_index);
                }
            }
            return;
        }
        query_node(node.left, position, result);
        query_node(node.right, position, result);
    }

    const PreparedGuides& guides_;
    std::vector<Item> items_;
    std::vector<Node> nodes_;
};

enum class BoundaryFeatureKind : std::uint8_t {
    Open = 0U,
};

struct BoundarySegment {
    std::uint32_t start_vertex{0U};
    std::uint32_t end_vertex{0U};
    std::uint32_t triangle_index{0U};
    Vec3 start{};
    Vec3 end{};
    Vec3 normal{0.0, 1.0, 0.0};
    Vec3 inward{1.0, 0.0, 0.0};
    double length{0.0};
    double maximum_inset{0.0};
    BoundaryFeatureKind feature_kind{BoundaryFeatureKind::Open};
    std::uint32_t component_id{0U};
};

struct BoundaryChain {
    std::vector<std::uint32_t> segment_indices;
    std::vector<bool> reversed_flags;
    bool closed{false};
    double total_length{0.0};
    BoundaryFeatureKind feature_kind{BoundaryFeatureKind::Open};
};

struct BoundaryTopology {
    std::vector<BoundarySegment> segments;
    std::vector<BoundaryChain> chains;
    std::uint32_t open_edge_count{0U};
};

struct BoundaryAnchor {
    Vec3 position{};
    std::uint32_t triangle_index{0U};
    BoundaryFeatureKind feature_kind{BoundaryFeatureKind::Open};
    std::uint32_t chain_index{0U};
    std::uint32_t ordinal{0U};
    std::uint32_t count{1U};
};

std::uint64_t boundary_edge_key(std::uint32_t left, std::uint32_t right) {
    const std::uint32_t minimum = std::min(left, right);
    const std::uint32_t maximum = std::max(left, right);
    return (static_cast<std::uint64_t>(minimum) << 32U) |
        static_cast<std::uint64_t>(maximum);
}

BoundaryTopology build_boundary_topology(const Mesh& mesh) {
    struct Occurrence {
        std::uint32_t triangle_index{0U};
        std::uint32_t start{0U};
        std::uint32_t end{0U};
        std::uint32_t opposite{0U};
    };
    std::unordered_map<std::uint64_t, std::vector<Occurrence>> occurrences;
    occurrences.reserve(mesh.triangles.size() * 3U);
    for (std::uint32_t triangle_index = 0U;
         triangle_index < mesh.triangles.size();
         ++triangle_index) {
        const Triangle& triangle = mesh.triangles[triangle_index];
        for (const std::array<std::uint32_t, 3>& edge : {
                 std::array<std::uint32_t, 3>{triangle.a, triangle.b, triangle.c},
                 std::array<std::uint32_t, 3>{triangle.b, triangle.c, triangle.a},
                 std::array<std::uint32_t, 3>{triangle.c, triangle.a, triangle.b}}) {
            occurrences[boundary_edge_key(edge[0], edge[1])].push_back({
                triangle_index,
                edge[0],
                edge[1],
                edge[2],
            });
        }
    }

    // Compute connected surface components without crossing physical openings.
    std::vector<std::vector<std::uint32_t>> adjacency(mesh.triangles.size());
    for (std::uint32_t index = 0U; index < adjacency.size(); ++index) {
        adjacency[index].push_back(index);
    }
    for (const auto& entry : occurrences) {
        if (entry.second.size() < 2U) {
            continue;
        }
        std::vector<std::uint32_t> triangles;
        triangles.reserve(entry.second.size());
        for (const Occurrence& occurrence : entry.second) {
            triangles.push_back(occurrence.triangle_index);
        }
        std::sort(triangles.begin(), triangles.end());
        triangles.erase(std::unique(triangles.begin(), triangles.end()), triangles.end());
        for (std::size_t left = 0U; left < triangles.size(); ++left) {
            for (std::size_t right = left + 1U; right < triangles.size(); ++right) {
                adjacency[triangles[left]].push_back(triangles[right]);
                adjacency[triangles[right]].push_back(triangles[left]);
            }
        }
    }
    for (std::vector<std::uint32_t>& neighbors : adjacency) {
        std::sort(neighbors.begin(), neighbors.end());
        neighbors.erase(std::unique(neighbors.begin(), neighbors.end()), neighbors.end());
    }
    const std::uint32_t unassigned = std::numeric_limits<std::uint32_t>::max();
    std::vector<std::uint32_t> components(mesh.triangles.size(), unassigned);
    std::uint32_t component_id = 0U;
    for (std::uint32_t start = 0U; start < components.size(); ++start) {
        if (components[start] != unassigned) {
            continue;
        }
        components[start] = component_id;
        std::vector<std::uint32_t> stack{start};
        while (!stack.empty()) {
            const std::uint32_t current = stack.back();
            stack.pop_back();
            for (const std::uint32_t neighbor : adjacency[current]) {
                if (components[neighbor] != unassigned) {
                    continue;
                }
                components[neighbor] = component_id;
                stack.push_back(neighbor);
            }
        }
        ++component_id;
    }

    struct RawBoundary {
        std::uint64_t key{0U};
        BoundaryFeatureKind feature_kind{BoundaryFeatureKind::Open};
        Occurrence occurrence{};
    };
    std::vector<RawBoundary> raw;
    raw.reserve(occurrences.size());
    BoundaryTopology result;
    for (const auto& entry : occurrences) {
        if (entry.second.size() == 1U) {
            raw.push_back({entry.first, BoundaryFeatureKind::Open, entry.second.front()});
            ++result.open_edge_count;
            continue;
        }
    }
    std::sort(
        raw.begin(),
        raw.end(),
        [](const RawBoundary& left, const RawBoundary& right) {
            if (left.key != right.key) {
                return left.key < right.key;
            }
            if (left.feature_kind != right.feature_kind) {
                return static_cast<std::uint8_t>(left.feature_kind) <
                    static_cast<std::uint8_t>(right.feature_kind);
            }
            if (left.occurrence.triangle_index != right.occurrence.triangle_index) {
                return left.occurrence.triangle_index < right.occurrence.triangle_index;
            }
            if (left.occurrence.start != right.occurrence.start) {
                return left.occurrence.start < right.occurrence.start;
            }
            return left.occurrence.end < right.occurrence.end;
        });

    result.segments.reserve(raw.size());
    for (const RawBoundary& value : raw) {
        const Occurrence& edge = value.occurrence;
        const Vec3& start = mesh.vertices[edge.start];
        const Vec3& end = mesh.vertices[edge.end];
        const Vec3& opposite = mesh.vertices[edge.opposite];
        const Vec3 edge_vector = sub(end, start);
        const double edge_length = length(edge_vector);
        if (edge_length <= kEpsilon) {
            continue;
        }
        const Triangle& triangle = mesh.triangles[edge.triangle_index];
        const Vec3 normal = normal_and_area(
            mesh.vertices[triangle.a],
            mesh.vertices[triangle.b],
            mesh.vertices[triangle.c]).first;
        Vec3 inward = normalize(cross(normal, edge_vector), {0.0, 0.0, 0.0});
        const Vec3 midpoint = mul(add(start, end), 0.5);
        if (dot(sub(opposite, midpoint), inward) < 0.0) {
            inward = mul(inward, -1.0);
        }
        result.segments.push_back({
            edge.start,
            edge.end,
            edge.triangle_index,
            start,
            end,
            normal,
            inward,
            edge_length,
            std::max(0.0, dot(sub(opposite, midpoint), inward)),
            value.feature_kind,
            components[edge.triangle_index],
        });
    }
    if (result.segments.empty()) {
        return result;
    }

    using EndpointKey = std::tuple<std::uint8_t, std::uint32_t, std::uint32_t>;
    std::map<EndpointKey, std::vector<std::uint32_t>> by_endpoint;
    auto endpoint_key = [](const BoundarySegment& segment, std::uint32_t vertex) {
        return EndpointKey{
            static_cast<std::uint8_t>(segment.feature_kind),
            segment.component_id,
            vertex,
        };
    };
    for (std::uint32_t index = 0U; index < result.segments.size(); ++index) {
        const BoundarySegment& segment = result.segments[index];
        by_endpoint[endpoint_key(segment, segment.start_vertex)].push_back(index);
        by_endpoint[endpoint_key(segment, segment.end_vertex)].push_back(index);
    }
    for (auto& entry : by_endpoint) {
        std::sort(entry.second.begin(), entry.second.end());
    }
    std::vector<bool> visited(result.segments.size(), false);

    auto walk = [&](std::uint32_t start_vertex, std::uint32_t start_segment) {
        BoundaryChain chain;
        chain.feature_kind = result.segments[start_segment].feature_kind;
        std::uint32_t current_vertex = start_vertex;
        std::uint32_t current_segment = start_segment;
        while (!visited[current_segment]) {
            visited[current_segment] = true;
            const BoundarySegment& segment = result.segments[current_segment];
            const bool reversed = segment.end_vertex == current_vertex;
            const std::uint32_t next_vertex = reversed
                ? segment.start_vertex
                : segment.end_vertex;
            chain.segment_indices.push_back(current_segment);
            chain.reversed_flags.push_back(reversed);
            chain.total_length += segment.length;
            std::optional<std::uint32_t> next_segment;
            const auto found = by_endpoint.find(endpoint_key(segment, next_vertex));
            if (found != by_endpoint.end()) {
                for (const std::uint32_t candidate : found->second) {
                    if (!visited[candidate]) {
                        next_segment = candidate;
                        break;
                    }
                }
            }
            current_vertex = next_vertex;
            if (!next_segment.has_value()) {
                break;
            }
            current_segment = *next_segment;
        }
        chain.closed = !chain.segment_indices.empty() && current_vertex == start_vertex;
        return chain;
    };

    for (const auto& entry : by_endpoint) {
        if (entry.second.size() == 2U) {
            continue;
        }
        const std::uint32_t vertex = std::get<2>(entry.first);
        for (const std::uint32_t index : entry.second) {
            if (!visited[index]) {
                BoundaryChain chain = walk(vertex, index);
                if (!chain.segment_indices.empty()) {
                    result.chains.push_back(std::move(chain));
                }
            }
        }
    }
    for (std::uint32_t index = 0U; index < result.segments.size(); ++index) {
        if (visited[index]) {
            continue;
        }
        const BoundarySegment& segment = result.segments[index];
        BoundaryChain chain = walk(
            std::min(segment.start_vertex, segment.end_vertex),
            index);
        if (!chain.segment_indices.empty()) {
            result.chains.push_back(std::move(chain));
        }
    }
    std::sort(
        result.chains.begin(),
        result.chains.end(),
        [](const BoundaryChain& left, const BoundaryChain& right) {
            if (left.feature_kind != right.feature_kind) {
                return static_cast<std::uint8_t>(left.feature_kind) <
                    static_cast<std::uint8_t>(right.feature_kind);
            }
            const std::uint32_t left_min = *std::min_element(
                left.segment_indices.begin(), left.segment_indices.end());
            const std::uint32_t right_min = *std::min_element(
                right.segment_indices.begin(), right.segment_indices.end());
            if (left_min != right_min) {
                return left_min < right_min;
            }
            if (left.segment_indices.size() != right.segment_indices.size()) {
                return left.segment_indices.size() < right.segment_indices.size();
            }
            return left.closed < right.closed;
        });
    return result;
}

std::optional<BoundaryAnchor> point_on_boundary_chain(
    const BoundaryTopology& topology,
    const BoundaryChain& chain,
    double distance,
    double desired_inset,
    std::uint32_t chain_ordinal,
    std::uint32_t anchor_ordinal,
    std::uint32_t anchor_count) {
    double cursor = 0.0;
    for (std::size_t chain_index = 0U;
         chain_index < chain.segment_indices.size();
         ++chain_index) {
        const BoundarySegment& segment = topology.segments[
            chain.segment_indices[chain_index]];
        const double next_cursor = cursor + segment.length;
        if (distance <= next_cursor ||
            chain_index + 1U == chain.segment_indices.size()) {
            double amount = clamp(
                (distance - cursor) / segment.length,
                0.0,
                1.0);
            if (chain.reversed_flags[chain_index]) {
                amount = 1.0 - amount;
            }
            const Vec3 edge_point = add(
                segment.start,
                mul(sub(segment.end, segment.start), amount));
            const double inset = std::min(
                std::max(0.0, desired_inset),
                std::max(0.0, segment.maximum_inset * 0.45));
            return BoundaryAnchor{
                add(edge_point, mul(segment.inward, inset)),
                segment.triangle_index,
                segment.feature_kind,
                chain_ordinal,
                anchor_ordinal,
                std::max<std::uint32_t>(1U, anchor_count),
            };
        }
        cursor = next_cursor;
    }
    return std::nullopt;
}

std::vector<BoundaryAnchor> boundary_anchor_positions(
    const BoundaryTopology& topology,
    double spacing,
    std::uint32_t limit,
    double gap_world,
    const PreparedGuides& guides,
    bool* density_adapted = nullptr) {
    struct MetricInterval {
        double physical_begin{0.0};
        double physical_length{0.0};
        double weighted_begin{0.0};
        double weighted_length{0.0};
        double density_sqrt{1.0};
    };
    struct Allocation {
        const BoundaryChain* chain{nullptr};
        std::uint32_t desired{0U};
        std::uint32_t count{0U};
        double fraction{0.0};
        double weighted_length{0.0};
        std::vector<MetricInterval> metric;
    };

    const double base_spacing = std::max(1.0e-12, spacing);
    const bool adaptive_density = std::any_of(
        guides.begin(),
        guides.end(),
        [](const PreparedGuide& guide) {
            return guide.source != nullptr &&
                guide.source->enabled &&
                guide.uses_density &&
                std::abs(guide.source->density_multiplier - 1.0) > 1.0e-12;
        });
    if (density_adapted != nullptr) {
        *density_adapted = adaptive_density;
    }
    std::vector<Allocation> allocations;
    allocations.reserve(topology.chains.size());
    for (const BoundaryChain& chain : topology.chains) {
        if (chain.total_length <= kEpsilon) {
            continue;
        }
        Allocation allocation;
        allocation.chain = &chain;
        allocation.weighted_length = chain.total_length;
        if (adaptive_density) {
            allocation.weighted_length = 0.0;
            double physical_cursor = 0.0;
            for (std::size_t chain_segment_index = 0U;
                 chain_segment_index < chain.segment_indices.size();
                 ++chain_segment_index) {
                const BoundarySegment& segment = topology.segments[
                    chain.segment_indices[chain_segment_index]];
                const std::uint32_t subdivisions = std::clamp<std::uint32_t>(
                    static_cast<std::uint32_t>(std::ceil(
                        segment.length / std::max(1.0e-12, base_spacing * 0.5))),
                    1U,
                    64U);
                const double physical_length =
                    segment.length / static_cast<double>(subdivisions);
                for (std::uint32_t index = 0U; index < subdivisions; ++index) {
                    const double physical_begin =
                        physical_cursor + physical_length * static_cast<double>(index);
                    const double midpoint_distance = physical_begin + physical_length * 0.5;
                    const auto midpoint = point_on_boundary_chain(
                        topology,
                        chain,
                        midpoint_distance,
                        0.0,
                        0U,
                        0U,
                        1U);
                    const double density = midpoint.has_value()
                        ? density_factors(
                              midpoint->position,
                              guides,
                              midpoint->triangle_index).first
                        : 1.0;
                    const double density_sqrt = std::sqrt(
                        clamp(density, 0.02, 16.0));
                    const double weighted_length = physical_length * density_sqrt;
                    allocation.metric.push_back({
                        physical_begin,
                        physical_length,
                        allocation.weighted_length,
                        weighted_length,
                        density_sqrt,
                    });
                    allocation.weighted_length += weighted_length;
                }
                physical_cursor += segment.length;
            }
        }
        const std::uint32_t desired = std::max<std::uint32_t>(
            1U,
            static_cast<std::uint32_t>(std::floor(
                allocation.weighted_length / base_spacing + 0.5)));
        allocation.desired = desired;
        allocations.push_back(std::move(allocation));
    }
    if (allocations.empty() || limit == 0U) {
        return {};
    }

    const std::uint32_t base_count = std::min<std::uint32_t>(
        limit,
        static_cast<std::uint32_t>(allocations.size()));
    for (std::uint32_t index = 0U; index < base_count; ++index) {
        allocations[index].count = 1U;
    }
    std::uint32_t remaining = limit - base_count;
    std::uint64_t total_need = 0U;
    for (const Allocation& allocation : allocations) {
        total_need += allocation.desired - allocation.count;
    }
    if (remaining > 0U && total_need > 0U) {
        if (total_need <= remaining) {
            for (Allocation& allocation : allocations) {
                allocation.count = allocation.desired;
            }
        } else {
            std::uint32_t used = 0U;
            for (Allocation& allocation : allocations) {
                const std::uint32_t need = allocation.desired - allocation.count;
                const double quota = static_cast<double>(remaining) *
                    static_cast<double>(need) / static_cast<double>(total_need);
                const std::uint32_t whole = std::min<std::uint32_t>(
                    need,
                    static_cast<std::uint32_t>(std::floor(quota)));
                allocation.count += whole;
                allocation.fraction = quota - static_cast<double>(whole);
                used += whole;
            }
            std::uint32_t leftover = remaining - used;
            std::vector<std::size_t> order(allocations.size());
            for (std::size_t index = 0U; index < order.size(); ++index) {
                order[index] = index;
            }
            std::sort(
                order.begin(),
                order.end(),
                [&](std::size_t left, std::size_t right) {
                    if (allocations[left].fraction != allocations[right].fraction) {
                        return allocations[left].fraction > allocations[right].fraction;
                    }
                    return left < right;
                });
            for (const std::size_t index : order) {
                if (leftover == 0U) {
                    break;
                }
                Allocation& allocation = allocations[index];
                if (allocation.count >= allocation.desired) {
                    continue;
                }
                ++allocation.count;
                --leftover;
            }
        }
    }

    std::vector<BoundaryAnchor> result;
    result.reserve(limit);
    for (std::uint32_t chain_index = 0U;
         chain_index < allocations.size();
         ++chain_index) {
        const Allocation& allocation = allocations[chain_index];
        const BoundaryChain& chain = *allocation.chain;
        for (std::uint32_t index = 0U; index < allocation.count; ++index) {
            const double weighted_distance = chain.closed
                ? allocation.weighted_length * static_cast<double>(index) /
                    static_cast<double>(allocation.count)
                : allocation.weighted_length * (static_cast<double>(index) + 0.5) /
                    static_cast<double>(allocation.count);
            double distance = weighted_distance;
            double local_density_sqrt = 1.0;
            if (adaptive_density && !allocation.metric.empty()) {
                const auto found = std::lower_bound(
                    allocation.metric.begin(),
                    allocation.metric.end(),
                    weighted_distance,
                    [](const MetricInterval& interval, double value) {
                        return interval.weighted_begin + interval.weighted_length < value;
                    });
                const MetricInterval& interval = found == allocation.metric.end()
                    ? allocation.metric.back()
                    : *found;
                const double weighted_amount = interval.weighted_length <= 1.0e-20
                    ? 0.0
                    : clamp(
                        (weighted_distance - interval.weighted_begin) /
                            interval.weighted_length,
                        0.0,
                        1.0);
                distance = interval.physical_begin +
                    interval.physical_length * weighted_amount;
                local_density_sqrt = interval.density_sqrt;
            }
            const double desired_inset =
                base_spacing / std::max(1.0e-8, local_density_sqrt) * 0.46 +
                std::max(0.0, gap_world);
            const auto anchor = point_on_boundary_chain(
                topology,
                chain,
                distance,
                desired_inset,
                chain_index,
                index,
                allocation.count);
            if (anchor.has_value()) {
                result.push_back(*anchor);
            }
        }
    }
    return result;
}


class BoundaryIndex {
public:
    BoundaryIndex(
        const std::vector<BoundarySegment>& segments,
        double cell_size)
        : segments_(segments), cell_size_(std::max(1.0e-8, cell_size)) {
        for (std::uint32_t index = 0U; index < segments_.size(); ++index) {
            const BoundarySegment& segment = segments_[index];
            const Vec3 minimum{
                std::min(segment.start.x, segment.end.x),
                std::min(segment.start.y, segment.end.y),
                std::min(segment.start.z, segment.end.z),
            };
            const Vec3 maximum{
                std::max(segment.start.x, segment.end.x),
                std::max(segment.start.y, segment.end.y),
                std::max(segment.start.z, segment.end.z),
            };
            const GridCell lower = cell_for(minimum, cell_size_);
            const GridCell upper = cell_for(maximum, cell_size_);
            for (std::int64_t x = lower.x; x <= upper.x; ++x) {
                for (std::int64_t y = lower.y; y <= upper.y; ++y) {
                    for (std::int64_t z = lower.z; z <= upper.z; ++z) {
                        grid_[{x, y, z}].push_back(index);
                    }
                }
            }
        }
    }

    std::vector<std::uint32_t> query(
        const Vec3& position,
        double radius,
        std::uint32_t component_id) const {
        std::unordered_set<std::uint32_t> found;
        const GridCell origin = cell_for(position, cell_size_);
        const std::int64_t cells = std::max<std::int64_t>(
            1,
            static_cast<std::int64_t>(std::ceil(
                std::max(0.0, radius) / cell_size_)));
        for (std::int64_t x = -cells; x <= cells; ++x) {
            for (std::int64_t y = -cells; y <= cells; ++y) {
                for (std::int64_t z = -cells; z <= cells; ++z) {
                    const auto iterator = grid_.find({
                        origin.x + x,
                        origin.y + y,
                        origin.z + z,
                    });
                    if (iterator == grid_.end()) {
                        continue;
                    }
                    for (const std::uint32_t index : iterator->second) {
                        if (segments_[index].component_id == component_id) {
                            found.insert(index);
                        }
                    }
                }
            }
        }
        std::vector<std::uint32_t> result(found.begin(), found.end());
        std::sort(result.begin(), result.end());
        return result;
    }

    double ray_limit(
        const Vec3& origin,
        const Vec3& direction,
        double maximum,
        const std::vector<std::uint32_t>& indices) const {
        double limit = std::max(0.0, maximum);
        for (const std::uint32_t index : indices) {
            const BoundarySegment& segment = segments_[index];
            const double denominator = dot(direction, segment.inward);
            if (denominator >= -1.0e-12) {
                continue;
            }
            const double signed_distance = dot(
                sub(origin, segment.start),
                segment.inward);
            const double candidate = signed_distance / -denominator;
            if (candidate < 0.0 || candidate >= limit) {
                continue;
            }
            const Vec3 hit = add(origin, mul(direction, candidate));
            const Vec3 edge = sub(segment.end, segment.start);
            const double edge_length_squared = std::max(
                1.0e-20,
                length_squared(edge));
            const double amount = dot(sub(hit, segment.start), edge) /
                edge_length_squared;
            if (amount >= -1.0e-6 && amount <= 1.0 + 1.0e-6) {
                limit = std::max(0.0, candidate);
            }
        }
        return limit;
    }

private:
    const std::vector<BoundarySegment>& segments_;
    double cell_size_{1.0};
    std::unordered_map<GridCell, std::vector<std::uint32_t>, GridCellHash> grid_;
};

struct NeighborIndex {
    double distance_squared{0.0};
    std::uint32_t index{0};
};

struct PartitionConstraint {
    double delta_x{0.0};
    double delta_y{0.0};
    double right{0.0};
};

void append_partition_constraints(
    std::vector<PartitionConstraint>& constraints,
    const Vec2& owner,
    const std::vector<Vec2>& competitors,
    double shared_gap) {
    const double owner_squared = owner.x * owner.x + owner.y * owner.y;
    const double separation = std::max(0.0, shared_gap);
    for (const Vec2& competitor : competitors) {
        const double delta_x = competitor.x - owner.x;
        const double delta_y = competitor.y - owner.y;
        const double competitor_squared =
            competitor.x * competitor.x + competitor.y * competitor.y;
        // Shift each Voronoi bisector by half of the desired total shared
        // separation. The costly distance is independent of the Ray and is
        // therefore prepared once per owner/competitor pair.
        const double right = competitor_squared - owner_squared -
            separation * std::sqrt(delta_x * delta_x + delta_y * delta_y);
        constraints.push_back({delta_x, delta_y, right});
    }
}

std::optional<std::pair<double, double>> ray_interval_for_constraints(
    const Vec2& direction,
    const std::vector<PartitionConstraint>& constraints,
    std::size_t offset,
    std::size_t count,
    double maximum) {
    double lower = 0.0;
    double upper = std::max(0.0, maximum);
    const std::size_t end = std::min(constraints.size(), offset + count);
    for (std::size_t index = offset; index < end; ++index) {
        const PartitionConstraint& constraint = constraints[index];
        const double denominator = 2.0 * (
            direction.x * constraint.delta_x +
            direction.y * constraint.delta_y);
        if (std::abs(denominator) <= 1.0e-12) {
            if (constraint.right < -1.0e-12) {
                return std::nullopt;
            }
            continue;
        }
        const double bound = constraint.right / denominator;
        if (denominator > 0.0) {
            upper = std::min(upper, bound);
        } else {
            lower = std::max(lower, bound);
        }
        if (upper < lower) {
            return std::nullopt;
        }
    }
    return std::pair<double, double>{lower, upper};
}

CellResult build_cells_impl(
    const Mesh& mesh,
    const std::vector<OrientedSample>& oriented_samples,
    const Settings& settings,
    PreviewMode mode,
    const PreparedGuides& guides,
    const std::vector<SymmetryPlane>& symmetry_planes,
    GenerationReport report,
    std::uint32_t* used_workers = nullptr) {
    if (used_workers != nullptr) {
        *used_workers = 1U;
    }
    const std::uint32_t ray_count = effective_cell_resolution(settings, mode);
    report.used_cells = true;
    report.cell_resolution = ray_count;
    report.cell_shape_divisions = std::clamp<std::uint32_t>(
        settings.cell_shape_divisions,
        1U,
        6U);
    if (oriented_samples.empty()) {
        report.cell_count = 0U;
        report.paired_sample_count = 0U;
        report.partition_seed_count = 0U;
        return {{}, std::move(report)};
    }

    std::vector<Sample> samples;
    samples.reserve(oriented_samples.size());
    for (const OrientedSample& oriented : oriented_samples) {
        samples.push_back(oriented.sample);
    }

    double fallback_spacing =
        report.final_spacing > 0.0 ? report.final_spacing : report.initial_spacing;
    if (fallback_spacing <= 0.0) {
        double spacing_sum = 0.0;
        std::size_t spacing_count = 0U;
        for (const Sample& sample : samples) {
            if (sample.local_spacing > 0.0) {
                spacing_sum += sample.local_spacing;
                ++spacing_count;
            }
        }
        fallback_spacing = spacing_count > 0U
            ? spacing_sum / static_cast<double>(spacing_count)
            : std::max(1.0e-6, settings.size);
    }
    fallback_spacing = std::max(1.0e-8, fallback_spacing);
    const double gap_amount = clamp(settings.cell_gap, 0.0, 0.49);
    const double collision_amount = clamp(settings.cell_collision_margin, 0.0, 0.49);
    const double gap_world = gap_amount * fallback_spacing;
    const double collision_world = collision_amount * fallback_spacing;
    const double shared_gap_world = gap_world + collision_world;
    const double radius_scale = clamp(settings.cell_radius_multiplier, 0.35, 6.0);
    const std::uint32_t projection_rings = effective_cell_projection_rings(settings, mode);
    constexpr double normal_threshold = 0.0;
    constexpr std::size_t neighbor_limit = 64U;

    // Cell rays share the same angular table. Computing sin/cos once removes
    // hundreds of thousands of transcendental calls on 20-ray settled cells
    // while preserving the exact arguments and values used by every cell.
    std::vector<Vec2> ray_directions;
    ray_directions.reserve(ray_count);
    for (std::uint32_t ray_index = 0U; ray_index < ray_count; ++ray_index) {
        const double angle =
            2.0 * kPi * static_cast<double>(ray_index) /
            static_cast<double>(ray_count);
        ray_directions.push_back({std::cos(angle), std::sin(angle)});
    }

    SurfaceProjector projector(mesh, true, false);
    std::vector<std::uint32_t> projection_triangles;
    projection_triangles.reserve(samples.size());
    for (const Sample& sample : samples) {
        projection_triangles.push_back(sample.triangle_index);
    }
    projector.prepare_candidates(projection_triangles, projection_rings);
    const BoundaryTopology boundary_topology = build_boundary_topology(mesh);
    const BoundaryIndex boundary_index(
        boundary_topology.segments,
        fallback_spacing);
    // 0.8.7's virtual reflected competitors introduced a hard center cut
    // and sparse seam. Symmetry remains an authoring/evaluation feature; Cell
    // partitioning no longer inserts a synthetic mirror-plane boundary.
    (void)symmetry_planes;
    std::vector<double> spacings;
    spacings.reserve(samples.size());
    double maximum_spacing = 0.0;
    for (const Sample& sample : samples) {
        const double spacing = std::max(
            1.0e-8,
            sample.local_spacing > 0.0 ? sample.local_spacing : fallback_spacing);
        spacings.push_back(spacing);
        maximum_spacing = std::max(maximum_spacing, spacing);
    }

    const double grid_size = std::max(1.0e-8, fallback_spacing * 2.0);
    std::unordered_map<GridCell, std::vector<std::uint32_t>, GridCellHash> grid;
    grid.reserve(samples.size() * 2U);
    for (std::uint32_t index = 0; index < samples.size(); ++index) {
        grid[cell_for(samples[index].position, grid_size)].push_back(index);
    }

    std::vector<Vec3> normals;
    std::vector<std::uint32_t> components;
    std::vector<Vec3> stable_tangents;
    std::vector<Vec3> stable_bitangents;
    normals.reserve(samples.size());
    components.reserve(samples.size());
    stable_tangents.reserve(samples.size());
    stable_bitangents.reserve(samples.size());

    for (std::size_t sample_index = 0; sample_index < samples.size(); ++sample_index) {
        const Sample& sample = samples[sample_index];
        const Vec3 normal = normalize(sample.normal);
        const Vec3 stable_tangent = orthonormal_tangent(normal);
        const Vec3 stable_bitangent = normalize(cross(normal, stable_tangent));
        // Direction Pair authored a second partition site along the tangent,
        // but its controls were not visually reliable and are retired in
        // 0.8.9. One deterministic site now owns each scale; Direction affects
        // orientation only. Keep the report fields as zero-valued ABI data.
        normals.push_back(normal);
        components.push_back(projector.component(sample.triangle_index));
        stable_tangents.push_back(stable_tangent);
        stable_bitangents.push_back(stable_bitangent);
    }

    std::vector<CellData> cells(samples.size());
    struct CellWorkerStats {
        std::uint64_t neighbors{0U};
        std::uint64_t clipped_rays{0U};
        std::uint64_t boundary_clipped_rays{0U};
        std::uint64_t symmetry_stabilized_cells{0U};
        std::uint64_t symmetry_competitor_count{0U};
    };
    const std::uint32_t requested_workers = parallel_worker_count(
        samples.size(),
        192U);
    std::vector<CellWorkerStats> worker_stats(requested_workers);

    const std::uint32_t actual_workers = parallel_for_chunks(
        samples.size(),
        192U,
        [&](std::size_t begin, std::size_t end, std::uint32_t worker_index) {
            CellWorkerStats local_stats;
            std::vector<NeighborIndex> neighbors;
            neighbors.reserve(neighbor_limit * 2U);
            std::vector<Vec2> competitors;
            competitors.reserve(neighbor_limit * 2U);
            std::vector<PartitionConstraint> prepared_constraints;
            prepared_constraints.reserve(neighbor_limit * 4U);

            for (std::size_t sample_index = begin;
                 sample_index < end;
                 ++sample_index) {
                const Sample& sample = samples[sample_index];
                const Vec3 normal = normals[sample_index];
                const Vec3 stable_tangent = stable_tangents[sample_index];
                const Vec3 stable_bitangent = stable_bitangents[sample_index];
                const double local_spacing = spacings[sample_index];
                const double base_open_radius = local_spacing * radius_scale;
                const double search_radius =
                    base_open_radius * 2.5 +
                    maximum_spacing +
                    maximum_spacing * collision_amount;
                const GridCell origin_cell = cell_for(sample.position, grid_size);
                const std::int64_t search_cells = std::max<std::int64_t>(
                    1,
                    static_cast<std::int64_t>(std::ceil(
                        search_radius / grid_size)));
                const std::uint32_t component = components[sample_index];

                neighbors.clear();
                for (std::int64_t x = -search_cells; x <= search_cells; ++x) {
                    for (std::int64_t y = -search_cells; y <= search_cells; ++y) {
                        for (std::int64_t z = -search_cells; z <= search_cells; ++z) {
                            const auto found = grid.find({
                                origin_cell.x + x,
                                origin_cell.y + y,
                                origin_cell.z + z,
                            });
                            if (found == grid.end()) {
                                continue;
                            }
                            for (const std::uint32_t other_index : found->second) {
                                if (other_index == sample_index) {
                                    continue;
                                }
                                const Sample& other = samples[other_index];
                                if (components[other_index] != component) {
                                    continue;
                                }
                                if (dot(normal, normals[other_index]) < normal_threshold) {
                                    continue;
                                }
                                const double distance_squared = length_squared(
                                    sub(other.position, sample.position));
                                if (distance_squared <= 1.0e-20 ||
                                    distance_squared > search_radius * search_radius) {
                                    continue;
                                }
                                neighbors.push_back({distance_squared, other_index});
                            }
                        }
                    }
                }
                const auto neighbor_less = [](
                    const NeighborIndex& left,
                    const NeighborIndex& right) {
                    if (left.distance_squared != right.distance_squared) {
                        return left.distance_squared < right.distance_squared;
                    }
                    return left.index < right.index;
                };
                if (neighbors.size() > neighbor_limit) {
                    std::partial_sort(
                        neighbors.begin(),
                        neighbors.begin() + static_cast<std::ptrdiff_t>(neighbor_limit),
                        neighbors.end(),
                        neighbor_less);
                    neighbors.resize(neighbor_limit);
                } else {
                    std::sort(neighbors.begin(), neighbors.end(), neighbor_less);
                }
                local_stats.neighbors += neighbors.size();

                auto local_point = [&](const Vec3& point) -> Vec2 {
                    const Vec3 delta = sub(point, sample.position);
                    return {
                        dot(delta, stable_bitangent),
                        dot(delta, stable_tangent),
                    };
                };

                competitors.clear();
                for (const NeighborIndex& neighbor : neighbors) {
                    competitors.push_back(local_point(samples[neighbor.index].position));
                }

                prepared_constraints.clear();
                append_partition_constraints(
                    prepared_constraints,
                    Vec2{0.0, 0.0},
                    competitors,
                    shared_gap_world);

                const std::vector<std::uint32_t> nearby_boundaries =
                    boundary_index.query(
                        sample.position,
                        base_open_radius + fallback_spacing,
                        component);

                CellData cell;
                cell.sample_index = static_cast<std::uint32_t>(sample_index);
                cell.stable_tangent = stable_tangent;
                cell.stable_bitangent = stable_bitangent;
                cell.local_spacing = local_spacing;
                cell.neighbor_count = static_cast<std::uint32_t>(neighbors.size());
                cell.pair_influence = 0.0;
                cell.boundary.reserve(ray_count);

                for (std::uint32_t ray_index = 0U;
                     ray_index < ray_count;
                     ++ray_index) {
                    const double cosine = ray_directions[ray_index].x;
                    const double sine = ray_directions[ray_index].y;
                    const Vec2 direction{cosine, sine};
                    const double directional_maximum = base_open_radius;
                    double radius = directional_maximum;
                    bool found_reach = false;
                    const auto interval = ray_interval_for_constraints(
                        direction,
                        prepared_constraints,
                        0U,
                        prepared_constraints.size(),
                        directional_maximum);
                    if (interval.has_value()) {
                        const auto [lower, upper] = *interval;
                        if (lower <= 1.0e-8 && upper > 0.0) {
                            radius = upper;
                            found_reach = true;
                        }
                    }
                    const bool clipped =
                        found_reach && radius < directional_maximum - 1.0e-10;
                    if (clipped) {
                        ++cell.clipped_rays;
                    }
                    const Vec3 ray = add(
                        mul(stable_bitangent, cosine),
                        mul(stable_tangent, sine));
                    const double boundary_limit = boundary_index.ray_limit(
                        sample.position,
                        ray,
                        radius,
                        nearby_boundaries);
                    bool hard_clipped = boundary_limit < radius - 1.0e-10;
                    if (hard_clipped) {
                        radius = boundary_limit;
                        ++local_stats.boundary_clipped_rays;
                    }
                    const double minimum_radius = hard_clipped
                        ? 1.0e-8
                        : fallback_spacing * 0.025;
                    radius = std::max(
                        minimum_radius,
                        std::min(directional_maximum, radius));
                    Vec3 endpoint = add(sample.position, mul(ray, radius));
                    if (settings.cell_project_to_surface) {
                        endpoint = projector.project_prepared(
                            endpoint,
                            sample.triangle_index,
                            projection_rings);
                    }
                    cell.boundary.push_back(endpoint);
                }
                local_stats.clipped_rays += cell.clipped_rays;
                cells[sample_index] = std::move(cell);
            }
            worker_stats[worker_index] = local_stats;
        });
    if (used_workers != nullptr) {
        *used_workers = actual_workers;
    }

    std::uint64_t total_neighbors = 0U;
    std::uint64_t total_clipped_rays = 0U;
    std::uint64_t boundary_clipped_rays = 0U;
    std::uint64_t symmetry_stabilized_cells = 0U;
    std::uint64_t symmetry_competitor_count = 0U;
    for (const CellWorkerStats& stats : worker_stats) {
        total_neighbors += stats.neighbors;
        total_clipped_rays += stats.clipped_rays;
        boundary_clipped_rays += stats.boundary_clipped_rays;
        symmetry_stabilized_cells += stats.symmetry_stabilized_cells;
        symmetry_competitor_count += stats.symmetry_competitor_count;
    }

    report.cell_count = static_cast<std::uint32_t>(cells.size());
    report.cell_clipped_rays = static_cast<std::uint32_t>(std::min<std::uint64_t>(
        total_clipped_rays,
        std::numeric_limits<std::uint32_t>::max()));
    report.cell_mean_neighbors = cells.empty()
        ? 0.0
        : static_cast<double>(total_neighbors) / static_cast<double>(cells.size());
    report.paired_sample_count = 0U;
    report.partition_seed_count = static_cast<std::uint32_t>(std::min<std::size_t>(
        samples.size(),
        std::numeric_limits<std::uint32_t>::max()));
    report.open_boundary_edge_count = boundary_topology.open_edge_count;
    report.boundary_clipped_rays = static_cast<std::uint32_t>(
        std::min<std::uint64_t>(
            boundary_clipped_rays,
            std::numeric_limits<std::uint32_t>::max()));
    report.mask_clipped_rays = 0U;
    report.symmetry_stabilized_cells = static_cast<std::uint32_t>(
        std::min<std::uint64_t>(
            symmetry_stabilized_cells,
            std::numeric_limits<std::uint32_t>::max()));
    report.symmetry_competitor_count = static_cast<std::uint32_t>(
        std::min<std::uint64_t>(
            symmetry_competitor_count,
            std::numeric_limits<std::uint32_t>::max()));
    return {std::move(cells), std::move(report)};
}

std::uint32_t relax_samples(
    const Mesh& mesh,
    std::vector<Sample>& samples,
    std::uint32_t iterations,
    double strength,
    double target_spacing,
    std::uint32_t* used_workers = nullptr) {
    if (used_workers != nullptr) {
        *used_workers = 1U;
    }
    if (iterations == 0U || samples.size() < 2U || strength <= 0.0) {
        return 0U;
    }
    const double amount = clamp(strength, 0.0, 1.0);
    double largest_spacing = std::max(1.0e-8, target_spacing);
    for (const Sample& sample : samples) {
        largest_spacing = std::max(
            largest_spacing,
            std::max(1.0e-8, sample.local_spacing));
    }
    const double search_radius = largest_spacing * 2.4;
    std::uint64_t moved = 0U;

    for (std::uint32_t iteration = 0; iteration < iterations; ++iteration) {
        std::unordered_map<GridCell, std::vector<std::uint32_t>, GridCellHash> grid;
        grid.reserve(samples.size() * 2U);
        for (std::uint32_t index = 0; index < samples.size(); ++index) {
            grid[cell_for(samples[index].position, search_radius)].push_back(index);
        }
        std::vector<Sample> updated = samples;
        const std::uint32_t worker_count = parallel_worker_count(
            samples.size(),
            384U);
        std::vector<std::uint64_t> moved_by_worker(worker_count, 0U);
        const std::uint32_t actual_workers = parallel_for_chunks(
            samples.size(),
            384U,
            [&](std::size_t begin, std::size_t end, std::uint32_t worker_index) {
                std::uint64_t local_moved = 0U;
                for (std::size_t index = begin; index < end; ++index) {
                    const Sample& sample = samples[index];
                    const GridCell cell = cell_for(sample.position, search_radius);
                    Vec3 displacement{};
                    std::uint32_t neighbor_count = 0U;
                    for (int x = -1; x <= 1; ++x) {
                        for (int y = -1; y <= 1; ++y) {
                            for (int z = -1; z <= 1; ++z) {
                                const auto found = grid.find({
                                    cell.x + x,
                                    cell.y + y,
                                    cell.z + z,
                                });
                                if (found == grid.end()) {
                                    continue;
                                }
                                for (const std::uint32_t other_index : found->second) {
                                    if (other_index == index) {
                                        continue;
                                    }
                                    const Sample& other = samples[other_index];
                                    const Vec3 delta = sub(
                                        sample.position,
                                        other.position);
                                    const double distance_squared = length_squared(delta);
                                    if (distance_squared <= 1.0e-20) {
                                        continue;
                                    }
                                    const double distance = std::sqrt(distance_squared);
                                    const double desired = 1.08 * 0.5 *
                                        (std::max(1.0e-8, sample.local_spacing) +
                                         std::max(1.0e-8, other.local_spacing));
                                    const double interaction_radius = std::min(
                                        search_radius,
                                        std::max(desired * 2.2, desired + 1.0e-8));
                                    if (distance >= interaction_radius) {
                                        continue;
                                    }
                                    const double signed_error =
                                        (desired - distance) / desired;
                                    const double falloff = std::max(
                                        0.0,
                                        1.0 - distance / interaction_radius);
                                    const double weight =
                                        signed_error * falloff * falloff;
                                    displacement = add(
                                        displacement,
                                        mul(delta, weight / distance));
                                    ++neighbor_count;
                                }
                            }
                        }
                    }
                    if (neighbor_count == 0U) {
                        continue;
                    }
                    Vec3 tangent_move = project_on_plane(
                        mul(
                            displacement,
                            1.0 / static_cast<double>(neighbor_count)),
                        sample.normal);
                    const double move_length = length(tangent_move);
                    const double max_move = std::max(
                        target_spacing,
                        sample.local_spacing) * 0.32 * amount;
                    if (move_length > max_move) {
                        tangent_move = mul(tangent_move, max_move / move_length);
                    } else {
                        tangent_move = mul(tangent_move, amount);
                    }
                    if (length_squared(tangent_move) <= 1.0e-20) {
                        continue;
                    }
                    const Triangle& triangle = mesh.triangles[sample.triangle_index];
                    const Projection projected = closest_point_on_triangle(
                        add(sample.position, tangent_move),
                        mesh.vertices[triangle.a],
                        mesh.vertices[triangle.b],
                        mesh.vertices[triangle.c]);
                    if (length_squared(
                            sub(projected.point, sample.position)) > 1.0e-20) {
                        ++local_moved;
                    }
                    updated[index].position = projected.point;
                    updated[index].barycentric = projected.barycentric;
                }
                moved_by_worker[worker_index] = local_moved;
            });
        if (used_workers != nullptr) {
            *used_workers = std::max(*used_workers, actual_workers);
        }
        for (const std::uint64_t local_moved : moved_by_worker) {
            moved += local_moved;
        }
        samples = std::move(updated);
    }
    return static_cast<std::uint32_t>(std::min<std::uint64_t>(
        moved,
        std::numeric_limits<std::uint32_t>::max()));
}

std::pair<std::vector<Sample>, GenerationReport> sample_surface(
    const Mesh& mesh,
    const Settings& settings,
    std::uint32_t count,
    PreviewMode mode,
    const PreparedGuides& guides,
    std::uint32_t* used_workers = nullptr) {
    if (used_workers != nullptr) {
        *used_workers = 1U;
    }
    std::vector<std::uint32_t> triangle_indices;
    std::vector<double> cumulative_areas;
    std::vector<Vec3> normals(mesh.triangles.size());
    double total_area = 0.0;
    for (std::uint32_t index = 0; index < mesh.triangles.size(); ++index) {
        const Triangle& triangle = mesh.triangles[index];
        const auto [normal, area] = normal_and_area(
            mesh.vertices[triangle.a], mesh.vertices[triangle.b], mesh.vertices[triangle.c]);
        if (area <= 1.0e-14) {
            continue;
        }
        total_area += area;
        triangle_indices.push_back(index);
        cumulative_areas.push_back(total_area);
        normals[index] = normal;
    }
    if (total_area <= 1.0e-14 || triangle_indices.empty()) {
        throw std::invalid_argument("mesh has no non-degenerate surface area");
    }
    const std::uint64_t topology_hash = mesh_topology_hash(mesh);

    const double nominal_spacing = std::sqrt(total_area / static_cast<double>(count));
    const double initial_spacing = std::max(
        1.0e-12,
        nominal_spacing * clamp(settings.spacing_factor, 0.15, 2.5));
    const double cell_size = initial_spacing;
    const double maximum_density = maximum_density_factor(guides);
    const DistributionGuideIndex distribution_guide_index(guides);
    std::vector<std::uint32_t> distribution_guide_scratch;
    distribution_guide_scratch.reserve(guides.size());

    PythonRandom rng(settings.seed);
    std::vector<Sample> samples;
    std::unordered_map<GridCell, std::vector<std::uint32_t>, GridCellHash> grid;
    grid.reserve(static_cast<std::size_t>(count) * 2U);
    std::uint64_t attempts = 0;
    double final_spacing = initial_spacing;
    const std::uint64_t per_pass_limit = std::max<std::uint64_t>(count * 48ULL, 128ULL);

    const BoundaryTopology boundary_topology = build_boundary_topology(mesh);
    // Cell Gap belongs to the Cell stage. Boundary center placement remains
    // stable so Gap edits can reuse Distribution and Orientation caches.
    const double gap_world = 0.0;
    const std::vector<CurveCenterAnchor> authored_anchors = curve_center_anchors(
        guides,
        initial_spacing,
        count);
    const std::uint32_t minimum_boundary = boundary_topology.segments.empty()
        ? 0U
        : static_cast<std::uint32_t>(boundary_topology.chains.size());
    const std::uint32_t curve_count = std::min<std::uint32_t>(
        count,
        static_cast<std::uint32_t>(authored_anchors.size()));
    const std::uint32_t boundary_capacity = boundary_topology.segments.empty()
        ? 0U
        : std::max<std::uint32_t>(minimum_boundary, count - curve_count);
    bool boundary_density_adapted = false;
    const std::vector<BoundaryAnchor> boundary_anchors = boundary_anchor_positions(
        boundary_topology,
        initial_spacing,
        boundary_capacity,
        gap_world,
        guides,
        &boundary_density_adapted);
    const std::uint32_t anchor_limit = std::max<std::uint32_t>(
        count,
        static_cast<std::uint32_t>(
            boundary_anchors.size() + authored_anchors.size()));
    samples.reserve(anchor_limit);
    // Building the deterministic global BVH has a fixed cost. A short Guide
    // curve on a modest Preview can be projected faster by the exact linear
    // scan, while dense centerline authoring benefits strongly from the BVH.
    // Both paths use the same triangle-index tie break, so this cost model does
    // not change the generated samples or Python/Native parity.
    constexpr std::uint64_t global_projection_bvh_work_threshold = 750000ULL;
    const std::uint64_t global_projection_work =
        static_cast<std::uint64_t>(authored_anchors.size()) *
        static_cast<std::uint64_t>(mesh.triangles.size());
    SurfaceProjector projector(
        mesh,
        true,
        global_projection_work >= global_projection_bvh_work_threshold);

    std::vector<Sample> anchor_samples;
    anchor_samples.reserve(boundary_anchors.size() + authored_anchors.size());
    std::uint32_t boundary_anchor_count = 0U;
    double largest_accepted_spacing = initial_spacing;

    auto accept_anchor = [&](
        const SurfaceSampleProjection& projected,
        std::uint64_t stable_id,
        bool boundary,
        bool force) {
        if (samples.size() >= anchor_limit) {
            return;
        }
        auto [density_multiplier, size_multiplier] = density_factors(
            projected.point,
            guides,
            projected.triangle_index);
        const double local_spacing = initial_spacing /
            std::sqrt(std::max(0.02, density_multiplier));
        const GridCell cell = cell_for(projected.point, cell_size);
        const double maximum_neighbor_threshold = 0.5 *
            (local_spacing + largest_accepted_spacing);
        const int neighbor_range = std::max(
            1,
            static_cast<int>(std::ceil(
                maximum_neighbor_threshold / cell_size)));
        bool too_close = false;
        for (int x = -neighbor_range; x <= neighbor_range && !too_close; ++x) {
            for (int y = -neighbor_range; y <= neighbor_range && !too_close; ++y) {
                for (int z = -neighbor_range; z <= neighbor_range && !too_close; ++z) {
                    const auto found = grid.find({
                        cell.x + x,
                        cell.y + y,
                        cell.z + z,
                    });
                    if (found == grid.end()) {
                        continue;
                    }
                    for (const std::uint32_t sample_index : found->second) {
                        const Sample& other = samples[sample_index];
                        const double threshold = 0.5 * (
                            local_spacing +
                            std::max(1.0e-12, other.local_spacing));
                        if (length_squared(
                                sub(projected.point, other.position)) <
                            threshold * threshold) {
                            too_close = true;
                            break;
                        }
                    }
                }
            }
        }
        if (too_close && !force) {
            return;
        }
        if (force) {
            const bool duplicate = std::any_of(
                samples.begin(),
                samples.end(),
                [&](const Sample& existing) {
                    return length_squared(sub(
                        projected.point,
                        existing.position)) <= 1.0e-20;
                });
            if (duplicate) {
                return;
            }
        }
        Sample accepted{
            projected.point,
            projected.normal,
            projected.triangle_index,
            projected.barycentric,
            rng.random(),
            rng.random(),
            rng.random(),
            rng.random(),
            density_multiplier,
            size_multiplier,
            local_spacing,
            stable_id,
        };
        const std::uint32_t sample_index = static_cast<std::uint32_t>(samples.size());
        anchor_samples.push_back(accepted);
        samples.push_back(std::move(accepted));
        grid[cell].push_back(sample_index);
        largest_accepted_spacing = std::max(
            largest_accepted_spacing,
            local_spacing);
        if (boundary) {
            ++boundary_anchor_count;
        }
    };

    for (const BoundaryAnchor& anchor : boundary_anchors) {
        accept_anchor(
            projector.project_sample(
                anchor.position,
                anchor.triangle_index,
                0U),
            sample_stable_id(
                topology_hash,
                settings.seed,
                kRoleOpenBoundary,
                {anchor.chain_index, anchor.ordinal, anchor.count}),
            true,
            true);
    }
    for (const CurveCenterAnchor& authored_anchor : authored_anchors) {
        accept_anchor(
            projector.project_sample_global(authored_anchor.position),
            sample_stable_id(
                topology_hash,
                settings.seed,
                kRoleCurveCenter,
                {
                    authored_anchor.guide_key,
                    authored_anchor.ordinal,
                    authored_anchor.count,
                }),
            false,
            false);
    }

    for (std::uint64_t pass_index = 0U;
         pass_index < kRelaxationFactors.size();
         ++pass_index) {
        const double factor = kRelaxationFactors[pass_index];
        if (samples.size() >= count) {
            break;
        }
        const double spacing = initial_spacing * factor;
        final_spacing = spacing;
        std::uint64_t pass_attempts = 0;
        while (samples.size() < count && pass_attempts < per_pass_limit) {
            ++pass_attempts;
            ++attempts;
            const double weighted = rng.random() * total_area;
            const auto iterator = std::lower_bound(
                cumulative_areas.begin(), cumulative_areas.end(), weighted);
            const std::size_t lookup = std::min<std::size_t>(
                static_cast<std::size_t>(iterator - cumulative_areas.begin()),
                triangle_indices.size() - 1U);
            std::uint32_t triangle_index = triangle_indices[lookup];
            const Triangle& triangle = mesh.triangles[triangle_index];
            const double root = std::sqrt(rng.random());
            const double second = rng.random();
            std::array<double, 3> barycentric{
                1.0 - root,
                root * (1.0 - second),
                root * second,
            };
            Vec3 position = add(
                add(mul(mesh.vertices[triangle.a], barycentric[0]),
                    mul(mesh.vertices[triangle.b], barycentric[1])),
                mul(mesh.vertices[triangle.c], barycentric[2]));
            const DistributionGuideField field =
                distribution_guide_index.evaluate(
                    position,
                    triangle_index,
                    distribution_guide_scratch);
            const double density_multiplier = field.density;
            const double size_multiplier = field.size;
            const double acceptance = clamp(
                density_multiplier / maximum_density,
                0.002,
                1.0);
            if (rng.random() > acceptance) {
                continue;
            }
            const Vec3 normal = normals[triangle_index];
            const double local_spacing = spacing /
                std::sqrt(std::max(0.02, density_multiplier));
            const GridCell cell = cell_for(position, cell_size);
            const double maximum_neighbor_threshold = 0.5 *
                (local_spacing + largest_accepted_spacing);
            const int neighbor_range = std::max(
                1,
                static_cast<int>(std::ceil(
                    maximum_neighbor_threshold / cell_size)));
            bool too_close = false;
            for (int x = -neighbor_range; x <= neighbor_range && !too_close; ++x) {
                for (int y = -neighbor_range; y <= neighbor_range && !too_close; ++y) {
                    for (int z = -neighbor_range; z <= neighbor_range && !too_close; ++z) {
                        const auto found = grid.find({cell.x + x, cell.y + y, cell.z + z});
                        if (found == grid.end()) {
                            continue;
                        }
                        for (const std::uint32_t sample_index : found->second) {
                            const Sample& other = samples[sample_index];
                            const double threshold = 0.5 *
                                (local_spacing + std::max(1.0e-12, other.local_spacing));
                            if (length_squared(sub(position, other.position)) < threshold * threshold) {
                                too_close = true;
                                break;
                            }
                        }
                    }
                }
            }
            if (too_close) {
                continue;
            }
            const std::uint32_t sample_index = static_cast<std::uint32_t>(samples.size());
            samples.push_back({
                position,
                normal,
                triangle_index,
                barycentric,
                rng.random(),
                rng.random(),
                rng.random(),
                rng.random(),
                density_multiplier,
                size_multiplier,
                local_spacing,
                sample_stable_id(
                    topology_hash,
                    settings.seed,
                    kRoleSurfaceCandidate,
                    {pass_index, attempts}),
            });
            grid[cell].push_back(sample_index);
            largest_accepted_spacing = std::max(
                largest_accepted_spacing,
                local_spacing);
        }
    }

    const std::uint32_t iterations = effective_relax_iterations(settings, mode);
    std::uint32_t relax_worker_count = 1U;
    const std::uint32_t moved = relax_samples(
        mesh,
        samples,
        iterations,
        settings.relax_strength,
        final_spacing,
        &relax_worker_count);
    if (used_workers != nullptr) {
        *used_workers = std::max(*used_workers, relax_worker_count);
    }
    for (std::size_t index = 0U;
         index < anchor_samples.size() && index < samples.size();
         ++index) {
        samples[index] = anchor_samples[index];
    }
    GenerationReport report;
    report.requested_count = count;
    report.accepted_count = static_cast<std::uint32_t>(samples.size());
    report.attempts = attempts;
    report.surface_area = total_area;
    report.initial_spacing = initial_spacing;
    report.final_spacing = final_spacing;
    report.relax_iterations = iterations;
    report.moved_samples = moved;
    report.density_guide_count = guide_count(guides, true);
    report.direction_guide_count = guide_count(guides, false);
    report.mask_guide_count = mask_guide_count(guides);
    report.masked_candidate_count = 0U;
    report.open_boundary_edge_count = boundary_topology.open_edge_count;
    report.boundary_anchor_count = boundary_anchor_count;
    report.boundary_density_adapted = boundary_density_adapted;
    report.direction_relax_iterations = effective_direction_relax_iterations(settings, mode);
    return {std::move(samples), std::move(report)};
}

std::optional<std::vector<OrientedSample>> try_gpu_orientation_field(
    const std::vector<Sample>& samples,
    const Settings& settings,
    const PreparedGuides& guides,
    GenerationProfile* profile) {
    gpu::ExecutionInfo availability_info;
    if (!gpu::should_attempt_orientation(samples.size(), availability_info)) {
        if (profile != nullptr) {
            profile->gpu_compute_requested = availability_info.requested;
            profile->gpu_compute_available = availability_info.available;
            profile->gpu_compute_used = false;
            profile->gpu_compute_backend = availability_info.backend;
            profile->gpu_device = availability_info.device;
            profile->gpu_fallback_reason = availability_info.fallback_reason;
            profile->gpu_sample_count = availability_info.sample_count;
        }
        return std::nullopt;
    }
    std::vector<gpu::DirectionInput> gpu_inputs;
    gpu_inputs.reserve(samples.size());
    for (const Sample& sample : samples) {
        gpu_inputs.push_back({
            {
                static_cast<float>(sample.position.x),
                static_cast<float>(sample.position.y),
                static_cast<float>(sample.position.z),
                0.0F,
            },
            {
                static_cast<float>(sample.normal.x),
                static_cast<float>(sample.normal.y),
                static_cast<float>(sample.normal.z),
                0.0F,
            },
            static_cast<float>(sample.random_rotation),
            0.0F,
            0.0F,
            0.0F,
        });
    }
    std::vector<gpu::DirectionGuide> gpu_guides;
    std::vector<gpu::DirectionSegment> gpu_segments;
    gpu_guides.reserve(guides.size());
    for (const PreparedGuide& guide : guides) {
        if (guide.source == nullptr ||
            !guide.source->enabled ||
            !guide.uses_direction) {
            continue;
        }
        const std::uint32_t segment_offset = static_cast<std::uint32_t>(
            gpu_segments.size());
        for (const PreparedCurveSegment& segment : guide.segments) {
            gpu_segments.push_back({
                {
                    static_cast<float>(segment.start.x),
                    static_cast<float>(segment.start.y),
                    static_cast<float>(segment.start.z),
                    0.0F,
                },
                {
                    static_cast<float>(segment.delta.x),
                    static_cast<float>(segment.delta.y),
                    static_cast<float>(segment.delta.z),
                    0.0F,
                },
                {
                    static_cast<float>(segment.tangent.x),
                    static_cast<float>(segment.tangent.y),
                    static_cast<float>(segment.tangent.z),
                    0.0F,
                },
                static_cast<float>(segment.denominator),
                0.0F,
                0.0F,
                0.0F,
            });
        }
        gpu_guides.push_back({
            {
                static_cast<float>(guide.fallback_point.x),
                static_cast<float>(guide.fallback_point.y),
                static_cast<float>(guide.fallback_point.z),
                0.0F,
            },
            {
                static_cast<float>(guide.fallback_tangent.x),
                static_cast<float>(guide.fallback_tangent.y),
                static_cast<float>(guide.fallback_tangent.z),
                0.0F,
            },
            {
                static_cast<float>(guide.bounds_min.x),
                static_cast<float>(guide.bounds_min.y),
                static_cast<float>(guide.bounds_min.z),
                0.0F,
            },
            {
                static_cast<float>(guide.bounds_max.x),
                static_cast<float>(guide.bounds_max.y),
                static_cast<float>(guide.bounds_max.z),
                0.0F,
            },
            static_cast<float>(guide.radius),
            static_cast<float>(guide.falloff),
            static_cast<float>(clamp(guide.source->strength, 0.0, 1.0)),
            static_cast<float>(guide.source->angle_degrees * kPi / 180.0),
            segment_offset,
            static_cast<std::uint32_t>(guide.segments.size()),
            guide.curve ? 1U : 0U,
            guide.curve ? 0U : 1U,
        });
    }
    std::vector<gpu::DirectionOutput> gpu_outputs;
    gpu::ExecutionInfo gpu_info;
    const bool gpu_used = gpu::try_compute_orientation(
        gpu_inputs,
        gpu_guides,
        gpu_segments,
        static_cast<float>(settings.direction_degrees * kPi / 180.0),
        static_cast<float>(settings.random_rotation_degrees),
        gpu_outputs,
        gpu_info);
    if (profile != nullptr) {
        profile->gpu_compute_requested = gpu_info.requested;
        profile->gpu_compute_available = gpu_info.available;
        profile->gpu_compute_used = gpu_info.used;
        profile->gpu_compute_backend = gpu_info.backend;
        profile->gpu_device = gpu_info.device;
        profile->gpu_fallback_reason = gpu_info.fallback_reason;
        profile->gpu_upload_ms = gpu_info.upload_ms;
        profile->gpu_kernel_ms = gpu_info.kernel_ms;
        profile->gpu_readback_ms = gpu_info.readback_ms;
        profile->gpu_sample_count = gpu_info.sample_count;
    }
    if (!gpu_used || gpu_outputs.size() != samples.size()) {
        return std::nullopt;
    }
    std::vector<OrientedSample> result(samples.size());
    bool finite = true;
    for (std::size_t index = 0U; index < samples.size(); ++index) {
        const gpu::DirectionOutput& value = gpu_outputs[index];
        finite = finite &&
            std::isfinite(value.tangent.x) &&
            std::isfinite(value.tangent.y) &&
            std::isfinite(value.tangent.z) &&
            std::isfinite(value.partition_tangent.x) &&
            std::isfinite(value.partition_tangent.y) &&
            std::isfinite(value.partition_tangent.z) &&
            std::isfinite(value.point_influence);
        result[index] = {
            samples[index],
            {
                static_cast<double>(value.tangent.x),
                static_cast<double>(value.tangent.y),
                static_cast<double>(value.tangent.z),
            },
            {
                static_cast<double>(value.partition_tangent.x),
                static_cast<double>(value.partition_tangent.y),
                static_cast<double>(value.partition_tangent.z),
            },
            static_cast<double>(value.point_influence),
        };
    }
    if (!finite) {
        if (profile != nullptr) {
            profile->gpu_compute_used = false;
            profile->gpu_compute_backend = "cpu-multicore";
            profile->gpu_fallback_reason =
                "OpenCL orientation produced non-finite output";
        }
        return std::nullopt;
    }
    return result;
}

std::vector<OrientedSample> orientation_field(
    const std::vector<Sample>& samples,
    const Settings& settings,
    PreviewMode mode,
    const PreparedGuides& guides,
    double spacing,
    std::uint32_t* used_workers = nullptr,
    GenerationProfile* profile = nullptr) {
    if (used_workers != nullptr) {
        *used_workers = 1U;
    }
    // GPU Preview deliberately covers the exact 0.10.2 full-orientation
    // boundary, not the withdrawn 0.10.3 Dirty Region. Surface-connected
    // Falloff currently stays on the exact CPU path until the compact GPU
    // distance-field buffer is available.
    const bool has_surface_direction_guides = std::any_of(
        guides.begin(),
        guides.end(),
        [](const PreparedGuide& guide) {
            return guide.source != nullptr &&
                   guide.source->enabled &&
                   guide.uses_direction &&
                   !guide.surface_node_distances.empty();
        });
    const bool interactive_gpu_eligible =
        mode == PreviewMode::Interactive &&
        effective_direction_relax_iterations(settings, mode) == 0U;
    if (interactive_gpu_eligible && has_surface_direction_guides) {
        gpu::ExecutionInfo availability_info;
        const bool would_attempt =
            gpu::should_attempt_orientation(samples.size(), availability_info);
        if (profile != nullptr) {
            profile->gpu_compute_requested = availability_info.requested;
            profile->gpu_compute_available = availability_info.available;
            profile->gpu_compute_used = false;
            profile->gpu_compute_backend = availability_info.backend;
            profile->gpu_device = availability_info.device;
            profile->gpu_sample_count = availability_info.sample_count;
            profile->gpu_fallback_reason = would_attempt
                ? "Surface-connected Guide Falloff requires the CPU exact preview path"
                : availability_info.fallback_reason;
        }
    } else if (interactive_gpu_eligible) {
        auto gpu_result = try_gpu_orientation_field(
            samples, settings, guides, profile);
        if (gpu_result.has_value()) {
            if (used_workers != nullptr) {
                *used_workers = 0U;
            }
            return std::move(*gpu_result);
        }
    } else if (profile != nullptr && mode == PreviewMode::Interactive) {
        profile->gpu_fallback_reason =
            "Direction Relax requires the CPU exact preview path";
    }
    std::vector<Vec3> tangents(samples.size());
    const std::uint32_t initial_workers = parallel_for_chunks(
        samples.size(),
        512U,
        [&](std::size_t begin, std::size_t end, std::uint32_t) {
            for (std::size_t index = begin; index < end; ++index) {
                const Sample& sample = samples[index];
                const Vec3 normal = normalize(sample.normal);
                Vec3 tangent = orthonormal_tangent(normal);
                tangent = normalize(
                    rotate_around_axis(
                        tangent,
                        normal,
                        settings.direction_degrees * kPi / 180.0),
                    tangent);
                tangents[index] = guided_direction_solution(
                    sample.position,
                    normal,
                    tangent,
                    sample.triangle_index,
                    guides).tangent;
            }
        });
    if (used_workers != nullptr) {
        *used_workers = std::max(*used_workers, initial_workers);
    }

    const std::uint32_t iterations = effective_direction_relax_iterations(
        settings,
        mode);
    const double amount = clamp(settings.direction_relax_strength, 0.0, 1.0);
    const double radius = std::max(1.0e-8, spacing * 2.4);
    const double radius_squared = radius * radius;
    // Sample positions do not change during direction relaxation. Build the
    // spatial index once and preserve the original ascending sample-index
    // accumulation order for deterministic output across worker counts.
    std::unordered_map<GridCell, std::vector<std::uint32_t>, GridCellHash>
        direction_grid;
    if (iterations > 0U && samples.size() > 1U) {
        direction_grid.reserve(samples.size() * 2U);
        for (std::uint32_t index = 0U; index < samples.size(); ++index) {
            direction_grid[cell_for(samples[index].position, radius)].push_back(index);
        }
    }
    for (std::uint32_t iteration = 0U;
         iteration < iterations && tangents.size() > 1U;
         ++iteration) {
        std::vector<Vec3> updated = tangents;
        const std::uint32_t relax_workers = parallel_for_chunks(
            samples.size(),
            384U,
            [&](std::size_t begin, std::size_t end, std::uint32_t) {
                std::vector<std::uint32_t> nearby_indices;
                nearby_indices.reserve(96U);
                for (std::size_t index = begin; index < end; ++index) {
                    const Vec3 reference = tangents[index];
                    Vec3 accumulated = reference;
                    std::uint32_t count = 1U;
                    nearby_indices.clear();
                    const GridCell origin = cell_for(
                        samples[index].position,
                        radius);
                    for (std::int64_t x = -1; x <= 1; ++x) {
                        for (std::int64_t y = -1; y <= 1; ++y) {
                            for (std::int64_t z = -1; z <= 1; ++z) {
                                const auto found = direction_grid.find({
                                    origin.x + x,
                                    origin.y + y,
                                    origin.z + z,
                                });
                                if (found == direction_grid.end()) {
                                    continue;
                                }
                                nearby_indices.insert(
                                    nearby_indices.end(),
                                    found->second.begin(),
                                    found->second.end());
                            }
                        }
                    }
                    std::sort(nearby_indices.begin(), nearby_indices.end());
                    for (const std::uint32_t other_index : nearby_indices) {
                        if (other_index == index ||
                            length_squared(sub(
                                samples[index].position,
                                samples[other_index].position)) > radius_squared) {
                            continue;
                        }
                        Vec3 candidate = tangents[other_index];
                        if (dot(candidate, reference) < 0.0) {
                            candidate = mul(candidate, -1.0);
                        }
                        candidate = normalize(
                            project_on_plane(
                                candidate,
                                samples[index].normal),
                            reference);
                        accumulated = add(accumulated, candidate);
                        ++count;
                    }
                    const Vec3 average = normalize(
                        mul(accumulated, 1.0 / static_cast<double>(count)),
                        reference);
                    updated[index] = normalize(
                        project_on_plane(
                            add(
                                mul(reference, 1.0 - amount),
                                mul(average, amount)),
                            samples[index].normal),
                        reference);
                }
            });
        if (used_workers != nullptr) {
            *used_workers = std::max(*used_workers, relax_workers);
        }
        tangents = std::move(updated);
    }

    std::vector<OrientedSample> result(samples.size());
    const std::uint32_t final_workers = parallel_for_chunks(
        samples.size(),
        512U,
        [&](std::size_t begin, std::size_t end, std::uint32_t) {
            for (std::size_t index = begin; index < end; ++index) {
                const Sample& sample = samples[index];
                const Vec3 normal = normalize(sample.normal);
                const DirectionSolution solution = guided_direction_solution(
                    sample.position,
                    normal,
                    tangents[index],
                    sample.triangle_index,
                    guides);
                const Vec3 partition_tangent = solution.tangent;
                const double random_angle =
                    (sample.random_rotation * 2.0 - 1.0) *
                    settings.random_rotation_degrees;
                const Vec3 final_tangent = normalize(
                    rotate_around_axis(
                        partition_tangent,
                        normal,
                        random_angle * kPi / 180.0),
                    partition_tangent);
                result[index] = {
                    sample,
                    final_tangent,
                    partition_tangent,
                    point_direction_influence(
                        sample.position,
                        sample.triangle_index,
                        guides),
                };
            }
        });
    if (used_workers != nullptr) {
        *used_workers = std::max(*used_workers, final_workers);
    }
    return result;
}

struct SelectedType {
    const ScaleType* value{nullptr};
    std::uint32_t index{0};
    double local_amount{1.0};
};

SelectedType select_scale_type(
    const Sample& sample,
    const Settings& settings,
    const PreparedGuides& guides) {
    static const ScaleType fallback{};
    std::vector<std::uint32_t> active;
    std::vector<std::uint32_t> unlinked;
    active.reserve(settings.scale_types.size());
    unlinked.reserve(settings.scale_types.size());

    double strongest_amount = 0.0;
    std::optional<std::uint32_t> strongest_index;
    for (std::uint32_t index = 0U; index < settings.scale_types.size(); ++index) {
        const ScaleType& type = settings.scale_types[index];
        if (!type.enabled) {
            continue;
        }
        active.push_back(index);
        if (type.guide_id.empty()) {
            unlinked.push_back(index);
            continue;
        }
        const double amount = clamp(
            influence_for_id(
                type.guide_id,
                sample.position,
                0.0,
                sample.triangle_index,
                guides),
            0.0,
            1.0);
        // A Guide-linked type is a deterministic local assignment. The
        // strongest positive Guide or Group influence wins; equal strengths
        // preserve Settings list order instead of entering a global lottery.
        if (amount > strongest_amount + 1.0e-12) {
            strongest_amount = amount;
            strongest_index = index;
        }
    }

    if (active.empty()) {
        return {&fallback, 0U, 1.0};
    }
    if (strongest_index.has_value() && strongest_amount > 1.0e-12) {
        return {
            &settings.scale_types[*strongest_index],
            *strongest_index,
            strongest_amount,
        };
    }
    if (!unlinked.empty()) {
        const double random_value = clamp(sample.random_type, 0.0, 0.999999999);
        const std::size_t selected = std::min<std::size_t>(
            unlinked.size() - 1U,
            static_cast<std::size_t>(
                random_value * static_cast<double>(unlinked.size())));
        const std::uint32_t index = unlinked[selected];
        return {&settings.scale_types[index], index, 1.0};
    }

    // Every active type is linked, but no link influences this Sample. Keep
    // the first stable type id for attributes while applying no authored
    // shape or color deformation.
    const std::uint32_t index = active.front();
    return {&settings.scale_types[index], index, 0.0};
}

Vec3 make_point(
    const Vec3& origin,
    const Vec3& tangent,
    const Vec3& bitangent,
    const Vec3& normal,
    double lateral,
    double longitudinal,
    double normal_offset) {
    return add(
        add(add(origin, mul(bitangent, lateral)), mul(tangent, longitudinal)),
        mul(normal, normal_offset));
}

void initialize_topology(
    GeneratedMesh& mesh,
    const GenerationOptions& options,
    std::size_t face_count,
    std::size_t face_vertex_count) {
    if (options.materialize_faces) {
        mesh.faces.reserve(face_count);
    }
    if (options.include_flat_topology) {
        mesh.face_offsets.reserve(face_count + 1U);
        mesh.face_vertices.reserve(face_vertex_count);
        mesh.face_offsets.push_back(0U);
    }
}

void append_face(
    GeneratedMesh& mesh,
    const std::uint32_t* indices,
    std::size_t count,
    const GenerationOptions& options) {
    if (options.materialize_faces) {
        mesh.faces.emplace_back(indices, indices + count);
    }
    if (options.include_flat_topology) {
        mesh.face_vertices.insert(
            mesh.face_vertices.end(),
            indices,
            indices + count);
        mesh.face_offsets.push_back(
            static_cast<std::uint32_t>(mesh.face_vertices.size()));
    }
}

template <std::size_t Count>
void append_face(
    GeneratedMesh& mesh,
    const std::array<std::uint32_t, Count>& indices,
    const GenerationOptions& options) {
    append_face(mesh, indices.data(), Count, options);
}

void append_face(
    GeneratedMesh& mesh,
    const std::vector<std::uint32_t>& indices,
    const GenerationOptions& options) {
    append_face(mesh, indices.data(), indices.size(), options);
}

std::vector<std::uint32_t> triangle_toward_normal(
    const std::vector<Vec3>& vertices,
    std::uint32_t first,
    std::uint32_t second,
    std::uint32_t third,
    const Vec3& normal) {
    const Vec3 geometric_normal = cross(
        sub(vertices[second], vertices[first]),
        sub(vertices[third], vertices[first]));
    const double orientation = dot(geometric_normal, normal);
    // Hard masks and open-boundary clipping can collapse an individual
    // center-fan triangle to nearly zero area. Ignore a numerically
    // meaningless sign so Python and C++ keep the same deterministic order.
    const double tolerance =
        length(geometric_normal) * std::max(1.0, length(normal)) * 1.0e-12;
    if (orientation < -tolerance) {
        return {first, third, second};
    }
    return {first, second, third};
}

struct ScaleShape {
    std::uint32_t type_id{0};
    double size{0.1};
    double width{0.1};
    double scale_length{0.165};
    double curvature{0.22};
    double inset{0.0};
    double squash{0.0};
    double expand{0.0};
    double round_sharp{0.0};
    double roundness{0.15};
    double sharpness{0.0};
    double smooth{0.0};
    double tip_offset{0.0};
    double normal_offset{0.0};
    double forward_offset{0.0};
    Color4 color{};
};

ScaleShape shape_for(
    const Sample& sample,
    const Settings& settings,
    const PreparedGuides& guides,
    bool cell_safe = false) {
    const SelectedType selected = select_scale_type(sample, settings, guides);
    const ScaleType& type = *selected.value;
    const double type_amount = clamp(selected.local_amount, 0.0, 1.0);
    const double random_scale = std::max(
        0.05,
        1.0 + (sample.random_size * 2.0 - 1.0) *
                  clamp(settings.random_size, 0.0, 0.95));
    const double type_size_multiplier = lerp_scalar(
        1.0,
        clamp(type.size_multiplier, 0.05, 8.0),
        type_amount);
    // Keep Guide and Scale Type size inside the authored neutral envelope.
    // The 0.8.9 raw delta sum could collapse 0.5 + 0.5 to the emergency 0.05
    // floor, creating locally pinched interior rings.
    const double combined_size_multiplier = combine_size_multipliers(
        sample.size_multiplier,
        type_size_multiplier);
    double size = settings.size * combined_size_multiplier * random_scale;
    if (cell_safe) {
        size = std::min(
            size,
            std::max(1.0e-8, sample.local_spacing * 0.92));
    }
    const double width_multiplier = lerp_scalar(
        1.0,
        clamp(type.width_multiplier, 0.05, 8.0),
        type_amount);
    double width = size * width_multiplier;
    const double combined_squash = clamp(settings.squash, -0.9, 0.9);
    width *= std::max(0.1, 1.0 + 0.58 * combined_squash);
    const double length_multiplier = lerp_scalar(
        1.0,
        clamp(type.length_multiplier, 0.05, 8.0),
        type_amount);
    const double scale_length = size * kFixedScaleAspect *
        length_multiplier *
        std::max(0.1, 1.0 - 0.58 * combined_squash);
    const double random_offset = (sample.random_shape * 2.0 - 1.0) *
        clamp(type.random_offset, 0.0, 1.0) *
        type_amount * size * 0.35;
    const Color4 authored_color = type.use_custom_color ? type.color : settings.color;
    const Color4 color{
        lerp_scalar(settings.color.r, authored_color.r, type_amount),
        lerp_scalar(settings.color.g, authored_color.g, type_amount),
        lerp_scalar(settings.color.b, authored_color.b, type_amount),
        lerp_scalar(settings.color.a, authored_color.a, type_amount),
    };
    return {
        selected.index,
        size,
        width,
        scale_length,
        settings.curvature * lerp_scalar(
            1.0,
            clamp(type.curvature_multiplier, -4.0, 4.0),
            type_amount),
        clamp(settings.inset, 0.0, 0.95),
        combined_squash,
        clamp(settings.expand, -0.75, 3.0),
        0.0,
        clamp(settings.tip_roundness, 0.0, 1.0),
        0.0,
        0.0,
        clamp(settings.tip_offset + type.tip_offset * type_amount, -1.0, 1.0),
        type.offset * type_amount * size + random_offset,
        settings.forward_offset,
        color,
    };
}

std::array<std::array<double, 3>, 5> outline_for(const ScaleShape& shape) {
    const double base_width = 0.38 * (1.0 - 0.60 * shape.inset);
    const double side_width = (0.52 + 0.22 * shape.expand) *
                              (1.0 - 0.18 * shape.inset);
    const double base_y = -0.32 + 0.16 * shape.inset;
    const double side_y = 0.06 + 0.06 * shape.expand +
                          0.18 * shape.roundness + 0.08 * shape.smooth;
    const double tip_y = 0.76 - 0.14 * shape.roundness +
                         0.12 * shape.sharpness + 0.20 * shape.tip_offset;
    const double side_curve = 0.22 + 0.16 * std::max(0.0, shape.expand) +
                              0.10 * shape.roundness;
    const double tip_curve = 1.0 + 0.16 * shape.sharpness -
                             0.12 * shape.roundness;
    return {{{-base_width, base_y, 0.0},
             {-side_width, side_y, side_curve},
             {0.0, tip_y, tip_curve},
             {side_width, side_y, side_curve},
             {base_width, base_y, 0.0}}};
}

bool wants_cell_metadata(
    const GenerationOptions& options,
    std::uint32_t scale_index,
    std::uint64_t stable_id) {
    if (std::binary_search(
            options.cell_metadata_indices.begin(),
            options.cell_metadata_indices.end(),
            scale_index)) {
        return true;
    }
    return std::binary_search(
        options.resolve_cell_ids.begin(),
        options.resolve_cell_ids.end(),
        stable_id);
}

std::uint64_t cell_boundary_signature(const std::vector<Vec3>& points) {
    if (points.empty()) {
        return 0U;
    }
    std::uint64_t result = fnv_text(
        kFnvOffsetBasis64,
        "bifrost-scales/cell-boundary/1");
    const unsigned char terminator = 0U;
    result = fnv_bytes(result, &terminator, 1U);
    result = fnv_u64(result, static_cast<std::uint64_t>(points.size()));
    for (const Vec3& point : points) {
        for (const double component : {point.x, point.y, point.z}) {
            std::uint64_t bits = 0U;
            static_assert(sizeof(bits) == sizeof(component));
            std::memcpy(&bits, &component, sizeof(bits));
            result = fnv_u64(result, bits);
        }
    }
    return result == 0U ? 1U : result;
}

void append_cell_identity(
    GeneratedMesh& result,
    const Sample& sample,
    std::uint32_t scale_index,
    std::uint64_t boundary_signature,
    const GenerationOptions& options) {
    const std::uint64_t stable_id = sample.stable_id == 0U
        ? stable_hash_values(
            "bifrost-scales/legacy-sample-id/1",
            {
                sample.triangle_index,
                scale_index,
            })
        : sample.stable_id;
    if (options.include_cell_ids) {
        result.cell_ids.push_back(stable_id);
    }
    if (wants_cell_metadata(options, scale_index, stable_id)) {
        result.cell_metadata.push_back({
            stable_id,
            scale_index,
            sample.position,
            sample.normal,
            sample.triangle_index,
            sample.barycentric,
            boundary_signature,
        });
    }
}

GeneratedMesh build_mesh_impl(
    const std::vector<OrientedSample>& oriented_samples,
    const Settings& settings,
    PreviewMode mode,
    const PreparedGuides& guides,
    const GenerationOptions& options) {
    GeneratedMesh result;
    result.scale_count = static_cast<std::uint32_t>(oriented_samples.size());
    const bool interactive = mode == PreviewMode::Interactive;
    const std::size_t vertices_per_scale = interactive ? 3U : 6U;
    const std::size_t faces_per_scale = interactive ? 1U : 5U;
    result.vertices.reserve(oriented_samples.size() * vertices_per_scale);
    initialize_topology(
        result,
        options,
        oriented_samples.size() * faces_per_scale,
        oriented_samples.size() * faces_per_scale * 3U);
    if (options.include_uvs) {
        result.uvs.reserve(oriented_samples.size() * vertices_per_scale);
    }
    if (options.include_colors) {
        result.colors.reserve(oriented_samples.size() * vertices_per_scale);
    }
    if (options.include_scale_type_ids) {
        result.scale_type_ids.reserve(oriented_samples.size());
    }
    if (options.include_cell_ids) {
        result.cell_ids.reserve(oriented_samples.size());
    }
    result.cell_metadata.reserve(
        options.cell_metadata_indices.size() + options.resolve_cell_ids.size());

    constexpr std::array<Vec2, 5> outline_uvs{{
        {0.12, 0.00},
        {0.00, 0.38},
        {0.50, 1.00},
        {1.00, 0.38},
        {0.88, 0.00},
    }};
    for (std::uint32_t source_index = 0U;
         source_index < oriented_samples.size();
         ++source_index) {
        const OrientedSample& oriented = oriented_samples[source_index];
        const Sample& sample = oriented.sample;
        const Vec3 normal = normalize(sample.normal);
        const Vec3 tangent = normalize(oriented.tangent, orthonormal_tangent(normal));
        const Vec3 bitangent = normalize(cross(normal, tangent));
        const ScaleShape shape = shape_for(sample, settings, guides);
        const Vec3 origin = add(
            add(sample.position, mul(normal, settings.lift + shape.normal_offset)),
            mul(tangent, shape.forward_offset * shape.size));
        const auto outline = outline_for(shape);
        const std::uint32_t base = static_cast<std::uint32_t>(result.vertices.size());

        if (interactive) {
            for (const std::size_t index : {0U, 4U, 2U}) {
                result.vertices.push_back(make_point(
                    origin,
                    tangent,
                    bitangent,
                    normal,
                    outline[index][0] * shape.width,
                    outline[index][1] * shape.scale_length,
                    shape.curvature * shape.size * outline[index][2]));
                if (options.include_uvs) {
                    result.uvs.push_back(outline_uvs[index]);
                }
                if (options.include_colors) {
                    result.colors.push_back(shape.color);
                }
            }
            // Outline points 0, 4, 2 are stored in the opposite geometric
            // order to the source-surface normal. Reverse only the face
            // indices so vertex and UV storage remain stable.
            append_face(
                result,
                std::array<std::uint32_t, 3>{base, base + 2U, base + 1U},
                options);
            if (options.include_scale_type_ids) {
                result.scale_type_ids.push_back(shape.type_id);
            }
            append_cell_identity(
                result, sample, source_index, 0U, options);
            continue;
        }

        for (std::size_t index = 0; index < outline.size(); ++index) {
            const auto& value = outline[index];
            result.vertices.push_back(make_point(
                origin,
                tangent,
                bitangent,
                normal,
                value[0] * shape.width,
                value[1] * shape.scale_length,
                shape.curvature * shape.size * value[2]));
            if (options.include_uvs) {
                result.uvs.push_back(outline_uvs[index]);
            }
            if (options.include_colors) {
                result.colors.push_back(shape.color);
            }
        }
        result.vertices.push_back(make_point(
            origin,
            tangent,
            bitangent,
            normal,
            0.0,
            (0.12 + shape.inset * 0.06) * shape.scale_length,
            shape.curvature * shape.size *
                (0.28 + 0.10 * shape.roundness)));
        if (options.include_uvs) {
            result.uvs.push_back({0.50, 0.42});
        }
        if (options.include_colors) {
            result.colors.push_back(shape.color);
        }
        const std::uint32_t center = base + 5U;
        for (std::uint32_t index = 0; index < 5U; ++index) {
            append_face(
                result,
                std::array<std::uint32_t, 3>{
                    center,
                    base + index,
                    base + ((index + 1U) % 5U),
                },
                options);
        }
        if (options.include_scale_type_ids) {
            result.scale_type_ids.push_back(shape.type_id);
        }
        append_cell_identity(result, sample, source_index, 0U, options);
    }
    return result;
}

Vec3 blend_point(const Vec3& left, const Vec3& right, double amount) {
    return add(mul(left, 1.0 - amount), mul(right, amount));
}

Vec3 average_points(const std::vector<Vec3>& points) {
    if (points.empty()) {
        return {};
    }
    Vec3 total{};
    for (const Vec3& point : points) {
        total = add(total, point);
    }
    return mul(total, 1.0 / static_cast<double>(points.size()));
}

std::vector<Vec3> smooth_cell_outline(
    const std::vector<Vec3>& boundary,
    std::uint32_t iterations = 5U) {
    std::vector<Vec3> current = boundary;
    if (current.size() < 3U) {
        return current;
    }
    for (std::uint32_t iteration = 0U; iteration < iterations; ++iteration) {
        const std::vector<Vec3> previous = current;
        const std::size_t count = previous.size();
        for (std::size_t index = 0U; index < count; ++index) {
            current[index] = mul(
                add(
                    add(previous[(index + count - 1U) % count], previous[index]),
                    previous[(index + 1U) % count]),
                1.0 / 3.0);
        }
    }
    return current;
}

double cross2(const Vec2& left, const Vec2& right) {
    return left.x * right.y - left.y * right.x;
}

double ray_polygon_radius(
    const Vec2& direction,
    const std::vector<Vec2>& polygon) {
    const double magnitude = std::hypot(direction.x, direction.y);
    if (magnitude <= 1.0e-12 || polygon.size() < 3U) {
        return 0.0;
    }
    const Vec2 ray{direction.x / magnitude, direction.y / magnitude};
    double best = std::numeric_limits<double>::infinity();
    for (std::size_t index = 0U; index < polygon.size(); ++index) {
        const Vec2& start = polygon[index];
        const Vec2& end = polygon[(index + 1U) % polygon.size()];
        const Vec2 edge{end.x - start.x, end.y - start.y};
        const double denominator = cross2(ray, edge);
        if (std::abs(denominator) <= 1.0e-12) {
            continue;
        }
        const double distance = cross2(start, edge) / denominator;
        const double edge_amount = cross2(start, ray) / denominator;
        if (distance <= 1.0e-10) {
            continue;
        }
        if (edge_amount < -1.0e-9 || edge_amount > 1.0 + 1.0e-9) {
            continue;
        }
        best = std::min(best, distance);
    }
    return std::isfinite(best) ? best : 0.0;
}

double cell_edit_weight(double weight, double round_sharp) {
    const double value = clamp(weight, 0.0, 1.0);
    const double sharp_amount = clamp(0.5 + 0.5 * round_sharp, 0.0, 1.0);
    const double rounded = std::pow(value, 1.65);
    const double sharpened = std::pow(value, 0.62);
    return lerp_scalar(rounded, sharpened, sharp_amount);
}

Vec2 clamp_inside_cell(
    double lateral,
    double longitudinal,
    const std::vector<Vec2>& polygon) {
    const double radius = std::hypot(lateral, longitudinal);
    if (radius <= 1.0e-12) {
        return {lateral, longitudinal};
    }
    const double limit = ray_polygon_radius({lateral, longitudinal}, polygon);
    if (limit <= 1.0e-12 || radius <= limit) {
        return {lateral, longitudinal};
    }
    const double amount = std::max(0.0, (limit * (1.0 - 1.0e-7)) / radius);
    return {lateral * amount, longitudinal * amount};
}

GeneratedMesh build_cell_mesh_range(
    const std::vector<OrientedSample>& oriented_samples,
    const std::vector<CellData>& cells,
    const Settings& settings,
    const PreparedGuides& guides,
    const GenerationOptions& options,
    std::size_t begin_index,
    std::size_t end_index,
    const std::vector<std::uint32_t>& global_scale_indices) {
    GeneratedMesh result;
    const std::size_t available_count = std::min(
        oriented_samples.size(),
        cells.size());
    begin_index = std::min(begin_index, available_count);
    end_index = std::min(std::max(end_index, begin_index), available_count);
    if (begin_index == end_index) {
        return result;
    }

    const std::uint32_t divisions = std::clamp<std::uint32_t>(
        settings.cell_shape_divisions,
        1U,
        6U);
    std::size_t estimated_vertices = 0U;
    std::size_t estimated_faces = 0U;
    for (std::size_t index = begin_index; index < end_index; ++index) {
        const std::size_t ring_size = cells[index].boundary.size();
        if (ring_size < 3U) {
            continue;
        }
        estimated_vertices += ring_size * (static_cast<std::size_t>(divisions) + 1U) + 1U;
        estimated_faces += ring_size * static_cast<std::size_t>(divisions) + ring_size;
    }
    result.vertices.reserve(estimated_vertices);
    initialize_topology(
        result,
        options,
        estimated_faces,
        estimated_faces * 4U);
    if (options.include_uvs) {
        result.uvs.reserve(estimated_vertices);
    }
    if (options.include_colors) {
        result.colors.reserve(estimated_vertices);
    }
    if (options.include_scale_type_ids) {
        result.scale_type_ids.reserve(end_index - begin_index);
    }
    if (options.include_cell_ids) {
        result.cell_ids.reserve(end_index - begin_index);
    }
    result.cell_metadata.reserve(
        options.cell_metadata_indices.size() + options.resolve_cell_ids.size());
    const double growth = clamp(settings.cell_growth, 0.0, 1.0);

    for (std::size_t scale_index = begin_index;
         scale_index < end_index;
         ++scale_index) {
        const OrientedSample& oriented = oriented_samples[scale_index];
        const Sample& sample = oriented.sample;
        const CellData& cell = cells[scale_index];
        if (cell.boundary.size() < 3U) {
            continue;
        }

        const Vec3 normal = normalize(sample.normal);
        const Vec3 tangent = normalize(oriented.tangent, orthonormal_tangent(normal));
        const Vec3 bitangent = normalize(cross(normal, tangent));
        const ScaleShape shape = shape_for(sample, settings, guides, true);

        // The Cell stage owns the exact global Gap contract.  Preserve the
        // outer ring verbatim so local Density/Size cannot open an additional
        // visual gap.  Cell Growth develops only the interior rings.
        const std::vector<Vec3> source_boundary = cell.boundary;
        const Vec3 full_center = average_points(source_boundary);
        const double start_fill = clamp(
            shape.size / std::max(1.0e-8, cell.local_spacing),
            0.12,
            0.96);
        const double growth_fill = lerp_scalar(start_fill, 1.0, growth);
        std::vector<Vec3> interior_boundary;
        interior_boundary.reserve(source_boundary.size());
        for (const Vec3& point : source_boundary) {
            interior_boundary.push_back(add(
                full_center,
                mul(sub(point, full_center), growth_fill)));
        }
        const Vec3 center = full_center;
        const std::vector<Vec3> smoothed_boundary =
            smooth_cell_outline(interior_boundary, 5U);

        std::vector<Vec2> polygon;
        polygon.reserve(source_boundary.size());
        double maximum_lateral = 1.0e-8;
        double maximum_longitudinal = 1.0e-8;
        double back_extent = std::numeric_limits<double>::infinity();
        double front_extent = -std::numeric_limits<double>::infinity();
        for (const Vec3& point : source_boundary) {
            const Vec3 delta = sub(point, center);
            const Vec2 local{
                dot(delta, bitangent),
                dot(delta, tangent),
            };
            polygon.push_back(local);
            maximum_lateral = std::max(maximum_lateral, std::abs(local.x));
            maximum_longitudinal = std::max(
                maximum_longitudinal,
                std::abs(local.y));
            back_extent = std::min(back_extent, local.y);
            front_extent = std::max(front_extent, local.y);
        }
        const double longitudinal_span = std::max(
            1.0e-8, front_extent - back_extent);

        std::vector<std::uint32_t> ring_starts;
        ring_starts.reserve(static_cast<std::size_t>(divisions) + 1U);
        const std::uint32_t ring_size = static_cast<std::uint32_t>(source_boundary.size());
        for (std::uint32_t ring_index = 0U; ring_index <= divisions; ++ring_index) {
            ring_starts.push_back(static_cast<std::uint32_t>(result.vertices.size()));
            const double topology_weight = ring_index == 0U
                ? 0.0
                : static_cast<double>(ring_index) / static_cast<double>(divisions);
            const double edit_weight = cell_edit_weight(
                topology_weight,
                shape.round_sharp);
            const double collapse = 0.003 * topology_weight;

            for (std::uint32_t point_index = 0U; point_index < ring_size; ++point_index) {
                const Vec3& boundary_point = source_boundary[point_index];
                Vec3 point{};
                if (ring_index == 0U) {
                    point = add(boundary_point, mul(normal, settings.lift));
                } else {
                    const Vec3 developed_boundary = blend_point(
                        boundary_point,
                        interior_boundary[point_index],
                        topology_weight);
                    const Vec3 base = blend_point(
                        developed_boundary,
                        center,
                        collapse);
                    const Vec3 developed_smooth = blend_point(
                        boundary_point,
                        smoothed_boundary[point_index],
                        topology_weight);
                    const Vec3 smooth_target = blend_point(
                        developed_smooth,
                        center,
                        collapse);
                    const double sharp_amount = clamp(
                        0.5 + 0.5 * shape.round_sharp,
                        0.0,
                        1.0);
                    const double round_smooth =
                        (1.0 - sharp_amount) * topology_weight * 0.65;
                    const double smooth_amount = clamp(
                        shape.smooth + (1.0 - shape.smooth) * round_smooth,
                        0.0,
                        1.0);
                    const Vec3 deformed = blend_point(
                        base,
                        smooth_target,
                        smooth_amount);
                    const Vec3 local = sub(deformed, center);
                    double lateral = dot(local, bitangent);
                    double longitudinal = dot(local, tangent);
                    const double surface_height = dot(local, normal);

                    const double planar_radius = std::hypot(lateral, longitudinal);
                    if (planar_radius > 1.0e-12) {
                        const double expanded_radius = std::max(
                            cell.local_spacing * 0.002,
                            planar_radius + shape.expand * shape.size * 0.22 * edit_weight);
                        const double radius_scale = expanded_radius / planar_radius;
                        lateral *= radius_scale;
                        longitudinal *= radius_scale;
                    }

                    const double inset_scale = std::max(0.02, 1.0 - shape.inset);
                    const double width_scale = clamp(
                        shape.width / std::max(1.0e-8, shape.size),
                        0.15,
                        4.0);
                    double length_scale = clamp(
                        shape.scale_length /
                            std::max(
                                1.0e-8,
                                shape.size * kFixedScaleAspect),
                        0.15,
                        4.0);
                    const double target_lateral = lateral * inset_scale * width_scale;
                    const double target_longitudinal =
                        longitudinal * inset_scale * length_scale;
                    lateral = lerp_scalar(lateral, target_lateral, edit_weight);
                    longitudinal = lerp_scalar(
                        longitudinal,
                        target_longitudinal,
                        edit_weight);

                    const double source_longitudinal = polygon[point_index].y;
                    const double front_coordinate = clamp(
                        (source_longitudinal - back_extent) / longitudinal_span,
                        0.0,
                        1.0);
                    const double tip_coordinate = clamp(
                        (front_coordinate - 0.42) / 0.58,
                        0.0,
                        1.0);
                    const double tip_mask = tip_coordinate * tip_coordinate *
                        (3.0 - 2.0 * tip_coordinate) * edit_weight;
                    longitudinal += shape.forward_offset * shape.size * 0.30 * edit_weight;
                    longitudinal += shape.tip_offset * shape.size * 0.45 * tip_mask;
                    const double round_amount = shape.roundness * tip_mask;
                    const double sharpness_amount = shape.sharpness * tip_mask;
                    longitudinal +=
                        -round_amount * shape.size * 0.20 +
                        sharpness_amount * shape.size * 0.28;
                    lateral *=
                        1.0 + 0.18 * round_amount - 0.30 * sharpness_amount;
                    const Vec2 clamped_local = clamp_inside_cell(
                        lateral,
                        longitudinal,
                        polygon);
                    lateral = clamped_local.x;
                    longitudinal = clamped_local.y;

                    const double curve_weight = 0.20 + 0.80 * clamp(
                        0.5 + 0.5 * longitudinal / maximum_longitudinal,
                        0.0,
                        1.0);
                    const double normal_height =
                        settings.lift +
                        shape.normal_offset * edit_weight +
                        shape.curvature * shape.size * curve_weight * edit_weight;
                    point = add(
                        add(
                            add(center, mul(bitangent, lateral)),
                            mul(tangent, longitudinal)),
                        mul(normal, surface_height + normal_height));
                }

                if (options.include_uvs) {
                    const Vec3 local_uv = sub(point, center);
                    result.uvs.push_back({
                        clamp(
                            0.5 + 0.48 * dot(local_uv, bitangent) / maximum_lateral,
                            0.0,
                            1.0),
                        clamp(
                            0.5 + 0.48 * dot(local_uv, tangent) / maximum_longitudinal,
                            0.0,
                            1.0),
                    });
                }
                result.vertices.push_back(point);
                if (options.include_colors) {
                    result.colors.push_back(shape.color);
                }
            }
        }

        double center_lateral = 0.0;
        double center_longitudinal =
            shape.forward_offset * shape.size * 0.28 +
            shape.tip_offset * shape.size * 0.10;
        const Vec2 clamped_center = clamp_inside_cell(
            center_lateral,
            center_longitudinal,
            polygon);
        center_lateral = clamped_center.x;
        center_longitudinal = clamped_center.y;
        Vec3 center_point = add(
            add(center, mul(bitangent, center_lateral)),
            mul(tangent, center_longitudinal));
        center_point = add(
            center_point,
            mul(
                normal,
                settings.lift + shape.normal_offset +
                    shape.curvature * shape.size *
                        (0.78 + 0.12 * shape.roundness)));
        const std::uint32_t center_index =
            static_cast<std::uint32_t>(result.vertices.size());
        result.vertices.push_back(center_point);
        if (options.include_uvs) {
            result.uvs.push_back({0.5, 0.5});
        }
        if (options.include_colors) {
            result.colors.push_back(shape.color);
        }

        for (std::uint32_t ring_index = 0U; ring_index < divisions; ++ring_index) {
            const std::uint32_t outer_start = ring_starts[ring_index];
            const std::uint32_t inner_start = ring_starts[ring_index + 1U];
            for (std::uint32_t point_index = 0U; point_index < ring_size; ++point_index) {
                const std::uint32_t next_index = (point_index + 1U) % ring_size;
                append_face(
                    result,
                    std::array<std::uint32_t, 4>{
                        outer_start + point_index,
                        inner_start + point_index,
                        inner_start + next_index,
                        outer_start + next_index,
                    },
                    options);
            }
        }
        const std::uint32_t final_ring = ring_starts.back();
        for (std::uint32_t point_index = 0U; point_index < ring_size; ++point_index) {
            // Cell boundaries are clockwise when viewed along the sample
            // normal. The ring quads already account for that convention;
            // use next -> current for the center fan as well.
            append_face(
                result,
                triangle_toward_normal(
                    result.vertices,
                    center_index,
                    final_ring + ((point_index + 1U) % ring_size),
                    final_ring + point_index,
                    normal),
                options);
        }
        if (options.include_scale_type_ids) {
            result.scale_type_ids.push_back(shape.type_id);
        }
        append_cell_identity(
            result,
            sample,
            global_scale_indices[scale_index],
            cell_boundary_signature(source_boundary),
            options);
        ++result.scale_count;
    }
    return result;
}

GeneratedMesh merge_generated_mesh_chunks(
    std::vector<GeneratedMesh>& chunks,
    const GenerationOptions& options) {
    GeneratedMesh result;
    std::size_t total_vertices = 0U;
    std::size_t total_faces = 0U;
    std::size_t total_face_vertices = 0U;
    std::size_t total_uvs = 0U;
    std::size_t total_colors = 0U;
    std::size_t total_type_ids = 0U;
    std::size_t total_cell_ids = 0U;
    std::size_t total_metadata = 0U;
    for (const GeneratedMesh& chunk : chunks) {
        total_vertices += chunk.vertices.size();
        total_faces += chunk.face_count();
        total_face_vertices += chunk.face_vertex_count();
        total_uvs += chunk.uvs.size();
        total_colors += chunk.colors.size();
        total_type_ids += chunk.scale_type_ids.size();
        total_cell_ids += chunk.cell_ids.size();
        total_metadata += chunk.cell_metadata.size();
    }
    result.vertices.reserve(total_vertices);
    initialize_topology(
        result,
        options,
        total_faces,
        total_face_vertices);
    if (options.include_uvs) {
        result.uvs.reserve(total_uvs);
    }
    if (options.include_colors) {
        result.colors.reserve(total_colors);
    }
    if (options.include_scale_type_ids) {
        result.scale_type_ids.reserve(total_type_ids);
    }
    if (options.include_cell_ids) {
        result.cell_ids.reserve(total_cell_ids);
    }
    result.cell_metadata.reserve(total_metadata);

    for (GeneratedMesh& chunk : chunks) {
        const std::uint32_t vertex_base = static_cast<std::uint32_t>(
            result.vertices.size());
        result.vertices.insert(
            result.vertices.end(),
            std::make_move_iterator(chunk.vertices.begin()),
            std::make_move_iterator(chunk.vertices.end()));

        if (options.materialize_faces) {
            for (const std::vector<std::uint32_t>& face : chunk.faces) {
                std::vector<std::uint32_t> adjusted;
                adjusted.reserve(face.size());
                for (const std::uint32_t index : face) {
                    adjusted.push_back(vertex_base + index);
                }
                result.faces.push_back(std::move(adjusted));
            }
        }
        if (options.include_flat_topology && !chunk.face_offsets.empty()) {
            const std::uint32_t face_vertex_base = static_cast<std::uint32_t>(
                result.face_vertices.size());
            for (const std::uint32_t index : chunk.face_vertices) {
                result.face_vertices.push_back(vertex_base + index);
            }
            for (std::size_t offset_index = 1U;
                 offset_index < chunk.face_offsets.size();
                 ++offset_index) {
                result.face_offsets.push_back(
                    face_vertex_base + chunk.face_offsets[offset_index]);
            }
        }

        result.uvs.insert(
            result.uvs.end(),
            std::make_move_iterator(chunk.uvs.begin()),
            std::make_move_iterator(chunk.uvs.end()));
        result.colors.insert(
            result.colors.end(),
            std::make_move_iterator(chunk.colors.begin()),
            std::make_move_iterator(chunk.colors.end()));
        result.scale_type_ids.insert(
            result.scale_type_ids.end(),
            chunk.scale_type_ids.begin(),
            chunk.scale_type_ids.end());
        result.cell_ids.insert(
            result.cell_ids.end(),
            chunk.cell_ids.begin(),
            chunk.cell_ids.end());
        result.cell_metadata.insert(
            result.cell_metadata.end(),
            chunk.cell_metadata.begin(),
            chunk.cell_metadata.end());
        result.scale_count += chunk.scale_count;
    }
    return result;
}

GeneratedMesh build_cell_mesh_impl(
    const std::vector<OrientedSample>& oriented_samples,
    const std::vector<CellData>& cells,
    const Settings& settings,
    const PreparedGuides& guides,
    const GenerationOptions& options,
    std::uint32_t* used_workers = nullptr) {
    if (used_workers != nullptr) {
        *used_workers = 1U;
    }
    const std::size_t available_count = std::min(
        oriented_samples.size(),
        cells.size());
    if (available_count == 0U) {
        return {};
    }

    std::vector<std::uint32_t> global_scale_indices(available_count, 0U);
    std::uint32_t next_scale_index = 0U;
    for (std::size_t index = 0U; index < available_count; ++index) {
        global_scale_indices[index] = next_scale_index;
        if (cells[index].boundary.size() >= 3U) {
            ++next_scale_index;
        }
    }

    const std::uint32_t worker_count = parallel_worker_count(
        available_count,
        256U);
    if (worker_count <= 1U) {
        return build_cell_mesh_range(
            oriented_samples,
            cells,
            settings,
            guides,
            options,
            0U,
            available_count,
            global_scale_indices);
    }

    std::vector<GeneratedMesh> chunks(worker_count);
    const std::uint32_t actual_workers = parallel_for_chunks(
        available_count,
        256U,
        [&](std::size_t begin, std::size_t end, std::uint32_t worker_index) {
            chunks[worker_index] = build_cell_mesh_range(
                oriented_samples,
                cells,
                settings,
                guides,
                options,
                begin,
                end,
                global_scale_indices);
        });
    if (used_workers != nullptr) {
        *used_workers = actual_workers;
    }
    return merge_generated_mesh_chunks(chunks, options);
}

std::vector<std::pair<std::string, std::uint32_t>> type_counts(
    const GeneratedMesh& mesh,
    const Settings& settings) {
    std::unordered_map<std::string, std::uint32_t> counts;
    for (const std::uint32_t index : mesh.scale_type_ids) {
        const std::string name = index < settings.scale_types.size()
                                     ? settings.scale_types[index].name
                                     : std::string("Type ") + std::to_string(index);
        ++counts[name];
    }
    std::vector<std::pair<std::string, std::uint32_t>> result(counts.begin(), counts.end());
    std::sort(result.begin(), result.end());
    return result;
}

DistributionResult distribute_impl(
    const Mesh& mesh,
    const Settings& settings,
    PreviewMode mode,
    const PreparedGuides& guides,
    std::uint32_t* used_workers = nullptr) {
    validate_mesh(mesh);
    const std::uint32_t count = std::max<std::uint32_t>(
        1U,
        effective_count(settings, mode));
    auto [samples, report] = sample_surface(
        mesh,
        settings,
        count,
        mode,
        guides,
        used_workers);
    const auto active_count = std::count_if(
        settings.scale_types.begin(),
        settings.scale_types.end(),
        [](const ScaleType& type) {
            return type.enabled;
        });
    report.active_scale_type_count = static_cast<std::uint32_t>(
        std::max<std::ptrdiff_t>(1, active_count));
    return {std::move(samples), std::move(report)};
}

OrientationResult orient_samples_impl(
    const std::vector<Sample>& samples,
    const Settings& settings,
    PreviewMode mode,
    const PreparedGuides& guides,
    GenerationReport report,
    std::uint32_t* used_workers = nullptr,
    GenerationProfile* profile = nullptr) {
    double spacing = report.final_spacing;
    if (!(spacing > 0.0)) {
        spacing = report.initial_spacing;
    }
    if (!(spacing > 0.0)) {
        for (const Sample& sample : samples) {
            spacing = std::max(spacing, sample.local_spacing);
        }
    }
    std::vector<OrientedSample> oriented = orientation_field(
        samples,
        settings,
        mode,
        guides,
        spacing,
        used_workers,
        profile);
    report.direction_guide_count = guide_count(guides, false);
    report.direction_relax_iterations = effective_direction_relax_iterations(
        settings,
        mode);
    return {std::move(oriented), std::move(report)};
}

struct CacheKey {
    std::uint64_t first{1469598103934665603ULL};
    std::uint64_t second{1099511628211ULL};

    bool operator==(const CacheKey& other) const noexcept {
        return first == other.first && second == other.second;
    }
};

class CacheHasher {
public:
    void bytes(const void* data, std::size_t size) {
        const auto* values = static_cast<const unsigned char*>(data);
        for (std::size_t index = 0U; index < size; ++index) {
            first_ ^= static_cast<std::uint64_t>(values[index]);
            first_ *= 1099511628211ULL;
            second_ += static_cast<std::uint64_t>(values[index]) +
                0x9e3779b97f4a7c15ULL + (second_ << 6U) + (second_ >> 2U);
            second_ ^= second_ >> 29U;
            second_ *= 0xbf58476d1ce4e5b9ULL;
        }
    }

    template <typename T>
    void scalar(const T& value) {
        bytes(&value, sizeof(T));
    }

    void boolean(bool value) {
        const std::uint8_t encoded = value ? 1U : 0U;
        scalar(encoded);
    }

    void string(const std::string& value) {
        const std::uint64_t size = static_cast<std::uint64_t>(value.size());
        scalar(size);
        bytes(value.data(), value.size());
    }

    void vec3(const Vec3& value) {
        scalar(value.x);
        scalar(value.y);
        scalar(value.z);
    }

    void key(const CacheKey& value) {
        scalar(value.first);
        scalar(value.second);
    }

    [[nodiscard]] CacheKey finish() const noexcept {
        return {first_, second_};
    }

private:
    std::uint64_t first_{1469598103934665603ULL};
    std::uint64_t second_{0x6a09e667f3bcc909ULL};
};

void hash_mesh(CacheHasher& hasher, const Mesh& mesh) {
    hasher.scalar(static_cast<std::uint64_t>(mesh.vertices.size()));
    for (const Vec3& point : mesh.vertices) {
        hasher.vec3(point);
    }
    hasher.scalar(static_cast<std::uint64_t>(mesh.triangles.size()));
    for (const Triangle& triangle : mesh.triangles) {
        hasher.scalar(triangle.a);
        hasher.scalar(triangle.b);
        hasher.scalar(triangle.c);
    }
}

void hash_guide_geometry(CacheHasher& hasher, const Guide& guide) {
    hasher.string(guide.id);
    hasher.scalar(static_cast<std::uint32_t>(guide.kind));
    hasher.boolean(guide.enabled);
    hasher.boolean(guide.closed);
    hasher.scalar(static_cast<std::uint64_t>(guide.points.size()));
    for (const Vec3& point : guide.points) {
        hasher.vec3(point);
    }
}

void hash_distribution_guide(CacheHasher& hasher, const Guide& guide) {
    hash_guide_geometry(hasher, guide);
    const bool density = guide_uses_density(guide);
    const bool size = guide_uses_size(guide);
    const bool mask = guide_uses_mask(guide);
    const bool curve_centerline =
        guide.points.size() > 1U &&
        guide_uses_direction(guide) &&
        guide.strength > kEpsilon;
    hasher.boolean(density);
    hasher.boolean(size);
    hasher.boolean(mask);
    hasher.boolean(curve_centerline);
    if (density || size) {
        hasher.scalar(guide.radius);
        hasher.scalar(guide.falloff);
        hasher.scalar(guide.density_multiplier);
        hasher.scalar(guide.size_multiplier);
    }
    if (mask) {
        hasher.scalar(guide.radius);
        hasher.scalar(guide.falloff);
    }
    if (curve_centerline) {
        // Positive Direction Strength enables center candidates, but its
        // magnitude affects Orientation only.
        hasher.boolean(true);
    }
}

void hash_orientation_guide(CacheHasher& hasher, const Guide& guide) {
    hash_guide_geometry(hasher, guide);
    hasher.vec3(guide.direction);
    hasher.scalar(guide.radius);
    hasher.scalar(guide.falloff);
    hasher.scalar(guide.strength);
    hasher.scalar(guide.angle_degrees);
    hasher.boolean(guide_uses_direction(guide));
}


CacheKey distribution_cache_key(
    const Mesh& mesh,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides) {
    CacheHasher hasher;
    hash_mesh(hasher, mesh);
    hasher.scalar(static_cast<std::uint32_t>(mode));
    hasher.scalar(effective_count(settings, mode));
    hasher.scalar(settings.seed);
    hasher.scalar(settings.spacing_factor);
    hasher.scalar(effective_relax_iterations(settings, mode));
    hasher.scalar(settings.relax_strength);
    std::uint64_t relevant_count = 0U;
    for (const Guide& guide : guides) {
        const bool curve = guide.points.size() > 1U;
        if (!guide.enabled ||
            !(guide_uses_density(guide) || guide_uses_size(guide) ||
              guide_uses_mask(guide) ||
              (curve && guide_uses_direction(guide) &&
               guide.strength > kEpsilon))) {
            continue;
        }
        ++relevant_count;
        hash_distribution_guide(hasher, guide);
    }
    hasher.scalar(relevant_count);
    return hasher.finish();
}

CacheKey orientation_cache_key(
    const CacheKey& distribution,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides) {
    CacheHasher hasher;
    hasher.key(distribution);
    hasher.scalar(settings.direction_degrees);
    hasher.scalar(settings.random_rotation_degrees);
    hasher.scalar(effective_direction_relax_iterations(settings, mode));
    hasher.scalar(settings.direction_relax_strength);
    std::uint64_t relevant_count = 0U;
    for (const Guide& guide : guides) {
        if (!guide.enabled || !guide_uses_direction(guide)) {
            continue;
        }
        ++relevant_count;
        hash_orientation_guide(hasher, guide);
    }
    hasher.scalar(relevant_count);
    return hasher.finish();
}

CacheKey cell_cache_key(
    const CacheKey& distribution,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<SymmetryPlane>& symmetry_planes) {
    CacheHasher hasher;
    // Cell partitioning depends on distributed sample positions, normals,
    // spacing, mask geometry and Cell settings. Direction Pair was retired in
    // 0.8.9, so neither the oriented tangent nor Direction Guide influence can
    // change a Cell boundary. Key Cells from Distribution directly to preserve
    // the exact partition while reusing it for direction-only edits.
    hasher.key(distribution);
    hasher.scalar(static_cast<std::uint32_t>(settings.cell_mode));
    hasher.scalar(effective_cell_resolution(settings, mode));
    hasher.scalar(settings.cell_gap);
    hasher.scalar(settings.cell_collision_margin);
    hasher.scalar(settings.cell_radius_multiplier);
    hasher.scalar(effective_cell_projection_rings(settings, mode));
    hasher.boolean(settings.cell_project_to_surface);
    // Mirror planes no longer alter Cell partitioning. Keep the argument for
    // ABI/source compatibility, but exclude it from the cache key.
    (void)symmetry_planes;
    return hasher.finish();
}

std::uint32_t active_scale_type_count(const Settings& settings) {
    const auto count = std::count_if(
        settings.scale_types.begin(),
        settings.scale_types.end(),
        [](const ScaleType& type) {
            return type.enabled;
        });
    return static_cast<std::uint32_t>(
        std::max<std::ptrdiff_t>(1, count));
}

std::uint32_t configured_stage_cache_capacity() {
    constexpr std::uint32_t kDefaultCapacity = 2U;
    const char* encoded = std::getenv("BIFROST_SCALES_STAGE_CACHE_ENTRIES");
    if (encoded == nullptr || encoded[0] == '\0') {
        return kDefaultCapacity;
    }
    char* end = nullptr;
    const unsigned long parsed = std::strtoul(encoded, &end, 10);
    if (end == encoded || *end != '\0') {
        return kDefaultCapacity;
    }
    return static_cast<std::uint32_t>(std::clamp<unsigned long>(
        parsed,
        1UL,
        8UL));
}

template <typename Value>
struct SharedStageEntry {
    CacheKey key{};
    std::shared_ptr<const Value> value;
    std::uint64_t access_stamp{0U};
};

class ProcessStageCache {
public:
    std::shared_ptr<const DistributionResult> find_distribution(
        const CacheKey& key) {
        std::lock_guard<std::mutex> lock(mutex_);
        return find_locked(distributions_, key);
    }

    std::shared_ptr<const OrientationResult> find_orientation(
        const CacheKey& key) {
        std::lock_guard<std::mutex> lock(mutex_);
        return find_locked(orientations_, key);
    }

    std::shared_ptr<const CellResult> find_cells(const CacheKey& key) {
        std::lock_guard<std::mutex> lock(mutex_);
        return find_locked(cells_, key);
    }

    bool insert_distribution(
        const CacheKey& key,
        std::shared_ptr<const DistributionResult> value) {
        std::lock_guard<std::mutex> lock(mutex_);
        return insert_locked(distributions_, key, std::move(value));
    }

    bool insert_orientation(
        const CacheKey& key,
        std::shared_ptr<const OrientationResult> value) {
        std::lock_guard<std::mutex> lock(mutex_);
        return insert_locked(orientations_, key, std::move(value));
    }

    bool insert_cells(
        const CacheKey& key,
        std::shared_ptr<const CellResult> value) {
        std::lock_guard<std::mutex> lock(mutex_);
        return insert_locked(cells_, key, std::move(value));
    }

    void clear() {
        std::lock_guard<std::mutex> lock(mutex_);
        distributions_.clear();
        orientations_.clear();
        cells_.clear();
        access_clock_ = 0U;
    }

    [[nodiscard]] std::uint32_t capacity() const {
        return configured_stage_cache_capacity();
    }

private:
    template <typename Value>
    std::shared_ptr<const Value> find_locked(
        std::vector<SharedStageEntry<Value>>& entries,
        const CacheKey& key) {
        const auto found = std::find_if(
            entries.begin(),
            entries.end(),
            [&](const SharedStageEntry<Value>& entry) {
                return entry.key == key;
            });
        if (found == entries.end()) {
            return {};
        }
        found->access_stamp = ++access_clock_;
        return found->value;
    }

    template <typename Value>
    bool insert_locked(
        std::vector<SharedStageEntry<Value>>& entries,
        const CacheKey& key,
        std::shared_ptr<const Value> value) {
        const auto found = std::find_if(
            entries.begin(),
            entries.end(),
            [&](const SharedStageEntry<Value>& entry) {
                return entry.key == key;
            });
        if (found != entries.end()) {
            found->value = std::move(value);
            found->access_stamp = ++access_clock_;
            return false;
        }
        const std::size_t capacity_value = configured_stage_cache_capacity();
        bool evicted = false;
        if (entries.size() >= capacity_value) {
            const auto oldest = std::min_element(
                entries.begin(),
                entries.end(),
                [](const SharedStageEntry<Value>& left,
                   const SharedStageEntry<Value>& right) {
                    return left.access_stamp < right.access_stamp;
                });
            entries.erase(oldest);
            evicted = true;
        }
        entries.push_back({key, std::move(value), ++access_clock_});
        return evicted;
    }

    mutable std::mutex mutex_;
    std::uint64_t access_clock_{0U};
    std::vector<SharedStageEntry<DistributionResult>> distributions_;
    std::vector<SharedStageEntry<OrientationResult>> orientations_;
    std::vector<SharedStageEntry<CellResult>> cells_;
};

ProcessStageCache& native_stage_cache() {
    static ProcessStageCache cache;
    return cache;
}

}  // namespace

void clear_native_stage_cache() {
    native_stage_cache().clear();
}

GenerationResult generate(
    const Mesh& mesh,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides,
    const GenerationOptions& options) {
    return generate(mesh, settings, mode, guides, {}, options);
}

GenerationResult generate(
    const Mesh& mesh,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides,
    const std::vector<SymmetryPlane>& symmetry_planes,
    const GenerationOptions& options) {
    using Clock = std::chrono::steady_clock;
    const auto total_started = Clock::now();
    validate_mesh(mesh);
    GenerationProfile profile;
    PreparedGuides prepared_guides = prepare_guides(guides);
    prepare_surface_guide_fields(mesh, prepared_guides);
    ProcessStageCache& cache = native_stage_cache();
    profile.stage_cache_capacity = cache.capacity();

    const CacheKey distribution_key = distribution_cache_key(
        mesh,
        settings,
        mode,
        guides);
    const auto distribution_started = Clock::now();
    std::shared_ptr<const DistributionResult> distribution =
        cache.find_distribution(distribution_key);
    if (distribution) {
        profile.distribution_cache_hit = true;
    } else {
        distribution = std::make_shared<const DistributionResult>(
            distribute_impl(
                mesh,
                settings,
                mode,
                prepared_guides,
                &profile.distribution_worker_threads));
        profile.stage_cache_evictions += cache.insert_distribution(
            distribution_key,
            distribution) ? 1U : 0U;
    }
    profile.distribution_ms = std::chrono::duration<double, std::milli>(
        Clock::now() - distribution_started).count();

    const CacheKey orientation_key = orientation_cache_key(
        distribution_key,
        settings,
        mode,
        guides);
    const auto orientation_started = Clock::now();
    std::shared_ptr<const OrientationResult> orientation =
        cache.find_orientation(orientation_key);
    if (orientation) {
        profile.orientation_cache_hit = true;
    } else {
        GenerationReport distribution_report = distribution->report;
        distribution_report.active_scale_type_count =
            active_scale_type_count(settings);
        orientation = std::make_shared<const OrientationResult>(
            orient_samples_impl(
                distribution->samples,
                settings,
                mode,
                prepared_guides,
                std::move(distribution_report),
                &profile.orientation_worker_threads,
                &profile));
        profile.stage_cache_evictions += cache.insert_orientation(
            orientation_key,
            orientation) ? 1U : 0U;
        // Cells are keyed from Distribution, not Orientation. An orientation
        // miss no longer invalidates a still-exact Cell partition.
    }
    profile.orientation_ms = std::chrono::duration<double, std::milli>(
        Clock::now() - orientation_started).count();

    GeneratedMesh generated;
    GenerationReport report = orientation->report;
    report.active_scale_type_count = active_scale_type_count(settings);
    if (uses_cells(settings, mode)) {
        const CacheKey cells_key = cell_cache_key(
            distribution_key,
            settings,
            mode,
            symmetry_planes);
        const auto cells_started = Clock::now();
        std::shared_ptr<const CellResult> cells = cache.find_cells(cells_key);
        if (cells) {
            profile.cell_cache_hit = true;
        } else {
            cells = std::make_shared<const CellResult>(build_cells_impl(
                mesh,
                orientation->samples,
                settings,
                mode,
                prepared_guides,
                symmetry_planes,
                report,
                &profile.cell_worker_threads));
            profile.stage_cache_evictions += cache.insert_cells(
                cells_key,
                cells) ? 1U : 0U;
        }
        // A Cell cache hit may now cross an Orientation change. Keep the
        // cached geometric statistics, but refresh the Orientation-owned
        // report fields so diagnostics always describe the current payload.
        GenerationReport cell_report = cells->report;
        cell_report.active_scale_type_count = active_scale_type_count(settings);
        cell_report.direction_guide_count =
            orientation->report.direction_guide_count;
        cell_report.direction_relax_iterations =
            orientation->report.direction_relax_iterations;
        profile.cell_cache_reused_after_orientation_change =
            profile.cell_cache_hit && !profile.orientation_cache_hit;
        profile.cells_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - cells_started).count();

        const auto shape_started = Clock::now();
        generated = build_cell_mesh_impl(
            orientation->samples,
            cells->cells,
            settings,
            prepared_guides,
            options,
            &profile.shape_worker_threads);
        profile.shape_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - shape_started).count();
        report = std::move(cell_report);
    } else {
        const auto shape_started = Clock::now();
        generated = build_mesh_impl(
            orientation->samples,
            settings,
            mode,
            prepared_guides,
            options);
        profile.shape_worker_threads = 1U;
        profile.shape_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - shape_started).count();
        report.used_cells = false;
        report.cell_count = 0U;
        report.cell_resolution = 0U;
        report.cell_clipped_rays = 0U;
        report.cell_mean_neighbors = 0.0;
        report.paired_sample_count = 0U;
        report.partition_seed_count = 0U;
        report.boundary_clipped_rays = 0U;
        report.mask_clipped_rays = 0U;
        report.symmetry_stabilized_cells = 0U;
        report.symmetry_competitor_count = 0U;
        report.cell_shape_divisions = 0U;
    }
    if (options.include_scale_type_ids) {
        report.type_counts = type_counts(generated, settings);
    }
    profile.total_ms = std::chrono::duration<double, std::milli>(
        Clock::now() - total_started).count();
    return {std::move(generated), std::move(report), profile};
}

DistributionResult distribute(
    const Mesh& mesh,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides) {
    validate_mesh(mesh);
    PreparedGuides prepared_guides = prepare_guides(guides);
    prepare_surface_guide_fields(mesh, prepared_guides);
    return distribute_impl(mesh, settings, mode, prepared_guides);
}

OrientationResult orient_samples(
    const std::vector<Sample>& samples,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides,
    GenerationReport report) {
    const PreparedGuides prepared_guides = prepare_guides(guides);
    return orient_samples_impl(
        samples,
        settings,
        mode,
        prepared_guides,
        std::move(report));
}

CellResult build_cells(
    const Mesh& mesh,
    const std::vector<Sample>& samples,
    const Settings& settings,
    PreviewMode mode,
    GenerationReport report) {
    validate_mesh(mesh);
    std::vector<OrientedSample> oriented;
    oriented.reserve(samples.size());
    for (const Sample& sample : samples) {
        const Vec3 tangent = orthonormal_tangent(sample.normal);
        oriented.push_back({sample, tangent, tangent, 0.0});
    }
    const PreparedGuides prepared_guides;
    return build_cells_impl(
        mesh,
        oriented,
        settings,
        mode,
        prepared_guides,
        {},
        std::move(report));
}

CellResult build_cells(
    const Mesh& mesh,
    const std::vector<OrientedSample>& samples,
    const Settings& settings,
    PreviewMode mode,
    GenerationReport report) {
    validate_mesh(mesh);
    const PreparedGuides prepared_guides;
    return build_cells_impl(
        mesh,
        samples,
        settings,
        mode,
        prepared_guides,
        {},
        std::move(report));
}

CellResult build_cells(
    const Mesh& mesh,
    const std::vector<OrientedSample>& samples,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides,
    const std::vector<SymmetryPlane>& symmetry_planes,
    GenerationReport report) {
    validate_mesh(mesh);
    const PreparedGuides prepared_guides = prepare_guides(guides);
    return build_cells_impl(
        mesh,
        samples,
        settings,
        mode,
        prepared_guides,
        symmetry_planes,
        std::move(report));
}

GeneratedMesh shape_cells(
    const std::vector<OrientedSample>& samples,
    const std::vector<CellData>& cells,
    const Settings& settings,
    const std::vector<Guide>& guides,
    const GenerationOptions& options) {
    const PreparedGuides prepared_guides = prepare_guides(guides);
    return build_cell_mesh_impl(
        samples,
        cells,
        settings,
        prepared_guides,
        options);
}

GeneratedMesh shape_samples(
    const std::vector<OrientedSample>& samples,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides,
    const GenerationOptions& options) {
    const PreparedGuides prepared_guides = prepare_guides(guides);
    return build_mesh_impl(
        samples,
        settings,
        mode,
        prepared_guides,
        options);
}

GeneratedMesh shape_samples(
    const std::vector<Sample>& samples,
    const Settings& settings,
    PreviewMode mode) {
    const OrientationResult orientation = orient_samples(samples, settings, mode);
    return shape_samples(orientation.samples, settings, mode);
}

}  // namespace bifrost_scales
