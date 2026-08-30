cmake_minimum_required(VERSION 3.20)
project(BifrostScalesCore VERSION 0.10.8 LANGUAGES CXX)

option(
    BIFROST_SCALES_ENABLE_SANITIZERS
    "Enable AddressSanitizer and UndefinedBehaviorSanitizer for native tests"
    OFF
)
option(
    BIFROST_SCALES_BUILD_BIFROST_OPERATOR
    "Build the Bifrost SDK operator and pack"
    OFF
)
option(
    BIFROST_SCALES_BUILD_PARITY_TOOLS
    "Build host-independent Python/C++ parity diagnostics"
    ON
)

find_package(Threads REQUIRED)

add_library(bifrost_scales_core STATIC
    src/core.cpp
    src/gpu_compute.cpp
    src/payload.cpp
    src/preview_distribution.cpp
)
target_include_directories(bifrost_scales_core PUBLIC include)
target_link_libraries(
    bifrost_scales_core
    PUBLIC Threads::Threads ${CMAKE_DL_LIBS}
)
target_compile_features(bifrost_scales_core PUBLIC cxx_std_17)
set_target_properties(bifrost_scales_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

if(MSVC)
    target_compile_options(bifrost_scales_core PRIVATE /W4 /permissive-)
else()
    target_compile_options(bifrost_scales_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

if(BIFROST_SCALES_ENABLE_SANITIZERS)
    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        add_library(bifrost_scales_sanitizers INTERFACE)
        target_compile_options(
            bifrost_scales_sanitizers
            INTERFACE -fsanitize=address,undefined -fno-omit-frame-pointer
        )
        target_link_options(
            bifrost_scales_sanitizers
            INTERFACE -fsanitize=address,undefined
        )
        target_link_libraries(bifrost_scales_core PUBLIC bifrost_scales_sanitizers)
    else()
        message(WARNING "BIFROST_SCALES_ENABLE_SANITIZERS is only configured for GCC/Clang")
    endif()
endif()

include(CTest)
if(BIFROST_SCALES_BUILD_PARITY_TOOLS)
    add_executable(bifrost_scales_parity_dump tools/parity_dump.cpp)
    target_link_libraries(bifrost_scales_parity_dump PRIVATE bifrost_scales_core)

    add_executable(
        bifrost_scales_performance_benchmark
        tools/performance_benchmark.cpp
    )
    add_executable(
        bifrost_scales_gpu_preview_benchmark
        tools/gpu_preview_benchmark.cpp
    )
    add_executable(
        bifrost_scales_open_boundary_density_benchmark
        tools/open_boundary_density_benchmark.cpp
    )
    add_executable(
        bifrost_scales_stage_cache_benchmark
        tools/stage_cache_benchmark.cpp
    )
    add_executable(
        bifrost_scales_interactive_distribution_benchmark
        tools/interactive_distribution_benchmark.cpp
    )
    add_executable(
        bifrost_scales_candidate_batch_benchmark
        tools/candidate_batch_benchmark.cpp
    )
    add_executable(
        bifrost_scales_conflict_gpu_benchmark
        tools/conflict_gpu_benchmark.cpp
    )
    target_link_libraries(
        bifrost_scales_performance_benchmark
        PRIVATE bifrost_scales_core
    )
    target_link_libraries(
        bifrost_scales_gpu_preview_benchmark
        PRIVATE bifrost_scales_core
    )
    target_link_libraries(
        bifrost_scales_open_boundary_density_benchmark
        PRIVATE bifrost_scales_core
    )
    target_link_libraries(
        bifrost_scales_stage_cache_benchmark
        PRIVATE bifrost_scales_core
    )
    target_link_libraries(
        bifrost_scales_interactive_distribution_benchmark
        PRIVATE bifrost_scales_core
    )
    target_link_libraries(
        bifrost_scales_candidate_batch_benchmark
        PRIVATE bifrost_scales_core
    )
    target_link_libraries(
        bifrost_scales_conflict_gpu_benchmark
        PRIVATE bifrost_scales_core
    )
    if(MSVC)
        target_compile_options(bifrost_scales_parity_dump PRIVATE /W4 /permissive-)
        target_compile_options(
            bifrost_scales_performance_benchmark
            PRIVATE /W4 /permissive-
        )
        target_compile_options(
            bifrost_scales_gpu_preview_benchmark
            PRIVATE /W4 /permissive-
        )
        target_compile_options(
            bifrost_scales_open_boundary_density_benchmark
            PRIVATE /W4 /permissive-
        )
        target_compile_options(
            bifrost_scales_stage_cache_benchmark
            PRIVATE /W4 /permissive-
        )
        target_compile_options(
            bifrost_scales_interactive_distribution_benchmark
            PRIVATE /W4 /permissive-
        )
        target_compile_options(
            bifrost_scales_candidate_batch_benchmark
            PRIVATE /W4 /permissive-
        )
        target_compile_options(
            bifrost_scales_conflict_gpu_benchmark
            PRIVATE /W4 /permissive-
        )
    else()
        target_compile_options(bifrost_scales_parity_dump PRIVATE -Wall -Wextra -Wpedantic -Werror)
        target_compile_options(
            bifrost_scales_performance_benchmark
            PRIVATE -Wall -Wextra -Wpedantic -Werror
        )
        target_compile_options(
            bifrost_scales_gpu_preview_benchmark
            PRIVATE -Wall -Wextra -Wpedantic -Werror
        )
        target_compile_options(
            bifrost_scales_open_boundary_density_benchmark
            PRIVATE -Wall -Wextra -Wpedantic -Werror
        )
        target_compile_options(
            bifrost_scales_stage_cache_benchmark
            PRIVATE -Wall -Wextra -Wpedantic -Werror
        )
        target_compile_options(
            bifrost_scales_interactive_distribution_benchmark
            PRIVATE -Wall -Wextra -Wpedantic -Werror
        )
        target_compile_options(
            bifrost_scales_candidate_batch_benchmark
            PRIVATE -Wall -Wextra -Wpedantic -Werror
        )
        target_compile_options(
            bifrost_scales_conflict_gpu_benchmark
            PRIVATE -Wall -Wextra -Wpedantic -Werror
        )
    endif()
    install(
        TARGETS
            bifrost_scales_parity_dump
            bifrost_scales_performance_benchmark
            bifrost_scales_gpu_preview_benchmark
            bifrost_scales_open_boundary_density_benchmark
            bifrost_scales_stage_cache_benchmark
            bifrost_scales_interactive_distribution_benchmark
            bifrost_scales_candidate_batch_benchmark
            bifrost_scales_conflict_gpu_benchmark
        RUNTIME DESTINATION tools
    )
endif()

if(BUILD_TESTING)
    add_executable(bifrost_scales_core_tests tests/core_tests.cpp)
    target_link_libraries(bifrost_scales_core_tests PRIVATE bifrost_scales_core)
    add_test(NAME bifrost_scales_core_tests COMMAND bifrost_scales_core_tests)

    add_executable(
        bifrost_scales_preview_distribution_tests
        tests/preview_distribution_tests.cpp
    )
    target_link_libraries(
        bifrost_scales_preview_distribution_tests
        PRIVATE bifrost_scales_core
    )
    add_test(
        NAME bifrost_scales_preview_distribution_tests
        COMMAND bifrost_scales_preview_distribution_tests
    )
endif()

if(BIFROST_SCALES_BUILD_BIFROST_OPERATOR)
    if(NOT BIFROST_LOCATION)
        message(FATAL_ERROR "BIFROST_LOCATION must point to the Bifrost installation root")
    endif()
    include(${BIFROST_LOCATION}/sdk/cmake/setup.cmake)
    find_package(Bifrost REQUIRED SDK)
    add_subdirectory(operator)
endif()
