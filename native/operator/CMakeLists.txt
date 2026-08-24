set(BIFROST_SCALES_OPS_TARGET BifrostScalesOps)

add_library(${BIFROST_SCALES_OPS_TARGET} SHARED
    src/bifrost_scales_nodedef.cpp
    src/bifrost_scales_nodedef.hpp
    src/bifrost_scales_operator_export.hpp
)
target_compile_definitions(
    ${BIFROST_SCALES_OPS_TARGET}
    PRIVATE BIFROST_SCALES_BUILD_NODEDEF_DLL
)
target_include_directories(
    ${BIFROST_SCALES_OPS_TARGET}
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_SOURCE_DIR}/include
)
target_compile_features(${BIFROST_SCALES_OPS_TARGET} PRIVATE cxx_std_17)
target_link_libraries(
    ${BIFROST_SCALES_OPS_TARGET}
    PRIVATE
        bifrost_scales_core
        Amino::Cpp
        Amino::Core
)
if(MSVC)
    target_compile_options(
        ${BIFROST_SCALES_OPS_TARGET}
        PRIVATE /W4 /permissive- /EHsc
    )
endif()
bifrost_set_install_rpath(${BIFROST_SCALES_OPS_TARGET})
install(TARGETS ${BIFROST_SCALES_OPS_TARGET} DESTINATION lib)

bifrost_header_parser(
    BifrostScalesJsonFiles
    "json/BifrostScales/operators"
    INCLUDE_DIRS
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_SOURCE_DIR}/include
    HEADER_FILES
        src/bifrost_scales_nodedef.hpp
)

configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/PackConfig.json.in
    ${CMAKE_CURRENT_BINARY_DIR}/BifrostScalesPackConfig.json
    @ONLY
)
install(
    FILES ${CMAKE_CURRENT_BINARY_DIR}/BifrostScalesPackConfig.json
    DESTINATION .
)

set(
    BIFROST_SCALES_STATIC_GRAPH_DIR
    ""
    CACHE PATH
    "Directory containing the static Bifrost Scales Published Graph resources"
)
if(NOT BIFROST_SCALES_STATIC_GRAPH_DIR)
    foreach(_candidate
            "${CMAKE_SOURCE_DIR}/../BifrostScales/bifrost/compounds"
            "${CMAKE_SOURCE_DIR}/../compounds")
        if(EXISTS "${_candidate}/BifrostScales_native_scales_v4_graph.json")
            set(BIFROST_SCALES_STATIC_GRAPH_DIR "${_candidate}")
            break()
        endif()
    endforeach()
endif()
set(BIFROST_SCALES_STATIC_COMPOUND
    ${BIFROST_SCALES_STATIC_GRAPH_DIR}/BifrostScales_native_scales_v4_graph.json
)
set(BIFROST_SCALES_STATIC_MANIFEST
    ${BIFROST_SCALES_STATIC_GRAPH_DIR}/manifest.bifrost-scales.json
)
if(EXISTS ${BIFROST_SCALES_STATIC_COMPOUND})
    install(
        FILES ${BIFROST_SCALES_STATIC_COMPOUND}
        DESTINATION json/BifrostScales/graphs
    )
endif()
if(EXISTS ${BIFROST_SCALES_STATIC_MANIFEST})
    install(
        FILES ${BIFROST_SCALES_STATIC_MANIFEST}
        DESTINATION metadata
    )
endif()
