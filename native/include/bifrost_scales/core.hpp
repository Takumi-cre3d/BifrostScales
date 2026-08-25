#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace bifrost_scales {

struct Vec2 {
    double x{0.0};
    double y{0.0};

    bool operator==(const Vec2& other) const noexcept {
        return x == other.x && y == other.y;
    }
    bool operator!=(const Vec2& other) const noexcept {
        return !(*this == other);
    }
};

struct Vec3 {
    double x{0.0};
    double y{0.0};
    double z{0.0};

    bool operator==(const Vec3& other) const noexcept {
        return x == other.x && y == other.y && z == other.z;
    }
    bool operator!=(const Vec3& other) const noexcept {
        return !(*this == other);
    }
};

struct Color4 {
    double r{1.0};
    double g{1.0};
    double b{1.0};
    double a{1.0};

    bool operator==(const Color4& other) const noexcept {
        return r == other.r && g == other.g && b == other.b && a == other.a;
    }
    bool operator!=(const Color4& other) const noexcept {
        return !(*this == other);
    }
};

struct Triangle {
    std::uint32_t a{0};
    std::uint32_t b{0};
    std::uint32_t c{0};
};

struct Edge {
    std::uint32_t a{0};
    std::uint32_t b{0};

    bool operator==(const Edge& other) const noexcept {
        return a == other.a && b == other.b;
    }
    bool operator!=(const Edge& other) const noexcept {
        return !(*this == other);
    }
};

struct Mesh {
    std::vector<Vec3> vertices;
    std::vector<Triangle> triangles;
};

enum class PreviewMode {
    Interactive,
    Settled,
    Final,
};

enum class GeometryMode {
    Auto,
    Cards,
    Cells,
};

enum class GuideKind {
    DensityPoint,
    DensityCurve,
    DirectionPoint,
    DirectionCurve,
    FlowCurve,
};

struct Guide {
    std::string id;
    std::string group_id;
    GuideKind kind{GuideKind::DensityPoint};
    std::vector<Vec3> points;
    Vec3 direction{1.0, 0.0, 0.0};
    bool enabled{true};
    double radius{1.0};
    double falloff{1.0};
    double density_multiplier{1.75};
    double size_multiplier{1.0};
    double strength{1.0};
    double angle_degrees{0.0};
    bool closed{false};
    std::optional<bool> use_density;
    std::optional<bool> use_size;
    std::optional<bool> use_direction;
    std::optional<bool> use_mask;
};

struct SymmetryPlane {
    Vec3 origin{};
    Vec3 normal{1.0, 0.0, 0.0};
};

struct ScaleType {
    std::string id{"classic"};
    std::string name{"Classic"};
    bool enabled{true};
    double size_multiplier{1.0};
    double width_multiplier{1.0};
    double length_multiplier{1.0};
    double curvature_multiplier{1.0};
    double offset{0.0};
    double random_offset{0.0};
    double tip_offset{0.0};
    std::string guide_id;
    bool use_custom_color{false};
    Color4 color{0.34, 0.58, 0.82, 1.0};
};
struct Settings {
    std::uint32_t target_count{512};
    std::uint64_t seed{1};
    double spacing_factor{0.82};
    std::uint32_t relax_iterations{0};
    double relax_strength{0.45};

    double size{0.1};
    double lift{0.002};
    double curvature{0.22};
    double direction_degrees{0.0};
    std::uint32_t direction_relax_iterations{0};
    double direction_relax_strength{0.35};
    double random_size{0.12};
    double random_rotation_degrees{8.0};

    double inset{0.0};
    double squash{0.0};
    double expand{0.0};
    double tip_roundness{0.15};
    double tip_offset{0.0};
    double forward_offset{0.0};

    GeometryMode cell_mode{GeometryMode::Auto};
    double cell_growth{0.85};
    double cell_gap{0.06};
    double cell_collision_margin{0.02};
    double cell_radius_multiplier{1.65};
    std::uint32_t cell_shape_divisions{2};
    std::uint32_t cell_interactive_resolution{6};
    std::uint32_t cell_settled_resolution{10};
    std::uint32_t cell_projection_rings{2};
    bool cell_project_to_surface{true};

    Color4 color{0.34, 0.58, 0.82, 1.0};
    std::vector<ScaleType> scale_types;

    std::uint32_t interactive_budget{128};
    std::uint32_t settled_budget{512};
};

struct Sample {
    Vec3 position;
    Vec3 normal;
    std::uint32_t triangle_index{0};
    std::array<double, 3> barycentric{1.0, 0.0, 0.0};
    double random_size{0.5};
    double random_rotation{0.5};
    double random_type{0.5};
    double random_shape{0.5};
    double density_multiplier{1.0};
    double size_multiplier{1.0};
    double local_spacing{0.0};
    std::uint64_t stable_id{0};
};

struct OrientedSample {
    Sample sample;
    Vec3 tangent{1.0, 0.0, 0.0};
    Vec3 partition_tangent{1.0, 0.0, 0.0};
    double direction_influence{0.0};
};

struct CellData {
    std::uint32_t sample_index{0};
    std::vector<Vec3> boundary;
    Vec3 stable_tangent{1.0, 0.0, 0.0};
    Vec3 stable_bitangent{0.0, 0.0, 1.0};
    double local_spacing{0.0};
    std::uint32_t neighbor_count{0};
    std::uint32_t clipped_rays{0};
    double pair_influence{0.0};
};

struct CellMetadata {
    std::uint64_t cell_id{0};
    std::uint32_t scale_index{0};
    Vec3 position{};
    Vec3 normal{0.0, 1.0, 0.0};
    std::uint32_t triangle_index{0};
    std::array<double, 3> barycentric{1.0, 0.0, 0.0};
    std::uint64_t boundary_signature{0};
};

struct GeneratedMesh {
    std::vector<Vec3> vertices;
    std::vector<std::vector<std::uint32_t>> faces;
    // Native Preview can emit topology directly as flat Bifrost-compatible
    // buffers.  The legacy nested ``faces`` representation remains the
    // default for tests, parity dumps, and external C++ callers.
    std::vector<std::uint32_t> face_offsets;
    std::vector<std::uint32_t> face_vertices;
    std::vector<Vec2> uvs;
    std::vector<Color4> colors;
    std::vector<std::uint32_t> scale_type_ids;
    std::vector<std::uint64_t> cell_ids;
    std::vector<CellMetadata> cell_metadata;
    std::uint32_t scale_count{0};

    [[nodiscard]] std::size_t face_count() const noexcept {
        return face_offsets.empty() ? faces.size() : face_offsets.size() - 1U;
    }

    [[nodiscard]] std::size_t face_vertex_count() const noexcept {
        if (!face_offsets.empty()) {
            return face_vertices.size();
        }
        std::size_t count = 0U;
        for (const auto& face : faces) {
            count += face.size();
        }
        return count;
    }
};

struct GenerationOptions {
    // Reference/parity callers keep the complete mesh contract by default.
    // The Bifrost Preview operator disables auxiliary arrays that are not
    // connected by Static Graph v4 and requests flat topology instead.
    bool include_uvs{true};
    bool include_colors{true};
    bool include_scale_type_ids{true};
    bool materialize_faces{true};
    bool include_flat_topology{false};
    bool include_cell_ids{true};
    std::vector<std::uint32_t> cell_metadata_indices;
    std::vector<std::uint64_t> resolve_cell_ids;
};

struct GenerationProfile {
    double distribution_ms{0.0};
    double orientation_ms{0.0};
    double cells_ms{0.0};
    double cell_setup_ms{0.0};
    double cell_neighbors_ms{0.0};
    double cell_boundaries_ms{0.0};
    double cell_projection_ms{0.0};
    double shape_ms{0.0};
    double total_ms{0.0};
    bool distribution_cache_hit{false};
    bool orientation_cache_hit{false};
    bool cell_cache_hit{false};
    bool cell_cache_reused_after_orientation_change{false};
    std::string stage_cache_scope{"process-shared-bounded"};
    std::uint32_t stage_cache_capacity{0};
    std::uint32_t stage_cache_evictions{0};
    bool gpu_compute_requested{false};
    bool gpu_compute_available{false};
    bool gpu_compute_used{false};
    std::string gpu_compute_backend{"cpu-multicore"};
    std::string gpu_device;
    std::string gpu_fallback_reason;
    double gpu_upload_ms{0.0};
    double gpu_kernel_ms{0.0};
    double gpu_readback_ms{0.0};
    std::uint32_t gpu_sample_count{0};
    std::uint32_t distribution_worker_threads{0};
    std::uint32_t orientation_worker_threads{0};
    std::uint32_t cell_worker_threads{0};
    std::uint32_t shape_worker_threads{0};
};

struct GenerationReport {
    std::uint32_t requested_count{0};
    std::uint32_t accepted_count{0};
    std::uint64_t attempts{0};
    double surface_area{0.0};
    double initial_spacing{0.0};
    double final_spacing{0.0};
    std::uint32_t density_guide_count{0};
    std::uint32_t direction_guide_count{0};
    std::uint32_t active_scale_type_count{1};
    std::uint32_t relax_iterations{0};
    std::uint32_t direction_relax_iterations{0};
    std::uint32_t moved_samples{0};
    bool used_cells{false};
    std::uint32_t cell_count{0};
    std::uint32_t cell_resolution{0};
    std::uint32_t cell_clipped_rays{0};
    double cell_mean_neighbors{0.0};
    std::uint32_t paired_sample_count{0};
    std::uint32_t partition_seed_count{0};
    std::uint32_t open_boundary_edge_count{0};
    std::uint32_t boundary_anchor_count{0};
    bool boundary_density_adapted{false};
    std::uint32_t masked_candidate_count{0};
    std::uint32_t mask_guide_count{0};
    std::uint32_t boundary_clipped_rays{0};
    std::uint32_t mask_clipped_rays{0};
    std::uint32_t symmetry_stabilized_cells{0};
    std::uint32_t symmetry_competitor_count{0};
    std::uint32_t cell_shape_divisions{0};
    std::vector<std::pair<std::string, std::uint32_t>> type_counts;
};

struct DistributionResult {
    std::vector<Sample> samples;
    GenerationReport report;
};

struct OrientationResult {
    std::vector<OrientedSample> samples;
    GenerationReport report;
};

struct CellResult {
    std::vector<CellData> cells;
    GenerationReport report;
};

struct GenerationResult {
    GeneratedMesh mesh;
    GenerationReport report;
    GenerationProfile profile;
};

DistributionResult distribute(
    const Mesh& mesh,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides = {});

OrientationResult orient_samples(
    const std::vector<Sample>& samples,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides = {},
    GenerationReport report = {});

CellResult build_cells(
    const Mesh& mesh,
    const std::vector<Sample>& samples,
    const Settings& settings,
    PreviewMode mode,
    GenerationReport report = {});

CellResult build_cells(
    const Mesh& mesh,
    const std::vector<OrientedSample>& samples,
    const Settings& settings,
    PreviewMode mode,
    GenerationReport report = {});

CellResult build_cells(
    const Mesh& mesh,
    const std::vector<OrientedSample>& samples,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides,
    const std::vector<SymmetryPlane>& symmetry_planes,
    GenerationReport report = {});

GeneratedMesh shape_cells(
    const std::vector<OrientedSample>& samples,
    const std::vector<CellData>& cells,
    const Settings& settings,
    const std::vector<Guide>& guides = {},
    const GenerationOptions& options = {});

GeneratedMesh shape_samples(
    const std::vector<OrientedSample>& samples,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides = {},
    const GenerationOptions& options = {});

// Compatibility overload for 0.2 callers. It performs orientation with no guides.
GeneratedMesh shape_samples(
    const std::vector<Sample>& samples,
    const Settings& settings,
    PreviewMode mode);

GenerationResult generate(
    const Mesh& mesh,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides = {},
    const GenerationOptions& options = {});


GenerationResult generate(
    const Mesh& mesh,
    const Settings& settings,
    PreviewMode mode,
    const std::vector<Guide>& guides,
    const std::vector<SymmetryPlane>& symmetry_planes,
    const GenerationOptions& options = {});

// Clear the current worker thread's bounded stage cache. Benchmark and host
// diagnostics use this to distinguish cold full-pipeline work from exact warm
// stage reuse; production callers normally leave the cache intact.
void clear_native_stage_cache();

}  // namespace bifrost_scales
