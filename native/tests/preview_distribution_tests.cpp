#include "bifrost_scales/core.hpp"
#include "bifrost_scales/preview_distribution.hpp"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void check(bool condition, const char* expression, int line) {
    if (!condition) {
        throw std::runtime_error(
            std::string("check failed at line ") + std::to_string(line) +
            ": " + expression);
    }
}

#define CHECK(expression) check(static_cast<bool>(expression), #expression, __LINE__)

bifrost_scales::Mesh plane_mesh() {
    return {
        {
            {-10.0, 0.0, -10.0},
            {10.0, 0.0, -10.0},
            {10.0, 0.0, 10.0},
            {-10.0, 0.0, 10.0},
        },
        {{0U, 2U, 1U}, {0U, 3U, 2U}},
    };
}

bool throws_invalid_fields(
    const bifrost_scales::InteractiveCandidateBatch& batch,
    const bifrost_scales::Settings& settings,
    const bifrost_scales::InteractiveCandidateFields& fields) {
    try {
        (void)bifrost_scales::arbitrate_interactive_candidates(
            batch,
            settings,
            16U,
            fields);
    } catch (const std::invalid_argument&) {
        return true;
    }
    return false;
}


void set_gpu_override(const char* value) {
#ifdef _WIN32
    _putenv_s("BIFROST_SCALES_GPU", value);
#else
    setenv("BIFROST_SCALES_GPU", value, 1);
#endif
}

bool same_conflict_result(
    const bifrost_scales::InteractiveConflictResult& left,
    const bifrost_scales::InteractiveConflictResult& right) {
    return left.considered_count == right.considered_count &&
           left.accepted_count == right.accepted_count &&
           left.rejected_density == right.rejected_density &&
           left.rejected_mask == right.rejected_mask &&
           left.rejected_conflict == right.rejected_conflict &&
           left.default_spacing == right.default_spacing &&
           left.accepted_candidate_indices ==
               right.accepted_candidate_indices &&
           left.accepted_candidate_keys ==
               right.accepted_candidate_keys;
}

}  // namespace

int main() {
    const auto mesh = plane_mesh();
    bifrost_scales::Settings settings;
    settings.seed = 1106U;
    settings.spacing_factor = 0.82;

    const auto small =
        bifrost_scales::build_interactive_candidate_batch(mesh, settings, 512U);
    const auto large =
        bifrost_scales::build_interactive_candidate_batch(mesh, settings, 2048U);
    const auto reference =
        bifrost_scales::arbitrate_interactive_candidates(
            large,
            settings,
            256U);
    const auto repeat =
        bifrost_scales::arbitrate_interactive_candidates(
            large,
            settings,
            256U);

    CHECK(reference.has_consistent_sizes());
    CHECK(reference.accepted_count > 0U);
    CHECK(reference.accepted_count <= 256U);
    CHECK(reference.accepted_candidate_indices ==
          repeat.accepted_candidate_indices);
    CHECK(reference.accepted_candidate_keys ==
          repeat.accepted_candidate_keys);
    CHECK(reference.considered_count == repeat.considered_count);
    CHECK(reference.rejected_conflict == repeat.rejected_conflict);
    for (std::size_t slot = 0U;
         slot < reference.accepted_candidate_indices.size();
         ++slot) {
        const std::uint32_t index =
            reference.accepted_candidate_indices[slot];
        CHECK(index < large.candidate_count);
        CHECK(reference.accepted_candidate_keys[slot] ==
              large.candidate_keys[index]);
        if (slot > 0U) {
            CHECK(reference.accepted_candidate_indices[slot - 1U] < index);
        }
    }

    const auto small_result =
        bifrost_scales::arbitrate_interactive_candidates(
            small,
            settings,
            256U);
    std::vector<std::uint32_t> large_prefix;
    for (const std::uint32_t index :
         reference.accepted_candidate_indices) {
        if (index < small.candidate_count) {
            large_prefix.push_back(index);
        }
    }
    CHECK(large_prefix == small_result.accepted_candidate_indices);

    bifrost_scales::InteractiveCandidateFields rejected_density;
    rejected_density.density_acceptance.assign(
        small.candidate_count,
        0.0F);
    const auto density_result =
        bifrost_scales::arbitrate_interactive_candidates(
            small,
            settings,
            32U,
            rejected_density);
    CHECK(density_result.has_consistent_sizes());
    CHECK(density_result.accepted_count == 0U);
    CHECK(density_result.rejected_density == small.candidate_count);

    bifrost_scales::InteractiveCandidateFields rejected_mask;
    rejected_mask.mask_acceptance.assign(small.candidate_count, 0.0F);
    const auto mask_result =
        bifrost_scales::arbitrate_interactive_candidates(
            small,
            settings,
            32U,
            rejected_mask);
    CHECK(mask_result.has_consistent_sizes());
    CHECK(mask_result.accepted_count == 0U);
    CHECK(mask_result.rejected_mask == small.candidate_count);

    bifrost_scales::InteractiveCandidateFields no_conflicts;
    no_conflicts.local_spacing.assign(small.candidate_count, 1.0e-8F);
    const auto no_conflict_result =
        bifrost_scales::arbitrate_interactive_candidates(
            small,
            settings,
            100U,
            no_conflicts);
    CHECK(no_conflict_result.has_consistent_sizes());
    CHECK(no_conflict_result.accepted_count == 100U);
    CHECK(no_conflict_result.considered_count == 100U);

    bifrost_scales::InteractiveCandidateFields one_winner;
    one_winner.local_spacing.assign(small.candidate_count, 1000.0F);
    const auto one_winner_result =
        bifrost_scales::arbitrate_interactive_candidates(
            small,
            settings,
            32U,
            one_winner);
    CHECK(one_winner_result.accepted_count == 1U);
    CHECK(one_winner_result.rejected_conflict ==
          small.candidate_count - 1U);

    const auto zero_limit =
        bifrost_scales::arbitrate_interactive_candidates(
            small,
            settings,
            0U);
    CHECK(zero_limit.has_consistent_sizes());
    CHECK(zero_limit.considered_count == 0U);

    bifrost_scales::InteractiveCandidateFields wrong_size;
    wrong_size.local_spacing.assign(2U, 1.0F);
    CHECK(throws_invalid_fields(small, settings, wrong_size));
    bifrost_scales::InteractiveCandidateFields invalid_spacing;
    invalid_spacing.local_spacing.assign(small.candidate_count, 1.0F);
    invalid_spacing.local_spacing[5U] = 0.0F;
    CHECK(throws_invalid_fields(small, settings, invalid_spacing));

    set_gpu_override("off");
    bifrost_scales::gpu::ExecutionInfo gpu_off_info;
    const auto gpu_off_result =
        bifrost_scales::arbitrate_interactive_candidates_accelerated(
            large,
            settings,
            256U,
            gpu_off_info);
    CHECK(same_conflict_result(gpu_off_result, reference));
    CHECK(!gpu_off_info.requested);
    CHECK(!gpu_off_info.used);
    CHECK(gpu_off_info.backend == "cpu-conflict-reference");
    CHECK(!gpu_off_info.fallback_reason.empty());

    set_gpu_override("force");
    bifrost_scales::gpu::ExecutionInfo gpu_force_info;
    const auto gpu_force_result =
        bifrost_scales::arbitrate_interactive_candidates_accelerated(
            large,
            settings,
            256U,
            gpu_force_info);
    CHECK(same_conflict_result(gpu_force_result, reference));
    CHECK(gpu_force_info.requested);
    if (gpu_force_info.used) {
        CHECK(gpu_force_info.available);
        CHECK(gpu_force_info.backend ==
              "opencl-gpu-conflict-reference+cpu-exact-settle");
        CHECK(!gpu_force_info.device.empty());
        CHECK(gpu_force_info.iteration_count > 0U);
    } else {
        CHECK(!gpu_force_info.fallback_reason.empty());
        CHECK(gpu_force_info.backend == "cpu-conflict-reference");
    }

    bifrost_scales::InteractiveCandidateFields varied_fields;
    varied_fields.density_acceptance.resize(large.candidate_count);
    varied_fields.mask_acceptance.resize(large.candidate_count);
    varied_fields.local_spacing.resize(large.candidate_count);
    for (std::size_t index = 0U;
         index < large.candidate_count;
         ++index) {
        varied_fields.density_acceptance[index] =
            index % 3U == 0U ? 0.45F : 0.85F;
        varied_fields.mask_acceptance[index] =
            index % 5U == 0U ? 0.55F : 0.95F;
        varied_fields.local_spacing[index] =
            reference.default_spacing *
            (index % 2U == 0U ? 0.75F : 1.25F);
    }
    const auto varied_reference =
        bifrost_scales::arbitrate_interactive_candidates(
            large,
            settings,
            256U,
            varied_fields);
    bifrost_scales::gpu::ExecutionInfo varied_gpu_info;
    const auto varied_gpu =
        bifrost_scales::arbitrate_interactive_candidates_accelerated(
            large,
            settings,
            256U,
            varied_gpu_info,
            varied_fields);
    CHECK(same_conflict_result(varied_gpu, varied_reference));
    if (varied_gpu_info.used) {
        CHECK(varied_gpu_info.available);
        CHECK(varied_gpu_info.iteration_count > 0U);
    } else {
        CHECK(!varied_gpu_info.fallback_reason.empty());
    }

    if (gpu_force_info.used) {
        for (std::uint64_t seed = 1U; seed <= 8U; ++seed) {
            bifrost_scales::Settings sweep_settings = settings;
            sweep_settings.seed = seed;
            const auto sweep_batch =
                bifrost_scales::build_interactive_candidate_batch(
                    mesh,
                    sweep_settings,
                    1024U);
            const auto sweep_reference =
                bifrost_scales::arbitrate_interactive_candidates(
                    sweep_batch,
                    sweep_settings,
                    128U);
            bifrost_scales::gpu::ExecutionInfo sweep_info;
            const auto sweep_gpu =
                bifrost_scales::arbitrate_interactive_candidates_accelerated(
                    sweep_batch,
                    sweep_settings,
                    128U,
                    sweep_info);
            CHECK(sweep_info.used);
            CHECK(same_conflict_result(
                sweep_gpu,
                sweep_reference));
        }
    }

    bifrost_scales::gpu::ExecutionInfo no_conflict_gpu_info;
    const auto no_conflict_gpu =
        bifrost_scales::arbitrate_interactive_candidates_accelerated(
            small,
            settings,
            100U,
            no_conflict_gpu_info,
            no_conflicts);
    CHECK(same_conflict_result(
        no_conflict_gpu,
        no_conflict_result));
    bifrost_scales::gpu::ExecutionInfo one_winner_gpu_info;
    const auto one_winner_gpu =
        bifrost_scales::arbitrate_interactive_candidates_accelerated(
            small,
            settings,
            32U,
            one_winner_gpu_info,
            one_winner);
    CHECK(same_conflict_result(
        one_winner_gpu,
        one_winner_result));
    set_gpu_override("auto");
    bifrost_scales::gpu::ExecutionInfo auto_small_info;
    const auto auto_small =
        bifrost_scales::arbitrate_interactive_candidates_accelerated(
            small,
            settings,
            256U,
            auto_small_info);
    CHECK(same_conflict_result(auto_small, small_result));
    CHECK(auto_small_info.requested);
    CHECK(!auto_small_info.used);
    CHECK(auto_small_info.fallback_reason.find("below") !=
          std::string::npos);

    bifrost_scales::Settings settled_settings = settings;
    settled_settings.target_count = 32U;
    settled_settings.interactive_budget = 32U;
    settled_settings.settled_budget = 32U;
    bifrost_scales::clear_native_stage_cache();
    const auto settled_before = bifrost_scales::generate(
        mesh,
        settled_settings,
        bifrost_scales::PreviewMode::Settled);
    (void)bifrost_scales::arbitrate_interactive_candidates(
        large,
        settings,
        256U);
    bifrost_scales::clear_native_stage_cache();
    const auto settled_after = bifrost_scales::generate(
        mesh,
        settled_settings,
        bifrost_scales::PreviewMode::Settled);
    CHECK(settled_after.mesh.vertices == settled_before.mesh.vertices);
    CHECK(settled_after.mesh.faces == settled_before.mesh.faces);
    CHECK(settled_after.mesh.cell_ids == settled_before.mesh.cell_ids);

    std::cout << "bifrost_scales_preview_distribution_tests: PASS\n";
    return 0;
}
