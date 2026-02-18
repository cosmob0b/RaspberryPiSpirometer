import serial


def main():
    port_name = "COM8"
    baud_rate = 9600

    try:
        ser = serial.Serial(port_name, baudrate=baud_rate, timeout=0.1)
    except Exception as exc:
        print(f"Failed to open port: {exc}")
        return

    print("Port opened. Listening...")

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
