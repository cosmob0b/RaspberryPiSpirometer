from main import ArduinoSerialLiveReader


def main():
    original_detector = ArduinoSerialLiveReader.detect_available_serial_ports

    try:
        ArduinoSerialLiveReader.detect_available_serial_ports = staticmethod(lambda: ["/dev/ttyUSB0", "/dev/ttyS0"])
        auto_port = ArduinoSerialLiveReader.resolve_serial_port("auto")
        assert auto_port == "/dev/ttyUSB0", f"Expected /dev/ttyUSB0, got {auto_port}"

        explicit_port = ArduinoSerialLiveReader.resolve_serial_port("/dev/custom-device")
        assert explicit_port == "/dev/custom-device", f"Expected explicit port to be kept, got {explicit_port}"

        ArduinoSerialLiveReader.detect_available_serial_ports = staticmethod(lambda: [])
        no_port = ArduinoSerialLiveReader.resolve_serial_port("auto")
        assert no_port is None, f"Expected None when no ports exist, got {no_port}"
    finally:
        ArduinoSerialLiveReader.detect_available_serial_ports = original_detector

    print("SerialPortResolutionTest passed")


if __name__ == "__main__":
    main()
