import threading
import time
import tkinter as tk
from tkinter import messagebox

import serial
import serial.tools.list_ports


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
            return "No scores recorded yet.\nHold a button to start scoring!"
        lines = []
        for i, score in enumerate(cls.scores, start=1):
            lines.append(f"#{i}: {score} points")
        return "\n".join(lines)


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
    def __init__(self):
        super().__init__()
        self.title("My Game Menu")
        self.geometry("460x460")
        self.resizable(False, False)
        self.current_frame = None
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
        self.port = None
        self.holding_button = False
        self.current_hold_score = 0
        self.last_tick = time.monotonic()
        self.hold_after_id = None

        base_font = AppSettings.get_base_font_size()
        fg = AppSettings.get_foreground_color()
        bg = AppSettings.get_background_color()

        self.status_label = tk.Label(
            self,
            text="Press and hold A or B on the board!",
            font=("Arial", base_font, "bold"),
            fg=fg,
            bg=bg,
        )
        self.status_label.pack(pady=(16, 8))

        self.balloon = BalloonCanvas(self, bg=bg)
        self.balloon.pack(fill="both", expand=True, padx=16, pady=8)

        self.score_label = tk.Label(self, text="Hold Score: 0", font=("Arial", max(base_font - 2, 10)), fg=fg, bg=bg)
        self.score_label.pack(pady=8)

        back_button = tk.Button(self, text="Back to Menu", font=("Arial", max(base_font - 2, 10)), command=self.back_to_menu)
        back_button.pack(pady=(0, 16))

        self.start_serial_listener()

    def destroy(self):
        self.running = False
        self.stop_hold_timer()
        self.close_port()
        super().destroy()

    def back_to_menu(self):
        self.running = False
        self.stop_hold_timer()
        self.close_port()
        self.app.show_main_menu()

    def start_serial_listener(self):
        thread = threading.Thread(target=self.serial_loop, name="CPX-Serial-Listener", daemon=True)
        thread.start()

    def serial_loop(self):
        try:
            ports = list(serial.tools.list_ports.comports())
            if not ports:
                print("No serial ports found.")
                return

            candidate = None
            for p in ports:
                name = p.device
                desc = p.description or ""
                print(f"Found port: {name} - {desc}")
                lower = f"{desc} {name}".lower()
                if "com1" not in name.lower() and any(x in lower for x in ("usb", "circuit", "playground")):
                    candidate = p
                    break

            if candidate is None:
                candidate = ports[-1]
                print(f"No specific CPX match found, falling back to: {candidate.device}")

            print(f"Trying to open: {candidate.device}")
            self.port = serial.Serial(candidate.device, baudrate=9600, timeout=0.1)
            print(f"Serial connected on {candidate.device} (game).")

            while self.running and self.port and self.port.is_open:
                raw = self.port.readline()
                if not raw:
                    continue
                line = raw.decode(errors="ignore").strip()
                if line:
                    print(f"Serial: {line}")
                    self.app.after(0, self.handle_serial_line, line)
        except Exception as exc:
            print(f"Serial listener error: {exc}")
        finally:
            self.close_port()

    def handle_serial_line(self, line):
        if line == "A_PRESSED":
            self.handle_button_pressed("A", "#2e7d32")
        elif line == "B_PRESSED":
            self.handle_button_pressed("B", "#c62828")
        elif line == "A_RELEASED":
            self.handle_button_released("A")
        elif line == "B_RELEASED":
            self.handle_button_released("B")

    def handle_button_pressed(self, button_name, panel_color):
        self.configure(bg=panel_color)
        self.status_label.configure(bg=panel_color)
        self.score_label.configure(bg=panel_color)
        self.balloon.configure(bg=panel_color)

        if not self.holding_button:
            self.holding_button = True
            self.current_hold_score = 0
            self.update_score_label()
            self.status_label.configure(text=f"Holding {button_name}... keep going!")
            self.balloon.set_inflation_level(0.0)
            self.last_tick = time.monotonic()
            self.schedule_hold_tick()

    def handle_button_released(self, button_name):
        if self.holding_button:
            self.holding_button = False
            self.stop_hold_timer()
            GameHistory.add_score(self.current_hold_score)
            self.status_label.configure(text=f"Released {button_name}! Score recorded.")
        else:
            self.status_label.configure(text="Press and hold A or B on the board!")

        bg = AppSettings.get_background_color()
        self.configure(bg=bg)
        self.status_label.configure(bg=bg)
        self.score_label.configure(bg=bg)
        self.balloon.configure(bg=bg)
        self.balloon.set_inflation_level(0.0)

    def schedule_hold_tick(self):
        self.hold_after_id = self.app.after(50, self.update_hold_score)

    def stop_hold_timer(self):
        if self.hold_after_id is not None:
            self.app.after_cancel(self.hold_after_id)
            self.hold_after_id = None
        self.holding_button = False

    def update_hold_score(self):
        now = time.monotonic()
        delta_seconds = now - self.last_tick
        self.last_tick = now

        points = round(delta_seconds * 20)
        if points < 1:
            points = 1

        self.current_hold_score += points
        self.update_score_label()

        normalized = min(self.current_hold_score / 200.0, 1.0)
        self.balloon.set_inflation_level(normalized)

        if self.holding_button:
            self.schedule_hold_tick()

    def update_score_label(self):
        self.score_label.configure(text=f"Hold Score: {self.current_hold_score}")

    def close_port(self):
        if self.port and self.port.is_open:
            self.port.close()
            print("Serial port closed.")


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


if __name__ == "__main__":
    app = MainApp()
    app.mainloop()
