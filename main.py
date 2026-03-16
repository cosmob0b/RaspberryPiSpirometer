import argparse
import threading
import time
import tkinter as tk
from tkinter import messagebox


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

    @classmethod
    def add_score(cls, score):
        cls.scores.append(score)

    @classmethod
    def format_scores(cls):
        if not cls.scores:
            return "No scores recorded yet.\nRun water through the sensor to animate the balloon!"
        lines = []
        for i, score in enumerate(cls.scores, start=1):
            lines.append(f"#{i}: {score} points")
        return "\n".join(lines)


class YFS201CGPIOReader:
    """Read YF-S201C pulse output on a Raspberry Pi GPIO pin."""

    def __init__(self, gpio_pin):
        self.gpio_pin = gpio_pin
        self.pulse_count = 0
        self._lock = threading.Lock()
        self._gpio = None

    def _pulse_callback(self, _channel):
        with self._lock:
            self.pulse_count += 1

    def start(self):
        try:
            import RPi.GPIO as GPIO  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "RPi.GPIO is required. Install on Raspberry Pi with: sudo apt install python3-rpi.gpio"
            ) from exc

        self._gpio = GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(self.gpio_pin, GPIO.FALLING, callback=self._pulse_callback)

    def stop(self):
        if self._gpio is not None:
            try:
                self._gpio.remove_event_detect(self.gpio_pin)
            except Exception:
                pass
            self._gpio.cleanup(self.gpio_pin)
            self._gpio = None

    def read_flow_lpm(self, sample_seconds=0.5):
        time.sleep(sample_seconds)

        with self._lock:
            pulses = self.pulse_count
            self.pulse_count = 0

        frequency_hz = pulses / sample_seconds
        flow_lpm = max((frequency_hz + 3.0) / 5.0, 0.0)
        return flow_lpm


class BalloonCanvas(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, highlightthickness=0, **kwargs)
        self.inflation_level = 0.0
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_inflation_level(self, level):
        self.inflation_level = max(0.0, min(level, 1.0))
        self.redraw()

    def redraw(self):
        self.delete("all")
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)

        max_diameter = max(min(width, height) - 40, 40)
        min_diameter = max(40, max_diameter // 3)
        diameter = round(min_diameter + (max_diameter - min_diameter) * self.inflation_level)

        x = (width - diameter) // 2
        y = (height - diameter) // 2

        self.create_oval(x, y, x + diameter, y + diameter, fill="#ff69b4", outline="#ffffff", width=2)

        string_x = x + diameter // 2
        string_y = y + diameter
        self.create_line(string_x, string_y, string_x, string_y + 30, fill="#444444", width=2)


class MainApp(tk.Tk):
    def __init__(self, gpio_pin=17, sample_window=0.5):
        super().__init__()
        self.title("My Game Menu")
        self.geometry("460x460")
        self.resizable(False, False)
        self.current_frame = None

        self.gpio_pin = gpio_pin
        self.sample_window = sample_window

        self.show_main_menu()

    def show_frame(self, frame_cls):
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = frame_cls(self)
        self.current_frame.pack(fill="both", expand=True)

    def show_main_menu(self):
        self.show_frame(MainMenuFrame)

    def show_game(self):
        self.show_frame(BeginGameFrame)

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
            ("Begin Game", app.show_game),
            ("Settings", app.show_settings),
            ("History & Data", app.show_history),
            ("Exit", app.destroy),
        ]

        for text, cmd in buttons:
            btn = tk.Button(button_wrap, text=text, font=("Arial", base_font), width=18, command=cmd)
            btn.pack(pady=8)


class BeginGameFrame(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=AppSettings.get_background_color())
        self.app = app
        self.running = True
        self.gpio_reader = None

        self.last_flow_lpm = None
        self.inflation_level = 0.0

        base_font = AppSettings.get_base_font_size()
        fg = AppSettings.get_foreground_color()
        bg = AppSettings.get_background_color()

        self.status_label = tk.Label(
            self,
            text=f"YF-S201C on BCM GPIO {app.gpio_pin}",
            font=("Arial", base_font, "bold"),
            fg=fg,
            bg=bg,
        )
        self.status_label.pack(pady=(16, 8))

        self.balloon = BalloonCanvas(self, bg=bg)
        self.balloon.pack(fill="both", expand=True, padx=16, pady=8)

        self.score_label = tk.Label(self, text="Flow: 0.00 L/min", font=("Arial", max(base_font - 2, 10)), fg=fg, bg=bg)
        self.score_label.pack(pady=8)

        back_button = tk.Button(self, text="Back to Menu", font=("Arial", max(base_font - 2, 10)), command=self.back_to_menu)
        back_button.pack(pady=(0, 16))

        self.start_gpio_listener()

    def destroy(self):
        self.running = False
        self.close_inputs()
        super().destroy()

    def back_to_menu(self):
        self.running = False
        self.close_inputs()
        self.app.show_main_menu()

    def start_gpio_listener(self):
        thread = threading.Thread(target=self.gpio_loop, name="YFS201C-Listener", daemon=True)
        thread.start()

    def gpio_loop(self):
        try:
            self.gpio_reader = YFS201CGPIOReader(self.app.gpio_pin)
            self.gpio_reader.start()
            while self.running:
                flow_lpm = self.gpio_reader.read_flow_lpm(sample_seconds=self.app.sample_window)
                self.app.after(0, self.handle_flow_reading, flow_lpm)
        except Exception as exc:
            print(f"GPIO listener error: {exc}")
            self.app.after(0, lambda: self.status_label.configure(text=f"GPIO error: {exc}"))
        finally:
            self.close_inputs()

    def handle_flow_reading(self, flow_lpm):
        self.score_label.configure(text=f"Flow: {flow_lpm:.2f} L/min")

        if self.last_flow_lpm is None:
            self.last_flow_lpm = flow_lpm
            return

        delta = flow_lpm - self.last_flow_lpm

        if delta > 0.02:
            step = min(0.12, 0.01 + (delta * 0.04))
            self.inflation_level = min(1.0, self.inflation_level + step)
            self.status_label.configure(text="Flow increasing → balloon inflating")
        elif delta < -0.02:
            step = min(0.12, 0.01 + (abs(delta) * 0.04))
            self.inflation_level = max(0.0, self.inflation_level - step)
            self.status_label.configure(text="Flow decreasing → balloon deflating")
        else:
            self.status_label.configure(text="Flow steady")

        self.balloon.set_inflation_level(self.inflation_level)
        self.last_flow_lpm = flow_lpm

    def close_inputs(self):
        if self.gpio_reader is not None:
            self.gpio_reader.stop()
            self.gpio_reader = None


class HistoryFrame(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=AppSettings.get_background_color())
        base_font = AppSettings.get_base_font_size()
        fg = AppSettings.get_foreground_color()
        bg = AppSettings.get_background_color()

        title = tk.Label(self, text="Hold Scores", font=("Arial", base_font, "bold"), fg=fg, bg=bg)
        title.pack(pady=(16, 8))

        text = tk.Text(self, height=14, wrap="word", font=("Arial", max(base_font - 2, 10)), fg=fg, bg=bg)
        text.insert("1.0", GameHistory.format_scores())
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=16, pady=8)

        back_button = tk.Button(self, text="Back to Menu", font=("Arial", max(base_font - 2, 10)), command=app.show_main_menu)
        back_button.pack(pady=(0, 16))


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

        apply_button = tk.Button(bottom, text="Apply", font=("Arial", max(base_font - 2, 10)), command=self.apply_settings)
        apply_button.pack(side="left", padx=8)

        back_button = tk.Button(bottom, text="Back to Menu", font=("Arial", max(base_font - 2, 10)), command=app.show_main_menu)
        back_button.pack(side="left", padx=8)

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
    parser = argparse.ArgumentParser(description="Balloon game with YF-S201C GPIO flow input")
    parser.add_argument("--gpio-pin", type=int, default=17, help="BCM GPIO pin for YF-S201C output (default: 17)")
    parser.add_argument(
        "--sample-window",
        type=float,
        default=0.5,
        help="Seconds per flow sample. Lower is more responsive, higher is smoother (default: 0.5)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app = MainApp(gpio_pin=args.gpio_pin, sample_window=args.sample_window)
    app.mainloop()
