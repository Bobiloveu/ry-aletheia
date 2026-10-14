from autodrive_console.scenario_activation import ScenarioActivationTracker


class _DeferredThread:
    def __init__(self, *, target, daemon, name):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self):
        self.started = True


def test_activation_is_visible_before_slow_runtime_work_finishes():
    threads = []
    events = []

    def runner(profile_id, document, progress):
        events.append((profile_id, document))
        progress("restarting", "正在重启定位与导航依赖", {"stages": []})
        return {"message": "场景已应用，定位与导航依赖已稳定就绪"}

    tracker = ScenarioActivationTracker(
        runner,
        thread_factory=lambda **kwargs: threads.append(_DeferredThread(**kwargs)) or threads[-1],
    )

    accepted = tracker.start("hall", {"profiles": []})

    assert accepted["state"] == "running"
    assert accepted["phase"] == "queued"
    assert threads[0].started is True
    assert events == []

    threads[0].target()

    assert events == [("hall", {"profiles": []})]
    assert tracker.status()["state"] == "completed"
    assert tracker.status()["phase"] == "completed"
