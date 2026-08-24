#ifndef BIFROST_SCALES_NODEDEF_HPP
#define BIFROST_SCALES_NODEDEF_HPP

#if defined(_MSC_VER) && _MSC_VER >= 1930
#  define _ALLOW_COMPILER_AND_STL_VERSION_MISMATCH
#endif

#include <Amino/Cpp/Annotate.h>
#include <Amino/Core/Array.h>
#include <Amino/Core/BuiltInTypes.h>
#include <Amino/Core/Ptr.h>
#include <Amino/Core/String.h>
#include <Bifrost/Math/Types.h>

#include "bifrost_scales_operator_export.hpp"

namespace BifrostScales {

// The C++ namespace is the public Bifrost library namespace. Do not repeat
// it in an Amino ``name`` annotation or the header parser registers
// ``BifrostScales::BifrostScales``.
//
// Mesh topology uses Amino::uint_t because Geometry::Mesh::get_mesh_structure
// and Geometry::Mesh::construct_mesh expose face_offset/face_vertex as
// array<uint>. Using long here makes the static graph fail compilation.
BIFROST_SCALES_NODEDEF_DECL
void generate_scale_mesh_payload_arrays(
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
    Amino::String& status)
    AMINO_ANNOTATE(
        "Amino::Node "
        "metadata=[{documentation, string, Native HDA-like scale generation from mesh arrays and a versioned payload.}] "
    );

}  // namespace BifrostScales

#endif  // BIFROST_SCALES_NODEDEF_HPP
