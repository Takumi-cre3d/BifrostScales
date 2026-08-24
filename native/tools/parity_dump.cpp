#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "bifrost_scales/core.hpp"
#include "bifrost_scales/payload.hpp"

namespace {

using bifrost_scales::CellData;
using bifrost_scales::Color4;
using bifrost_scales::GeneratedMesh;
using bifrost_scales::GenerationReport;
using bifrost_scales::Guide;
using bifrost_scales::Mesh;
using bifrost_scales::OrientedSample;
using bifrost_scales::PreviewMode;
using bifrost_scales::Sample;
using bifrost_scales::Settings;
using bifrost_scales::Vec2;
using bifrost_scales::Vec3;

std::string read_text(const std::string& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        throw std::runtime_error("cannot open file: " + path);
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    if (!stream.good() && !stream.eof()) {
        throw std::runtime_error("cannot read file: " + path);
    }
    return buffer.str();
}

std::string trim(std::string value) {
    const auto first = std::find_if_not(
        value.begin(), value.end(), [](unsigned char ch) { return std::isspace(ch) != 0; });
    const auto last = std::find_if_not(
        value.rbegin(), value.rend(), [](unsigned char ch) { return std::isspace(ch) != 0; }).base();
    if (first >= last) {
        return {};
    }
    return std::string(first, last);
}

std::int64_t parse_obj_index(const std::string& token, std::size_t vertex_count) {
    const std::size_t slash = token.find('/');
    const std::string raw = token.substr(0, slash);
    if (raw.empty()) {
        throw std::runtime_error("OBJ face contains an empty vertex index");
    }
    std::size_t parsed = 0U;
    const long long value = std::stoll(raw, &parsed, 10);
    if (parsed != raw.size() || value == 0) {
        throw std::runtime_error("OBJ face contains an invalid vertex index: " + raw);
    }
    const long long resolved = value > 0
        ? value - 1
        : static_cast<long long>(vertex_count) + value;
    if (resolved < 0 || static_cast<std::size_t>(resolved) >= vertex_count) {
        throw std::runtime_error("OBJ face vertex index is out of range: " + raw);
    }
    return static_cast<std::int64_t>(resolved);
}

Mesh load_obj(const std::string& path) {
    std::ifstream stream(path);
    if (!stream) {
        throw std::runtime_error("cannot open OBJ: " + path);
    }
    Mesh mesh;
    std::string line;
    std::size_t line_number = 0U;
    while (std::getline(stream, line)) {
        ++line_number;
        const std::size_t comment = line.find('#');
        if (comment != std::string::npos) {
            line.erase(comment);
        }
        line = trim(std::move(line));
        if (line.empty()) {
            continue;
        }
        std::istringstream parser(line);
        std::string kind;
        parser >> kind;
        if (kind == "v") {
            Vec3 point;
            if (!(parser >> point.x >> point.y >> point.z)) {
                throw std::runtime_error(
                    "OBJ vertex parse error at line " + std::to_string(line_number));
            }
            mesh.vertices.push_back(point);
            continue;
        }
        if (kind != "f") {
            continue;
        }
        std::vector<std::uint32_t> face;
        std::string token;
        while (parser >> token) {
            const auto index = parse_obj_index(token, mesh.vertices.size());
            if (static_cast<std::uint64_t>(index) >
                static_cast<std::uint64_t>(std::numeric_limits<std::uint32_t>::max())) {
                throw std::runtime_error("OBJ vertex index exceeds uint32 range");
            }
            face.push_back(static_cast<std::uint32_t>(index));
        }
        if (face.size() < 3U) {
            throw std::runtime_error(
                "OBJ face has fewer than three vertices at line " +
                std::to_string(line_number));
        }
        for (std::size_t index = 1U; index + 1U < face.size(); ++index) {
            mesh.triangles.push_back({face[0], face[index], face[index + 1U]});
        }
    }
    if (mesh.vertices.empty() || mesh.triangles.empty()) {
        throw std::runtime_error("OBJ must contain vertices and polygon faces");
    }
    return mesh;
}

std::vector<Sample> load_samples(const std::string& path, const Mesh& mesh) {
    std::ifstream stream(path);
    if (!stream) {
        throw std::runtime_error("cannot open replay samples: " + path);
    }
    std::vector<Sample> samples;
    std::string line;
    std::size_t line_number = 0U;
    while (std::getline(stream, line)) {
        ++line_number;
        const std::size_t comment = line.find('#');
        if (comment != std::string::npos) {
            line.erase(comment);
        }
        line = trim(std::move(line));
        if (line.empty()) {
            continue;
        }
        Sample sample;
        std::uint64_t triangle_index = 0U;
        std::istringstream parser(line);
        if (!(parser
              >> sample.position.x >> sample.position.y >> sample.position.z
              >> sample.normal.x >> sample.normal.y >> sample.normal.z
              >> triangle_index
              >> sample.barycentric[0] >> sample.barycentric[1] >> sample.barycentric[2]
              >> sample.random_size >> sample.random_rotation
              >> sample.random_type >> sample.random_shape
              >> sample.density_multiplier >> sample.size_multiplier
              >> sample.local_spacing)) {
            throw std::runtime_error(
                "replay sample parse error at line " + std::to_string(line_number));
        }
        std::string trailing;
        if (parser >> trailing) {
            throw std::runtime_error(
                "unexpected replay sample data at line " + std::to_string(line_number));
        }
        if (triangle_index >= mesh.triangles.size() ||
            triangle_index > std::numeric_limits<std::uint32_t>::max()) {
            throw std::runtime_error(
                "replay sample triangle index is out of range at line " +
                std::to_string(line_number));
        }
        sample.triangle_index = static_cast<std::uint32_t>(triangle_index);
        samples.push_back(sample);
    }
    if (samples.empty()) {
        throw std::runtime_error("replay samples file is empty");
    }
    return samples;
}

std::string escaped(std::string_view value) {
    std::ostringstream result;
    result << '"';
    for (const unsigned char ch : value) {
        switch (ch) {
            case '"': result << "\\\""; break;
            case '\\': result << "\\\\"; break;
            case '\b': result << "\\b"; break;
            case '\f': result << "\\f"; break;
            case '\n': result << "\\n"; break;
            case '\r': result << "\\r"; break;
            case '\t': result << "\\t"; break;
            default:
                if (ch < 0x20U) {
                    result << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                           << static_cast<unsigned int>(ch) << std::dec << std::setfill(' ');
                } else {
                    result << static_cast<char>(ch);
                }
                break;
        }
    }
    result << '"';
    return result.str();
}

const char* mode_name(PreviewMode mode) {
    switch (mode) {
        case PreviewMode::Interactive: return "interactive";
        case PreviewMode::Settled: return "settled";
        case PreviewMode::Final: return "final";
    }
    return "settled";
}

bool uses_cells(const Settings& settings, PreviewMode mode) {
    switch (settings.cell_mode) {
        case bifrost_scales::GeometryMode::Cards: return false;
        case bifrost_scales::GeometryMode::Cells: return true;
        case bifrost_scales::GeometryMode::Auto: return mode != PreviewMode::Interactive;
    }
    return mode != PreviewMode::Interactive;
}

void write_number(std::ostream& output, double value) {
    output << std::setprecision(std::numeric_limits<double>::max_digits10) << value;
}

void write_hex_u64(std::ostream& output, std::uint64_t value) {
    const auto flags = output.flags();
    const char fill = output.fill();
    output << '"' << std::hex << std::nouppercase << std::setw(16)
           << std::setfill('0') << value << '"';
    output.flags(flags);
    output.fill(fill);
}

void write_vec2(std::ostream& output, const Vec2& value) {
    output << '[';
    write_number(output, value.x);
    output << ',';
    write_number(output, value.y);
    output << ']';
}

void write_vec3(std::ostream& output, const Vec3& value) {
    output << '[';
    write_number(output, value.x);
    output << ',';
    write_number(output, value.y);
    output << ',';
    write_number(output, value.z);
    output << ']';
}

void write_color(std::ostream& output, const Color4& value) {
    output << '[';
    write_number(output, value.r);
    output << ',';
    write_number(output, value.g);
    output << ',';
    write_number(output, value.b);
    output << ',';
    write_number(output, value.a);
    output << ']';
}

void write_distribution_report(
    std::ostream& output,
    const GenerationReport& report) {
    output << '{'
           << "\"requested_count\":" << report.requested_count << ','
           << "\"accepted_count\":" << report.accepted_count << ','
           << "\"attempts\":" << report.attempts << ','
           << "\"surface_area\":";
    write_number(output, report.surface_area);
    output << ",\"initial_spacing\":";
    write_number(output, report.initial_spacing);
    output << ",\"final_spacing\":";
    write_number(output, report.final_spacing);
    output << ",\"density_guide_count\":" << report.density_guide_count
           << ",\"mask_guide_count\":" << report.mask_guide_count
           << ",\"masked_candidate_count\":" << report.masked_candidate_count
           << ",\"open_boundary_edge_count\":" << report.open_boundary_edge_count
           << ",\"boundary_anchor_count\":" << report.boundary_anchor_count
           << ",\"relax_iterations\":" << report.relax_iterations
           << ",\"moved_samples\":" << report.moved_samples
           << '}';
}

void write_orientation_report(
    std::ostream& output,
    const GenerationReport& report,
    std::size_t sample_count) {
    output << '{'
           << "\"sample_count\":" << sample_count
           << ",\"direction_guide_count\":" << report.direction_guide_count
           << ",\"direction_relax_iterations\":"
           << report.direction_relax_iterations
           << '}';
}

void write_cell_report(
    std::ostream& output,
    const GenerationReport& report) {
    output << '{'
           << "\"cell_count\":" << report.cell_count
           << ",\"cell_resolution\":" << report.cell_resolution
           << ",\"cell_clipped_rays\":" << report.cell_clipped_rays
           << ",\"cell_mean_neighbors\":";
    write_number(output, report.cell_mean_neighbors);
    output << ",\"paired_sample_count\":" << report.paired_sample_count
           << ",\"partition_seed_count\":" << report.partition_seed_count
           << ",\"open_boundary_edge_count\":" << report.open_boundary_edge_count
           << ",\"boundary_clipped_rays\":" << report.boundary_clipped_rays
           << ",\"mask_clipped_rays\":" << report.mask_clipped_rays
           << ",\"symmetry_stabilized_cells\":" << report.symmetry_stabilized_cells
           << ",\"symmetry_competitor_count\":" << report.symmetry_competitor_count
           << ",\"cell_shape_divisions\":" << report.cell_shape_divisions
           << '}';
}

void write_sample(std::ostream& output, const Sample& sample) {
    output << "{\"position\":";
    write_vec3(output, sample.position);
    output << ",\"normal\":";
    write_vec3(output, sample.normal);
    output << ",\"triangle_index\":" << sample.triangle_index
           << ",\"barycentric\":[";
    write_number(output, sample.barycentric[0]);
    output << ',';
    write_number(output, sample.barycentric[1]);
    output << ',';
    write_number(output, sample.barycentric[2]);
    output << "] ,\"random_size\":";
    write_number(output, sample.random_size);
    output << ",\"random_rotation\":";
    write_number(output, sample.random_rotation);
    output << ",\"random_type\":";
    write_number(output, sample.random_type);
    output << ",\"random_shape\":";
    write_number(output, sample.random_shape);
    output << ",\"density_multiplier\":";
    write_number(output, sample.density_multiplier);
    output << ",\"size_multiplier\":";
    write_number(output, sample.size_multiplier);
    output << ",\"local_spacing\":";
    write_number(output, sample.local_spacing);
    output << ",\"stable_id\":";
    write_hex_u64(output, sample.stable_id);
    output << '}';
}

void write_distribution(
    std::ostream& output,
    const std::vector<Sample>& samples,
    const GenerationReport& report) {
    output << "{\"report\":";
    write_distribution_report(output, report);
    output << ",\"samples\":[";
    for (std::size_t index = 0U; index < samples.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        write_sample(output, samples[index]);
    }
    output << "]}";
}

void write_orientation(
    std::ostream& output,
    const std::vector<OrientedSample>& samples,
    const GenerationReport& report) {
    output << "{\"report\":";
    write_orientation_report(output, report, samples.size());
    output << ",\"samples\":[";
    for (std::size_t index = 0U; index < samples.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        const OrientedSample& sample = samples[index];
        output << "{\"tangent\":";
        write_vec3(output, sample.tangent);
        output << ",\"partition_tangent\":";
        write_vec3(output, sample.partition_tangent);
        output << ",\"direction_influence\":";
        write_number(output, sample.direction_influence);
        output << '}';
    }
    output << "]}";
}

void write_cells(
    std::ostream& output,
    const std::vector<CellData>& cells,
    const GenerationReport& report) {
    output << "{\"report\":";
    write_cell_report(output, report);
    output << ",\"cells\":[";
    for (std::size_t index = 0U; index < cells.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        const CellData& cell = cells[index];
        output << "{\"sample_index\":" << cell.sample_index
               << ",\"boundary\":[";
        for (std::size_t point_index = 0U; point_index < cell.boundary.size(); ++point_index) {
            if (point_index != 0U) {
                output << ',';
            }
            write_vec3(output, cell.boundary[point_index]);
        }
        output << "],\"stable_tangent\":";
        write_vec3(output, cell.stable_tangent);
        output << ",\"stable_bitangent\":";
        write_vec3(output, cell.stable_bitangent);
        output << ",\"local_spacing\":";
        write_number(output, cell.local_spacing);
        output << ",\"neighbor_count\":" << cell.neighbor_count
               << ",\"clipped_rays\":" << cell.clipped_rays
               << ",\"pair_influence\":";
        write_number(output, cell.pair_influence);
        output << '}';
    }
    output << "]}";
}

void write_mesh(std::ostream& output, const GeneratedMesh& mesh) {
    output << "{\"scale_count\":" << mesh.scale_count << ",\"vertices\":[";
    for (std::size_t index = 0U; index < mesh.vertices.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        write_vec3(output, mesh.vertices[index]);
    }
    output << "],\"faces\":[";
    for (std::size_t face_index = 0U; face_index < mesh.faces.size(); ++face_index) {
        if (face_index != 0U) {
            output << ',';
        }
        output << '[';
        const auto& face = mesh.faces[face_index];
        for (std::size_t point_index = 0U; point_index < face.size(); ++point_index) {
            if (point_index != 0U) {
                output << ',';
            }
            output << face[point_index];
        }
        output << ']';
    }
    output << "],\"face_offset\":[0";
    std::uint64_t offset = 0U;
    for (const auto& face : mesh.faces) {
        offset += static_cast<std::uint64_t>(face.size());
        output << ',' << offset;
    }
    output << "],\"face_vertex\":[";
    bool first_index = true;
    for (const auto& face : mesh.faces) {
        for (const std::uint32_t value : face) {
            if (!first_index) {
                output << ',';
            }
            first_index = false;
            output << value;
        }
    }
    output << "],\"uvs\":[";
    for (std::size_t index = 0U; index < mesh.uvs.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        write_vec2(output, mesh.uvs[index]);
    }
    output << "],\"colors\":[";
    for (std::size_t index = 0U; index < mesh.colors.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        write_color(output, mesh.colors[index]);
    }
    output << "],\"scale_type_ids\":[";
    for (std::size_t index = 0U; index < mesh.scale_type_ids.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        output << mesh.scale_type_ids[index];
    }
    output << "],\"cell_ids\":[";
    for (std::size_t index = 0U; index < mesh.cell_ids.size(); ++index) {
        if (index != 0U) {
            output << ',';
        }
        write_hex_u64(output, mesh.cell_ids[index]);
    }
    output << "]}";
}

struct Arguments {
    std::string mesh_path;
    std::string payload_path;
    std::string output_path;
    std::string samples_path;
};

Arguments parse_arguments(int argc, char** argv) {
    Arguments result;
    for (int index = 1; index < argc; ++index) {
        const std::string argument(argv[index]);
        if (argument == "--help" || argument == "-h") {
            std::cout
                << "Usage: bifrost_scales_parity_dump --mesh target.obj "
                   "--payload payload.json [--samples samples.tsv] "
                   "[--output native.json]\n";
            std::exit(0);
        }
        if (index + 1 >= argc) {
            throw std::runtime_error("missing value after argument: " + argument);
        }
        const std::string value(argv[++index]);
        if (argument == "--mesh") {
            result.mesh_path = value;
        } else if (argument == "--payload") {
            result.payload_path = value;
        } else if (argument == "--output") {
            result.output_path = value;
        } else if (argument == "--samples") {
            result.samples_path = value;
        } else {
            throw std::runtime_error("unknown argument: " + argument);
        }
    }
    if (result.mesh_path.empty() || result.payload_path.empty()) {
        throw std::runtime_error("--mesh and --payload are required");
    }
    return result;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Arguments arguments = parse_arguments(argc, argv);
        Mesh mesh = load_obj(arguments.mesh_path);
        const bifrost_scales::PayloadDecodeResult decoded =
            bifrost_scales::decode_native_payload(read_text(arguments.payload_path));
        if (!decoded.success) {
            throw std::runtime_error("payload decode failed: " + decoded.status);
        }
        const Settings& settings = decoded.payload.settings;
        const PreviewMode mode = decoded.payload.mode;
        const std::vector<Guide>& guides = decoded.payload.guides;

        const bifrost_scales::DistributionResult distribution =
            bifrost_scales::distribute(mesh, settings, mode, guides);
        const std::vector<Sample> replay_samples = arguments.samples_path.empty()
            ? std::vector<Sample>{}
            : load_samples(arguments.samples_path, mesh);
        const std::vector<Sample>& stage_samples = replay_samples.empty()
            ? distribution.samples
            : replay_samples;
        const bifrost_scales::OrientationResult orientation =
            bifrost_scales::orient_samples(
                stage_samples,
                settings,
                mode,
                guides,
                distribution.report);

        bifrost_scales::CellResult cells;
        GeneratedMesh generated;
        GenerationReport final_report = orientation.report;
        const bool cell_geometry = uses_cells(settings, mode);
        if (cell_geometry) {
            cells = bifrost_scales::build_cells(
                mesh,
                orientation.samples,
                settings,
                mode,
                guides,
                decoded.payload.symmetry_planes,
                orientation.report);
            generated = bifrost_scales::shape_cells(
                orientation.samples,
                cells.cells,
                settings,
                guides);
            final_report = cells.report;
        } else {
            generated = bifrost_scales::shape_samples(
                orientation.samples,
                settings,
                mode,
                guides);
            final_report.used_cells = false;
        }

        std::ostringstream json;
        json << "{\"schema\":\"bifrost-scales/parity-dump/1\","
             << "\"source\":\"native-cpp\","
             << "\"mode\":" << escaped(mode_name(mode)) << ','
             << "\"geometry_kind\":" << escaped(cell_geometry ? "cell" : "card") << ','
             << "\"input\":{\"vertex_count\":" << mesh.vertices.size()
             << ",\"triangle_count\":" << mesh.triangles.size() << "},"
             << "\"replay\":{\"samples\":"
             << (replay_samples.empty() ? "false" : "true")
             << ",\"sample_count\":" << stage_samples.size() << "},"
             << "\"distribution\":";
        write_distribution(json, distribution.samples, distribution.report);
        json << ",\"orientation\":";
        write_orientation(json, orientation.samples, orientation.report);
        json << ",\"cells\":";
        write_cells(json, cells.cells, final_report);
        json << ",\"mesh\":";
        write_mesh(json, generated);
        json << '}';

        if (arguments.output_path.empty()) {
            std::cout << json.str() << '\n';
        } else {
            std::ofstream output(arguments.output_path, std::ios::binary);
            if (!output) {
                throw std::runtime_error("cannot open output file: " + arguments.output_path);
            }
            output << json.str() << '\n';
            if (!output) {
                throw std::runtime_error("cannot write output file: " + arguments.output_path);
            }
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Bifrost Scales parity dump failed: " << error.what() << '\n';
        return 2;
    }
}
