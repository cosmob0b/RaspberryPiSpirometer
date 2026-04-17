from types import SimpleNamespace

from main import ArduinoTargetGameFrame, GameHistory, TargetSession


class FakeLabel:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]


class FakeBalloon:
    def __init__(self):
        self.goal_level = None
        self.volume_level = None

    def set_goal_level(self, level):
        self.goal_level = level

    def set_volume_level(self, level):
        self.volume_level = level


class FakeTargetSession:
    def __init__(self):
        self.visual_start_level = 0.1
        self.target_volume_level = 0.2
        self.spawned = []

    def spawn_new_target(self, forced_direction=None):
        self.spawned.append(forced_direction)
        self.visual_start_level += 0.1
        self.target_volume_level += 0.1


def test_forced_direction_and_history_wording():
    session = TargetSession()
    session.spawn_new_target(forced_direction="suck")
    assert session.target_direction == "suck"

    inhale_summary = GameHistory.format_directional_summary()
    assert "Inhale" in inhale_summary
    assert "Suck" not in inhale_summary


def test_trial_sequence_rotates_exhale_inhale_exhale():
    fake_frame = SimpleNamespace(
        trial_directions=["blow", "suck", "blow"],
        trial_index=0,
        status_label=FakeLabel(),
        direction_label=FakeLabel(),
        balloon=FakeBalloon(),
        target_session=FakeTargetSession(),
        display_volume_level=0.0,
        update_goal_text=lambda: None,
        reset_inference_state_for_new_target=lambda _v: None,
    )

    record = {"direction": "Exhale", "success_volume_liters": 1.23}
    ArduinoTargetGameFrame.advance_to_next_trial(fake_frame, 1.0, record)
    assert fake_frame.trial_index == 1
    assert fake_frame.target_session.spawned[-1] == "suck"

    ArduinoTargetGameFrame.advance_to_next_trial(fake_frame, 1.0, record)
    assert fake_frame.trial_index == 2
    assert fake_frame.target_session.spawned[-1] == "blow"

    ArduinoTargetGameFrame.advance_to_next_trial(fake_frame, 1.0, record)
    assert fake_frame.trial_index == 0
    assert fake_frame.target_session.spawned[-1] == "blow"
    assert "3-trial set complete" in fake_frame.status_label.text


def main():
    test_forced_direction_and_history_wording()
    test_trial_sequence_rotates_exhale_inhale_exhale()
    print("TrialSequenceTest passed")


if __name__ == "__main__":
    main()
