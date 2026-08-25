#include "bifrost_scales/core.hpp"
#include "bifrost_scales/payload.hpp"
#include "bifrost_scales/preview_distribution.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <numeric>
#include <set>
#include <thread>
#include <vector>

using bifrost_scales::Guide;
using bifrost_scales::CellData;
using bifrost_scales::GeneratedMesh;
using bifrost_scales::GenerationResult;
using bifrost_scales::GenerationReport;
using bifrost_scales::GeometryMode;
using bifrost_scales::GuideKind;
using bifrost_scales::Mesh;
using bifrost_scales::OrientedSample;
using bifrost_scales::PreviewMode;
using bifrost_scales::ScaleType;
using bifrost_scales::Sample;
using bifrost_scales::Settings;
using bifrost_scales::Triangle;
using bifrost_scales::Vec3;

namespace {

void check(bool condition, const char* expression, int line) {
    if (!condition) {
        throw std::runtime_error(
            std::string("check failed at line ") + std::to_string(line) +
            ": " + expression);
    }
}

#define CHECK(expression) check(static_cast<bool>(expression), #expression, __LINE__)


void set_cpu_thread_override(const char* value) {
#ifdef _WIN32
    _putenv_s("BIFROST_SCALES_CPU_THREADS", value);
#else
    setenv("BIFROST_SCALES_CPU_THREADS", value, 1);
#endif
}

void set_gpu_override(const char* value) {
#ifdef _WIN32
    _putenv_s("BIFROST_SCALES_GPU", value);
#else
    setenv("BIFROST_SCALES_GPU", value, 1);
#endif
}

bool cell_metadata_equal(
    const bifrost_scales::CellMetadata& left,
    const bifrost_scales::CellMetadata& right) {
    return left.cell_id == right.cell_id &&
           left.scale_index == right.scale_index &&
           left.position == right.position &&
           left.normal == right.normal &&
           left.triangle_index == right.triangle_index &&
           left.barycentric == right.barycentric &&
           left.boundary_signature == right.boundary_signature;
}

Mesh plane_mesh() {
    return {
        {
            Vec3{-2.0, 0.0, -2.0},
            Vec3{2.0, 0.0, -2.0},
            Vec3{2.0, 0.0, 2.0},
            Vec3{-2.0, 0.0, 2.0},
        },
        {Triangle{0, 1, 2}, Triangle{0, 2, 3}},
    };
}

Mesh close_disconnected_planes_mesh() {
    return {
        {
            Vec3{-2.0, 0.0, -2.0},
            Vec3{2.0, 0.0, -2.0},
            Vec3{2.0, 0.0, 2.0},
            Vec3{-2.0, 0.0, 2.0},
            Vec3{-2.0, 0.08, -2.0},
            Vec3{2.0, 0.08, -2.0},
            Vec3{2.0, 0.08, 2.0},
            Vec3{-2.0, 0.08, 2.0},
        },
        {
            Triangle{0, 1, 2},
            Triangle{0, 2, 3},
            Triangle{4, 5, 6},
            Triangle{4, 6, 7},
        },
    };
}

Mesh fan_mesh(std::uint32_t count = 12U) {
    Mesh mesh;
    mesh.vertices.push_back({0.0, 0.0, 0.0});
    const double pi = std::acos(-1.0);
    for (std::uint32_t index = 0U; index < count; ++index) {
        const double angle = 2.0 * pi * static_cast<double>(index) /
            static_cast<double>(count);
        mesh.vertices.push_back({
            2.0 * std::cos(angle),
            0.0,
            2.0 * std::sin(angle),
        });
    }
    for (std::uint32_t index = 0U; index < count; ++index) {
        mesh.triangles.push_back({
            0U,
            1U + index,
            1U + ((index + 1U) % count),
        });
    }
    return mesh;
}

std::uint32_t counted_types(
    const std::vector<std::pair<std::string, std::uint32_t>>& counts) {
    return std::accumulate(
        counts.begin(),
        counts.end(),
        0U,
        [](std::uint32_t total, const auto& item) {
            return total + item.second;
        });
}

double face_normal_dot(
    const GeneratedMesh& mesh,
    const std::vector<std::uint32_t>& face,
    const Vec3& normal) {
    Vec3 newell{};
    for (std::size_t index = 0U; index < face.size(); ++index) {
        const Vec3& current = mesh.vertices[face[index]];
        const Vec3& following = mesh.vertices[face[(index + 1U) % face.size()]];
        newell.x += (current.y - following.y) * (current.z + following.z);
        newell.y += (current.z - following.z) * (current.x + following.x);
        newell.z += (current.x - following.x) * (current.y + following.y);
    }
    return newell.x * normal.x + newell.y * normal.y + newell.z * normal.z;
}

void check_faces_follow_normal(const GeneratedMesh& mesh, const Vec3& normal) {
    CHECK(!mesh.faces.empty());
    for (const auto& face : mesh.faces) {
        CHECK(face_normal_dot(mesh, face, normal) > 1.0e-12);
    }
}

bool same_face_connectivity(
    const std::vector<std::vector<std::uint32_t>>& left,
    const std::vector<std::vector<std::uint32_t>>& right) {
    if (left.size() != right.size()) {
        return false;
    }
    for (std::size_t index = 0U; index < left.size(); ++index) {
        auto left_face = left[index];
        auto right_face = right[index];
        std::sort(left_face.begin(), left_face.end());
        std::sort(right_face.begin(), right_face.end());
        if (left_face != right_face) {
            return false;
        }
    }
    return true;
}

void check_cell_center_faces_follow_normal(
    const GenerationResult& result,
    const Vec3& normal) {
    const std::uint32_t resolution = result.report.cell_resolution;
    const std::uint32_t ring_face_count =
        resolution * result.report.cell_shape_divisions;
    const std::uint32_t faces_per_scale = ring_face_count + resolution;
    CHECK(resolution > 0U);
    CHECK(result.mesh.faces.size() ==
          static_cast<std::size_t>(result.mesh.scale_count) * faces_per_scale);
    for (std::uint32_t scale_index = 0U;
         scale_index < result.mesh.scale_count;
         ++scale_index) {
        const std::uint32_t start = scale_index * faces_per_scale;
        for (std::uint32_t face_index = ring_face_count;
             face_index < faces_per_scale;
             ++face_index) {
            CHECK(face_normal_dot(
                      result.mesh,
                      result.mesh.faces[start + face_index],
                      normal) > 1.0e-12);
        }
    }
}

}  // namespace

int main() {
    try {
    const auto decoded_payload = bifrost_scales::decode_native_payload(R"json(
        {
          "schema":"bifrost-scales/native-payload/10",
          "mode":"settled",
          "settings":{
            "target_count":24,
            "seed":9,
            "size":0.25,
            "cell_mode":"cells",
            "scale_types":[{
              "type_id":"guided",
              "name":"Guided",
              "enabled":true,
              "weight":1.0,
              "size_multiplier":1.8,
              "guide_id":"flow",
              "guide_strength":1.0
            }]
          },
          "cell_metadata_indices":[3,1,3],
          "resolve_cell_ids":["0000000000000002","0000000000000001","0000000000000002"],
          "guides":[{
            "guide_id":"flow",
            "group_id":"group_flow",
            "kind":"flow_curve",
            "points":[[-1,0,0],[1,0,0]],
            "radius":2.0,
            "use_density":true,
            "use_size":false,
            "use_direction":true
          }]
        }
    )json");
    CHECK(decoded_payload.success);
    CHECK(decoded_payload.status == "ok");
    CHECK(decoded_payload.payload.mode == PreviewMode::Settled);
    CHECK(decoded_payload.payload.settings.target_count == 24U);
    CHECK(std::abs(decoded_payload.payload.settings.size - 0.25) < 1.0e-12);
    CHECK(decoded_payload.payload.settings.scale_types.size() == 1U);
    CHECK(decoded_payload.payload.settings.scale_types[0].guide_id == "flow");
    CHECK(decoded_payload.payload.guides.size() == 1U);
    CHECK(decoded_payload.payload.guides[0].kind == GuideKind::FlowCurve);
    CHECK(decoded_payload.payload.guides[0].group_id == "group_flow");
    CHECK(decoded_payload.payload.guides[0].points.size() == 2U);
    CHECK(decoded_payload.payload.guides[0].use_density.value());
    CHECK(!decoded_payload.payload.guides[0].use_size.value());
    CHECK(decoded_payload.payload.guides[0].use_direction.value());
    CHECK(decoded_payload.payload.cell_metadata_indices.size() == 2U);
    CHECK(decoded_payload.payload.cell_metadata_indices[0] == 1U);
    CHECK(decoded_payload.payload.cell_metadata_indices[1] == 3U);
    CHECK(decoded_payload.payload.resolve_cell_ids.size() == 2U);
    CHECK(decoded_payload.payload.resolve_cell_ids[0] == 1U);
    CHECK(decoded_payload.payload.resolve_cell_ids[1] == 2U);
    CHECK(!bifrost_scales::decode_native_payload("{}").success);

    Settings group_link_settings;
    group_link_settings.size = 1.0;
    group_link_settings.lift = 0.0;
    group_link_settings.curvature = 0.0;
    group_link_settings.random_size = 0.0;
    group_link_settings.random_rotation_degrees = 0.0;
    group_link_settings.cell_mode = GeometryMode::Cards;
    ScaleType group_link_type;
    group_link_type.id = "group_linked";
    group_link_type.name = "Group Linked";
    group_link_type.width_multiplier = 2.0;
    group_link_type.guide_id = "group_primary";
    group_link_settings.scale_types = {group_link_type};

    Sample group_link_sample;
    group_link_sample.position = {0.0, 0.0, 0.0};
    group_link_sample.normal = {0.0, 1.0, 0.0};
    group_link_sample.size_multiplier = 1.0;
    group_link_sample.random_size = 0.5;
    group_link_sample.random_rotation = 0.5;
    group_link_sample.random_type = 0.5;
    const OrientedSample group_link_oriented{
        group_link_sample,
        {0.0, 0.0, 1.0},
        {0.0, 0.0, 1.0},
        0.0,
    };
    Guide group_member;
    group_member.id = "member";
    group_member.group_id = "group_primary";
    group_member.kind = GuideKind::DensityPoint;
    group_member.points = {{0.0, 0.0, 0.0}};
    group_member.radius = 2.0;
    group_member.falloff = 1.0;

    const auto group_linked_mesh = bifrost_scales::shape_samples(
        {group_link_oriented},
        group_link_settings,
        PreviewMode::Interactive,
        {group_member});
    group_member.group_id.clear();
    const auto group_unlinked_mesh = bifrost_scales::shape_samples(
        {group_link_oriented},
        group_link_settings,
        PreviewMode::Interactive,
        {group_member});
    const double linked_width = std::abs(
        group_linked_mesh.vertices[0].x - group_linked_mesh.vertices[1].x);
    const double unlinked_width = std::abs(
        group_unlinked_mesh.vertices[0].x - group_unlinked_mesh.vertices[1].x);
    CHECK(std::abs(linked_width / unlinked_width - 2.0) < 1.0e-12);

    group_member.group_id = "group_primary";
    Guide exact_id_guide;
    exact_id_guide.id = "group_primary";
    exact_id_guide.kind = GuideKind::DensityPoint;
    exact_id_guide.points = {{100.0, 0.0, 0.0}};
    exact_id_guide.radius = 0.25;
    exact_id_guide.falloff = 1.0;
    const auto exact_precedence_mesh = bifrost_scales::shape_samples(
        {group_link_oriented},
        group_link_settings,
        PreviewMode::Interactive,
        {group_member, exact_id_guide});
    const double exact_precedence_width = std::abs(
        exact_precedence_mesh.vertices[0].x - exact_precedence_mesh.vertices[1].x);
    CHECK(std::abs(exact_precedence_width - unlinked_width) < 1.0e-12);

    Guide mirrored_exact = exact_id_guide;
    mirrored_exact.points = {{0.0, 0.0, 0.0}};
    mirrored_exact.radius = 2.0;
    const auto mirrored_exact_mesh = bifrost_scales::shape_samples(
        {group_link_oriented},
        group_link_settings,
        PreviewMode::Interactive,
        {exact_id_guide, mirrored_exact});
    const double mirrored_exact_width = std::abs(
        mirrored_exact_mesh.vertices[0].x - mirrored_exact_mesh.vertices[1].x);
    CHECK(std::abs(mirrored_exact_width / unlinked_width - 2.0) < 1.0e-12);

    group_member.group_id = "group_primary";
    group_member.enabled = false;
    const auto disabled_group_mesh = bifrost_scales::shape_samples(
        {group_link_oriented},
        group_link_settings,
        PreviewMode::Interactive,
        {group_member});
    const double disabled_group_width = std::abs(
        disabled_group_mesh.vertices[0].x - disabled_group_mesh.vertices[1].x);
    CHECK(std::abs(disabled_group_width - unlinked_width) < 1.0e-12);

    const auto negative_seed_payload = bifrost_scales::decode_native_payload(R"json(
        {
          "schema":"bifrost-scales/native-payload/10",
          "mode":"settled",
          "settings":{"seed":-37}
        }
    )json");
    CHECK(negative_seed_payload.success);
    CHECK(negative_seed_payload.payload.settings.seed == 37U);

    const Mesh mesh = plane_mesh();

    Settings normal_winding_settings;
    normal_winding_settings.target_count = 1U;
    normal_winding_settings.interactive_budget = 1U;
    normal_winding_settings.settled_budget = 1U;
    normal_winding_settings.size = 0.28;
    normal_winding_settings.lift = 0.0;
    normal_winding_settings.curvature = 0.45;
    normal_winding_settings.random_size = 0.0;
    normal_winding_settings.random_rotation_degrees = 0.0;
    normal_winding_settings.cell_shape_divisions = 2U;

    Sample normal_winding_sample;
    normal_winding_sample.position = {0.0, 0.0, 0.0};
    normal_winding_sample.normal = {0.0, 1.0, 0.0};
    normal_winding_sample.local_spacing = 1.0;
    const OrientedSample normal_winding_oriented{
        normal_winding_sample,
        {0.0, 0.0, 1.0},
        {0.0, 0.0, 1.0},
        0.0,
    };

    normal_winding_settings.cell_mode = GeometryMode::Cards;
    const auto normal_interactive = bifrost_scales::shape_samples(
        {normal_winding_oriented},
        normal_winding_settings,
        PreviewMode::Interactive);
    const auto normal_settled = bifrost_scales::shape_samples(
        {normal_winding_oriented},
        normal_winding_settings,
        PreviewMode::Settled);
    check_faces_follow_normal(normal_interactive, normal_winding_sample.normal);
    check_faces_follow_normal(normal_settled, normal_winding_sample.normal);

    CellData normal_winding_cell;
    normal_winding_cell.sample_index = 0U;
    normal_winding_cell.stable_tangent = {0.0, 0.0, 1.0};
    normal_winding_cell.stable_bitangent = {1.0, 0.0, 0.0};
    normal_winding_cell.local_spacing = 1.0;
    constexpr double normal_winding_pi = 3.14159265358979323846;
    for (std::uint32_t index = 0U; index < 12U; ++index) {
        const double angle = 2.0 * normal_winding_pi *
            static_cast<double>(index) / 12.0;
        const double radius = 0.92 + 0.12 * std::cos(3.0 * angle);
        normal_winding_cell.boundary.push_back({
            radius * std::cos(angle),
            0.0,
            radius * std::sin(angle),
        });
    }
    normal_winding_settings.cell_mode = GeometryMode::Cells;
    const auto normal_cells = bifrost_scales::shape_cells(
        {normal_winding_oriented},
        {normal_winding_cell},
        normal_winding_settings);
    check_faces_follow_normal(normal_cells, normal_winding_sample.normal);

    Settings generated_winding_settings;
    generated_winding_settings.target_count = 32U;
    generated_winding_settings.interactive_budget = 32U;
    generated_winding_settings.settled_budget = 32U;
    generated_winding_settings.seed = 19U;
    generated_winding_settings.size = 0.22;
    generated_winding_settings.lift = 0.0;
    generated_winding_settings.curvature = 0.55;
    generated_winding_settings.random_size = 0.35;
    generated_winding_settings.random_rotation_degrees = 28.0;
    generated_winding_settings.cell_mode = GeometryMode::Cells;
    generated_winding_settings.cell_shape_divisions = 3U;
    generated_winding_settings.cell_interactive_resolution = 8U;
    generated_winding_settings.cell_settled_resolution = 12U;
    for (const PreviewMode mode : {
             PreviewMode::Interactive,
             PreviewMode::Settled,
             PreviewMode::Final,
         }) {
        const auto generated_winding = bifrost_scales::generate(
            mesh,
            generated_winding_settings,
            mode);
        check_cell_center_faces_follow_normal(
            generated_winding,
            {0.0, -1.0, 0.0});
    }

    Settings rng_contract;
    rng_contract.target_count = 1U;
    rng_contract.interactive_budget = 1U;
    rng_contract.settled_budget = 1U;
    rng_contract.seed = 37U;
    rng_contract.spacing_factor = 0.72;
    rng_contract.relax_iterations = 0U;
    const auto rng_distribution = bifrost_scales::distribute(
        mesh,
        rng_contract,
        PreviewMode::Settled);
    CHECK(rng_distribution.samples.size() == 1U);
    const Sample& rng_sample = rng_distribution.samples.front();
    CHECK(rng_sample.triangle_index == 0U);
    CHECK(std::abs(rng_sample.random_size - 0.6820045605879779) < 1.0e-15);
    CHECK(std::abs(rng_sample.random_rotation - 0.09160260807956389) < 1.0e-15);
    CHECK(std::abs(rng_sample.random_type - 0.6178163488614024) < 1.0e-15);
    CHECK(std::abs(rng_sample.random_shape - 0.8419199045509562) < 1.0e-15);

    // Projection neighborhoods must span all triangles sharing a high-valence
    // vertex. 0.8.9 used edge-only adjacency, so opposite rays on a triangle
    // fan projected to the center vertex and produced dented Cell rings.
    const Mesh fan = fan_mesh();
    Sample fan_sample;
    fan_sample.position = {0.0, 0.0, 0.0};
    fan_sample.normal = {0.0, 1.0, 0.0};
    fan_sample.triangle_index = 0U;
    fan_sample.local_spacing = 0.5;
    Settings fan_settings;
    fan_settings.cell_mode = GeometryMode::Cells;
    fan_settings.cell_settled_resolution = 12U;
    fan_settings.cell_gap = 0.0;
    fan_settings.cell_collision_margin = 0.0;
    fan_settings.cell_radius_multiplier = 1.0;
    fan_settings.cell_projection_rings = 1U;
    fan_settings.cell_project_to_surface = true;
    GenerationReport fan_report;
    fan_report.initial_spacing = 0.5;
    fan_report.final_spacing = 0.5;
    const auto fan_cells = bifrost_scales::build_cells(
        fan,
        {fan_sample},
        fan_settings,
        PreviewMode::Settled,
        fan_report);
    CHECK(fan_cells.cells.size() == 1U);
    CHECK(fan_cells.cells.front().boundary.size() == 12U);
    for (const Vec3& point : fan_cells.cells.front().boundary) {
        CHECK(std::hypot(point.x, point.z) > 0.49);
    }

    // Boundary clipping is component-local. A small disconnected shell close
    // to a larger shell must not cut a bite into the larger shell's Cell.
    Mesh nearby_shells;
    nearby_shells.vertices = {
        {-3.0, 0.0, -3.0},
        {3.0, 0.0, -3.0},
        {3.0, 0.0, 3.0},
        {-3.0, 0.0, 3.0},
        {-0.5, 0.05, -0.5},
        {0.5, 0.05, -0.5},
        {0.5, 0.05, 0.5},
        {-0.5, 0.05, 0.5},
    };
    nearby_shells.triangles = {
        {0U, 1U, 2U},
        {0U, 2U, 3U},
        {4U, 5U, 6U},
        {4U, 6U, 7U},
    };
    Sample large_shell_sample;
    large_shell_sample.position = {0.0, 0.0, 0.0};
    large_shell_sample.normal = {0.0, 1.0, 0.0};
    large_shell_sample.triangle_index = 0U;
    large_shell_sample.local_spacing = 1.0;
    Settings nearby_shell_settings;
    nearby_shell_settings.cell_mode = GeometryMode::Cells;
    nearby_shell_settings.cell_settled_resolution = 8U;
    nearby_shell_settings.cell_gap = 0.0;
    nearby_shell_settings.cell_collision_margin = 0.0;
    nearby_shell_settings.cell_radius_multiplier = 2.0;
    nearby_shell_settings.cell_projection_rings = 0U;
    nearby_shell_settings.cell_project_to_surface = false;
    GenerationReport nearby_shell_report;
    nearby_shell_report.initial_spacing = 1.0;
    nearby_shell_report.final_spacing = 1.0;
    const auto nearby_shell_cells = bifrost_scales::build_cells(
        nearby_shells,
        {large_shell_sample},
        nearby_shell_settings,
        PreviewMode::Settled,
        nearby_shell_report);
    CHECK(nearby_shell_cells.cells.size() == 1U);
    for (const Vec3& point : nearby_shell_cells.cells.front().boundary) {
        CHECK(std::hypot(point.x, point.z) > 1.99);
    }

    // Guide and Scale Type shrink controls must not collapse each other to the
    // emergency 0.05 floor. The combined result equals either authored 0.5
    // control instead of multiplying or neutral-delta underflowing.
    Settings size_envelope_settings;
    size_envelope_settings.cell_mode = GeometryMode::Cards;
    size_envelope_settings.size = 1.0;
    size_envelope_settings.random_size = 0.0;
    size_envelope_settings.random_rotation_degrees = 0.0;
    ScaleType half_type;
    half_type.id = "half";
    half_type.name = "Half";
    half_type.size_multiplier = 0.5;
    size_envelope_settings.scale_types = {half_type};
    Sample half_sample;
    half_sample.position = {0.0, 0.0, 0.0};
    half_sample.normal = {0.0, 1.0, 0.0};
    half_sample.local_spacing = 2.0;
    half_sample.size_multiplier = 0.5;
    half_sample.random_size = 0.5;
    half_sample.random_rotation = 0.5;
    half_sample.random_type = 0.5;
    half_sample.random_shape = 0.5;
    const OrientedSample half_oriented{
        half_sample,
        {1.0, 0.0, 0.0},
        {1.0, 0.0, 0.0},
        0.0,
    };
    const auto both_half = bifrost_scales::shape_samples(
        {half_oriented},
        size_envelope_settings,
        PreviewMode::Interactive);
    half_sample.size_multiplier = 1.0;
    const OrientedSample type_only_half{
        half_sample,
        {1.0, 0.0, 0.0},
        {1.0, 0.0, 0.0},
        0.0,
    };
    const auto type_half = bifrost_scales::shape_samples(
        {type_only_half},
        size_envelope_settings,
        PreviewMode::Interactive);
    CHECK(both_half.vertices == type_half.vertices);

    Settings settings;
    settings.target_count = 120;
    settings.interactive_budget = 20;
    settings.settled_budget = 60;
    settings.spacing_factor = 0.5;
    settings.relax_iterations = 3;
    settings.relax_strength = 0.7;
    settings.direction_relax_iterations = 2;
    settings.direction_relax_strength = 0.4;

    ScaleType classic;
    classic.id = "classic";
    classic.name = "Classic";
    ScaleType wide;
    wide.id = "wide";
    wide.name = "Wide";
    wide.width_multiplier = 1.6;
    wide.length_multiplier = 0.78;
    wide.use_custom_color = true;
    wide.color = {0.9, 0.2, 0.1, 1.0};
    settings.scale_types = {classic, wide};

    Guide density;
    density.id = "density";
    density.kind = GuideKind::DensityPoint;
    density.points = {{0.0, 0.0, 0.0}};
    density.radius = 5.0;
    density.density_multiplier = 1.8;
    density.size_multiplier = 1.1;

    Guide direction;
    direction.id = "direction";
    direction.kind = GuideKind::DirectionPoint;
    direction.points = {{0.0, 0.0, 0.0}};
    direction.direction = {1.0, 0.0, 0.0};
    direction.radius = 5.0;
    direction.strength = 0.85;
    direction.angle_degrees = 18.0;
    const std::vector<Guide> guides{density, direction};

    const auto interactive = bifrost_scales::generate(
        mesh,
        settings,
        PreviewMode::Interactive,
        guides);
    CHECK(interactive.mesh.scale_count == 20);
    CHECK(interactive.mesh.vertices.size() == 60);
    CHECK(interactive.mesh.faces.size() == 20);
    CHECK(interactive.mesh.uvs.size() == interactive.mesh.vertices.size());
    CHECK(interactive.mesh.colors.size() == interactive.mesh.vertices.size());

    const auto settled = bifrost_scales::generate(
        mesh,
        settings,
        PreviewMode::Settled,
        guides);
    CHECK(settled.mesh.scale_count == 60);
    CHECK(settled.mesh.vertices.size() == 1860U);
    CHECK(settled.mesh.faces.size() == 1800U);
    CHECK(settled.mesh.uvs.size() == settled.mesh.vertices.size());
    CHECK(settled.mesh.colors.size() == settled.mesh.vertices.size());
    CHECK(settled.report.used_cells);
    CHECK(settled.report.cell_count == settled.mesh.scale_count);
    CHECK(settled.report.cell_resolution == 10U);
    CHECK(settled.report.cell_clipped_rays > 0U);
    CHECK(settled.report.cell_mean_neighbors > 0.0);
    CHECK(settled.report.paired_sample_count == 0U);
    CHECK(settled.report.partition_seed_count == settled.report.cell_count);
    CHECK(settled.report.cell_shape_divisions == 2U);
    CHECK(settled.report.density_guide_count == 1);
    CHECK(settled.report.direction_guide_count == 1);
    CHECK(settled.report.active_scale_type_count == 2);
    CHECK(settled.report.relax_iterations == 3);
    CHECK(settled.report.direction_relax_iterations == 2);
    CHECK(settled.report.moved_samples > 0);
    CHECK(settled.report.type_counts.size() == 2);
    CHECK(counted_types(settled.report.type_counts) == settled.mesh.scale_count);
    CHECK(std::find(
               settled.mesh.scale_type_ids.begin(),
               settled.mesh.scale_type_ids.end(),
               0U) != settled.mesh.scale_type_ids.end());
    CHECK(std::find(
               settled.mesh.scale_type_ids.begin(),
               settled.mesh.scale_type_ids.end(),
               1U) != settled.mesh.scale_type_ids.end());

    const auto repeat = bifrost_scales::generate(
        mesh,
        settings,
        PreviewMode::Settled,
        guides);
    CHECK(settled.mesh.vertices == repeat.mesh.vertices);
    CHECK(settled.mesh.faces == repeat.mesh.faces);
    CHECK(settled.mesh.colors == repeat.mesh.colors);
    CHECK(settled.mesh.scale_type_ids == repeat.mesh.scale_type_ids);

    const auto distribution = bifrost_scales::distribute(
        mesh,
        settings,
        PreviewMode::Settled,
        guides);
    const auto orientation = bifrost_scales::orient_samples(
        distribution.samples,
        settings,
        PreviewMode::Settled,
        guides,
        distribution.report);
    Settings changed_shape = settings;
    changed_shape.size = 0.35;
    changed_shape.curvature = 0.9;
    changed_shape.inset = 0.25;
    changed_shape.tip_offset = 0.4;
    const auto original_shape = bifrost_scales::shape_samples(
        orientation.samples,
        settings,
        PreviewMode::Settled,
        guides);
    const auto modified_shape = bifrost_scales::shape_samples(
        orientation.samples,
        changed_shape,
        PreviewMode::Settled,
        guides);
    CHECK(original_shape.scale_count == modified_shape.scale_count);
    CHECK(original_shape.faces == modified_shape.faces);
    CHECK(original_shape.scale_type_ids == modified_shape.scale_type_ids);
    CHECK(original_shape.vertices != modified_shape.vertices);

    const auto cells = bifrost_scales::build_cells(
        mesh,
        orientation.samples,
        settings,
        PreviewMode::Settled,
        orientation.report);
    CHECK(cells.cells.size() == orientation.samples.size());
    CHECK(cells.report.used_cells);
    CHECK(cells.report.cell_resolution == 10U);
    CHECK(std::all_of(
        cells.cells.begin(),
        cells.cells.end(),
        [](const auto& cell) { return cell.boundary.size() == 10U; }));
    const auto original_cells = bifrost_scales::shape_cells(
        orientation.samples,
        cells.cells,
        settings,
        guides);
    const auto modified_cells = bifrost_scales::shape_cells(
        orientation.samples,
        cells.cells,
        changed_shape,
        guides);
    CHECK(original_cells.scale_count == modified_cells.scale_count);
    CHECK(original_cells.faces == modified_cells.faces);
    CHECK(original_cells.scale_type_ids == modified_cells.scale_type_ids);
    CHECK(original_cells.vertices != modified_cells.vertices);

    Settings hda_cell_base = settings;
    hda_cell_base.cell_growth = 1.0;
    hda_cell_base.size = 0.18;
    hda_cell_base.curvature = 0.0;
    hda_cell_base.lift = 0.0;
    hda_cell_base.random_size = 0.0;
    hda_cell_base.random_rotation_degrees = 0.0;
    hda_cell_base.scale_types = {classic};
    const auto hda_cell_shape = bifrost_scales::shape_cells(
        orientation.samples,
        cells.cells,
        hda_cell_base,
        guides);
    const std::size_t ring_size = cells.cells.front().boundary.size();
    const std::size_t cell_stride =
        ring_size * (static_cast<std::size_t>(hda_cell_base.cell_shape_divisions) + 1U) + 1U;
    for (std::size_t scale_index = 0U; scale_index < cells.cells.size(); ++scale_index) {
        for (std::size_t ray_index = 0U; ray_index < ring_size; ++ray_index) {
            const Vec3& expected = cells.cells[scale_index].boundary[ray_index];
            const Vec3& actual = hda_cell_shape.vertices[scale_index * cell_stride + ray_index];
            CHECK(std::abs(actual.x - expected.x) < 1.0e-9);
            CHECK(std::abs(actual.y - expected.y) < 1.0e-9);
            CHECK(std::abs(actual.z - expected.z) < 1.0e-9);
        }
    }
    std::vector<Settings> hda_cell_variants;
    Settings variant = hda_cell_base;
    variant.size = 0.42;
    hda_cell_variants.push_back(variant);
    variant = hda_cell_base;
    variant.inset = 0.55;
    hda_cell_variants.push_back(variant);
    variant = hda_cell_base;
    variant.squash = 0.55;
    hda_cell_variants.push_back(variant);
    variant = hda_cell_base;
    variant.expand = 1.2;
    hda_cell_variants.push_back(variant);
    variant = hda_cell_base;
    variant.tip_roundness = 0.9;
    hda_cell_variants.push_back(variant);
    variant = hda_cell_base;
    variant.tip_offset = 0.75;
    hda_cell_variants.push_back(variant);
    variant = hda_cell_base;
    variant.forward_offset = 1.2;
    hda_cell_variants.push_back(variant);
    for (const Settings& hda_variant : hda_cell_variants) {
        const auto changed = bifrost_scales::shape_cells(
            orientation.samples,
            cells.cells,
            hda_variant,
            guides);
        CHECK(same_face_connectivity(changed.faces, hda_cell_shape.faces));
        CHECK(changed.vertices != hda_cell_shape.vertices);
    }

    Settings center_contract = hda_cell_base;
    center_contract.size = 0.5;
    center_contract.tip_offset = 0.6;
    center_contract.forward_offset = 0.4;
    center_contract.cell_shape_divisions = 1U;
    Sample center_sample;
    center_sample.position = {0.0, 0.0, 0.0};
    center_sample.normal = {0.0, 1.0, 0.0};
    center_sample.random_size = 0.5;
    center_sample.random_rotation = 0.5;
    center_sample.random_type = 0.5;
    center_sample.random_shape = 0.5;
    center_sample.size_multiplier = 1.0;
    center_sample.local_spacing = 2.0;
    const bifrost_scales::OrientedSample center_oriented{
        center_sample,
        {0.0, 0.0, 1.0},
        {0.0, 0.0, 1.0},
        0.0,
    };
    bifrost_scales::CellData center_cell;
    center_cell.sample_index = 0U;
    center_cell.boundary = {
        {-1.0, 0.0, -1.0},
        {1.0, 0.0, -1.0},
        {1.0, 0.0, 1.0},
        {-1.0, 0.0, 1.0},
    };
    center_cell.local_spacing = 2.0;
    const auto center_contract_mesh = bifrost_scales::shape_cells(
        {center_oriented},
        {center_cell},
        center_contract);
    CHECK(center_contract_mesh.scale_count == 1U);
    CHECK(center_contract_mesh.vertices.size() == 9U);
    const Vec3& center_vertex = center_contract_mesh.vertices.back();
    const double expected_center_longitudinal =
        center_contract.forward_offset * center_contract.size * 0.28 +
        center_contract.tip_offset * center_contract.size * 0.10;
    CHECK(std::abs(center_vertex.x) < 1.0e-12);
    CHECK(std::abs(center_vertex.y) < 1.0e-12);
    CHECK(std::abs(center_vertex.z - expected_center_longitudinal) < 1.0e-12);

    Settings typed_cell = hda_cell_base;
    ScaleType typed_classic = classic;
    typed_classic.width_multiplier = 1.4;
    typed_classic.length_multiplier = 0.8;
    typed_classic.tip_offset = 0.6;
    typed_cell.scale_types = {typed_classic};
    const auto typed_cell_shape = bifrost_scales::shape_cells(
        orientation.samples,
        cells.cells,
        typed_cell,
        guides);
    CHECK(typed_cell_shape.faces == hda_cell_shape.faces);
    CHECK(typed_cell_shape.vertices != hda_cell_shape.vertices);

    for (std::size_t scale_index = 0; scale_index < cells.cells.size(); ++scale_index) {
        const Vec3& sample_position = orientation.samples[scale_index].sample.position;
        const auto& boundary = cells.cells[scale_index].boundary;
        for (std::size_t ray_index = 0; ray_index < boundary.size(); ++ray_index) {
            const Vec3& shaped = typed_cell_shape.vertices[
                scale_index * cell_stride + ray_index];
            const double shaped_radius = std::hypot(
                shaped.x - sample_position.x,
                shaped.z - sample_position.z);
            const double boundary_radius = std::hypot(
                boundary[ray_index].x - sample_position.x,
                boundary[ray_index].z - sample_position.z);
            CHECK(std::isfinite(shaped_radius));
            CHECK(shaped_radius <= boundary_radius + 1.0e-8);
        }
    }

    Settings card_settings = settings;
    card_settings.cell_mode = GeometryMode::Cards;
    const auto settled_cards = bifrost_scales::generate(
        mesh,
        card_settings,
        PreviewMode::Settled,
        guides);
    CHECK(!settled_cards.report.used_cells);
    CHECK(settled_cards.mesh.vertices.size() == 360U);
    CHECK(settled_cards.mesh.faces.size() == 300U);

    Settings interactive_cells_settings = settings;
    interactive_cells_settings.cell_mode = GeometryMode::Cells;
    const auto interactive_cells = bifrost_scales::generate(
        mesh,
        interactive_cells_settings,
        PreviewMode::Interactive,
        guides);
    CHECK(interactive_cells.report.used_cells);
    CHECK(interactive_cells.report.cell_resolution == 6U);
    CHECK(interactive_cells.mesh.vertices.size() == 380U);
    CHECK(interactive_cells.mesh.faces.size() == 360U);
    CHECK(interactive_cells.report.cell_shape_divisions == 2U);

    Guide rotated_direction = direction;
    rotated_direction.direction = {0.0, 0.0, 1.0};
    const auto rotation_ignored = bifrost_scales::orient_samples(
        distribution.samples,
        settings,
        PreviewMode::Settled,
        {density, rotated_direction},
        distribution.report);
    CHECK(rotation_ignored.samples.size() == orientation.samples.size());
    CHECK(rotation_ignored.samples.front().sample.position ==
           orientation.samples.front().sample.position);
    CHECK(rotation_ignored.samples.front().tangent ==
           orientation.samples.front().tangent);

    Guide moved_direction = direction;
    moved_direction.points = {{2.0, 0.0, 0.0}};
    const auto reoriented = bifrost_scales::orient_samples(
        distribution.samples,
        settings,
        PreviewMode::Settled,
        {density, moved_direction},
        distribution.report);
    CHECK(reoriented.samples.size() == orientation.samples.size());
    bool point_move_changed_orientation = false;
    for (std::size_t index = 0U; index < reoriented.samples.size(); ++index) {
        if (reoriented.samples[index].tangent != orientation.samples[index].tangent) {
            point_move_changed_orientation = true;
            break;
        }
    }
    CHECK(point_move_changed_orientation);

    Settings direction_only_cell_settings;
    direction_only_cell_settings.cell_mode = GeometryMode::Cells;
    direction_only_cell_settings.cell_radius_multiplier = 1.0;
    direction_only_cell_settings.cell_settled_resolution = 8U;
    Sample direction_only_sample;
    direction_only_sample.position = {0.0, 0.0, 0.0};
    direction_only_sample.normal = {0.0, 1.0, 0.0};
    direction_only_sample.local_spacing = 1.0;
    const auto cell_x = bifrost_scales::build_cells(
        mesh,
        std::vector<bifrost_scales::OrientedSample>{
            {direction_only_sample, {1.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, 1.0}},
        direction_only_cell_settings,
        PreviewMode::Settled);
    const auto cell_z = bifrost_scales::build_cells(
        mesh,
        std::vector<bifrost_scales::OrientedSample>{
            {direction_only_sample, {0.0, 0.0, 1.0}, {0.0, 0.0, 1.0}, 1.0}},
        direction_only_cell_settings,
        PreviewMode::Settled);
    CHECK(cell_x.cells.size() == 1U);
    CHECK(cell_z.cells.size() == 1U);
    CHECK(cell_x.report.paired_sample_count == 0U);
    CHECK(cell_x.report.partition_seed_count == 1U);
    CHECK(cell_x.cells.front().boundary == cell_z.cells.front().boundary);

    Sample directed_sample;
    directed_sample.position = {0.0, 0.0, 0.0};
    directed_sample.normal = {0.0, 1.0, 0.0};
    directed_sample.local_spacing = 1.0;

    Settings directed_settings;
    directed_settings.random_rotation_degrees = 0.0;
    directed_settings.direction_relax_iterations = 0;

    Guide forward_curve;
    forward_curve.id = "forward_curve";
    forward_curve.kind = GuideKind::DirectionCurve;
    forward_curve.points = {{-1.0, 0.0, 0.0}, {1.0, 0.0, 0.0}};
    forward_curve.radius = 3.0;
    forward_curve.strength = 1.0;
    const auto forward_orientation = bifrost_scales::orient_samples(
        {directed_sample},
        directed_settings,
        PreviewMode::Final,
        {forward_curve});
    CHECK(forward_orientation.samples.size() == 1U);
    CHECK(forward_orientation.samples.front().tangent.x > 0.999);

    Guide reverse_curve = forward_curve;
    reverse_curve.id = "reverse_curve";
    reverse_curve.points = {{1.0, 0.0, 0.0}, {-1.0, 0.0, 0.0}};
    const auto reverse_orientation = bifrost_scales::orient_samples(
        {directed_sample},
        directed_settings,
        PreviewMode::Final,
        {reverse_curve});
    CHECK(reverse_orientation.samples.size() == 1U);
    CHECK(reverse_orientation.samples.front().tangent.x < -0.999);

    Guide point_attractor;
    point_attractor.id = "point_attractor";
    point_attractor.kind = GuideKind::DirectionPoint;
    point_attractor.points = {{0.0, 0.0, 0.0}};
    point_attractor.radius = 3.0;
    point_attractor.strength = 1.0;
    Sample left_sample = directed_sample;
    left_sample.position = {-0.5, 0.0, 0.0};
    Sample right_sample = directed_sample;
    right_sample.position = {0.5, 0.0, 0.0};
    const auto point_orientation = bifrost_scales::orient_samples(
        {left_sample, right_sample},
        directed_settings,
        PreviewMode::Final,
        {point_attractor});
    CHECK(point_orientation.samples.size() == 2U);
    CHECK(point_orientation.samples[0].tangent.x > 0.9);
    CHECK(point_orientation.samples[1].tangent.x < -0.9);
    CHECK(point_orientation.samples[0].direction_influence > 0.0);
    CHECK(point_orientation.samples[1].direction_influence > 0.0);

    Sample scoped_relax_a = directed_sample;
    scoped_relax_a.position = {0.0, 0.0, 0.0};
    scoped_relax_a.normal = {0.0, 1.0, 0.0};
    scoped_relax_a.local_spacing = 1.0;
    Sample scoped_relax_b = directed_sample;
    scoped_relax_b.position = {1.0, 0.0, 0.0};
    scoped_relax_b.normal = {0.5, 0.5, 0.7071067811865476};
    scoped_relax_b.local_spacing = 10.0;
    Settings no_relax_settings = directed_settings;
    no_relax_settings.direction_relax_iterations = 0U;
    Settings scoped_relax_settings = directed_settings;
    scoped_relax_settings.direction_relax_iterations = 1U;
    scoped_relax_settings.direction_relax_strength = 1.0;
    GenerationReport scoped_relax_report;
    scoped_relax_report.initial_spacing = 0.1;
    scoped_relax_report.final_spacing = 0.1;
    const auto no_relax_orientation = bifrost_scales::orient_samples(
        {scoped_relax_a, scoped_relax_b},
        no_relax_settings,
        PreviewMode::Final);
    const auto scoped_relax_orientation = bifrost_scales::orient_samples(
        {scoped_relax_a, scoped_relax_b},
        scoped_relax_settings,
        PreviewMode::Final,
        {},
        scoped_relax_report);
    CHECK(scoped_relax_orientation.samples.size() == 2U);
    for (std::size_t index = 0U; index < 2U; ++index) {
        const Vec3 delta{
            scoped_relax_orientation.samples[index].tangent.x -
                no_relax_orientation.samples[index].tangent.x,
            scoped_relax_orientation.samples[index].tangent.y -
                no_relax_orientation.samples[index].tangent.y,
            scoped_relax_orientation.samples[index].tangent.z -
                no_relax_orientation.samples[index].tangent.z,
        };
        CHECK(std::sqrt(delta.x * delta.x + delta.y * delta.y + delta.z * delta.z) < 1.0e-12);
    }

    Guide combined_curve;
    combined_curve.id = "combined_curve";
    combined_curve.kind = GuideKind::FlowCurve;
    combined_curve.points = {{-2.0, 0.0, 0.0}, {2.0, 0.0, 0.0}};
    combined_curve.radius = 4.0;
    combined_curve.density_multiplier = 1.6;
    combined_curve.strength = 1.0;
    const auto combined_distribution = bifrost_scales::distribute(
        mesh,
        settings,
        PreviewMode::Interactive,
        {combined_curve});
    const auto combined_orientation = bifrost_scales::orient_samples(
        combined_distribution.samples,
        settings,
        PreviewMode::Interactive,
        {combined_curve},
        combined_distribution.report);
    CHECK(combined_distribution.report.density_guide_count == 1U);
    CHECK(combined_orientation.report.direction_guide_count == 1U);
    CHECK(std::any_of(
        combined_distribution.samples.begin(),
        combined_distribution.samples.end(),
        [](const auto& sample) { return std::abs(sample.position.z) < 1.0e-12; }));
    CHECK(std::all_of(
        combined_orientation.samples.begin(),
        combined_orientation.samples.end(),
        [](const auto& sample) { return sample.direction_influence == 0.0; }));

    Settings localized_type_settings;
    localized_type_settings.cell_mode = GeometryMode::Cards;
    localized_type_settings.size = 0.2;
    localized_type_settings.random_size = 0.0;
    localized_type_settings.random_rotation_degrees = 0.0;
    localized_type_settings.color = {0.2, 0.4, 0.6, 1.0};
    ScaleType localized_type;
    localized_type.id = "localized";
    localized_type.name = "Localized";
    localized_type.size_multiplier = 3.0;
    localized_type.tip_offset = 0.9;
    localized_type.guide_id = "local-zero-bias";
    localized_type.use_custom_color = true;
    localized_type.color = {1.0, 0.0, 0.0, 1.0};
    localized_type_settings.scale_types = {localized_type};

    Guide local_zero_bias;
    local_zero_bias.id = "local-zero-bias";
    local_zero_bias.kind = GuideKind::FlowCurve;
    local_zero_bias.points = {{-0.5, 0.0, 0.0}, {0.5, 0.0, 0.0}};
    local_zero_bias.radius = 1.0;
    local_zero_bias.use_density = false;
    local_zero_bias.use_size = false;
    local_zero_bias.use_direction = false;

    Sample localized_near;
    localized_near.position = {0.0, 0.0, 0.0};
    localized_near.normal = {0.0, 1.0, 0.0};
    localized_near.local_spacing = 1.0;
    localized_near.random_size = 0.5;
    localized_near.random_rotation = 0.5;
    localized_near.random_type = 0.5;
    localized_near.random_shape = 0.5;
    Sample localized_far = localized_near;
    localized_far.position = {3.0, 0.0, 0.0};
    const std::vector<bifrost_scales::OrientedSample> localized_oriented{
        {localized_near, {1.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, 0.0},
        {localized_far, {1.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, 0.0},
    };
    const auto localized_mesh = bifrost_scales::shape_samples(
        localized_oriented,
        localized_type_settings,
        PreviewMode::Final,
        {local_zero_bias});
    CHECK(localized_mesh.scale_count == 2U);
    CHECK(localized_mesh.colors.size() == localized_mesh.vertices.size());
    const std::size_t localized_stride = localized_mesh.vertices.size() / 2U;
    CHECK(localized_stride > 0U);
    CHECK(localized_mesh.colors.front().r > 0.99);
    CHECK(std::abs(localized_mesh.colors[localized_stride].r - 0.2) < 1.0e-9);
    double localized_near_radius = 0.0;
    double localized_far_radius = 0.0;
    for (std::size_t index = 0U; index < localized_stride; ++index) {
        const Vec3 near_delta{
            localized_mesh.vertices[index].x - localized_near.position.x,
            localized_mesh.vertices[index].y - localized_near.position.y,
            localized_mesh.vertices[index].z - localized_near.position.z,
        };
        const Vec3 far_delta{
            localized_mesh.vertices[localized_stride + index].x - localized_far.position.x,
            localized_mesh.vertices[localized_stride + index].y - localized_far.position.y,
            localized_mesh.vertices[localized_stride + index].z - localized_far.position.z,
        };
        localized_near_radius = std::max(
            localized_near_radius,
            std::sqrt(near_delta.x * near_delta.x + near_delta.y * near_delta.y +
                      near_delta.z * near_delta.z));
        localized_far_radius = std::max(
            localized_far_radius,
            std::sqrt(far_delta.x * far_delta.x + far_delta.y * far_delta.y +
                      far_delta.z * far_delta.z));
    }
    CHECK(localized_near_radius > localized_far_radius * 2.0);

    Sample bounded_neighbor_a;
    bounded_neighbor_a.position = {-0.5, 0.0, 0.0};
    bounded_neighbor_a.normal = {0.0, 1.0, 0.0};
    bounded_neighbor_a.triangle_index = 0U;
    bounded_neighbor_a.local_spacing = 0.1;
    Sample bounded_neighbor_b = bounded_neighbor_a;
    bounded_neighbor_b.position = {0.5, 0.0, 0.0};
    GenerationReport broad_fallback_report;
    broad_fallback_report.initial_spacing = 1.0;
    broad_fallback_report.final_spacing = 1.0;
    Settings bounded_neighbor_settings;
    bounded_neighbor_settings.cell_radius_multiplier = 1.7;
    bounded_neighbor_settings.cell_collision_margin = 0.015;
    const auto bounded_neighbors = bifrost_scales::build_cells(
        mesh,
        {bounded_neighbor_a, bounded_neighbor_b},
        bounded_neighbor_settings,
        PreviewMode::Settled,
        broad_fallback_report);
    CHECK(bounded_neighbors.cells.size() == 2U);
    CHECK(bounded_neighbors.cells[0].neighbor_count == 0U);
    CHECK(bounded_neighbors.cells[1].neighbor_count == 0U);

    Mesh disconnected_mesh{
        {
            Vec3{0.0, 0.0, 0.0},
            Vec3{2.0, 0.0, 0.0},
            Vec3{0.0, 0.0, 2.0},
            Vec3{0.0, 0.01, 0.0},
            Vec3{2.0, 0.01, 0.0},
            Vec3{0.0, 0.01, 2.0},
        },
        {Triangle{0, 1, 2}, Triangle{3, 4, 5}},
    };
    Sample lower;
    lower.position = {0.5, 0.0, 0.5};
    lower.normal = {0.0, -1.0, 0.0};
    lower.triangle_index = 0U;
    lower.local_spacing = 1.0;
    Sample upper = lower;
    upper.position = {0.7, 0.01, 0.5};
    upper.triangle_index = 1U;
    const auto disconnected_cells = bifrost_scales::build_cells(
        disconnected_mesh,
        {lower, upper},
        settings,
        PreviewMode::Settled);
    CHECK(disconnected_cells.cells.size() == 2U);
    CHECK(disconnected_cells.cells[0].neighbor_count == 0U);
    CHECK(disconnected_cells.cells[1].neighbor_count == 0U);
    CHECK(disconnected_cells.cells[0].clipped_rays == 0U);
    CHECK(disconnected_cells.cells[1].clipped_rays == 0U);

    Settings card_center_settings;
    card_center_settings.cell_mode = GeometryMode::Cards;
    card_center_settings.size = 0.2;
    card_center_settings.lift = 0.0;
    card_center_settings.curvature = 0.3;
    card_center_settings.inset = 0.5;
    card_center_settings.tip_roundness = 0.4;
    card_center_settings.forward_offset = 0.0;
    card_center_settings.random_size = 0.0;
    card_center_settings.random_rotation_degrees = 0.0;
    Sample card_center_sample;
    card_center_sample.position = {0.0, 0.0, 0.0};
    card_center_sample.normal = {0.0, 1.0, 0.0};
    card_center_sample.local_spacing = 1.0;
    card_center_sample.size_multiplier = 1.0;
    card_center_sample.random_size = 0.5;
    card_center_sample.random_rotation = 0.5;
    card_center_sample.random_type = 0.5;
    card_center_sample.random_shape = 0.5;
    const auto card_center_mesh = bifrost_scales::shape_samples(
        std::vector<bifrost_scales::OrientedSample>{
            {card_center_sample, {1.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, 0.0}},
        card_center_settings,
        PreviewMode::Settled);
    CHECK(card_center_mesh.vertices.size() == 6U);
    const Vec3& card_center = card_center_mesh.vertices[5U];
    CHECK(std::abs(card_center.x - 0.0495) < 1.0e-12);
    CHECK(std::abs(card_center.y - 0.0192) < 1.0e-12);
    CHECK(std::abs(card_center.z) < 1.0e-12);

    Settings optimized_output_settings;
    optimized_output_settings.target_count = 48U;
    optimized_output_settings.settled_budget = 48U;
    optimized_output_settings.seed = 404U;
    optimized_output_settings.size = 0.2;
    optimized_output_settings.cell_mode = GeometryMode::Cells;
    optimized_output_settings.cell_settled_resolution = 8U;
    optimized_output_settings.cell_shape_divisions = 2U;
    optimized_output_settings.direction_relax_iterations = 1U;
    const GenerationResult reference_output = bifrost_scales::generate(
        mesh,
        optimized_output_settings,
        PreviewMode::Settled);
    bifrost_scales::GenerationOptions optimized_options;
    optimized_options.include_uvs = false;
    optimized_options.include_colors = false;
    optimized_options.include_scale_type_ids = false;
    optimized_options.materialize_faces = false;
    optimized_options.include_flat_topology = true;
    const GenerationResult optimized_output = bifrost_scales::generate(
        mesh,
        optimized_output_settings,
        PreviewMode::Settled,
        {},
        optimized_options);
    CHECK(optimized_output.mesh.faces.empty());
    CHECK(!optimized_output.mesh.face_offsets.empty());
    CHECK(optimized_output.mesh.face_offsets.front() == 0U);
    CHECK(optimized_output.mesh.face_offsets.back() ==
          optimized_output.mesh.face_vertices.size());
    CHECK(optimized_output.mesh.uvs.empty());
    CHECK(optimized_output.mesh.colors.empty());
    CHECK(optimized_output.mesh.scale_type_ids.empty());
    CHECK(optimized_output.mesh.scale_count == reference_output.mesh.scale_count);
    CHECK(optimized_output.mesh.vertices.size() == reference_output.mesh.vertices.size());
    CHECK(optimized_output.mesh.face_count() == reference_output.mesh.faces.size());
    CHECK(optimized_output.mesh.face_vertex_count() ==
          reference_output.mesh.face_vertex_count());
    for (std::size_t index = 0U; index < optimized_output.mesh.vertices.size(); ++index) {
        CHECK(optimized_output.mesh.vertices[index].x ==
              reference_output.mesh.vertices[index].x);
        CHECK(optimized_output.mesh.vertices[index].y ==
              reference_output.mesh.vertices[index].y);
        CHECK(optimized_output.mesh.vertices[index].z ==
              reference_output.mesh.vertices[index].z);
    }
    std::size_t flat_cursor = 0U;
    CHECK(optimized_output.mesh.face_offsets.size() ==
          reference_output.mesh.faces.size() + 1U);
    for (std::size_t face_index = 0U;
         face_index < reference_output.mesh.faces.size();
         ++face_index) {
        const auto& reference_face = reference_output.mesh.faces[face_index];
        CHECK(optimized_output.mesh.face_offsets[face_index] == flat_cursor);
        for (const std::uint32_t vertex : reference_face) {
            CHECK(optimized_output.mesh.face_vertices[flat_cursor] == vertex);
            ++flat_cursor;
        }
    }
    CHECK(flat_cursor == optimized_output.mesh.face_vertices.size());
    CHECK(optimized_output.profile.distribution_ms >= 0.0);
    CHECK(optimized_output.profile.orientation_ms >= 0.0);
    CHECK(optimized_output.profile.cells_ms >= 0.0);
    CHECK(optimized_output.profile.shape_ms >= 0.0);
    CHECK(optimized_output.profile.total_ms >= 0.0);

    // Cell Gap is the total shared-edge separation. Each neighbor moves by
    // half the requested width, independent of local Density spacing.
    auto neighbor_boundaries_x = [&](double local_spacing, double gap) {
        Sample left;
        left.position = {-1.0, 0.0, 0.0};
        left.normal = {0.0, 1.0, 0.0};
        left.triangle_index = 0U;
        left.local_spacing = local_spacing;
        Sample right = left;
        right.position = {1.0, 0.0, 0.0};
        Settings gap_settings;
        gap_settings.cell_mode = GeometryMode::Cells;
        gap_settings.cell_settled_resolution = 8U;
        gap_settings.cell_gap = gap;
        gap_settings.cell_collision_margin = 0.0;
        gap_settings.cell_radius_multiplier = 3.0;
        gap_settings.cell_project_to_surface = false;
        GenerationReport gap_report;
        gap_report.initial_spacing = 1.0;
        gap_report.final_spacing = 1.0;
        const auto result = bifrost_scales::build_cells(
            mesh,
            {left, right},
            gap_settings,
            PreviewMode::Settled,
            gap_report);
        return std::pair<double, double>{
            result.cells[0U].boundary[2U].x,
            result.cells[1U].boundary[6U].x,
        };
    };
    for (const double local_spacing : {1.0, 2.0}) {
        const auto base = neighbor_boundaries_x(local_spacing, 0.0);
        const auto gapped = neighbor_boundaries_x(local_spacing, 0.1);
        CHECK(std::abs((base.first - gapped.first) - 0.05) < 1.0e-9);
        CHECK(std::abs((gapped.second - base.second) - 0.05) < 1.0e-9);
        CHECK(std::abs((gapped.second - gapped.first) - 0.1) < 1.0e-9);
    }

    Settings coverage_settings;
    coverage_settings.target_count = 48U;
    coverage_settings.settled_budget = 48U;
    coverage_settings.seed = 812U;
    coverage_settings.cell_mode = GeometryMode::Cells;
    coverage_settings.cell_settled_resolution = 12U;
    coverage_settings.cell_project_to_surface = false;
    const GenerationResult coverage = bifrost_scales::generate(
        mesh,
        coverage_settings,
        PreviewMode::Settled);
    CHECK(coverage.report.open_boundary_edge_count == 4U);
    CHECK(coverage.report.boundary_anchor_count > 0U);
    CHECK(!coverage.report.boundary_density_adapted);
    CHECK(coverage.report.boundary_clipped_rays > 0U);
    for (const Vec3& point : coverage.mesh.vertices) {
        CHECK(point.x >= -2.0000001 && point.x <= 2.0000001);
        CHECK(point.z >= -2.0000001 && point.z <= 2.0000001);
    }

    // Open-boundary anchor rows must obey local Density. The former forced
    // row kept the neutral anchor count while local spacing grew, producing
    // an over-packed rim at low Density. Density 0.25 has twice the desired
    // spacing and therefore approximately half as many boundary anchors.
    Guide low_boundary_density;
    low_boundary_density.id = "low-boundary-density";
    low_boundary_density.kind = GuideKind::DensityPoint;
    low_boundary_density.points = {{0.0, 0.0, 0.0}};
    low_boundary_density.radius = 1000.0;
    low_boundary_density.falloff = 1.0;
    low_boundary_density.density_multiplier = 0.25;
    low_boundary_density.use_density = true;
    low_boundary_density.use_size = false;
    low_boundary_density.use_direction = false;
    const auto neutral_boundary_distribution = bifrost_scales::distribute(
        mesh,
        coverage_settings,
        PreviewMode::Settled);
    const auto sparse_boundary_distribution = bifrost_scales::distribute(
        mesh,
        coverage_settings,
        PreviewMode::Settled,
        {low_boundary_density});
    CHECK(sparse_boundary_distribution.report.boundary_density_adapted);
    CHECK(sparse_boundary_distribution.report.boundary_anchor_count <
          neutral_boundary_distribution.report.boundary_anchor_count);
    CHECK(sparse_boundary_distribution.report.boundary_anchor_count * 100U <=
          neutral_boundary_distribution.report.boundary_anchor_count * 60U);
    CHECK(sparse_boundary_distribution.samples.size() >=
          sparse_boundary_distribution.report.boundary_anchor_count);

    Guide mask_guide;
    mask_guide.id = "mask";
    mask_guide.kind = GuideKind::DensityPoint;
    mask_guide.points = {{0.0, 0.0, 0.0}};
    mask_guide.radius = 0.55;
    mask_guide.use_density = false;
    mask_guide.use_size = false;
    mask_guide.use_direction = false;
    mask_guide.use_mask = true;
    Settings mask_settings = coverage_settings;
    mask_settings.target_count = 96U;
    mask_settings.settled_budget = 96U;
    mask_settings.seed = 813U;
    const GenerationResult masked = bifrost_scales::generate(
        mesh,
        mask_settings,
        PreviewMode::Settled,
        {mask_guide});
    CHECK(masked.report.mask_guide_count == 1U);
    CHECK(masked.report.masked_candidate_count > 0U);
    const auto masked_distribution = bifrost_scales::distribute(
        mesh,
        mask_settings,
        PreviewMode::Settled,
        {mask_guide});
    constexpr double default_mask_core_fraction = 0.05905480523664686;
    const double mask_core_radius =
        mask_guide.radius * default_mask_core_fraction;
    bool survived_in_falloff = false;
    for (const Sample& sample : masked_distribution.samples) {
        const double radial = std::hypot(sample.position.x, sample.position.z);
        CHECK(radial >= mask_core_radius - 1.0e-12);
        survived_in_falloff = survived_in_falloff || radial < mask_guide.radius;
    }
    CHECK(survived_in_falloff);

    const Mesh close_layers = close_disconnected_planes_mesh();
    Guide surface_mask = mask_guide;
    surface_mask.id = "surface-mask";
    surface_mask.radius = 1.5;
    Settings surface_mask_settings = mask_settings;
    surface_mask_settings.target_count = 700U;
    surface_mask_settings.settled_budget = 700U;
    surface_mask_settings.spacing_factor = 0.15;
    surface_mask_settings.relax_iterations = 0U;
    surface_mask_settings.seed = 911U;
    const auto surface_mask_distribution = bifrost_scales::distribute(
        close_layers,
        surface_mask_settings,
        PreviewMode::Settled,
        {surface_mask});
    std::uint32_t guided_layer_near = 0U;
    std::uint32_t disconnected_layer_near = 0U;
    for (const Sample& sample : surface_mask_distribution.samples) {
        if (std::hypot(sample.position.x, sample.position.z) >= 0.45) {
            continue;
        }
        if (std::abs(sample.position.y) < 1.0e-9) {
            ++guided_layer_near;
        } else if (std::abs(sample.position.y - 0.08) < 1.0e-9) {
            ++disconnected_layer_near;
        }
    }
    CHECK(disconnected_layer_near >= 8U);
    CHECK(disconnected_layer_near > guided_layer_near * 2U);

    Sample seam_left;
    seam_left.position = {0.45, 0.0, 0.0};
    seam_left.normal = {0.0, 1.0, 0.0};
    seam_left.triangle_index = 0U;
    seam_left.local_spacing = 1.0;
    Sample seam_right = seam_left;
    seam_right.position = {1.45, 0.0, 0.0};
    const std::vector<OrientedSample> seam_samples{
        {seam_left, {1.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, 0.0},
        {seam_right, {1.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, 0.0},
    };
    Settings seam_settings;
    seam_settings.cell_mode = GeometryMode::Cells;
    seam_settings.cell_settled_resolution = 16U;
    seam_settings.cell_gap = 0.0;
    seam_settings.cell_collision_margin = 0.0;
    seam_settings.cell_radius_multiplier = 2.0;
    seam_settings.cell_project_to_surface = false;
    GenerationReport seam_report;
    seam_report.initial_spacing = 1.0;
    seam_report.final_spacing = 1.0;
    const auto seam_baseline = bifrost_scales::build_cells(
        mesh,
        seam_samples,
        seam_settings,
        PreviewMode::Settled,
        {},
        {},
        seam_report);
    const auto seam_cells = bifrost_scales::build_cells(
        mesh,
        seam_samples,
        seam_settings,
        PreviewMode::Settled,
        {},
        {{{0.0, 0.0, 0.0}, {1.0, 0.0, 0.0}}},
        seam_report);
    CHECK(seam_cells.report.symmetry_stabilized_cells == 0U);
    CHECK(seam_cells.report.symmetry_competitor_count == 0U);
    CHECK(seam_cells.cells.size() == seam_baseline.cells.size());
    for (std::size_t cell_index = 0U;
         cell_index < seam_cells.cells.size();
         ++cell_index) {
        CHECK(seam_cells.cells[cell_index].boundary.size() ==
              seam_baseline.cells[cell_index].boundary.size());
        for (std::size_t point_index = 0U;
             point_index < seam_cells.cells[cell_index].boundary.size();
             ++point_index) {
            const Vec3& left = seam_cells.cells[cell_index].boundary[point_index];
            const Vec3& right =
                seam_baseline.cells[cell_index].boundary[point_index];
            CHECK(left.x == right.x);
            CHECK(left.y == right.y);
            CHECK(left.z == right.z);
        }
    }
    bool crossed_center = false;
    for (const Vec3& point : seam_cells.cells.front().boundary) {
        crossed_center = crossed_center || point.x < -1.0e-8;
    }
    CHECK(crossed_center);

    // Shape-only edits reuse Distribution, Orientation and Cells exactly.
    bifrost_scales::clear_native_stage_cache();
    Settings cache_settings = coverage_settings;
    cache_settings.target_count = 37U;
    cache_settings.settled_budget = 37U;
    cache_settings.seed = 987654U;
    const GenerationResult cache_first = bifrost_scales::generate(
        mesh,
        cache_settings,
        PreviewMode::Settled);
    CHECK(cache_first.profile.stage_cache_scope == "process-shared-bounded");
    CHECK(cache_first.profile.stage_cache_capacity >= 1U);

    // A Bifrost operator may move between worker threads. The completed stage
    // results must remain visible process-wide instead of being stranded in a
    // thread_local cache.
    bifrost_scales::clear_native_stage_cache();
    GenerationResult worker_first;
    GenerationResult worker_second;
    std::thread first_worker([&]() {
        worker_first = bifrost_scales::generate(
            mesh,
            cache_settings,
            PreviewMode::Settled);
    });
    first_worker.join();
    std::thread second_worker([&]() {
        worker_second = bifrost_scales::generate(
            mesh,
            cache_settings,
            PreviewMode::Settled);
    });
    second_worker.join();
    CHECK(!worker_first.profile.distribution_cache_hit);
    CHECK(worker_second.profile.distribution_cache_hit);
    CHECK(worker_second.profile.orientation_cache_hit);
    CHECK(worker_second.profile.cell_cache_hit);
    CHECK(worker_second.mesh.vertices == worker_first.mesh.vertices);
    CHECK(worker_second.mesh.faces == worker_first.mesh.faces);
    CHECK(worker_second.mesh.cell_ids == worker_first.mesh.cell_ids);

    bifrost_scales::clear_native_stage_cache();
    (void)bifrost_scales::generate(
        mesh,
        cache_settings,
        PreviewMode::Settled);
    cache_settings.curvature += 0.17;
    const GenerationResult cache_shape = bifrost_scales::generate(
        mesh,
        cache_settings,
        PreviewMode::Settled);
    CHECK(cache_shape.profile.distribution_cache_hit);
    CHECK(cache_shape.profile.orientation_cache_hit);
    CHECK(cache_shape.profile.cell_cache_hit);
    CHECK(cache_shape.mesh.vertices != cache_first.mesh.vertices);
    cache_settings.direction_degrees += 11.0;
    const GenerationResult cache_direction = bifrost_scales::generate(
        mesh,
        cache_settings,
        PreviewMode::Settled);
    CHECK(cache_direction.profile.distribution_cache_hit);
    CHECK(!cache_direction.profile.orientation_cache_hit);
    CHECK(cache_direction.profile.cell_cache_hit);
    CHECK(cache_direction.profile.cell_cache_reused_after_orientation_change);
    bifrost_scales::clear_native_stage_cache();
    const GenerationResult cache_direction_cold = bifrost_scales::generate(
        mesh,
        cache_settings,
        PreviewMode::Settled);
    CHECK(cache_direction.mesh.vertices == cache_direction_cold.mesh.vertices);
    CHECK(cache_direction.mesh.faces == cache_direction_cold.mesh.faces);
    CHECK(cache_direction.mesh.cell_ids == cache_direction_cold.mesh.cell_ids);

    cache_settings.cell_gap += 0.035;
    const GenerationResult cache_cell = bifrost_scales::generate(
        mesh,
        cache_settings,
        PreviewMode::Settled);
    CHECK(cache_cell.profile.distribution_cache_hit);
    CHECK(cache_cell.profile.orientation_cache_hit);
    CHECK(!cache_cell.profile.cell_cache_hit);

    bifrost_scales::clear_native_stage_cache();
    Guide cache_curve;
    cache_curve.id = "cache-curve";
    cache_curve.kind = GuideKind::DirectionCurve;
    cache_curve.points = {{-0.7, 0.0, -0.2}, {0.7, 0.0, 0.2}};
    cache_curve.radius = 0.4;
    cache_curve.strength = 0.8;
    cache_curve.use_density = false;
    cache_curve.use_size = false;
    cache_curve.use_direction = true;
    Settings guide_cache_settings = coverage_settings;
    guide_cache_settings.target_count = 41U;
    guide_cache_settings.settled_budget = 41U;
    (void)bifrost_scales::generate(
        mesh,
        guide_cache_settings,
        PreviewMode::Settled,
        {cache_curve});
    cache_curve.radius = 1.4;
    const GenerationResult radius_edit = bifrost_scales::generate(
        mesh,
        guide_cache_settings,
        PreviewMode::Settled,
        {cache_curve});
    CHECK(radius_edit.profile.distribution_cache_hit);
    CHECK(!radius_edit.profile.orientation_cache_hit);
    CHECK(radius_edit.profile.cell_cache_hit);
    CHECK(radius_edit.profile.cell_cache_reused_after_orientation_change);
    bifrost_scales::clear_native_stage_cache();
    const GenerationResult radius_edit_cold = bifrost_scales::generate(
        mesh,
        guide_cache_settings,
        PreviewMode::Settled,
        {cache_curve});
    CHECK(radius_edit.mesh.vertices == radius_edit_cold.mesh.vertices);
    CHECK(radius_edit.mesh.faces == radius_edit_cold.mesh.faces);
    CHECK(radius_edit.mesh.cell_ids == radius_edit_cold.mesh.cell_ids);
    cache_curve.strength = 0.35;
    const GenerationResult centerline_edit = bifrost_scales::generate(
        mesh,
        guide_cache_settings,
        PreviewMode::Settled,
        {cache_curve});
    CHECK(centerline_edit.profile.distribution_cache_hit);
    CHECK(!centerline_edit.profile.orientation_cache_hit);
    CHECK(centerline_edit.profile.cell_cache_hit);
    CHECK(centerline_edit.profile.cell_cache_reused_after_orientation_change);
    cache_curve.strength = 0.0;
    const GenerationResult centerline_disabled = bifrost_scales::generate(
        mesh,
        guide_cache_settings,
        PreviewMode::Settled,
        {cache_curve});
    CHECK(!centerline_disabled.profile.distribution_cache_hit);

    Mesh disconnected_boundary;
    disconnected_boundary.vertices = {
        {-2.0, 0.0, -0.5}, {-1.0, 0.0, -0.5}, {-1.5, 0.0, 0.5},
        {1.0, 0.0, -0.5}, {2.0, 0.0, -0.5}, {1.5, 0.0, 0.5},
    };
    disconnected_boundary.triangles = {{0U, 2U, 1U}, {3U, 5U, 4U}};
    Settings disconnected_settings;
    disconnected_settings.target_count = 2U;
    disconnected_settings.settled_budget = 2U;
    disconnected_settings.seed = 11U;
    const bifrost_scales::DistributionResult disconnected = bifrost_scales::distribute(
        disconnected_boundary,
        disconnected_settings,
        PreviewMode::Settled);
    CHECK(disconnected.report.open_boundary_edge_count == 6U);
    CHECK(disconnected.report.boundary_anchor_count == 2U);
    CHECK(disconnected.samples.size() == 2U);
    CHECK((disconnected.samples[0].position.x < 0.0) !=
          (disconnected.samples[1].position.x < 0.0));

    // Stable Cell IDs are deterministic, unique, and metadata is opt-in.
    Settings identity_settings = coverage_settings;
    identity_settings.target_count = 24U;
    identity_settings.settled_budget = 24U;
    identity_settings.seed = 137U;
    bifrost_scales::clear_native_stage_cache();
    const GenerationResult identity_first = bifrost_scales::generate(
        mesh,
        identity_settings,
        PreviewMode::Settled);
    CHECK(identity_first.mesh.cell_ids.size() == identity_first.mesh.scale_count);
    CHECK(!identity_first.mesh.cell_ids.empty());
    std::set<std::uint64_t> unique_identity_ids(
        identity_first.mesh.cell_ids.begin(),
        identity_first.mesh.cell_ids.end());
    CHECK(unique_identity_ids.size() == identity_first.mesh.cell_ids.size());

    bifrost_scales::GenerationOptions metadata_options;
    metadata_options.cell_metadata_indices = {0U};
    metadata_options.resolve_cell_ids = {identity_first.mesh.cell_ids.back()};
    const GenerationResult identity_query = bifrost_scales::generate(
        mesh,
        identity_settings,
        PreviewMode::Settled,
        {},
        metadata_options);
    CHECK(identity_query.mesh.cell_ids == identity_first.mesh.cell_ids);
    CHECK(identity_query.mesh.cell_metadata.size() ==
          (identity_first.mesh.scale_count == 1U ? 1U : 2U));
    CHECK(identity_query.mesh.cell_metadata.front().scale_index == 0U);
    CHECK(identity_query.mesh.cell_metadata.front().cell_id ==
          identity_first.mesh.cell_ids.front());
    CHECK(identity_query.mesh.cell_metadata.back().cell_id ==
          identity_first.mesh.cell_ids.back());

    bifrost_scales::clear_native_stage_cache();
    const GenerationResult identity_repeat = bifrost_scales::generate(
        mesh,
        identity_settings,
        PreviewMode::Settled);
    CHECK(identity_repeat.mesh.cell_ids == identity_first.mesh.cell_ids);


    // Deterministic multicore execution must preserve the exact serial result.
    Settings multicore_settings = coverage_settings;
    multicore_settings.target_count = 768U;
    multicore_settings.settled_budget = 768U;
    multicore_settings.seed = 907U;
    multicore_settings.relax_iterations = 1U;
    multicore_settings.direction_relax_iterations = 2U;
    multicore_settings.cell_settled_resolution = 10U;
    multicore_settings.cell_shape_divisions = 2U;
    bifrost_scales::GenerationOptions multicore_options;
    multicore_options.include_flat_topology = true;
    multicore_options.cell_metadata_indices = {0U, 200U, 500U};

    set_cpu_thread_override("1");
    bifrost_scales::clear_native_stage_cache();
    const GenerationResult serial_multicore_reference = bifrost_scales::generate(
        mesh,
        multicore_settings,
        PreviewMode::Settled,
        {cache_curve},
        {},
        multicore_options);
    CHECK(serial_multicore_reference.profile.orientation_worker_threads == 1U);
    CHECK(serial_multicore_reference.profile.cell_worker_threads == 1U);
    CHECK(serial_multicore_reference.profile.shape_worker_threads == 1U);

    set_cpu_thread_override("8");
    bifrost_scales::clear_native_stage_cache();
    const GenerationResult parallel_multicore_result = bifrost_scales::generate(
        mesh,
        multicore_settings,
        PreviewMode::Settled,
        {cache_curve},
        {},
        multicore_options);
    CHECK(parallel_multicore_result.profile.orientation_worker_threads > 1U);
    CHECK(parallel_multicore_result.profile.cell_worker_threads > 1U);
    CHECK(parallel_multicore_result.profile.shape_worker_threads > 1U);
    CHECK(parallel_multicore_result.mesh.vertices ==
          serial_multicore_reference.mesh.vertices);
    CHECK(parallel_multicore_result.mesh.faces ==
          serial_multicore_reference.mesh.faces);
    CHECK(parallel_multicore_result.mesh.face_offsets ==
          serial_multicore_reference.mesh.face_offsets);
    CHECK(parallel_multicore_result.mesh.face_vertices ==
          serial_multicore_reference.mesh.face_vertices);
    CHECK(parallel_multicore_result.mesh.uvs ==
          serial_multicore_reference.mesh.uvs);
    CHECK(parallel_multicore_result.mesh.colors ==
          serial_multicore_reference.mesh.colors);
    CHECK(parallel_multicore_result.mesh.scale_type_ids ==
          serial_multicore_reference.mesh.scale_type_ids);
    CHECK(parallel_multicore_result.mesh.cell_ids ==
          serial_multicore_reference.mesh.cell_ids);
    CHECK(parallel_multicore_result.mesh.cell_metadata.size() ==
          serial_multicore_reference.mesh.cell_metadata.size());
    for (std::size_t index = 0U;
         index < parallel_multicore_result.mesh.cell_metadata.size();
         ++index) {
        CHECK(cell_metadata_equal(
            parallel_multicore_result.mesh.cell_metadata[index],
            serial_multicore_reference.mesh.cell_metadata[index]));
    }
    set_cpu_thread_override("0");

    // GPU is optional and must never make the operator unavailable. An
    // explicit off policy exercises the same deterministic CPU path used by
    // unsupported GPUs, missing OpenCL runtimes, and production Final output.
    Settings gpu_fallback_settings = coverage_settings;
    gpu_fallback_settings.target_count = 512U;
    gpu_fallback_settings.interactive_budget = 512U;
    gpu_fallback_settings.cell_mode = GeometryMode::Cards;
    gpu_fallback_settings.direction_relax_iterations = 0U;
    set_gpu_override("off");
    bifrost_scales::clear_native_stage_cache();
    const GenerationResult gpu_disabled = bifrost_scales::generate(
        mesh,
        gpu_fallback_settings,
        PreviewMode::Interactive,
        {cache_curve});
    CHECK(!gpu_disabled.profile.gpu_compute_requested);
    CHECK(!gpu_disabled.profile.gpu_compute_used);
    CHECK(gpu_disabled.profile.gpu_compute_backend == "cpu-multicore");
    CHECK(gpu_disabled.profile.gpu_fallback_reason.find("disabled") !=
          std::string::npos);
    CHECK(gpu_disabled.mesh.scale_count > 0U);
    set_gpu_override("force");
    bifrost_scales::clear_native_stage_cache();
    const GenerationResult gpu_attempt = bifrost_scales::generate(
        mesh,
        gpu_fallback_settings,
        PreviewMode::Interactive,
        {cache_curve});
    CHECK(gpu_attempt.profile.gpu_compute_requested);
    CHECK(gpu_attempt.mesh.scale_count > 0U);
    if (gpu_attempt.profile.gpu_compute_used) {
        CHECK(gpu_attempt.profile.gpu_compute_available);
        CHECK(gpu_attempt.profile.orientation_worker_threads == 0U);
        CHECK(gpu_attempt.profile.gpu_sample_count ==
              gpu_attempt.report.accepted_count);
    } else {
        CHECK(!gpu_attempt.profile.gpu_fallback_reason.empty());
        CHECK(gpu_attempt.profile.orientation_worker_threads >= 1U);
    }
    set_gpu_override("auto");

    // Interactive Candidate Batch is an isolated, counter-based Preview
    // foundation. It must be deterministic, prefix-stable, compact, and have
    // no effect on the exact Stage Cache or settled output.
    Settings candidate_settings;
    candidate_settings.seed = 1106U;
    const auto candidate_small =
        bifrost_scales::build_interactive_candidate_batch(
            mesh,
            candidate_settings,
            32U);
    const auto candidate_repeat =
        bifrost_scales::build_interactive_candidate_batch(
            mesh,
            candidate_settings,
            32U);
    const auto candidate_large =
        bifrost_scales::build_interactive_candidate_batch(
            mesh,
            candidate_settings,
            128U);
    CHECK(candidate_small.has_consistent_sizes());
    CHECK(candidate_small.upload_bytes() == 32U * 72U);
    CHECK(candidate_small.positions_xyz == candidate_repeat.positions_xyz);
    CHECK(candidate_small.normals_xyz == candidate_repeat.normals_xyz);
    CHECK(candidate_small.barycentric == candidate_repeat.barycentric);
    CHECK(candidate_small.random_values == candidate_repeat.random_values);
    CHECK(candidate_small.triangle_indices == candidate_repeat.triangle_indices);
    CHECK(candidate_small.candidate_keys == candidate_repeat.candidate_keys);
    CHECK(std::equal(
        candidate_small.positions_xyz.begin(),
        candidate_small.positions_xyz.end(),
        candidate_large.positions_xyz.begin()));
    CHECK(std::equal(
        candidate_small.random_values.begin(),
        candidate_small.random_values.end(),
        candidate_large.random_values.begin()));
    CHECK(std::equal(
        candidate_small.candidate_keys.begin(),
        candidate_small.candidate_keys.end(),
        candidate_large.candidate_keys.begin()));
    CHECK(std::set<std::uint64_t>(
              candidate_large.candidate_keys.begin(),
              candidate_large.candidate_keys.end()).size() ==
          candidate_large.candidate_keys.size());
    for (std::size_t index = 0U; index < candidate_small.candidate_count; ++index) {
        const float sum = candidate_small.barycentric[index * 3U] +
            candidate_small.barycentric[index * 3U + 1U] +
            candidate_small.barycentric[index * 3U + 2U];
        CHECK(std::abs(sum - 1.0F) < 2.0e-7F);
        CHECK(candidate_small.triangle_indices[index] < mesh.triangles.size());
    }
    Settings changed_candidate_seed = candidate_settings;
    changed_candidate_seed.seed += 1U;
    const auto candidate_changed =
        bifrost_scales::build_interactive_candidate_batch(
            mesh,
            changed_candidate_seed,
            32U);
    CHECK(candidate_changed.positions_xyz != candidate_small.positions_xyz);
    CHECK(candidate_changed.candidate_keys != candidate_small.candidate_keys);

    bifrost_scales::clear_native_stage_cache();
    const GenerationResult settled_before_candidate_batch =
        bifrost_scales::generate(mesh, coverage_settings, PreviewMode::Settled);
    (void)bifrost_scales::build_interactive_candidate_batch(
        mesh,
        candidate_settings,
        512U);
    bifrost_scales::clear_native_stage_cache();
    const GenerationResult settled_after_candidate_batch =
        bifrost_scales::generate(mesh, coverage_settings, PreviewMode::Settled);
    CHECK(settled_after_candidate_batch.mesh.vertices ==
          settled_before_candidate_batch.mesh.vertices);
    CHECK(settled_after_candidate_batch.mesh.faces ==
          settled_before_candidate_batch.mesh.faces);
    CHECK(settled_after_candidate_batch.mesh.cell_ids ==
          settled_before_candidate_batch.mesh.cell_ids);

    std::cout << "bifrost_scales_core_tests: PASS\n";
    return 0;
    } catch (const std::exception& error) {
        std::cerr << "bifrost_scales_core_tests: FAIL: " << error.what() << "\n";
        return 1;
    }
}
