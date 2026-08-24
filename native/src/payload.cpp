#include "bifrost_scales/payload.hpp"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace bifrost_scales {
namespace {

struct JsonValue {
    using Array = std::vector<JsonValue>;
    using Object = std::map<std::string, JsonValue, std::less<>>;
    using Storage = std::variant<std::nullptr_t, bool, double, std::string, Array, Object>;

    Storage value{nullptr};

    [[nodiscard]] const Object* object() const {
        return std::get_if<Object>(&value);
    }

    [[nodiscard]] const Array* array() const {
        return std::get_if<Array>(&value);
    }
};

class JsonParser {
public:
    explicit JsonParser(std::string_view text) : text_(text) {}

    JsonValue parse() {
        skip_whitespace();
        JsonValue result = parse_value();
        skip_whitespace();
        if (position_ != text_.size()) {
            fail("unexpected trailing data");
        }
        return result;
    }

private:
    std::string_view text_;
    std::size_t position_{0};

    [[noreturn]] void fail(const char* message) const {
        throw std::runtime_error(
            std::string(message) + " at byte " + std::to_string(position_));
    }

    void skip_whitespace() {
        while (position_ < text_.size()) {
            const char value = text_[position_];
            if (value != ' ' && value != '\t' && value != '\r' && value != '\n') {
                break;
            }
            ++position_;
        }
    }

    [[nodiscard]] char peek() const {
        if (position_ >= text_.size()) {
            return '\0';
        }
        return text_[position_];
    }

    char take() {
        if (position_ >= text_.size()) {
            fail("unexpected end of JSON");
        }
        return text_[position_++];
    }

    void expect(char expected) {
        if (take() != expected) {
            fail("unexpected character");
        }
    }

    bool consume(std::string_view token) {
        if (text_.substr(position_, token.size()) != token) {
            return false;
        }
        position_ += token.size();
        return true;
    }

    JsonValue parse_value() {
        skip_whitespace();
        switch (peek()) {
        case '{':
            return JsonValue{parse_object()};
        case '[':
            return JsonValue{parse_array()};
        case '"':
            return JsonValue{parse_string()};
        case 't':
            if (consume("true")) {
                return JsonValue{true};
            }
            break;
        case 'f':
            if (consume("false")) {
                return JsonValue{false};
            }
            break;
        case 'n':
            if (consume("null")) {
                return JsonValue{nullptr};
            }
            break;
        default:
            if (peek() == '-' || (peek() >= '0' && peek() <= '9')) {
                return JsonValue{parse_number()};
            }
            break;
        }
        fail("invalid JSON value");
    }

    JsonValue::Object parse_object() {
        JsonValue::Object result;
        expect('{');
        skip_whitespace();
        if (peek() == '}') {
            ++position_;
            return result;
        }
        while (true) {
            skip_whitespace();
            if (peek() != '"') {
                fail("object key must be a string");
            }
            std::string key = parse_string();
            skip_whitespace();
            expect(':');
            skip_whitespace();
            result.insert_or_assign(std::move(key), parse_value());
            skip_whitespace();
            const char separator = take();
            if (separator == '}') {
                break;
            }
            if (separator != ',') {
                fail("expected object separator");
            }
        }
        return result;
    }

    JsonValue::Array parse_array() {
        JsonValue::Array result;
        expect('[');
        skip_whitespace();
        if (peek() == ']') {
            ++position_;
            return result;
        }
        while (true) {
            result.push_back(parse_value());
            skip_whitespace();
            const char separator = take();
            if (separator == ']') {
                break;
            }
            if (separator != ',') {
                fail("expected array separator");
            }
            skip_whitespace();
        }
        return result;
    }

    static void append_utf8(std::string& result, std::uint32_t codepoint) {
        if (codepoint <= 0x7FU) {
            result.push_back(static_cast<char>(codepoint));
        } else if (codepoint <= 0x7FFU) {
            result.push_back(static_cast<char>(0xC0U | (codepoint >> 6U)));
            result.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
        } else if (codepoint <= 0xFFFFU) {
            result.push_back(static_cast<char>(0xE0U | (codepoint >> 12U)));
            result.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3FU)));
            result.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
        } else {
            result.push_back(static_cast<char>(0xF0U | (codepoint >> 18U)));
            result.push_back(static_cast<char>(0x80U | ((codepoint >> 12U) & 0x3FU)));
            result.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3FU)));
            result.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
        }
    }

    std::uint32_t parse_hex_quad() {
        if (position_ + 4U > text_.size()) {
            fail("incomplete unicode escape");
        }
        std::uint32_t result = 0U;
        for (int index = 0; index < 4; ++index) {
            const char value = text_[position_++];
            result <<= 4U;
            if (value >= '0' && value <= '9') {
                result |= static_cast<std::uint32_t>(value - '0');
            } else if (value >= 'a' && value <= 'f') {
                result |= static_cast<std::uint32_t>(value - 'a' + 10);
            } else if (value >= 'A' && value <= 'F') {
                result |= static_cast<std::uint32_t>(value - 'A' + 10);
            } else {
                fail("invalid unicode escape");
            }
        }
        return result;
    }

    std::string parse_string() {
        expect('"');
        std::string result;
        while (position_ < text_.size()) {
            const char value = take();
            if (value == '"') {
                return result;
            }
            if (value != '\\') {
                if (static_cast<unsigned char>(value) < 0x20U) {
                    fail("control character in string");
                }
                result.push_back(value);
                continue;
            }
            const char escaped = take();
            switch (escaped) {
            case '"': result.push_back('"'); break;
            case '\\': result.push_back('\\'); break;
            case '/': result.push_back('/'); break;
            case 'b': result.push_back('\b'); break;
            case 'f': result.push_back('\f'); break;
            case 'n': result.push_back('\n'); break;
            case 'r': result.push_back('\r'); break;
            case 't': result.push_back('\t'); break;
            case 'u': {
                std::uint32_t codepoint = parse_hex_quad();
                if (codepoint >= 0xD800U && codepoint <= 0xDBFFU) {
                    if (!consume("\\u")) {
                        fail("missing low unicode surrogate");
                    }
                    const std::uint32_t low = parse_hex_quad();
                    if (low < 0xDC00U || low > 0xDFFFU) {
                        fail("invalid low unicode surrogate");
                    }
                    codepoint = 0x10000U +
                        ((codepoint - 0xD800U) << 10U) + (low - 0xDC00U);
                }
                append_utf8(result, codepoint);
                break;
            }
            default:
                fail("invalid string escape");
            }
        }
        fail("unterminated string");
    }

    double parse_number() {
        const std::size_t start = position_;
        if (peek() == '-') {
            ++position_;
        }
        if (peek() == '0') {
            ++position_;
        } else {
            if (peek() < '1' || peek() > '9') {
                fail("invalid number");
            }
            while (peek() >= '0' && peek() <= '9') {
                ++position_;
            }
        }
        if (peek() == '.') {
            ++position_;
            if (peek() < '0' || peek() > '9') {
                fail("invalid fraction");
            }
            while (peek() >= '0' && peek() <= '9') {
                ++position_;
            }
        }
        if (peek() == 'e' || peek() == 'E') {
            ++position_;
            if (peek() == '+' || peek() == '-') {
                ++position_;
            }
            if (peek() < '0' || peek() > '9') {
                fail("invalid exponent");
            }
            while (peek() >= '0' && peek() <= '9') {
                ++position_;
            }
        }
        const std::string number(text_.substr(start, position_ - start));
        char* end = nullptr;
        const double result = std::strtod(number.c_str(), &end);
        if (end == nullptr || *end != '\0' || !std::isfinite(result)) {
            fail("invalid numeric value");
        }
        return result;
    }
};

const JsonValue* member(const JsonValue::Object& object, std::string_view key) {
    const auto iterator = object.find(key);
    return iterator == object.end() ? nullptr : &iterator->second;
}

const JsonValue::Object* object_member(
    const JsonValue::Object& object,
    std::string_view key) {
    const JsonValue* value = member(object, key);
    return value == nullptr ? nullptr : value->object();
}

const JsonValue::Array* array_member(
    const JsonValue::Object& object,
    std::string_view key) {
    const JsonValue* value = member(object, key);
    return value == nullptr ? nullptr : value->array();
}

std::string string_value(
    const JsonValue::Object& object,
    std::string_view key,
    std::string fallback = {}) {
    const JsonValue* value = member(object, key);
    if (value == nullptr) {
        return fallback;
    }
    if (const auto* text = std::get_if<std::string>(&value->value)) {
        return *text;
    }
    return fallback;
}

double number_value(
    const JsonValue::Object& object,
    std::string_view key,
    double fallback) {
    const JsonValue* value = member(object, key);
    if (value == nullptr) {
        return fallback;
    }
    if (const auto* number = std::get_if<double>(&value->value)) {
        return *number;
    }
    return fallback;
}

bool bool_value(
    const JsonValue::Object& object,
    std::string_view key,
    bool fallback) {
    const JsonValue* value = member(object, key);
    if (value == nullptr) {
        return fallback;
    }
    if (const auto* flag = std::get_if<bool>(&value->value)) {
        return *flag;
    }
    return fallback;
}

std::optional<bool> optional_bool_value(
    const JsonValue::Object& object,
    std::string_view key) {
    const JsonValue* value = member(object, key);
    if (value == nullptr) {
        return std::nullopt;
    }
    if (const auto* flag = std::get_if<bool>(&value->value)) {
        return *flag;
    }
    return std::nullopt;
}

std::uint32_t uint32_value(
    const JsonValue::Object& object,
    std::string_view key,
    std::uint32_t fallback) {
    const double value = number_value(object, key, static_cast<double>(fallback));
    if (!std::isfinite(value) || value <= 0.0) {
        return value == 0.0 ? 0U : fallback;
    }
    return static_cast<std::uint32_t>(std::min(
        value,
        static_cast<double>(std::numeric_limits<std::uint32_t>::max())));
}

std::uint64_t uint64_value(
    const JsonValue::Object& object,
    std::string_view key,
    std::uint64_t fallback) {
    const double value = number_value(object, key, static_cast<double>(fallback));
    if (!std::isfinite(value)) {
        return fallback;
    }
    // CPython random.Random(int_seed) normalizes integer seeds by magnitude.
    // Keep negative Settings seeds deterministic and parity-compatible instead
    // of collapsing every negative value to zero.
    const double magnitude = std::abs(value);
    const double clamped = std::min(
        magnitude,
        static_cast<double>(std::numeric_limits<std::uint64_t>::max()));
    return static_cast<std::uint64_t>(clamped);
}

Vec3 vec3_from_value(const JsonValue& value, const Vec3& fallback) {
    const auto* array = value.array();
    if (array == nullptr || array->size() < 3U) {
        return fallback;
    }
    const auto number_at = [array](std::size_t index, double default_value) {
        const auto* number = std::get_if<double>(&(*array)[index].value);
        return number == nullptr ? default_value : *number;
    };
    return {
        number_at(0U, fallback.x),
        number_at(1U, fallback.y),
        number_at(2U, fallback.z),
    };
}

Color4 color_from_object(
    const JsonValue::Object& object,
    const Color4& fallback) {
    return {
        number_value(object, "color_r", fallback.r),
        number_value(object, "color_g", fallback.g),
        number_value(object, "color_b", fallback.b),
        1.0,
    };
}

GeometryMode geometry_mode(std::string_view value) {
    if (value == "cards" || value == "card") {
        return GeometryMode::Cards;
    }
    if (value == "cells" || value == "cell") {
        return GeometryMode::Cells;
    }
    return GeometryMode::Auto;
}

GuideKind guide_kind(std::string_view value) {
    if (value == "density_curve") return GuideKind::DensityCurve;
    if (value == "direction_point") return GuideKind::DirectionPoint;
    if (value == "direction_curve") return GuideKind::DirectionCurve;
    if (value == "flow_curve") return GuideKind::FlowCurve;
    return GuideKind::DensityPoint;
}

PreviewMode preview_mode(const JsonValue::Object& root) {
    const std::string mode = string_value(root, "mode", "settled");
    if (mode == "interactive") return PreviewMode::Interactive;
    if (mode == "final") return PreviewMode::Final;
    return PreviewMode::Settled;
}

ScaleType parse_scale_type(const JsonValue::Object& object, std::size_t index) {
    ScaleType result;
    result.id = string_value(object, "type_id", "type_" + std::to_string(index + 1U));
    result.name = string_value(object, "name", result.id);
    result.enabled = bool_value(object, "enabled", result.enabled);
    result.size_multiplier = number_value(object, "size_multiplier", result.size_multiplier);
    result.width_multiplier = number_value(object, "width_multiplier", result.width_multiplier);
    result.length_multiplier = number_value(object, "length_multiplier", result.length_multiplier);
    result.curvature_multiplier = number_value(
        object, "curvature_multiplier", result.curvature_multiplier);
    result.offset = number_value(object, "offset", result.offset);
    result.random_offset = number_value(object, "random_offset", result.random_offset);
    result.tip_offset = number_value(object, "tip_offset", result.tip_offset);
    result.guide_id = string_value(object, "guide_id", result.guide_id);
    result.use_custom_color = bool_value(
        object, "use_custom_color", result.use_custom_color);
    result.color = color_from_object(object, result.color);
    return result;
}

void parse_settings(const JsonValue::Object& object, Settings& result) {
    result.target_count = uint32_value(object, "target_count", result.target_count);
    result.seed = uint64_value(object, "seed", result.seed);
    result.spacing_factor = number_value(object, "spacing_factor", result.spacing_factor);
    result.relax_iterations = uint32_value(object, "relax_iterations", result.relax_iterations);
    result.relax_strength = number_value(object, "relax_strength", result.relax_strength);
    result.size = number_value(object, "size", result.size);
    result.lift = number_value(object, "lift", result.lift);
    result.curvature = number_value(object, "curvature", result.curvature);
    result.direction_degrees = number_value(
        object, "direction_degrees", result.direction_degrees);
    result.direction_relax_iterations = uint32_value(
        object, "direction_relax_iterations", result.direction_relax_iterations);
    result.direction_relax_strength = number_value(
        object, "direction_relax_strength", result.direction_relax_strength);
    result.random_size = number_value(object, "random_size", result.random_size);
    result.random_rotation_degrees = number_value(
        object, "random_rotation_degrees", result.random_rotation_degrees);
    result.inset = number_value(object, "inset", result.inset);
    result.squash = number_value(object, "squash", result.squash);
    result.expand = number_value(object, "expand", result.expand);
    result.tip_roundness = number_value(object, "tip_roundness", result.tip_roundness);
    result.tip_offset = number_value(object, "tip_offset", result.tip_offset);
    result.forward_offset = number_value(object, "forward_offset", result.forward_offset);
    result.cell_mode = geometry_mode(string_value(object, "cell_mode", "auto"));
    result.cell_growth = number_value(object, "cell_growth", result.cell_growth);
    result.cell_gap = number_value(object, "cell_gap", result.cell_gap);
    result.cell_collision_margin = number_value(
        object, "cell_collision_margin", result.cell_collision_margin);
    result.cell_radius_multiplier = number_value(
        object, "cell_radius_multiplier", result.cell_radius_multiplier);
    result.cell_shape_divisions = uint32_value(
        object, "cell_shape_divisions", result.cell_shape_divisions);
    result.cell_interactive_resolution = uint32_value(
        object, "cell_interactive_resolution", result.cell_interactive_resolution);
    result.cell_settled_resolution = uint32_value(
        object, "cell_settled_resolution", result.cell_settled_resolution);
    result.cell_projection_rings = uint32_value(
        object, "cell_projection_rings", result.cell_projection_rings);
    result.cell_project_to_surface = bool_value(
        object, "cell_project_to_surface", result.cell_project_to_surface);
    result.color = color_from_object(object, result.color);
    result.interactive_budget = uint32_value(
        object, "interactive_budget", result.interactive_budget);
    result.settled_budget = uint32_value(
        object, "settled_budget", result.settled_budget);

    if (const JsonValue::Array* types = array_member(object, "scale_types")) {
        result.scale_types.clear();
        result.scale_types.reserve(types->size());
        for (std::size_t index = 0; index < types->size() && index < 16U; ++index) {
            if (const JsonValue::Object* type_object = (*types)[index].object()) {
                result.scale_types.push_back(parse_scale_type(*type_object, index));
            }
        }
    }
}

Guide parse_guide(const JsonValue::Object& object) {
    Guide result;
    result.id = string_value(object, "guide_id", "guide");
    result.group_id = string_value(object, "group_id", "");
    result.kind = guide_kind(string_value(object, "kind", "density_point"));
    result.enabled = bool_value(object, "enabled", result.enabled);
    result.radius = number_value(object, "radius", result.radius);
    result.falloff = number_value(object, "falloff", result.falloff);
    result.density_multiplier = number_value(
        object, "density_multiplier", result.density_multiplier);
    result.size_multiplier = number_value(
        object, "size_multiplier", result.size_multiplier);
    result.strength = number_value(object, "strength", result.strength);
    result.angle_degrees = number_value(
        object, "angle_degrees", result.angle_degrees);
    result.closed = bool_value(object, "closed", result.closed);
    result.use_density = optional_bool_value(object, "use_density");
    result.use_size = optional_bool_value(object, "use_size");
    result.use_direction = optional_bool_value(object, "use_direction");
    result.use_mask = optional_bool_value(object, "use_mask");
    if (const JsonValue* direction = member(object, "direction")) {
        result.direction = vec3_from_value(*direction, result.direction);
    }
    if (const JsonValue::Array* points = array_member(object, "points")) {
        result.points.reserve(points->size());
        for (const JsonValue& point : *points) {
            result.points.push_back(vec3_from_value(point, {}));
        }
    }
    return result;
}

}  // namespace

PayloadDecodeResult decode_native_payload(std::string_view json_text) {
    PayloadDecodeResult result;
    try {
        if (json_text.empty()) {
            throw std::runtime_error("payload is empty");
        }
        const JsonValue root_value = JsonParser(json_text).parse();
        const JsonValue::Object* root = root_value.object();
        if (root == nullptr) {
            throw std::runtime_error("payload root must be an object");
        }
        const std::string schema = string_value(*root, "schema", "");
        if (schema != "bifrost-scales/native-payload/10") {
            throw std::runtime_error(
                "unsupported native payload schema: " + schema +
                " (expected bifrost-scales/native-payload/10)");
        }
        result.payload.mode = preview_mode(*root);
        const JsonValue::Object* settings = object_member(*root, "settings");
        if (settings == nullptr) {
            throw std::runtime_error("payload settings object is missing");
        }
        parse_settings(*settings, result.payload.settings);
        if (const JsonValue::Array* guides = array_member(*root, "guides")) {
            result.payload.guides.reserve(guides->size());
            for (const JsonValue& guide_value : *guides) {
                if (const JsonValue::Object* guide = guide_value.object()) {
                    result.payload.guides.push_back(parse_guide(*guide));
                }
            }
        }
        if (const JsonValue::Array* planes = array_member(*root, "symmetry_planes")) {
            result.payload.symmetry_planes.reserve(planes->size());
            for (const JsonValue& plane_value : *planes) {
                const JsonValue::Object* plane = plane_value.object();
                if (plane == nullptr) {
                    continue;
                }
                SymmetryPlane value;
                if (const JsonValue* origin = member(*plane, "origin")) {
                    value.origin = vec3_from_value(*origin, value.origin);
                }
                if (const JsonValue* normal = member(*plane, "normal")) {
                    value.normal = vec3_from_value(*normal, value.normal);
                }
                result.payload.symmetry_planes.push_back(value);
            }
        }
        if (member(*root, "uv_boundary_edges") != nullptr) {
            throw std::runtime_error(
                "UV boundary payload data is unsupported in native-payload/10");
        }
        if (const JsonValue::Array* indices =
                array_member(*root, "cell_metadata_indices")) {
            if (indices->size() > 4096U) {
                throw std::runtime_error(
                    "cell_metadata_indices exceeds the 4096 item limit");
            }
            result.payload.cell_metadata_indices.reserve(indices->size());
            for (const JsonValue& value : *indices) {
                const auto* number = std::get_if<double>(&value.value);
                if (number == nullptr || !std::isfinite(*number) ||
                    *number < 0.0 || std::floor(*number) != *number ||
                    *number > static_cast<double>(
                        std::numeric_limits<std::uint32_t>::max())) {
                    throw std::runtime_error(
                        "cell_metadata_indices contains an invalid index");
                }
                result.payload.cell_metadata_indices.push_back(
                    static_cast<std::uint32_t>(*number));
            }
            std::sort(
                result.payload.cell_metadata_indices.begin(),
                result.payload.cell_metadata_indices.end());
            result.payload.cell_metadata_indices.erase(
                std::unique(
                    result.payload.cell_metadata_indices.begin(),
                    result.payload.cell_metadata_indices.end()),
                result.payload.cell_metadata_indices.end());
        }
        if (const JsonValue::Array* ids = array_member(*root, "resolve_cell_ids")) {
            if (ids->size() > 4096U) {
                throw std::runtime_error(
                    "resolve_cell_ids exceeds the 4096 item limit");
            }
            result.payload.resolve_cell_ids.reserve(ids->size());
            for (const JsonValue& value : *ids) {
                const auto* text = std::get_if<std::string>(&value.value);
                if (text == nullptr || text->empty() || text->size() > 16U ||
                    !std::all_of(text->begin(), text->end(), [](char character) {
                        return std::isxdigit(
                            static_cast<unsigned char>(character)) != 0;
                    })) {
                    throw std::runtime_error(
                        "resolve_cell_ids contains an invalid hexadecimal ID");
                }
                std::uint64_t parsed = 0U;
                const char* begin = text->data();
                const char* end = begin + text->size();
                const auto conversion = std::from_chars(begin, end, parsed, 16);
                if (conversion.ec != std::errc{} || conversion.ptr != end ||
                    parsed == 0U) {
                    throw std::runtime_error(
                        "resolve_cell_ids contains an invalid hexadecimal ID");
                }
                result.payload.resolve_cell_ids.push_back(parsed);
            }
            std::sort(
                result.payload.resolve_cell_ids.begin(),
                result.payload.resolve_cell_ids.end());
            result.payload.resolve_cell_ids.erase(
                std::unique(
                    result.payload.resolve_cell_ids.begin(),
                    result.payload.resolve_cell_ids.end()),
                result.payload.resolve_cell_ids.end());
        }
        result.success = true;
        result.status = "ok";
    } catch (const std::exception& error) {
        result.success = false;
        result.status = error.what();
    }
    return result;
}

}  // namespace bifrost_scales
