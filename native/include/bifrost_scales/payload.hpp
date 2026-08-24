#pragma once

#include <string>
#include <string_view>
#include <vector>

#include "bifrost_scales/core.hpp"

namespace bifrost_scales {

struct NativePayload {
    Settings settings;
    std::vector<Guide> guides;
    std::vector<SymmetryPlane> symmetry_planes;
    std::vector<std::uint32_t> cell_metadata_indices;
    std::vector<std::uint64_t> resolve_cell_ids;
    PreviewMode mode{PreviewMode::Settled};
};

struct PayloadDecodeResult {
    bool success{false};
    NativePayload payload;
    std::string status;
};

PayloadDecodeResult decode_native_payload(std::string_view json_text);

}  // namespace bifrost_scales
