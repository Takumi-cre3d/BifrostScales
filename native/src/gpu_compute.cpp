#include "bifrost_scales/gpu_compute.hpp"

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <mutex>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#if defined(_WIN32)
#  define NOMINMAX
#  include <windows.h>
#else
#  include <dlfcn.h>
#endif

namespace bifrost_scales::gpu {
namespace {

static_assert(sizeof(Float4) == 16U);
static_assert(sizeof(DirectionInput) == 48U);
static_assert(sizeof(DirectionGuide) == 96U);
static_assert(sizeof(DirectionSegment) == 64U);
static_assert(sizeof(DirectionOutput) == 48U);
static_assert(sizeof(Int4) == 16U);
static_assert(sizeof(ConflictInput) == 48U);
static_assert(sizeof(ConflictCounters) == 32U);

using ClInt = std::int32_t;
using ClUInt = std::uint32_t;
using ClULong = std::uint64_t;
using ClBool = ClUInt;
using ClBitfield = ClULong;
using ClDeviceType = ClBitfield;
using ClMemFlags = ClBitfield;
using ClCommandQueueProperties = ClBitfield;
using ClContextProperties = std::intptr_t;
using ClPlatformId = void*;
using ClDeviceId = void*;
using ClContext = void*;
using ClCommandQueue = void*;
using ClMem = void*;
using ClProgram = void*;
using ClKernel = void*;
using ClEvent = void*;

constexpr ClInt kClSuccess = 0;
constexpr ClBool kClTrue = 1U;
constexpr ClDeviceType kClDeviceTypeGpu = 1ULL << 2U;
constexpr ClMemFlags kClMemReadWrite = 1ULL << 0U;
constexpr ClMemFlags kClMemReadOnly = 1ULL << 2U;
constexpr ClMemFlags kClMemWriteOnly = 1ULL << 1U;
constexpr ClUInt kClDeviceName = 0x102BU;
constexpr ClUInt kClProgramBuildLog = 0x1183U;

using ClGetPlatformIDs = ClInt (*)(ClUInt, ClPlatformId*, ClUInt*);
using ClGetDeviceIDs = ClInt (*)(ClPlatformId, ClDeviceType, ClUInt, ClDeviceId*, ClUInt*);
using ClGetDeviceInfo = ClInt (*)(ClDeviceId, ClUInt, std::size_t, void*, std::size_t*);
using ClCreateContext = ClContext (*)(
    const ClContextProperties*,
    ClUInt,
    const ClDeviceId*,
    void (*)(const char*, const void*, std::size_t, void*),
    void*,
    ClInt*);
using ClCreateCommandQueue = ClCommandQueue (*)(
    ClContext,
    ClDeviceId,
    ClCommandQueueProperties,
    ClInt*);
using ClCreateProgramWithSource = ClProgram (*)(
    ClContext,
    ClUInt,
    const char**,
    const std::size_t*,
    ClInt*);
using ClBuildProgram = ClInt (*)(
    ClProgram,
    ClUInt,
    const ClDeviceId*,
    const char*,
    void (*)(ClProgram, void*),
    void*);
using ClGetProgramBuildInfo = ClInt (*)(
    ClProgram,
    ClDeviceId,
    ClUInt,
    std::size_t,
    void*,
    std::size_t*);
using ClCreateKernel = ClKernel (*)(ClProgram, const char*, ClInt*);
using ClCreateBuffer = ClMem (*)(ClContext, ClMemFlags, std::size_t, void*, ClInt*);
using ClSetKernelArg = ClInt (*)(ClKernel, ClUInt, std::size_t, const void*);
using ClEnqueueWriteBuffer = ClInt (*)(
    ClCommandQueue,
    ClMem,
    ClBool,
    std::size_t,
    std::size_t,
    const void*,
    ClUInt,
    const ClEvent*,
    ClEvent*);
using ClEnqueueNDRangeKernel = ClInt (*)(
    ClCommandQueue,
    ClKernel,
    ClUInt,
    const std::size_t*,
    const std::size_t*,
    const std::size_t*,
    ClUInt,
    const ClEvent*,
    ClEvent*);
using ClEnqueueReadBuffer = ClInt (*)(
    ClCommandQueue,
    ClMem,
    ClBool,
    std::size_t,
    std::size_t,
    void*,
    ClUInt,
    const ClEvent*,
    ClEvent*);
using ClFinish = ClInt (*)(ClCommandQueue);
using ClReleaseMemObject = ClInt (*)(ClMem);
using ClReleaseKernel = ClInt (*)(ClKernel);
using ClReleaseProgram = ClInt (*)(ClProgram);
using ClReleaseCommandQueue = ClInt (*)(ClCommandQueue);
using ClReleaseContext = ClInt (*)(ClContext);

constexpr const char* kOrientationKernel = R"CLC(
typedef struct {
    float4 position;
    float4 normal;
    float random_rotation;
    float padding0;
    float padding1;
    float padding2;
} DirectionInput;

typedef struct {
    float4 point;
    float4 fallback_tangent;
    float4 bounds_min;
    float4 bounds_max;
    float radius;
    float falloff;
    float strength;
    float angle_radians;
    uint segment_offset;
    uint segment_count;
    uint curve;
    uint point_guide;
} DirectionGuide;

typedef struct {
    float4 start;
    float4 delta;
    float4 tangent;
    float denominator;
    float padding0;
    float padding1;
    float padding2;
} DirectionSegment;

typedef struct {
    float4 tangent;
    float4 partition_tangent;
    float point_influence;
    float padding0;
    float padding1;
    float padding2;
} DirectionOutput;

float3 normalize_safe(float3 value, float3 fallback) {
    const float magnitude_squared = dot(value, value);
    return magnitude_squared <= 1.0e-20f
        ? fallback
        : value * rsqrt(magnitude_squared);
}

float3 project_plane(float3 value, float3 normal) {
    return value - normal * dot(value, normal);
}

float3 rotate_axis(float3 value, float3 axis, float radians) {
    const float3 unit_axis = normalize_safe(axis, (float3)(0.0f, 1.0f, 0.0f));
    const float cosine = cos(radians);
    const float sine = sin(radians);
    return value * cosine + cross(unit_axis, value) * sine +
        unit_axis * dot(unit_axis, value) * (1.0f - cosine);
}

float3 orthonormal_tangent(float3 normal) {
    const float3 unit_normal = normalize_safe(normal, (float3)(0.0f, 1.0f, 0.0f));
    float3 tangent = project_plane((float3)(0.0f, 1.0f, 0.0f), unit_normal);
    if (dot(tangent, tangent) <= 1.0e-10f) {
        tangent = project_plane((float3)(1.0f, 0.0f, 0.0f), unit_normal);
    }
    return normalize_safe(tangent, (float3)(1.0f, 0.0f, 0.0f));
}

float guide_influence(float distance, float radius, float falloff) {
    if (distance >= radius) {
        return 0.0f;
    }
    const float normalized = clamp(distance / radius, 0.0f, 1.0f);
    const float smooth = 1.0f - normalized * normalized * (3.0f - 2.0f * normalized);
    return pow(fmax(0.0f, smooth), falloff);
}

float3 blend_oriented(
    float3 current,
    float3 desired,
    float3 normal,
    float amount) {
    const float t = clamp(amount, 0.0f, 1.0f);
    const float3 start = normalize_safe(project_plane(current, normal), current);
    const float3 target = normalize_safe(project_plane(desired, normal), desired);
    if (t <= 0.0f) {
        return start;
    }
    if (t >= 1.0f) {
        return target;
    }
    const float cosine = clamp(dot(start, target), -1.0f, 1.0f);
    if (cosine <= -0.999999f) {
        return normalize_safe(
            rotate_axis(start, normal, 3.14159265358979323846f * t),
            target);
    }
    return normalize_safe(start * (1.0f - t) + target * t, target);
}

float3 guided_direction(
    float3 position,
    float3 normal,
    float3 fallback,
    __global const DirectionGuide* guides,
    uint guide_count,
    __global const DirectionSegment* segments,
    float* combined_influence) {
    const float3 base = normalize_safe(project_plane(fallback, normal), fallback);
    float3 accumulated = base;
    float remaining = 1.0f;
    for (uint guide_index = 0U; guide_index < guide_count; ++guide_index) {
        const DirectionGuide guide = guides[guide_index];
        if (position.x < guide.bounds_min.x - guide.radius ||
            position.x > guide.bounds_max.x + guide.radius ||
            position.y < guide.bounds_min.y - guide.radius ||
            position.y > guide.bounds_max.y + guide.radius ||
            position.z < guide.bounds_min.z - guide.radius ||
            position.z > guide.bounds_max.z + guide.radius) {
            continue;
        }
        float3 nearest_point = guide.point.xyz;
        float3 nearest_tangent = guide.fallback_tangent.xyz;
        float best_distance_squared = dot(position - nearest_point, position - nearest_point);
        if (guide.curve != 0U && guide.segment_count > 0U) {
            best_distance_squared = 3.402823466e+38f;
            for (uint local_index = 0U; local_index < guide.segment_count; ++local_index) {
                const DirectionSegment segment = segments[guide.segment_offset + local_index];
                const float amount = clamp(
                    dot(position - segment.start.xyz, segment.delta.xyz) /
                        fmax(segment.denominator, 1.0e-20f),
                    0.0f,
                    1.0f);
                const float3 point = segment.start.xyz + segment.delta.xyz * amount;
                const float distance_squared = dot(position - point, position - point);
                if (distance_squared < best_distance_squared) {
                    best_distance_squared = distance_squared;
                    nearest_point = point;
                    nearest_tangent = segment.tangent.xyz;
                }
            }
        }
        const float weight = clamp(
            guide.strength * guide_influence(
                sqrt(fmax(0.0f, best_distance_squared)),
                guide.radius,
                guide.falloff),
            0.0f,
            1.0f);
        if (weight <= 0.0f) {
            continue;
        }
        float3 desired = guide.curve != 0U
            ? nearest_tangent
            : nearest_point - position;
        desired = normalize_safe(project_plane(desired, normal), accumulated);
        if (fabs(guide.angle_radians) > 1.0e-12f) {
            desired = normalize_safe(
                rotate_axis(desired, normal, guide.angle_radians),
                accumulated);
        }
        accumulated = blend_oriented(accumulated, desired, normal, weight);
        remaining *= 1.0f - weight;
    }
    *combined_influence = clamp(1.0f - remaining, 0.0f, 1.0f);
    return normalize_safe(accumulated, base);
}

__kernel void orientation_preview(
    __global const DirectionInput* inputs,
    __global const DirectionGuide* guides,
    uint guide_count,
    __global const DirectionSegment* segments,
    float global_direction_radians,
    float random_rotation_degrees,
    __global DirectionOutput* outputs,
    uint sample_count) {
    const uint index = get_global_id(0);
    if (index >= sample_count) {
        return;
    }
    const DirectionInput input = inputs[index];
    const float3 normal = normalize_safe(input.normal.xyz, (float3)(0.0f, 1.0f, 0.0f));
    float3 tangent = orthonormal_tangent(normal);
    tangent = normalize_safe(
        rotate_axis(tangent, normal, global_direction_radians),
        tangent);
    float first_influence = 0.0f;
    tangent = guided_direction(
        input.position.xyz,
        normal,
        tangent,
        guides,
        guide_count,
        segments,
        &first_influence);
    float final_influence = 0.0f;
    const float3 partition = guided_direction(
        input.position.xyz,
        normal,
        tangent,
        guides,
        guide_count,
        segments,
        &final_influence);
    const float random_angle =
        (input.random_rotation * 2.0f - 1.0f) *
        random_rotation_degrees * 0.01745329251994329577f;
    const float3 final_tangent = normalize_safe(
        rotate_axis(partition, normal, random_angle),
        partition);
    float point_remaining = 1.0f;
    for (uint guide_index = 0U; guide_index < guide_count; ++guide_index) {
        const DirectionGuide guide = guides[guide_index];
        if (guide.point_guide == 0U) {
            continue;
        }
        const float distance = length(input.position.xyz - guide.point.xyz);
        const float weight = clamp(
            guide.strength * guide_influence(distance, guide.radius, guide.falloff),
            0.0f,
            1.0f);
        point_remaining *= 1.0f - weight;
    }
    DirectionOutput output;
    output.tangent = (float4)(final_tangent, 0.0f);
    output.partition_tangent = (float4)(partition, 0.0f);
    output.point_influence = clamp(1.0f - point_remaining, 0.0f, 1.0f);
    output.padding0 = 0.0f;
    output.padding1 = 0.0f;
    output.padding2 = 0.0f;
    outputs[index] = output;
}

typedef struct {
    float4 position;
    float4 gates;
    float local_spacing;
    int cell_x;
    int cell_y;
    int cell_z;
} ConflictInput;

typedef struct {
    uint considered_count;
    uint accepted_count;
    uint rejected_density;
    uint rejected_mask;
    uint rejected_conflict;
    uint padding0;
    uint padding1;
    uint padding2;
} ConflictCounters;

uint mix_conflict_component(uint value) {
    value ^= value >> 16U;
    value *= 0x7FEB352DU;
    value ^= value >> 15U;
    value *= 0x846CA68BU;
    return value ^ (value >> 16U);
}

uint hash_conflict_cell(int x, int y, int z) {
    const uint hx = mix_conflict_component(as_uint(x));
    const uint hy = mix_conflict_component(as_uint(y));
    const uint hz = mix_conflict_component(as_uint(z));
    return hx ^ rotate(hy, 11U) ^ rotate(hz, 22U);
}

int find_conflict_bucket(
    int x,
    int y,
    int z,
    uint bucket_capacity,
    __global int4* bucket_cells,
    __global int* bucket_heads,
    int create_bucket) {
    uint slot = hash_conflict_cell(x, y, z) & (bucket_capacity - 1U);
    for (uint probe = 0U; probe < bucket_capacity; ++probe) {
        const int head = bucket_heads[slot];
        if (head == -2) {
            if (create_bucket != 0) {
                bucket_cells[slot] = (int4)(x, y, z, 0);
                bucket_heads[slot] = -1;
                return (int)slot;
            }
            return -1;
        }
        const int4 stored = bucket_cells[slot];
        if (stored.x == x && stored.y == y && stored.z == z) {
            return (int)slot;
        }
        slot = (slot + 1U) & (bucket_capacity - 1U);
    }
    return -1;
}

__kernel void conflict_arbitration(
    __global const ConflictInput* inputs,
    uint candidate_count,
    uint max_accepted,
    uint bucket_capacity,
    __global int4* bucket_cells,
    __global int* bucket_heads,
    __global int* next_indices,
    __global uint* accepted_indices,
    __global ConflictCounters* output_counters) {
    if (get_global_id(0) != 0U) {
        return;
    }
    for (uint bucket = 0U; bucket < bucket_capacity; ++bucket) {
        bucket_heads[bucket] = -2;
    }

    ConflictCounters counters;
    counters.considered_count = 0U;
    counters.accepted_count = 0U;
    counters.rejected_density = 0U;
    counters.rejected_mask = 0U;
    counters.rejected_conflict = 0U;
    counters.padding0 = 0U;
    counters.padding1 = 0U;
    counters.padding2 = 0U;

    for (uint candidate_index = 0U;
         candidate_index < candidate_count &&
             counters.accepted_count < max_accepted;
         ++candidate_index) {
        ++counters.considered_count;
        const ConflictInput candidate = inputs[candidate_index];
        if (candidate.gates.x >= candidate.gates.z) {
            ++counters.rejected_density;
            continue;
        }
        if (candidate.gates.y >= candidate.gates.w) {
            ++counters.rejected_mask;
            continue;
        }

        int conflicts = 0;
        for (int dz = -1; dz <= 1 && conflicts == 0; ++dz) {
            for (int dy = -1; dy <= 1 && conflicts == 0; ++dy) {
                for (int dx = -1; dx <= 1 && conflicts == 0; ++dx) {
                    const int bucket = find_conflict_bucket(
                        candidate.cell_x + dx,
                        candidate.cell_y + dy,
                        candidate.cell_z + dz,
                        bucket_capacity,
                        bucket_cells,
                        bucket_heads,
                        0);
                    if (bucket < 0) {
                        continue;
                    }
                    for (int accepted_index = bucket_heads[bucket];
                         accepted_index >= 0;
                         accepted_index = next_indices[accepted_index]) {
                        const ConflictInput accepted = inputs[accepted_index];
                        const float delta_x =
                            candidate.position.x - accepted.position.x;
                        const float delta_y =
                            candidate.position.y - accepted.position.y;
                        const float delta_z =
                            candidate.position.z - accepted.position.z;
                        const float minimum_distance = fmax(
                            candidate.local_spacing,
                            accepted.local_spacing);
                        const float distance_squared =
                            delta_x * delta_x +
                            delta_y * delta_y +
                            delta_z * delta_z;
                        if (distance_squared <
                            minimum_distance * minimum_distance) {
                            conflicts = 1;
                            break;
                        }
                    }
                }
            }
        }
        if (conflicts != 0) {
            ++counters.rejected_conflict;
            continue;
        }

        const int bucket = find_conflict_bucket(
            candidate.cell_x,
            candidate.cell_y,
            candidate.cell_z,
            bucket_capacity,
            bucket_cells,
            bucket_heads,
            1);
        if (bucket < 0) {
            ++counters.rejected_conflict;
            continue;
        }
        next_indices[candidate_index] = bucket_heads[bucket];
        bucket_heads[bucket] = (int)candidate_index;
        accepted_indices[counters.accepted_count] = candidate_index;
        ++counters.accepted_count;
    }
    output_counters[0] = counters;
}

)CLC";

template <typename Function>
bool load_function(void* library, const char* name, Function& destination) {
#if defined(_WIN32)
    destination = reinterpret_cast<Function>(
        GetProcAddress(static_cast<HMODULE>(library), name));
#else
    destination = reinterpret_cast<Function>(dlsym(library, name));
#endif
    return destination != nullptr;
}

class Runtime {
public:
    Runtime() {
        initialize();
    }

    ~Runtime() {
        if (conflict_kernel_ != nullptr && release_kernel_ != nullptr) {
            release_kernel_(conflict_kernel_);
        }
        if (kernel_ != nullptr && release_kernel_ != nullptr) {
            release_kernel_(kernel_);
        }
        if (program_ != nullptr && release_program_ != nullptr) {
            release_program_(program_);
        }
        if (queue_ != nullptr && release_command_queue_ != nullptr) {
            release_command_queue_(queue_);
        }
        if (context_ != nullptr && release_context_ != nullptr) {
            release_context_(context_);
        }
#if defined(_WIN32)
        if (library_ != nullptr) {
            FreeLibrary(static_cast<HMODULE>(library_));
        }
#else
        if (library_ != nullptr) {
            dlclose(library_);
        }
#endif
    }

    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;

    bool available() const noexcept {
        return available_;
    }

    const std::string& reason() const noexcept {
        return reason_;
    }

    const std::string& device_name() const noexcept {
        return device_name_;
    }

    bool conflict_available() const noexcept {
        return conflict_available_;
    }

    const std::string& conflict_reason() const noexcept {
        return conflict_reason_;
    }

    bool execute(
        const std::vector<DirectionInput>& inputs,
        const std::vector<DirectionGuide>& guides,
        const std::vector<DirectionSegment>& segments,
        float global_direction_radians,
        float random_rotation_degrees,
        std::vector<DirectionOutput>& outputs,
        ExecutionInfo& info) {
        std::lock_guard<std::mutex> guard(mutex_);
        if (!available_) {
            info.fallback_reason = reason_;
            return false;
        }
        outputs.resize(inputs.size());
        const DirectionGuide empty_guide{};
        const DirectionSegment empty_segment{};
        const std::size_t input_bytes = inputs.size() * sizeof(DirectionInput);
        const std::size_t guide_bytes = std::max<std::size_t>(
            sizeof(DirectionGuide),
            guides.size() * sizeof(DirectionGuide));
        const std::size_t segment_bytes = std::max<std::size_t>(
            sizeof(DirectionSegment),
            segments.size() * sizeof(DirectionSegment));
        const std::size_t output_bytes = outputs.size() * sizeof(DirectionOutput);

        ClInt error = kClSuccess;
        ClMem input_buffer = create_buffer_(
            context_, kClMemReadOnly, input_bytes, nullptr, &error);
        if (error != kClSuccess || input_buffer == nullptr) {
            info.fallback_reason = "OpenCL input buffer creation failed";
            return false;
        }
        ClMem guide_buffer = create_buffer_(
            context_, kClMemReadOnly, guide_bytes, nullptr, &error);
        ClMem segment_buffer = create_buffer_(
            context_, kClMemReadOnly, segment_bytes, nullptr, &error);
        ClMem output_buffer = create_buffer_(
            context_, kClMemWriteOnly, output_bytes, nullptr, &error);
        auto release_buffers = [&]() {
            for (ClMem value : {input_buffer, guide_buffer, segment_buffer, output_buffer}) {
                if (value != nullptr) {
                    release_mem_object_(value);
                }
            }
        };
        if (guide_buffer == nullptr || segment_buffer == nullptr ||
            output_buffer == nullptr || error != kClSuccess) {
            info.fallback_reason = "OpenCL working buffer creation failed";
            release_buffers();
            return false;
        }

        using Clock = std::chrono::steady_clock;
        const auto upload_started = Clock::now();
        error = enqueue_write_buffer_(
            queue_, input_buffer, kClTrue, 0U, input_bytes,
            inputs.data(), 0U, nullptr, nullptr);
        error |= enqueue_write_buffer_(
            queue_, guide_buffer, kClTrue, 0U, guide_bytes,
            guides.empty() ? static_cast<const void*>(&empty_guide)
                           : static_cast<const void*>(guides.data()),
            0U, nullptr, nullptr);
        error |= enqueue_write_buffer_(
            queue_, segment_buffer, kClTrue, 0U, segment_bytes,
            segments.empty() ? static_cast<const void*>(&empty_segment)
                             : static_cast<const void*>(segments.data()),
            0U, nullptr, nullptr);
        info.upload_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - upload_started).count();
        const ClUInt guide_count = static_cast<ClUInt>(guides.size());
        const ClUInt sample_count = static_cast<ClUInt>(inputs.size());
        error |= set_kernel_arg_(kernel_, 0U, sizeof(input_buffer), &input_buffer);
        error |= set_kernel_arg_(kernel_, 1U, sizeof(guide_buffer), &guide_buffer);
        error |= set_kernel_arg_(kernel_, 2U, sizeof(guide_count), &guide_count);
        error |= set_kernel_arg_(kernel_, 3U, sizeof(segment_buffer), &segment_buffer);
        error |= set_kernel_arg_(
            kernel_, 4U, sizeof(global_direction_radians), &global_direction_radians);
        error |= set_kernel_arg_(
            kernel_, 5U, sizeof(random_rotation_degrees), &random_rotation_degrees);
        error |= set_kernel_arg_(kernel_, 6U, sizeof(output_buffer), &output_buffer);
        error |= set_kernel_arg_(kernel_, 7U, sizeof(sample_count), &sample_count);
        if (error != kClSuccess) {
            info.fallback_reason = "OpenCL orientation argument upload failed";
            release_buffers();
            return false;
        }

        const auto kernel_started = Clock::now();
        const std::size_t global_size =
            (inputs.size() + 63U) / 64U * 64U;
        const std::size_t local_size = 64U;
        error = enqueue_nd_range_kernel_(
            queue_, kernel_, 1U, nullptr, &global_size, &local_size,
            0U, nullptr, nullptr);
        if (error == kClSuccess) {
            error = finish_(queue_);
        }
        info.kernel_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - kernel_started).count();
        if (error != kClSuccess) {
            info.fallback_reason = "OpenCL orientation kernel execution failed";
            release_buffers();
            return false;
        }

        const auto readback_started = Clock::now();
        error = enqueue_read_buffer_(
            queue_, output_buffer, kClTrue, 0U, output_bytes,
            outputs.data(), 0U, nullptr, nullptr);
        info.readback_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - readback_started).count();
        release_buffers();
        if (error != kClSuccess) {
            outputs.clear();
            info.fallback_reason = "OpenCL orientation readback failed";
            return false;
        }
        return true;
    }


    bool execute_conflict(
        const std::vector<ConflictInput>& inputs,
        std::uint32_t max_accepted,
        std::vector<std::uint32_t>& accepted_indices,
        ConflictCounters& counters,
        ExecutionInfo& info) {
        std::lock_guard<std::mutex> guard(mutex_);
        if (!conflict_available_) {
            info.fallback_reason = conflict_reason_;
            return false;
        }
        if (inputs.empty() || max_accepted == 0U) {
            info.fallback_reason = "conflict arbitration input is empty";
            return false;
        }
        if (inputs.size() > (1ULL << 29U)) {
            info.fallback_reason = "conflict arbitration input exceeds hash capacity";
            return false;
        }

        std::uint32_t bucket_capacity = 16U;
        const std::size_t desired_capacity = inputs.size() * 2U;
        while (bucket_capacity < desired_capacity) {
            bucket_capacity <<= 1U;
        }
        const std::size_t accepted_capacity = std::min<std::size_t>(
            inputs.size(),
            max_accepted);
        const std::size_t input_bytes = inputs.size() * sizeof(ConflictInput);
        const std::size_t bucket_cell_bytes =
            static_cast<std::size_t>(bucket_capacity) * sizeof(Int4);
        const std::size_t bucket_head_bytes =
            static_cast<std::size_t>(bucket_capacity) * sizeof(std::int32_t);
        const std::size_t next_bytes =
            inputs.size() * sizeof(std::int32_t);
        const std::size_t accepted_bytes = std::max<std::size_t>(
            sizeof(std::uint32_t),
            accepted_capacity * sizeof(std::uint32_t));

        ClInt error = kClSuccess;
        ClMem input_buffer = create_buffer_(
            context_, kClMemReadOnly, input_bytes, nullptr, &error);
        ClMem bucket_cell_buffer = create_buffer_(
            context_, kClMemReadWrite, bucket_cell_bytes, nullptr, &error);
        ClMem bucket_head_buffer = create_buffer_(
            context_, kClMemReadWrite, bucket_head_bytes, nullptr, &error);
        ClMem next_buffer = create_buffer_(
            context_, kClMemReadWrite, next_bytes, nullptr, &error);
        ClMem accepted_buffer = create_buffer_(
            context_, kClMemWriteOnly, accepted_bytes, nullptr, &error);
        ClMem counters_buffer = create_buffer_(
            context_, kClMemWriteOnly, sizeof(ConflictCounters), nullptr, &error);
        auto release_buffers = [&]() {
            for (ClMem value : {
                     input_buffer,
                     bucket_cell_buffer,
                     bucket_head_buffer,
                     next_buffer,
                     accepted_buffer,
                     counters_buffer}) {
                if (value != nullptr) {
                    release_mem_object_(value);
                }
            }
        };
        if (input_buffer == nullptr ||
            bucket_cell_buffer == nullptr ||
            bucket_head_buffer == nullptr ||
            next_buffer == nullptr ||
            accepted_buffer == nullptr ||
            counters_buffer == nullptr ||
            error != kClSuccess) {
            info.fallback_reason =
                "OpenCL conflict working buffer creation failed";
            release_buffers();
            return false;
        }

        using Clock = std::chrono::steady_clock;
        const auto upload_started = Clock::now();
        error = enqueue_write_buffer_(
            queue_, input_buffer, kClTrue, 0U, input_bytes,
            inputs.data(), 0U, nullptr, nullptr);
        info.upload_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - upload_started).count();
        const ClUInt candidate_count = static_cast<ClUInt>(inputs.size());
        const ClUInt accepted_limit = std::min<ClUInt>(
            candidate_count,
            max_accepted);
        error |= set_kernel_arg_(
            conflict_kernel_, 0U, sizeof(input_buffer), &input_buffer);
        error |= set_kernel_arg_(
            conflict_kernel_, 1U, sizeof(candidate_count), &candidate_count);
        error |= set_kernel_arg_(
            conflict_kernel_, 2U, sizeof(accepted_limit), &accepted_limit);
        error |= set_kernel_arg_(
            conflict_kernel_, 3U, sizeof(bucket_capacity), &bucket_capacity);
        error |= set_kernel_arg_(
            conflict_kernel_, 4U, sizeof(bucket_cell_buffer), &bucket_cell_buffer);
        error |= set_kernel_arg_(
            conflict_kernel_, 5U, sizeof(bucket_head_buffer), &bucket_head_buffer);
        error |= set_kernel_arg_(
            conflict_kernel_, 6U, sizeof(next_buffer), &next_buffer);
        error |= set_kernel_arg_(
            conflict_kernel_, 7U, sizeof(accepted_buffer), &accepted_buffer);
        error |= set_kernel_arg_(
            conflict_kernel_, 8U, sizeof(counters_buffer), &counters_buffer);
        if (error != kClSuccess) {
            info.fallback_reason =
                "OpenCL conflict argument upload failed";
            release_buffers();
            return false;
        }

        const auto kernel_started = Clock::now();
        const std::size_t global_size = 1U;
        const std::size_t local_size = 1U;
        error = enqueue_nd_range_kernel_(
            queue_, conflict_kernel_, 1U, nullptr,
            &global_size, &local_size, 0U, nullptr, nullptr);
        if (error == kClSuccess) {
            error = finish_(queue_);
        }
        info.kernel_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - kernel_started).count();
        if (error != kClSuccess) {
            info.fallback_reason =
                "OpenCL conflict kernel execution failed";
            release_buffers();
            return false;
        }

        const auto readback_started = Clock::now();
        error = enqueue_read_buffer_(
            queue_, counters_buffer, kClTrue, 0U, sizeof(ConflictCounters),
            &counters, 0U, nullptr, nullptr);
        if (error == kClSuccess &&
            counters.accepted_count <= accepted_capacity) {
            accepted_indices.resize(counters.accepted_count);
            if (!accepted_indices.empty()) {
                error = enqueue_read_buffer_(
                    queue_, accepted_buffer, kClTrue, 0U,
                    accepted_indices.size() * sizeof(std::uint32_t),
                    accepted_indices.data(), 0U, nullptr, nullptr);
            }
        } else if (error == kClSuccess) {
            error = -1;
        }
        info.readback_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - readback_started).count();
        release_buffers();
        if (error != kClSuccess) {
            accepted_indices.clear();
            counters = ConflictCounters{};
            info.fallback_reason =
                "OpenCL conflict readback failed";
            return false;
        }
        return true;
    }

private:
    void initialize() {
#if defined(_WIN32)
        library_ = static_cast<void*>(LoadLibraryW(L"OpenCL.dll"));
#else
        library_ = dlopen("libOpenCL.so.1", RTLD_NOW | RTLD_LOCAL);
        if (library_ == nullptr) {
            library_ = dlopen("libOpenCL.so", RTLD_NOW | RTLD_LOCAL);
        }
#endif
        if (library_ == nullptr) {
            reason_ = "OpenCL runtime is not installed";
            return;
        }
        const bool loaded =
            load_function(library_, "clGetPlatformIDs", get_platform_ids_) &&
            load_function(library_, "clGetDeviceIDs", get_device_ids_) &&
            load_function(library_, "clGetDeviceInfo", get_device_info_) &&
            load_function(library_, "clCreateContext", create_context_) &&
            load_function(library_, "clCreateCommandQueue", create_command_queue_) &&
            load_function(library_, "clCreateProgramWithSource", create_program_with_source_) &&
            load_function(library_, "clBuildProgram", build_program_) &&
            load_function(library_, "clGetProgramBuildInfo", get_program_build_info_) &&
            load_function(library_, "clCreateKernel", create_kernel_) &&
            load_function(library_, "clCreateBuffer", create_buffer_) &&
            load_function(library_, "clSetKernelArg", set_kernel_arg_) &&
            load_function(library_, "clEnqueueWriteBuffer", enqueue_write_buffer_) &&
            load_function(library_, "clEnqueueNDRangeKernel", enqueue_nd_range_kernel_) &&
            load_function(library_, "clEnqueueReadBuffer", enqueue_read_buffer_) &&
            load_function(library_, "clFinish", finish_) &&
            load_function(library_, "clReleaseMemObject", release_mem_object_) &&
            load_function(library_, "clReleaseKernel", release_kernel_) &&
            load_function(library_, "clReleaseProgram", release_program_) &&
            load_function(library_, "clReleaseCommandQueue", release_command_queue_) &&
            load_function(library_, "clReleaseContext", release_context_);
        if (!loaded) {
            reason_ = "OpenCL runtime is missing required 1.2 entry points";
            return;
        }

        ClUInt platform_count = 0U;
        if (get_platform_ids_(0U, nullptr, &platform_count) != kClSuccess ||
            platform_count == 0U) {
            reason_ = "No OpenCL platform is available";
            return;
        }
        std::vector<ClPlatformId> platforms(platform_count);
        if (get_platform_ids_(platform_count, platforms.data(), nullptr) != kClSuccess) {
            reason_ = "OpenCL platform enumeration failed";
            return;
        }
        for (ClPlatformId platform : platforms) {
            ClUInt device_count = 0U;
            if (get_device_ids_(
                    platform, kClDeviceTypeGpu, 0U, nullptr, &device_count) != kClSuccess ||
                device_count == 0U) {
                continue;
            }
            std::vector<ClDeviceId> devices(device_count);
            if (get_device_ids_(
                    platform, kClDeviceTypeGpu, device_count,
                    devices.data(), nullptr) == kClSuccess) {
                device_ = devices.front();
                break;
            }
        }
        if (device_ == nullptr) {
            reason_ = "No OpenCL GPU device is available";
            return;
        }

        std::size_t device_name_size = 0U;
        if (get_device_info_(
                device_, kClDeviceName, 0U, nullptr, &device_name_size) == kClSuccess &&
            device_name_size > 1U) {
            std::vector<char> name(device_name_size, '\0');
            if (get_device_info_(
                    device_, kClDeviceName, name.size(), name.data(), nullptr) == kClSuccess) {
                device_name_ = name.data();
            }
        }
        ClInt error = kClSuccess;
        context_ = create_context_(
            nullptr, 1U, &device_, nullptr, nullptr, &error);
        if (context_ == nullptr || error != kClSuccess) {
            reason_ = "OpenCL context creation failed";
            return;
        }
        queue_ = create_command_queue_(context_, device_, 0U, &error);
        if (queue_ == nullptr || error != kClSuccess) {
            reason_ = "OpenCL command queue creation failed";
            return;
        }
        const char* source = kOrientationKernel;
        const std::size_t source_length = std::strlen(source);
        program_ = create_program_with_source_(
            context_, 1U, &source, &source_length, &error);
        if (program_ == nullptr || error != kClSuccess) {
            reason_ = "OpenCL orientation program creation failed";
            return;
        }
        error = build_program_(program_, 1U, &device_, "-cl-std=CL1.2", nullptr, nullptr);
        if (error != kClSuccess) {
            std::size_t log_size = 0U;
            get_program_build_info_(
                program_, device_, kClProgramBuildLog, 0U, nullptr, &log_size);
            std::vector<char> log(std::max<std::size_t>(1U, log_size), '\0');
            get_program_build_info_(
                program_, device_, kClProgramBuildLog,
                log.size(), log.data(), nullptr);
            reason_ = "OpenCL orientation kernel build failed";
            if (log_size > 1U) {
                reason_ += ": ";
                reason_ += log.data();
            }
            return;
        }
        kernel_ = create_kernel_(program_, "orientation_preview", &error);
        if (kernel_ == nullptr || error != kClSuccess) {
            reason_ = "OpenCL orientation kernel creation failed";
            return;
        }
        available_ = true;
        reason_.clear();
        conflict_kernel_ = create_kernel_(
            program_, "conflict_arbitration", &error);
        if (conflict_kernel_ == nullptr || error != kClSuccess) {
            conflict_reason_ = "OpenCL conflict kernel creation failed";
            return;
        }
        conflict_available_ = true;
        conflict_reason_.clear();
    }

    void* library_{nullptr};
    ClDeviceId device_{nullptr};
    ClContext context_{nullptr};
    ClCommandQueue queue_{nullptr};
    ClProgram program_{nullptr};
    ClKernel kernel_{nullptr};
    ClKernel conflict_kernel_{nullptr};
    bool available_{false};
    bool conflict_available_{false};
    std::string reason_{"OpenCL runtime is unavailable"};
    std::string conflict_reason_{"OpenCL conflict runtime is unavailable"};
    std::string device_name_;
    std::mutex mutex_;

    ClGetPlatformIDs get_platform_ids_{nullptr};
    ClGetDeviceIDs get_device_ids_{nullptr};
    ClGetDeviceInfo get_device_info_{nullptr};
    ClCreateContext create_context_{nullptr};
    ClCreateCommandQueue create_command_queue_{nullptr};
    ClCreateProgramWithSource create_program_with_source_{nullptr};
    ClBuildProgram build_program_{nullptr};
    ClGetProgramBuildInfo get_program_build_info_{nullptr};
    ClCreateKernel create_kernel_{nullptr};
    ClCreateBuffer create_buffer_{nullptr};
    ClSetKernelArg set_kernel_arg_{nullptr};
    ClEnqueueWriteBuffer enqueue_write_buffer_{nullptr};
    ClEnqueueNDRangeKernel enqueue_nd_range_kernel_{nullptr};
    ClEnqueueReadBuffer enqueue_read_buffer_{nullptr};
    ClFinish finish_{nullptr};
    ClReleaseMemObject release_mem_object_{nullptr};
    ClReleaseKernel release_kernel_{nullptr};
    ClReleaseProgram release_program_{nullptr};
    ClReleaseCommandQueue release_command_queue_{nullptr};
    ClReleaseContext release_context_{nullptr};
};

Runtime& runtime() {
    static Runtime value;
    return value;
}

enum class Policy {
    Off,
    Auto,
    Force,
};

Policy configured_policy() {
    const char* value = std::getenv("BIFROST_SCALES_GPU");
    if (value == nullptr || value[0] == '\0') {
        return Policy::Auto;
    }
    const std::string_view text(value);
    if (text == "off" || text == "0" || text == "false") {
        return Policy::Off;
    }
    if (text == "force" || text == "1" || text == "true" || text == "on") {
        return Policy::Force;
    }
    return Policy::Auto;
}

std::uint32_t minimum_sample_count() {
    const char* value = std::getenv("BIFROST_SCALES_GPU_MIN_SAMPLES");
    if (value == nullptr || value[0] == '\0') {
        return 4096U;
    }
    char* end = nullptr;
    const unsigned long parsed = std::strtoul(value, &end, 10);
    if (end == value || *end != '\0') {
        return 4096U;
    }
    return static_cast<std::uint32_t>(std::min<unsigned long>(
        parsed,
        std::numeric_limits<std::uint32_t>::max()));
}

std::uint32_t minimum_candidate_count() {
    const char* value = std::getenv(
        "BIFROST_SCALES_GPU_MIN_CANDIDATES");
    if (value == nullptr || value[0] == '\0') {
        return 4096U;
    }
    char* end = nullptr;
    const unsigned long parsed = std::strtoul(value, &end, 10);
    if (end == value || *end != '\0') {
        return 4096U;
    }
    return static_cast<std::uint32_t>(std::min<unsigned long>(
        parsed,
        std::numeric_limits<std::uint32_t>::max()));
}

}  // namespace

bool should_attempt_orientation(
    std::size_t sample_count,
    ExecutionInfo& info) {
    info = ExecutionInfo{};
    info.sample_count = static_cast<std::uint32_t>(std::min<std::size_t>(
        sample_count,
        std::numeric_limits<std::uint32_t>::max()));
    const Policy policy = configured_policy();
    if (policy == Policy::Off) {
        info.fallback_reason = "disabled by BIFROST_SCALES_GPU=off";
        return false;
    }
    info.requested = true;
    if (sample_count == 0U) {
        info.fallback_reason = "orientation input is empty";
        return false;
    }
    if (policy == Policy::Auto && sample_count < minimum_sample_count()) {
        info.fallback_reason = "sample count is below the GPU crossover threshold";
        return false;
    }
    Runtime& compute = runtime();
    info.available = compute.available();
    info.device = compute.device_name();
    if (!compute.available()) {
        info.fallback_reason = compute.reason();
        return false;
    }
    return true;
}

bool try_compute_orientation(
    const std::vector<DirectionInput>& inputs,
    const std::vector<DirectionGuide>& guides,
    const std::vector<DirectionSegment>& segments,
    float global_direction_radians,
    float random_rotation_degrees,
    std::vector<DirectionOutput>& outputs,
    ExecutionInfo& info) {
    if (!should_attempt_orientation(inputs.size(), info)) {
        return false;
    }
    Runtime& compute = runtime();
    if (!compute.execute(
            inputs,
            guides,
            segments,
            global_direction_radians,
            random_rotation_degrees,
            outputs,
            info)) {
        return false;
    }
    info.used = true;
    info.backend = "opencl-gpu+cpu-exact-settle";
    return true;
}

bool should_attempt_conflict(
    std::size_t candidate_count,
    ExecutionInfo& info) {
    info = ExecutionInfo{};
    info.sample_count = static_cast<std::uint32_t>(std::min<std::size_t>(
        candidate_count,
        std::numeric_limits<std::uint32_t>::max()));
    const Policy policy = configured_policy();
    if (policy == Policy::Off) {
        info.fallback_reason = "disabled by BIFROST_SCALES_GPU=off";
        return false;
    }
    info.requested = true;
    if (candidate_count == 0U) {
        info.fallback_reason = "conflict candidate input is empty";
        return false;
    }
    if (policy == Policy::Auto &&
        candidate_count < minimum_candidate_count()) {
        info.fallback_reason =
            "candidate count is below the GPU crossover threshold";
        return false;
    }
    Runtime& compute = runtime();
    info.available = compute.conflict_available();
    info.device = compute.device_name();
    if (!compute.conflict_available()) {
        info.fallback_reason = compute.conflict_reason().empty()
            ? compute.reason()
            : compute.conflict_reason();
        return false;
    }
    return true;
}

bool try_arbitrate_conflicts(
    const std::vector<ConflictInput>& inputs,
    std::uint32_t max_accepted,
    std::vector<std::uint32_t>& accepted_indices,
    ConflictCounters& counters,
    ExecutionInfo& info) {
    accepted_indices.clear();
    counters = ConflictCounters{};
    if (!should_attempt_conflict(inputs.size(), info)) {
        return false;
    }
    Runtime& compute = runtime();
    if (!compute.execute_conflict(
            inputs,
            max_accepted,
            accepted_indices,
            counters,
            info)) {
        return false;
    }
    info.used = true;
    info.backend =
        "opencl-gpu-conflict-reference+cpu-exact-settle";
    return true;
}

}  // namespace bifrost_scales::gpu
