import argparse
import random
import threading
import math
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import messagebox

# Gameplay constants (Arduino serial is authoritative gameplay input)
MAX_GAME_VOLUME_LITERS = 2.0
VOLUME_DIRECTION_EPSILON = 0.01
TARGET_MIN_LEVEL = 0.15
TARGET_MAX_LEVEL = 0.85
TARGET_TOLERANCE = 0.06


def clamp(value, low, high):
    return max(low, min(value, high))


@dataclass
class ArduinoLiveSample:
    total_pulses: int
    volume_liters: float
    rpm: float


class AppSettings:
    text_size = "Medium"
    sound_on = True
    color_mode = "Light"
    _listeners = []

    @classmethod
    def add_change_listener(cls, listener):
        cls._listeners.append(listener)

    @classmethod
    def remove_change_listener(cls, listener):
        if listener in cls._listeners:
            cls._listeners.remove(listener)

    @classmethod
    def _notify(cls, prop, old, new):
        if old == new:
            return
        for listener in list(cls._listeners):
            listener(prop, old, new)

    @classmethod
    def set_text_size(cls, size):
        old = cls.text_size
        cls.text_size = size
        cls._notify("text_size", old, size)

    @classmethod
    def set_sound_on(cls, enabled):
        old = cls.sound_on
        cls.sound_on = enabled
        cls._notify("sound_on", old, enabled)

    @classmethod
    def set_color_mode(cls, mode):
        old = cls.color_mode
        cls.color_mode = mode
        cls._notify("color_mode", old, mode)

    @classmethod
    def get_base_font_size(cls):
        if cls.text_size == "Small":
            return 14
        if cls.text_size == "Large":
            return 22
        return 18

    @classmethod
    def get_background_color(cls):
        return "#2f2f2f" if cls.color_mode == "Dark" else "#ffffff"

    @classmethod
    def get_foreground_color(cls):
        return "#ffffff" if cls.color_mode == "Dark" else "#000000"


class GameHistory:
    scores = []
    target_records = []

    @classmethod
    def add_score(cls, score):
        cls.scores.append(score)

    @classmethod
    def add_target_record(cls, record):
        cls.target_records.append(record)

    @classmethod
    def format_scores(cls):
        sections = []
        if cls.scores:
            lines = ["Classic Scores:"]
            for i, score in enumerate(cls.scores, start=1):
                lines.append(f"#{i}: {score} points")
            sections.append("\n".join(lines))
        else:
            sections.append("Classic Scores:\nNo scores recorded yet.")

        sections.append(cls.format_target_records())
        return "\n\n".join(sections)

    @classmethod
    def format_target_records(cls):
        if not cls.target_records:
            return "Completed Targets:\nNo completed targets recorded yet."

        lines = ["Completed Targets:"]
        for i, record in enumerate(cls.target_records, start=1):
            lines.append(
                f"#{i} [{record['timestamp']}]: Direction {record['direction']} | "
                f"Target Vol {record['target_volume_level']:.2f} ({record['target_volume_liters']:.2f} L) | "
                f"Success Vol {record['success_volume_liters']:.2f} L | "
                f"Peak RPM {record['peak_rpm']:.1f}"
            )
            lines.append(
                f"    RPM samples: {record['rpm_samples']} | "
                f"Pulses@Success: {record['success_total_pulses']}"
            )
        return "\n".join(lines)


class TargetSession:
    def __init__(self, tolerance=TARGET_TOLERANCE):
        self.tolerance = tolerance
        self.target_direction = "blow"
        self.start_volume_level = 0.5
        self.target_volume_level = 0.5
        self.peak_rpm = 0.0
        self.rpm_samples = []
        self.goal_met = False
        self.success_volume_liters = 0.0
        self.success_total_pulses = 0

    def spawn_new_target(self, min_level=TARGET_MIN_LEVEL, max_level=TARGET_MAX_LEVEL):
        self.target_direction = random.choice(["blow", "suck"])

        if self.target_direction == "blow":
            self.start_volume_level = random.uniform(0.20, 0.35)
            self.target_volume_level = random.uniform(0.55, min(0.85, max_level))
        else:
            self.start_volume_level = random.uniform(0.65, 0.85)
            self.target_volume_level = random.uniform(max(0.15, min_level), 0.45)

        self.start_volume_level = clamp(self.start_volume_level, min_level, max_level)
        self.target_volume_level = clamp(self.target_volume_level, min_level, max_level)
        self.rpm_samples = []
        self.peak_rpm = 0.0
        self.goal_met = False
        self.success_volume_liters = 0.0
        self.success_total_pulses = 0

    def check_goal(self, inferred_direction, volume_level, volume_liters, rpm, total_pulses):
        self.rpm_samples.append(round(rpm, 1))
        self.peak_rpm = max(self.peak_rpm, rpm)
        in_target = abs(volume_level - self.target_volume_level) <= self.tolerance
        direction_ok = inferred_direction == self.target_direction

        self.goal_met = in_target and direction_ok
        if self.goal_met:
            self.success_volume_liters = volume_liters
            self.success_total_pulses = total_pulses

        return self.goal_met

    def record(self):
        return {
            "timestamp": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "direction": "Blow" if self.target_direction == "blow" else "Suck",
            "target_volume_level": self.target_volume_level,
            "target_volume_liters": self.target_volume_level * MAX_GAME_VOLUME_LITERS,
            "success_volume_liters": self.success_volume_liters,
            "peak_rpm": self.peak_rpm,
            "rpm_samples": ", ".join(f"{x:.1f}" for x in self.rpm_samples) if self.rpm_samples else "none",
            "success_total_pulses": self.success_total_pulses,
        }


class ArduinoSerialLiveReader:
    """Read line-based LIVE packets from an Arduino over serial."""

    def __init__(self, serial_port, baud_rate=115200, timeout=0.1):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self._serial = None

    def start(self):
        try:
            import serial  # type: ignore
        except Exception as exc:
            raise RuntimeError("pyserial is required. Install with: pip install pyserial") from exc

        self._serial = serial.Serial(self.serial_port, self.baud_rate, timeout=self.timeout)
        self._serial.reset_input_buffer()

    def stop(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    @staticmethod
    def parse_live_line(text):
        parts = text.split(",")
        if len(parts) != 4 or parts[0] != "LIVE":
            return None

        try:
            sample = ArduinoLiveSample(
                total_pulses=int(parts[1]),
                volume_liters=float(parts[2]),
                rpm=float(parts[3]),
            )
        except ValueError:
            return None

        if sample.total_pulses < 0:
            return None
        if not math.isfinite(sample.volume_liters) or not math.isfinite(sample.rpm):
            return None
        return sample

    def read_latest_sample(self, sample_seconds=0.5):
        if self._serial is None:
            return None

        deadline = time.time() + sample_seconds
        latest = None

        while time.time() < deadline:
            raw = self._serial.readline()
            if not raw:
                continue
            text = raw.decode("utf-8", errors="ignore").strip()
            if not text:
                continue

            sample = self.parse_live_line(text)
            if sample is None:
                continue
            latest = sample

        return latest


class BalloonCanvas(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, highlightthickness=0, **kwargs)
        self.volume_level = 0.0
        self.goal_level = 0.6
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_volume_level(self, level):
        self.volume_level = max(0.0, min(level, 1.0))
        self.redraw()

    def set_goal_level(self, level):
        self.goal_level = max(0.0, min(level, 1.0))
        self.redraw()

    def redraw(self):
        self.delete("all")
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)

        max_diameter = max(min(width, height) - 40, 40)
        min_diameter = max(40, max_diameter // 3)

        diameter = round(min_diameter + (max_diameter - min_diameter) * self.volume_level)
        goal_diameter = round(min_diameter + (max_diameter - min_diameter) * self.goal_level)

        x = (width - diameter) // 2
        y = (height - diameter) // 2
        gx = (width - goal_diameter) // 2
        gy = (height - goal_diameter) // 2

        self.create_oval(gx, gy, gx + goal_diameter, gy + goal_diameter, outline="#1e90ff", width=2, dash=(6, 6))
        self.create_oval(x, y, x + diameter, y + diameter, fill="#ff69b4", outline="#ffffff", width=2)

        string_x = x + diameter // 2
        string_y = y + diameter
        self.create_line(string_x, string_y, string_x, string_y + 30, fill="#444444", width=2)


class MainApp(tk.Tk):
    def __init__(self, sample_window=0.5, serial_port="/dev/ttyACM0", baud_rate=115200):
        super().__init__()
        self.title("My Game Menu")
        self.set_window_size()
        self.minsize(420, 420)
        self.resizable(True, True)
        self.current_frame = None

        self.sample_window = sample_window
        self.serial_port = serial_port
        self.baud_rate = baud_rate

        self.show_main_menu()

    def set_window_size(self):
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(max(int(screen_w * 0.8), 460), screen_w)
        height = min(max(int(screen_h * 0.8), 460), screen_h)
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def show_frame(self, frame_cls):
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = frame_cls(self)
        self.current_frame.pack(fill="both", expand=True)

    def show_main_menu(self):
        self.show_frame(MainMenuFrame)

    def show_game_selection(self):
        self.show_frame(GameSelectionFrame)

    def show_breathing_target_game(self):
        self.show_frame(ArduinoTargetGameFrame)

    def show_history(self):
        self.show_frame(HistoryFrame)

    def show_settings(self):
        self.show_frame(SettingsFrame)


class MainMenuFrame(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=AppSettings.get_background_color())
        base_font = AppSettings.get_base_font_size()
        fg = AppSettings.get_foreground_color()
        bg = AppSettings.get_background_color()

        title = tk.Label(self, text="My Game Menu", font=("Arial", 28, "bold"), fg=fg, bg=bg)
        title.pack(pady=(24, 20))

        button_wrap = tk.Frame(self, bg=bg)
        button_wrap.pack(expand=True)

        buttons = [
            ("Begin Game", app.show_game_selection),
            ("Settings", app.show_settings),
            ("History & Data", app.show_history),
            ("Exit", app.destroy),
        ]

        for text, cmd in buttons:
            tk.Button(button_wrap, text=text, font=("Arial", base_font), width=18, command=cmd).pack(pady=8)


class GameSelectionFrame(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=AppSettings.get_background_color())
        base_font = AppSettings.get_base_font_size()
        fg = AppSettings.get_foreground_color()
        bg = AppSettings.get_background_color()

        tk.Label(self, text="Select a Game", font=("Arial", 24, "bold"), fg=fg, bg=bg).pack(pady=(24, 12))
        tk.Label(self, text="Arduino serial gameplay", font=("Arial", max(base_font - 2, 10)), fg=fg, bg=bg).pack(pady=(0, 20))

        games_wrap = tk.Frame(self, bg=bg)
        games_wrap.pack(expand=True)

        tk.Button(
            games_wrap,
            text="Breathing Target Game",
            font=("Arial", base_font),
            width=24,
            command=app.show_breathing_target_game,
        ).pack(pady=8)

        tk.Button(self, text="Back to Menu", font=("Arial", max(base_font - 2, 10)), command=app.show_main_menu).pack(pady=(0, 20))


class ArduinoTargetGameFrame(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=AppSettings.get_background_color())
        self.app = app
        self.running = True
        self.serial_reader = None

        self.previous_volume_liters = None
        self.live_direction = "neutral"
        self.current_volume_liters = 0.0
        self.current_volume_level = 0.0

        self.target_session = TargetSession()
        self.target_session.spawn_new_target()

        base_font = AppSettings.get_base_font_size()
        self.fg = AppSettings.get_foreground_color()
        bg = AppSettings.get_background_color()

        self.status_label = tk.Label(
            self,
            text=f"Arduino serial: {app.serial_port} @ {app.baud_rate}",
            font=("Arial", base_font, "bold"),
            fg=self.fg,
            bg=bg,
        )
        self.status_label.pack(pady=(16, 8))

        self.balloon = BalloonCanvas(self, bg=bg)
        self.balloon.set_goal_level(self.target_session.target_volume_level)
        self.balloon.set_volume_level(self.target_session.start_volume_level)
        self.balloon.pack(fill="both", expand=True, padx=16, pady=8)

        self.game_label = tk.Label(
            self,
            text="Breathing Target Game",
            font=("Arial", max(base_font - 2, 10), "bold"),
            fg=self.fg,
            bg=bg,
        )
        self.game_label.pack(pady=(0, 4))

        self.goal_label = tk.Label(self, font=("Arial", max(base_font - 3, 10)), fg=self.fg, bg=bg)
        self.goal_label.pack(pady=(0, 4))

        self.target_direction_label = tk.Label(self, font=("Arial", max(base_font - 3, 10)), fg=self.fg, bg=bg)
        self.target_direction_label.pack(pady=(0, 4))

        self.direction_label = tk.Label(self, text="Live direction: Neutral", font=("Arial", max(base_font - 3, 10)), fg=self.fg, bg=bg)
        self.direction_label.pack(pady=(0, 4))

        self.rpm_label = tk.Label(self, text="Current RPM: 0.0", font=("Arial", max(base_font - 2, 10)), fg=self.fg, bg=bg)
        self.rpm_label.pack(pady=(0, 4))

        self.volume_label = tk.Label(
            self,
            text="Current volume: 0.00 L (0.00)",
            font=("Arial", max(base_font - 2, 10)),
            fg=self.fg,
            bg=bg,
        )
        self.volume_label.pack(pady=(0, 8))

        tk.Button(self, text="Back to Menu", font=("Arial", max(base_font - 2, 10)), command=self.back_to_menu).pack(pady=(0, 16))

        self.update_goal_text()
        self.start_serial_listener()

    def destroy(self):
        self.running = False
        self.close_inputs()
        super().destroy()

    def back_to_menu(self):
        self.running = False
        self.close_inputs()
        self.app.show_main_menu()

    def update_goal_text(self):
        self.goal_label.configure(
            text=(
                f"Target volume: {self.target_session.target_volume_level:.2f} "
                f"({self.target_session.target_volume_level * MAX_GAME_VOLUME_LITERS:.2f} L) "
                f"± {self.target_session.tolerance:.2f}"
            )
        )
        direction_text = "Blow" if self.target_session.target_direction == "blow" else "Suck"
        self.target_direction_label.configure(text=f"Direction target: {direction_text}")

    def infer_direction(self, current_volume_liters):
        if self.previous_volume_liters is None:
            return "neutral"

        delta = current_volume_liters - self.previous_volume_liters
        if delta > VOLUME_DIRECTION_EPSILON:
            return "blow"
        if delta < -VOLUME_DIRECTION_EPSILON:
            return "suck"
        return "neutral"

    def start_serial_listener(self):
        threading.Thread(target=self.serial_loop, name="Arduino-Serial-Listener", daemon=True).start()

    def serial_loop(self):
        try:
            self.serial_reader = ArduinoSerialLiveReader(self.app.serial_port, self.app.baud_rate, timeout=0.1)
            self.serial_reader.start()
            while self.running:
                sample = self.serial_reader.read_latest_sample(sample_seconds=self.app.sample_window)
                if sample is not None:
                    self.app.after(0, self.handle_live_sample, sample)
        except Exception as exc:
            self.app.after(0, lambda: self.status_label.configure(text=f"Serial error: {exc}"))
        finally:
            self.close_inputs()

    def handle_live_sample(self, sample):
        inferred_direction = self.infer_direction(sample.volume_liters)

        self.current_volume_liters = sample.volume_liters
        self.current_volume_level = clamp(sample.volume_liters / MAX_GAME_VOLUME_LITERS, 0.0, 1.0)
        self.live_direction = inferred_direction

        self.volume_label.configure(
            text=f"Current volume: {sample.volume_liters:.2f} L ({self.current_volume_level:.2f})"
        )
        self.rpm_label.configure(text=f"Current RPM: {sample.rpm:.1f}")
        self.direction_label.configure(text=f"Live direction: {inferred_direction.capitalize()}")
        self.balloon.set_volume_level(self.current_volume_level)
        self.balloon.set_goal_level(self.target_session.target_volume_level)

        if self.target_session.check_goal(
            inferred_direction=inferred_direction,
            volume_level=self.current_volume_level,
            volume_liters=sample.volume_liters,
            rpm=sample.rpm,
            total_pulses=sample.total_pulses,
        ):
            GameHistory.add_target_record(self.target_session.record())
            self.status_label.configure(text="Target met! New target spawned.")
            self.target_session.spawn_new_target()
            self.balloon.set_goal_level(self.target_session.target_volume_level)
            self.balloon.set_volume_level(self.target_session.start_volume_level)
            self.update_goal_text()
        else:
            if self.target_session.target_direction == "blow":
                self.status_label.configure(text="Blow to move live volume toward the target ring.")
            else:
                self.status_label.configure(text="Suck to move live volume toward the target ring.")

        self.previous_volume_liters = sample.volume_liters

    def close_inputs(self):
        if self.serial_reader is not None:
            self.serial_reader.stop()
            self.serial_reader = None


class HistoryFrame(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=AppSettings.get_background_color())
        base_font = AppSettings.get_base_font_size()
        fg = AppSettings.get_foreground_color()
        bg = AppSettings.get_background_color()

        tk.Label(self, text="Game History & Data", font=("Arial", base_font, "bold"), fg=fg, bg=bg).pack(pady=(16, 8))

        text = tk.Text(self, height=14, wrap="word", font=("Arial", max(base_font - 2, 10)), fg=fg, bg=bg)
        text.insert("1.0", GameHistory.format_scores())
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=16, pady=8)

        tk.Button(self, text="Back to Menu", font=("Arial", max(base_font - 2, 10)), command=app.show_main_menu).pack(pady=(0, 16))


class SettingsFrame(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=AppSettings.get_background_color())
        self.app = app

        self.size_var = tk.StringVar(value=AppSettings.text_size)
        self.sound_var = tk.BooleanVar(value=AppSettings.sound_on)
        self.color_var = tk.StringVar(value=AppSettings.color_mode)

        base_font = AppSettings.get_base_font_size()
        fg = AppSettings.get_foreground_color()
        bg = AppSettings.get_background_color()

        self.title_label = tk.Label(self, text="Settings", font=("Arial", 24, "bold"), fg=fg, bg=bg)
        self.title_label.pack(pady=(20, 10))

        self.panel = tk.Frame(self, bg=bg)
        self.panel.pack(fill="x", padx=30, pady=10)

        self.text_size_label = tk.Label(self.panel, text="Text Size:", fg=fg, bg=bg, anchor="w")
        self.text_size_label.grid(row=0, column=0, sticky="w", pady=6)
        self.size_box = tk.OptionMenu(self.panel, self.size_var, "Small", "Medium", "Large")
        self.size_box.grid(row=0, column=1, sticky="ew", pady=6)

        self.sound_label = tk.Label(self.panel, text="Sound:", fg=fg, bg=bg, anchor="w")
        self.sound_label.grid(row=1, column=0, sticky="w", pady=6)
        self.sound_check = tk.Checkbutton(self.panel, text="Enabled", variable=self.sound_var, fg=fg, bg=bg, selectcolor=bg)
        self.sound_check.grid(row=1, column=1, sticky="w", pady=6)

        self.color_label = tk.Label(self.panel, text="Color Mode:", fg=fg, bg=bg, anchor="w")
        self.color_label.grid(row=2, column=0, sticky="w", pady=6)
        self.color_box = tk.OptionMenu(self.panel, self.color_var, "Light", "Dark")
        self.color_box.grid(row=2, column=1, sticky="ew", pady=6)

        self.preview_text_label = tk.Label(self.panel, text="Preview:", fg=fg, bg=bg, anchor="w")
        self.preview_text_label.grid(row=3, column=0, sticky="w", pady=6)
        self.preview_label = tk.Label(self.panel, text="Sample Text", relief="ridge")
        self.preview_label.grid(row=3, column=1, sticky="ew", pady=6)

        self.panel.columnconfigure(1, weight=1)

        bottom = tk.Frame(self, bg=bg)
        bottom.pack(pady=(8, 16))

        tk.Button(bottom, text="Apply", font=("Arial", max(base_font - 2, 10)), command=self.apply_settings).pack(side="left", padx=8)
        tk.Button(bottom, text="Back to Menu", font=("Arial", max(base_font - 2, 10)), command=app.show_main_menu).pack(side="left", padx=8)

        self.size_var.trace_add("write", lambda *_: self.update_preview())
        self.color_var.trace_add("write", lambda *_: self.update_preview())
        self.update_preview()

    def apply_settings(self):
        AppSettings.set_text_size(self.size_var.get())
        AppSettings.set_sound_on(self.sound_var.get())
        AppSettings.set_color_mode(self.color_var.get())
        messagebox.showinfo("Settings", "Settings applied!")
        self.app.show_main_menu()

    def update_preview(self):
        size_choice = self.size_var.get()
        color_choice = self.color_var.get()

        if size_choice == "Small":
            size = 14
        elif size_choice == "Large":
            size = 22
        else:
            size = 18

        dark_mode = color_choice == "Dark"
        bg = "#2f2f2f" if dark_mode else "#ffffff"
        fg = "#ffffff" if dark_mode else "#000000"

        self.preview_label.configure(font=("Arial", size), fg=fg, bg=bg)

        self.configure(bg=bg)
        self.title_label.configure(bg=bg, fg=fg)
        self.panel.configure(bg=bg)
        self.text_size_label.configure(bg=bg, fg=fg)
        self.sound_label.configure(bg=bg, fg=fg)
        self.color_label.configure(bg=bg, fg=fg)
        self.preview_text_label.configure(bg=bg, fg=fg)
        self.sound_check.configure(bg=bg, fg=fg, selectcolor=bg)


def parse_args():
    parser = argparse.ArgumentParser(description="Arduino serial breathing target game")
    parser.add_argument(
        "--sample-window",
        type=float,
        default=0.5,
        help="Seconds per serial sampling window (default: 0.5)",
    )
    parser.add_argument(
        "--serial-port",
        type=str,
        default="/dev/ttyACM0",
        help="Arduino serial device path (default: /dev/ttyACM0)",
    )
    parser.add_argument(
        "--baud-rate",
        type=int,
        default=115200,
        help="Arduino serial baud rate (default: 115200)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app = MainApp(sample_window=args.sample_window, serial_port=args.serial_port, baud_rate=args.baud_rate)
    app.mainloop()
