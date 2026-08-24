#ifndef BIFROST_SCALES_GPU_COMPUTE_HPP
#define BIFROST_SCALES_GPU_COMPUTE_HPP

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace bifrost_scales::gpu {

struct alignas(16) Float4 {
    float x{0.0F};
    float y{0.0F};
    float z{0.0F};
    float w{0.0F};
};

struct alignas(16) DirectionInput {
    Float4 position{};
    Float4 normal{};
    float random_rotation{0.5F};
    float padding0{0.0F};
    float padding1{0.0F};
    float padding2{0.0F};
};

struct alignas(16) DirectionGuide {
    Float4 point{};
    Float4 fallback_tangent{1.0F, 0.0F, 0.0F, 0.0F};
    Float4 bounds_min{};
    Float4 bounds_max{};
    float radius{1.0F};
    float falloff{2.0F};
    float strength{1.0F};
    float angle_radians{0.0F};
    std::uint32_t segment_offset{0U};
    std::uint32_t segment_count{0U};
    std::uint32_t curve{0U};
    std::uint32_t point_guide{0U};
};

struct alignas(16) DirectionSegment {
    Float4 start{};
    Float4 delta{};
    Float4 tangent{1.0F, 0.0F, 0.0F, 0.0F};
    float denominator{0.0F};
    float padding0{0.0F};
    float padding1{0.0F};
    float padding2{0.0F};
};

struct alignas(16) DirectionOutput {
    Float4 tangent{};
    Float4 partition_tangent{};
    float point_influence{0.0F};
    float padding0{0.0F};
    float padding1{0.0F};
    float padding2{0.0F};
};

struct ExecutionInfo {
    bool requested{false};
    bool available{false};
    bool used{false};
    std::string backend{"cpu-multicore"};
    std::string device;
    std::string fallback_reason;
    double upload_ms{0.0};
    double kernel_ms{0.0};
    double readback_ms{0.0};
    std::uint32_t sample_count{0U};
};

// Cheap policy/runtime gate used before constructing compact GPU buffers.
// A false result is a complete CPU-fallback decision in `info`.
bool should_attempt_orientation(
    std::size_t sample_count,
    ExecutionInfo& info);

bool try_compute_orientation(
    const std::vector<DirectionInput>& inputs,
    const std::vector<DirectionGuide>& guides,
    const std::vector<DirectionSegment>& segments,
    float global_direction_radians,
    float random_rotation_degrees,
    std::vector<DirectionOutput>& outputs,
    ExecutionInfo& info);

}  // namespace bifrost_scales::gpu

#endif  // BIFROST_SCALES_GPU_COMPUTE_HPP
