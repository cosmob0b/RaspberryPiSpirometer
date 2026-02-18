from main import AppSettings


def main():
    initial_text_size = AppSettings.text_size
    initial_color_mode = AppSettings.color_mode
    initial_sound_on = AppSettings.sound_on

    change_count = {"count": 0}

    def listener(_prop, _old, _new):
        change_count["count"] += 1

    AppSettings.add_change_listener(listener)

    next_text_size = "Small" if initial_text_size == "Medium" else "Medium"
    next_color_mode = "Dark" if initial_color_mode == "Light" else "Light"
    next_sound_on = not initial_sound_on

    AppSettings.set_text_size(next_text_size)
    AppSettings.set_color_mode(next_color_mode)
    AppSettings.set_sound_on(next_sound_on)

    assert change_count["count"] == 3, f"Expected 3 change events, got {change_count['count']}"

    AppSettings.set_text_size(next_text_size)
    assert change_count["count"] == 3, "Expected no new event when setting same value"

    AppSettings.remove_change_listener(listener)
    AppSettings.set_text_size(initial_text_size)
    AppSettings.set_color_mode(initial_color_mode)
    AppSettings.set_sound_on(initial_sound_on)

    print("SettingsListenerTest passed")


if __name__ == "__main__":
    main()
