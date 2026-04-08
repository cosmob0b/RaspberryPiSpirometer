from types import SimpleNamespace

from main import ArduinoTargetGameFrame


class FakeReader:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


def main():
    fake_reader = FakeReader()
    fake_frame = SimpleNamespace(inputs_closed=False, serial_reader=fake_reader)

    ArduinoTargetGameFrame.close_inputs(fake_frame)
    ArduinoTargetGameFrame.close_inputs(fake_frame)

    assert fake_reader.stop_calls == 1, f"Expected stop() once, got {fake_reader.stop_calls}"
    assert fake_frame.inputs_closed is True, "Expected inputs_closed to be True after first close"
    assert fake_frame.serial_reader is None, "Expected serial_reader to be cleared"

    print("CloseInputsTest passed")


if __name__ == "__main__":
    main()
