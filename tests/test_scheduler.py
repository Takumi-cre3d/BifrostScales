from bifrost_scales.scheduler import (
    ChangeCategory,
    PreviewMode,
    PreviewSchedulerCore,
    SchedulerState,
)


def test_coalesces_to_latest_snapshot():
    scheduler = PreviewSchedulerCore(60, 180)
    scheduler.begin_interaction(now=0.0)
    scheduler.queue_change(ChangeCategory.DISTRIBUTION, {"seed": 1}, now=0.0)
    scheduler.queue_change(ChangeCategory.DISTRIBUTION, {"seed": 2}, now=0.01)
    scheduler.queue_change(ChangeCategory.DISTRIBUTION, {"seed": 3}, now=0.02)
    assert scheduler.poll(now=0.079) is None
    request = scheduler.poll(now=0.080)
    assert request is not None
    assert request.mode is PreviewMode.INTERACTIVE
    assert request.snapshot["seed"] == 3
    assert request.revision == 3


def test_latest_wins_while_evaluating():
    scheduler = PreviewSchedulerCore(0, 0)
    scheduler.begin_interaction(now=0.0)
    scheduler.queue_change(ChangeCategory.DISTRIBUTION, {"seed": 1}, now=0.0)
    first = scheduler.poll(now=0.0)
    assert first is not None
    scheduler.queue_change(ChangeCategory.DISTRIBUTION, {"seed": 9}, now=0.1)
    scheduler.queue_change(ChangeCategory.SHAPE, {"radius": 0.25}, now=0.2)
    assert scheduler.poll(now=1.0) is None
    assert scheduler.complete(first.revision, True, now=1.0)
    second = scheduler.poll(now=1.0)
    assert second is not None
    assert second.snapshot == {"seed": 9, "radius": 0.25}
    assert second.scope is ChangeCategory.DISTRIBUTION
    assert second.revision == 3


def test_release_schedules_settled_refinement():
    scheduler = PreviewSchedulerCore(0, 100)
    scheduler.begin_interaction(now=0.0)
    scheduler.queue_change(ChangeCategory.SHAPE, {"radius": 0.5}, now=0.0)
    interactive = scheduler.poll(now=0.0)
    assert interactive is not None
    scheduler.complete(interactive.revision, True, now=0.01)
    scheduler.end_interaction(now=0.02)
    assert scheduler.poll(now=0.119) is None
    settled = scheduler.poll(now=0.120)
    assert settled is not None
    assert settled.mode is PreviewMode.SETTLED
    assert settled.scope is ChangeCategory.SHAPE


def test_fault_requires_explicit_clear():
    scheduler = PreviewSchedulerCore(0, 0)
    scheduler.queue_change(ChangeCategory.DISTRIBUTION, {"seed": 2}, now=0.0)
    request = scheduler.poll(now=0.0)
    assert request is not None
    scheduler.complete(request.revision, False, "native boundary failed", now=0.0)
    assert scheduler.status.state is SchedulerState.ERROR
    revision = scheduler.queue_change(
        ChangeCategory.DISTRIBUTION, {"seed": 3}, now=1.0
    )
    assert revision == request.revision
    assert scheduler.poll(now=1.0) is None
    scheduler.clear_error()
    scheduler.request_settled(
        ChangeCategory.DISTRIBUTION, {"seed": 3}, now=2.0, immediate=True
    )
    assert scheduler.poll(now=2.0) is not None


def test_pause_drops_pending_work():
    scheduler = PreviewSchedulerCore(0, 0)
    scheduler.queue_change(ChangeCategory.DISPLAY, {"visible": False}, now=0.0)
    scheduler.pause()
    assert scheduler.status.state is SchedulerState.PAUSED
    assert scheduler.poll(now=1.0) is None
    scheduler.resume()
    assert scheduler.status.state is SchedulerState.IDLE


def test_repeated_end_interaction_is_idempotent():
    scheduler = PreviewSchedulerCore(0, 100)
    scheduler.begin_interaction(now=0.0)
    scheduler.queue_change(ChangeCategory.SHAPE, {"radius": 0.5}, now=0.0)
    interactive = scheduler.poll(now=0.0)
    assert interactive is not None
    scheduler.complete(interactive.revision, True, now=0.01)
    scheduler.end_interaction(now=0.02)
    first_revision = scheduler.status.revision
    scheduler.end_interaction(now=0.03)
    assert scheduler.status.revision == first_revision
    settled = scheduler.poll(now=0.12)
    assert settled is not None
    assert settled.revision == first_revision
