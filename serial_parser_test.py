from main import ArduinoSerialLiveReader


def main():
    live = ArduinoSerialLiveReader.parse_live_line("LIVE,42,1.23,155.0")
    assert live is not None and live.total_pulses == 42

    raw = ArduinoSerialLiveReader.parse_live_line("42,1.23,155.0")
    assert raw is not None and raw.total_pulses == 42

    data = ArduinoSerialLiveReader.parse_live_line("DATA,42,1.23,155.0")
    assert data is not None and data.total_pulses == 42

    bad = ArduinoSerialLiveReader.parse_live_line("hello")
    assert bad is None

    print("SerialParserTest passed")


if __name__ == "__main__":
    main()
