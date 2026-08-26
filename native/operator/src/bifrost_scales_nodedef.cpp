#include "bifrost_scales_nodedef.hpp"

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <limits>
#include <locale>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "bifrost_scales/core.hpp"
#include "bifrost_scales/payload.hpp"

namespace {

using BifrostLong = Amino::long_t;
using BifrostUInt = Amino::uint_t;

void initialize_outputs(
    Amino::MutablePtr<Amino::Array<Bifrost::Math::float3>>& positions,
    Amino::MutablePtr<Amino::Array<BifrostUInt>>& face_offsets,
    Amino::MutablePtr<Amino::Array<BifrostUInt>>& face_vertices,
    Amino::MutablePtr<Amino::Array<Bifrost::Math::float2>>& uvs,
    Amino::MutablePtr<Amino::Array<Bifrost::Math::float4>>& colors,
    Amino::MutablePtr<Amino::Array<BifrostLong>>& type_ids) {
    positions = Amino::newMutablePtr<Amino::Array<Bifrost::Math::float3>>();
    face_offsets = Amino::newMutablePtr<Amino::Array<BifrostUInt>>();
    face_vertices = Amino::newMutablePtr<Amino::Array<BifrostUInt>>();
    uvs = Amino::newMutablePtr<Amino::Array<Bifrost::Math::float2>>();
    colors = Amino::newMutablePtr<Amino::Array<Bifrost::Math::float4>>();
    type_ids = Amino::newMutablePtr<Amino::Array<BifrostLong>>();
}

bool append_polygon_as_triangles(
    const Amino::Array<BifrostUInt>& indices,
    std::size_t begin,
    std::size_t end,
    std::size_t vertex_count,
    bifrost_scales::Mesh& mesh,
    std::string& error) {
    if (end <= begin || end - begin < 3U || end > indices.size()) {
        return true;
    }
    const BifrostUInt first_raw = indices[begin];
    if (static_cast<std::size_t>(first_raw) >= vertex_count) {
        error = "source face contains an invalid vertex index";
        return false;
    }
    const auto first = static_cast<std::uint32_t>(first_raw);
    for (std::size_t cursor = begin + 1U; cursor + 1U < end; ++cursor) {
        const BifrostUInt second_raw = indices[cursor];
        const BifrostUInt third_raw = indices[cursor + 1U];
        if (static_cast<std::size_t>(second_raw) >= vertex_count ||
            static_cast<std::size_t>(third_raw) >= vertex_count) {
            error = "source face contains an invalid vertex index";
            return false;
        }
        mesh.triangles.push_back({
            first,
            static_cast<std::uint32_t>(second_raw),
            static_cast<std::uint32_t>(third_raw),
        });
    }
    return true;
}

bool decode_source_mesh(
    const Amino::Array<Bifrost::Math::float3>& source_positions,
    const Amino::Array<BifrostUInt>& source_offsets,
    const Amino::Array<BifrostUInt>& source_indices,
    bifrost_scales::Mesh& mesh,
    std::string& error) {
    if (source_positions.empty()) {
        error = "source mesh has no positions";
        return false;
    }
    if (source_offsets.empty() || source_indices.empty()) {
        error = "source mesh has no face topology";
        return false;
    }
    if (source_positions.size() >
        static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max())) {
        error = "source mesh exceeds the supported vertex index range";
        return false;
    }
    mesh.vertices.reserve(source_positions.size());
    for (const Bifrost::Math::float3& point : source_positions) {
        mesh.vertices.push_back({point.x, point.y, point.z});
    }

    const bool cumulative_with_zero =
        source_offsets.size() >= 2U && source_offsets.front() == 0;
    if (cumulative_with_zero) {
        for (std::size_t face = 0U; face + 1U < source_offsets.size(); ++face) {
            const BifrostUInt begin_raw = source_offsets[face];
            const BifrostUInt end_raw = source_offsets[face + 1U];
            if (end_raw < begin_raw) {
                error = "source face offsets are invalid";
                return false;
            }
            if (!append_polygon_as_triangles(
                    source_indices,
                    static_cast<std::size_t>(begin_raw),
                    static_cast<std::size_t>(end_raw),
                    mesh.vertices.size(),
                    mesh,
                    error)) {
                return false;
            }
        }
    } else {
        std::size_t begin = 0U;
        for (const BifrostUInt end_raw : source_offsets) {
            if (static_cast<std::size_t>(end_raw) < begin) {
                error = "source face offsets are invalid";
                return false;
            }
            const std::size_t end = static_cast<std::size_t>(end_raw);
            if (!append_polygon_as_triangles(
                    source_indices,
                    begin,
                    end,
                    mesh.vertices.size(),
                    mesh,
                    error)) {
                return false;
            }
            begin = end;
        }
    }
    if (mesh.triangles.empty()) {
        error = "source mesh contains no valid polygon triangles";
        return false;
    }
    return true;
}

void encode_generated_mesh(
    const bifrost_scales::GeneratedMesh& mesh,
    Amino::Array<Bifrost::Math::float3>& positions,
    Amino::Array<BifrostUInt>& face_offsets,
    Amino::Array<BifrostUInt>& face_vertices,
    Amino::Array<Bifrost::Math::float2>& uvs,
    Amino::Array<Bifrost::Math::float4>& colors,
    Amino::Array<BifrostLong>& type_ids) {
    const std::size_t uint_max =
        static_cast<std::size_t>(std::numeric_limits<BifrostUInt>::max());
    if (mesh.vertices.size() > uint_max) {
        throw std::overflow_error(
            "generated mesh exceeds Bifrost uint point-index capacity");
    }
    if (mesh.face_count() >= uint_max) {
        throw std::overflow_error(
            "generated mesh exceeds Bifrost uint face-offset capacity");
    }

    positions.reserve(mesh.vertices.size());
    for (const bifrost_scales::Vec3& point : mesh.vertices) {
        positions.push_back({
            static_cast<float>(point.x),
            static_cast<float>(point.y),
            static_cast<float>(point.z),
        });
    }

    if (!mesh.face_offsets.empty()) {
        if (mesh.face_offsets.front() != 0U ||
            static_cast<std::size_t>(mesh.face_offsets.back()) !=
                mesh.face_vertices.size()) {
            throw std::runtime_error(
                "generated mesh flat topology offsets are invalid");
        }
        if (mesh.face_vertices.size() > uint_max) {
            throw std::overflow_error(
                "generated mesh exceeds Bifrost uint face-vertex capacity");
        }
        face_offsets.reserve(mesh.face_offsets.size());
        for (const std::uint32_t offset : mesh.face_offsets) {
            if (static_cast<std::size_t>(offset) > uint_max) {
                throw std::overflow_error(
                    "generated mesh contains an unsupported face offset");
            }
            face_offsets.push_back(static_cast<BifrostUInt>(offset));
        }
        face_vertices.reserve(mesh.face_vertices.size());
        for (const std::uint32_t index : mesh.face_vertices) {
            if (static_cast<std::size_t>(index) >= mesh.vertices.size()) {
                throw std::runtime_error(
                    "generated mesh contains an invalid face vertex index");
            }
            face_vertices.push_back(static_cast<BifrostUInt>(index));
        }
    } else {
        face_offsets.reserve(mesh.faces.size() + 1U);
        face_offsets.push_back(0U);
        for (const std::vector<std::uint32_t>& face : mesh.faces) {
            if (face.size() > uint_max - face_vertices.size()) {
                throw std::overflow_error(
                    "generated mesh exceeds Bifrost uint face-vertex capacity");
            }
            for (const std::uint32_t index : face) {
                if (static_cast<std::size_t>(index) >= mesh.vertices.size()) {
                    throw std::runtime_error(
                        "generated mesh contains an invalid face vertex index");
                }
                face_vertices.push_back(static_cast<BifrostUInt>(index));
            }
            face_offsets.push_back(
                static_cast<BifrostUInt>(face_vertices.size()));
        }
    }

    uvs.reserve(mesh.uvs.size());
    for (const bifrost_scales::Vec2& uv : mesh.uvs) {
        uvs.push_back({static_cast<float>(uv.x), static_cast<float>(uv.y)});
    }
    colors.reserve(mesh.colors.size());
    for (const bifrost_scales::Color4& color : mesh.colors) {
        colors.push_back({
            static_cast<float>(color.r),
            static_cast<float>(color.g),
            static_cast<float>(color.b),
            static_cast<float>(color.a),
        });
    }
    type_ids.reserve(mesh.scale_type_ids.size());
    for (const std::uint32_t value : mesh.scale_type_ids) {
        type_ids.push_back(static_cast<BifrostLong>(value));
    }
}

std::string hex_u64(std::uint64_t value) {
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::hex << std::nouppercase << std::setw(16)
           << std::setfill('0') << value;
    return stream.str();
}

void append_vec3_json(std::ostringstream& stream, const bifrost_scales::Vec3& value) {
    stream << '[' << value.x << ',' << value.y << ',' << value.z << ']';
}

void append_json_string(std::ostringstream& stream, const std::string& value) {
    stream << '"';
    for (const unsigned char character : value) {
        switch (character) {
            case '"': stream << "\\\""; break;
            case '\\': stream << "\\\\"; break;
            case '\b': stream << "\\b"; break;
            case '\f': stream << "\\f"; break;
            case '\n': stream << "\\n"; break;
            case '\r': stream << "\\r"; break;
            case '\t': stream << "\\t"; break;
            default:
                if (character < 0x20U) {
                    stream << "\\u00" << std::hex << std::setw(2)
                           << std::setfill('0') << static_cast<unsigned int>(character)
                           << std::dec << std::setfill(' ');
                } else {
                    stream << static_cast<char>(character);
                }
                break;
        }
    }
    stream << '"';
}

std::string make_profile_json(
    double payload_decode_ms,
    double source_decode_ms,
    const bifrost_scales::GenerationProfile& generation,
    double encode_ms,
    double operator_total_ms,
    const bifrost_scales::GeneratedMesh& mesh,
    const bifrost_scales::GenerationReport& report,
    const bifrost_scales::NativePayload& payload) {
    std::set<std::uint64_t> available_cell_ids;
    for (const bifrost_scales::CellMetadata& metadata : mesh.cell_metadata) {
        available_cell_ids.insert(metadata.cell_id);
    }

    std::vector<std::uint64_t> resolved_cell_ids;
    std::vector<std::uint64_t> orphaned_cell_ids;
    resolved_cell_ids.reserve(payload.resolve_cell_ids.size());
    orphaned_cell_ids.reserve(payload.resolve_cell_ids.size());
    for (const std::uint64_t cell_id : payload.resolve_cell_ids) {
        if (available_cell_ids.find(cell_id) != available_cell_ids.end()) {
            resolved_cell_ids.push_back(cell_id);
        } else {
            orphaned_cell_ids.push_back(cell_id);
        }
    }

    std::uint64_t faces_per_scale = 0U;
    if (mesh.scale_count > 0U && mesh.face_count() % mesh.scale_count == 0U) {
        faces_per_scale = mesh.face_count() / mesh.scale_count;
    }

    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::fixed << std::setprecision(6);
    stream
        << "{\"schema\":\"bifrost-scales/native-profile/9\""
        << ",\"compute_backend\":";
    append_json_string(stream, generation.gpu_compute_backend);
    stream
        << ",\"gpu_compute\":"
        << (generation.gpu_compute_used ? "true" : "false")
        << ",\"gpu_compute_requested\":"
        << (generation.gpu_compute_requested ? "true" : "false")
        << ",\"gpu_compute_available\":"
        << (generation.gpu_compute_available ? "true" : "false")
        << ",\"gpu_stage\":\"interactive-orientation\""
        << ",\"gpu_buffer_schema\":\"bifrost-scales/compact-orientation-buffer/1\""
        << ",\"gpu_device\":";
    append_json_string(stream, generation.gpu_device);
    stream << ",\"gpu_fallback_reason\":";
    append_json_string(stream, generation.gpu_fallback_reason);
    stream
        << ",\"gpu_upload_ms\":" << generation.gpu_upload_ms
        << ",\"gpu_kernel_ms\":" << generation.gpu_kernel_ms
        << ",\"gpu_readback_ms\":" << generation.gpu_readback_ms
        << ",\"gpu_sample_count\":" << generation.gpu_sample_count
        << ",\"cell_metadata_schema\":\"bifrost-scales/cell-metadata/1\""
        << ",\"payload_decode_ms\":" << payload_decode_ms
        << ",\"source_decode_ms\":" << source_decode_ms
        << ",\"distribution_ms\":" << generation.distribution_ms
        << ",\"orientation_ms\":" << generation.orientation_ms
        << ",\"cells_ms\":" << generation.cells_ms
        << ",\"cell_setup_ms\":" << generation.cell_setup_ms
        << ",\"cell_neighbors_ms\":" << generation.cell_neighbors_ms
        << ",\"cell_boundaries_ms\":" << generation.cell_boundaries_ms
        << ",\"cell_boundary_query_ms\":"
        << generation.cell_boundary_query_ms
        << ",\"cell_boundary_rays_ms\":"
        << generation.cell_boundary_rays_ms
        << ",\"cell_projection_ms\":" << generation.cell_projection_ms
        << ",\"shape_ms\":" << generation.shape_ms
        << ",\"core_total_ms\":" << generation.total_ms
        << ",\"distribution_cache_hit\":"
        << (generation.distribution_cache_hit ? "true" : "false")
        << ",\"orientation_cache_hit\":"
        << (generation.orientation_cache_hit ? "true" : "false")
        << ",\"cell_cache_hit\":"
        << (generation.cell_cache_hit ? "true" : "false")
        << ",\"cell_cache_basis\":\"distribution\""
        << ",\"cell_cache_reused_after_orientation_change\":"
        << (generation.cell_cache_reused_after_orientation_change
                ? "true"
                : "false")
        << ",\"stage_cache_scope\":";
    append_json_string(stream, generation.stage_cache_scope);
    stream
        << ",\"stage_cache_capacity\":" << generation.stage_cache_capacity
        << ",\"stage_cache_evictions\":" << generation.stage_cache_evictions
        << ",\"distribution_worker_threads\":"
        << generation.distribution_worker_threads
        << ",\"orientation_worker_threads\":"
        << generation.orientation_worker_threads
        << ",\"cell_worker_threads\":"
        << generation.cell_worker_threads
        << ",\"shape_worker_threads\":"
        << generation.shape_worker_threads
        << ",\"encode_ms\":" << encode_ms
        << ",\"operator_total_ms\":" << operator_total_ms
        << ",\"point_count\":" << mesh.vertices.size()
        << ",\"face_count\":" << mesh.face_count()
        << ",\"face_vertex_count\":" << mesh.face_vertex_count()
        << ",\"scale_count\":" << mesh.scale_count
        << ",\"faces_per_scale\":" << faces_per_scale
        << ",\"guide_count\":"
        << (report.density_guide_count + report.direction_guide_count)
        << ",\"mask_guide_count\":" << report.mask_guide_count
        << ",\"masked_candidate_count\":" << report.masked_candidate_count
        << ",\"open_boundary_edge_count\":" << report.open_boundary_edge_count
        << ",\"boundary_anchor_count\":" << report.boundary_anchor_count
        << ",\"boundary_density_adapted\":"
        << (report.boundary_density_adapted ? "true" : "false")
        << ",\"cell_clipped_rays\":" << report.cell_clipped_rays
        << ",\"cell_mean_neighbors\":" << report.cell_mean_neighbors
        << ",\"boundary_clipped_rays\":" << report.boundary_clipped_rays
        << ",\"mask_clipped_rays\":" << report.mask_clipped_rays
        << ",\"symmetry_stabilized_cells\":"
        << report.symmetry_stabilized_cells
        << ",\"auxiliary_arrays_emitted\":"
        << ((!mesh.uvs.empty() || !mesh.colors.empty() ||
             !mesh.scale_type_ids.empty()) ? "true" : "false")
        << ",\"flat_topology\":"
        << (!mesh.face_offsets.empty() ? "true" : "false")
        << ",\"selected_cells\":[";

    for (std::size_t index = 0U; index < mesh.cell_metadata.size(); ++index) {
        const bifrost_scales::CellMetadata& metadata = mesh.cell_metadata[index];
        if (index > 0U) {
            stream << ',';
        }
        stream << "{\"index\":" << metadata.scale_index
               << ",\"cell_id\":\"" << hex_u64(metadata.cell_id) << "\""
               << ",\"position\":";
        append_vec3_json(stream, metadata.position);
        stream << ",\"normal\":";
        append_vec3_json(stream, metadata.normal);
        stream << ",\"triangle_index\":" << metadata.triangle_index
               << ",\"barycentric\":["
               << metadata.barycentric[0] << ','
               << metadata.barycentric[1] << ','
               << metadata.barycentric[2] << ']'
               << ",\"boundary_signature\":\""
               << hex_u64(metadata.boundary_signature) << "\"}";
    }
    stream << "]";

    stream << ",\"resolved_cell_ids\":[";
    for (std::size_t index = 0U; index < resolved_cell_ids.size(); ++index) {
        if (index > 0U) {
            stream << ',';
        }
        stream << '\"' << hex_u64(resolved_cell_ids[index]) << '\"';
    }
    stream << "]";

    stream << ",\"orphaned_cell_ids\":[";
    for (std::size_t index = 0U; index < orphaned_cell_ids.size(); ++index) {
        if (index > 0U) {
            stream << ',';
        }
        stream << '\"' << hex_u64(orphaned_cell_ids[index]) << '\"';
    }
    stream << "]}";
    return stream.str();
}

}  // namespace

void BifrostScales::generate_scale_mesh_payload_arrays(
    const Amino::Ptr<Amino::Array<Bifrost::Math::float3>>& source_point_position,
    const Amino::Ptr<Amino::Array<Amino::uint_t>>& source_face_offset,
    const Amino::Ptr<Amino::Array<Amino::uint_t>>& source_face_vertex,
    const Amino::String& payload_json,
    Amino::MutablePtr<Amino::Array<Bifrost::Math::float3>>& point_position,
    Amino::MutablePtr<Amino::Array<Amino::uint_t>>& face_offset,
    Amino::MutablePtr<Amino::Array<Amino::uint_t>>& face_vertex,
    Amino::MutablePtr<Amino::Array<Bifrost::Math::float2>>& uv,
    Amino::MutablePtr<Amino::Array<Bifrost::Math::float4>>& color,
    Amino::MutablePtr<Amino::Array<Amino::long_t>>& scale_type_id,
    Amino::long_t& scale_count,
    Amino::long_t& point_count,
    Amino::long_t& face_count,
    Amino::String& profile_json,
    bool& success,
    Amino::String& status) {
    using Clock = std::chrono::steady_clock;
    const auto operator_started = Clock::now();

    initialize_outputs(
        point_position,
        face_offset,
        face_vertex,
        uv,
        color,
        scale_type_id);
    scale_count = 0;
    point_count = 0;
    face_count = 0;
    profile_json = "{}";
    success = false;
    status = "not evaluated";

    try {
        if (!source_point_position || !source_face_offset || !source_face_vertex) {
            status = "source mesh arrays are not connected";
            return;
        }

        const auto payload_started = Clock::now();
        const bifrost_scales::PayloadDecodeResult decoded =
            bifrost_scales::decode_native_payload(payload_json.c_str());
        const double payload_decode_ms =
            std::chrono::duration<double, std::milli>(
                Clock::now() - payload_started).count();
        if (!decoded.success) {
            status = decoded.status.c_str();
            return;
        }

        const auto source_started = Clock::now();
        bifrost_scales::Mesh source_mesh;
        std::string mesh_error;
        if (!decode_source_mesh(
                *source_point_position,
                *source_face_offset,
                *source_face_vertex,
                source_mesh,
                mesh_error)) {
            status = mesh_error.c_str();
            return;
        }
        const double source_decode_ms =
            std::chrono::duration<double, std::milli>(
                Clock::now() - source_started).count();
        bifrost_scales::GenerationOptions generation_options;
        generation_options.include_uvs = false;
        generation_options.include_colors = false;
        generation_options.include_scale_type_ids = false;
        generation_options.materialize_faces = false;
        generation_options.include_flat_topology = true;
        generation_options.include_cell_ids = false;
        generation_options.cell_metadata_indices =
            decoded.payload.cell_metadata_indices;
        generation_options.resolve_cell_ids = decoded.payload.resolve_cell_ids;

        const bifrost_scales::GenerationResult generated =
            bifrost_scales::generate(
                source_mesh,
                decoded.payload.settings,
                decoded.payload.mode,
                decoded.payload.guides,
                decoded.payload.symmetry_planes,
                generation_options);

        const auto encode_started = Clock::now();
        encode_generated_mesh(
            generated.mesh,
            *point_position,
            *face_offset,
            *face_vertex,
            *uv,
            *color,
            *scale_type_id);
        const double encode_ms =
            std::chrono::duration<double, std::milli>(
                Clock::now() - encode_started).count();
        const double operator_total_ms =
            std::chrono::duration<double, std::milli>(
                Clock::now() - operator_started).count();

        scale_count = static_cast<BifrostLong>(generated.mesh.scale_count);
        point_count = static_cast<BifrostLong>(generated.mesh.vertices.size());
        face_count = static_cast<BifrostLong>(generated.mesh.face_count());
        const std::string profile = make_profile_json(
            payload_decode_ms,
            source_decode_ms,
            generated.profile,
            encode_ms,
            operator_total_ms,
            generated.mesh,
            generated.report,
            decoded.payload);
        profile_json = profile.c_str();
        success = true;
        status = "ok";
    } catch (const std::exception& error) {
        status = error.what();
    } catch (...) {
        status = "unknown native operator error";
    }
}
