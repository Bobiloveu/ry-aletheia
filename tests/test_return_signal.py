from autodrive_console.return_signal import ReturnSignalGate


def test_return_signal_gate_accepts_only_the_first_waiting_return_event_for_each_armed_task():
    """A duplicate or unrelated TaskStatus event must not create a second return command."""
    gate = ReturnSignalGate()

    assert gate.accept("103") is False
    gate.arm(1)
    assert gate.accept("403") is False
    assert gate.accept("103") is True
    assert gate.accept("103") is False
    gate.disarm(1)
    assert gate.accept("103") is False

    gate.arm(2)
    assert gate.accept("103") is True
