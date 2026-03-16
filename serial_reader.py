import argparse

import serial


def parse_args():
    parser = argparse.ArgumentParser(description="Simple serial monitor for sensor values")
    parser.add_argument("--port", required=True, help="Serial port (e.g., COM8 or /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        ser = serial.Serial(args.port, baudrate=args.baud, timeout=0.1)
    except Exception as exc:
        print(f"Failed to open port: {exc}")
        return

    print(f"Port opened on {args.port} @ {args.baud}. Listening...")

    try:
        while True:
            data = ser.read(1024)
            if data:
                print(data.decode(errors="ignore"), end="")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
