#include "bifrost_scales/core.hpp"
#include "bifrost_scales/preview_distribution.hpp"

#include <algorithm>
#include <cstdint>
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
