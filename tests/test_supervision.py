import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from supervision import AlertSeverity, AlertType, DistanceConfidence, SupervisionConfig, Supervisor


class DummyPoseMetrics:
    def __init__(self, posture_score=0.0, quality_score=1.0, visible_keypoints=6, issues=None):
        self.posture_score = posture_score
        self.quality_score = quality_score
        self.visible_keypoints = visible_keypoints
        self.issues = issues or []


class SupervisorTests(unittest.TestCase):
    def make_supervisor(self, overrides=None):
        config = {
            "supervision": {
                "too_close_threshold_cm": 30.0,
                "too_close_severe_distance_margin_cm": 5.0,
                "too_close_severe_relative_multiplier": 1.25,
                "too_close_duration_s": 5.0,
                "distance_recovery_s": 1.5,
                "distance_confidence_grace_s": 1.5,
                "presence_grace_s": 2.0,
                "bad_posture_duration_s": 8.0,
                "posture_recovery_s": 2.0,
                "max_study_duration_min": 45,
                "rest_duration_min": 10,
                "alert_cooldown_s": 45.0,
                "severity_mild_threshold": 30.0,
                "severity_moderate_threshold": 60.0,
                "severity_severe_threshold": 80.0,
                "presence_enter_frames": 5,
                "presence_exit_frames": 15,
            },
            "pose": {
                "camera_view": "front",
                "posture_window_s": 4.0,
                "posture_alert_threshold": 55.0,
                "min_quality_score": 0.55,
                "min_visible_keypoints": 4,
            },
            "distance": {
                "baseline_face_width_px": 0,
                "too_close_relative_scale": 1.25,
                "prefer_relative_baseline": False,
            },
        }
        if overrides:
            for section, values in overrides.items():
                config.setdefault(section, {}).update(values)
        return Supervisor(SupervisionConfig(config))

    def test_person_session_clears_posture_window(self):
        supervisor = self.make_supervisor()
        supervisor._update_posture_window(1.0, 80.0)
        supervisor._update_posture_window(2.0, 90.0)
        self.assertGreater(supervisor._get_window_avg_score(), 0.0)
        supervisor.on_person_left(3.0)
        self.assertEqual(supervisor._get_window_avg_score(), 0.0)

    def test_too_close_severe_by_absolute_distance(self):
        supervisor = self.make_supervisor()
        supervisor.on_person_detected(0.0)
        alert = None
        for ts in [0.0, 1.0, 2.0, 3.0, 4.1, 5.2]:
            alert = supervisor.on_distance_update(
                distance_cm=24.0,
                confidence=DistanceConfidence.HIGH,
                timestamp=ts,
                face_width_px=100.0,
            )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, AlertType.TOO_CLOSE)
        self.assertEqual(alert.severity, AlertSeverity.SEVERE)

    def test_too_close_severe_by_relative_scale(self):
        supervisor = self.make_supervisor({"distance": {"baseline_face_width_px": 80}})
        supervisor.on_person_detected(0.0)
        alert = None
        for ts in [0.0, 1.0, 2.0, 3.0, 4.1, 5.2]:
            alert = supervisor.on_distance_update(
                distance_cm=28.0,
                confidence=DistanceConfidence.HIGH,
                timestamp=ts,
                face_width_px=130.0,
            )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, AlertType.TOO_CLOSE)
        self.assertEqual(alert.severity, AlertSeverity.SEVERE)

    def test_distance_low_confidence_does_not_immediately_alert(self):
        supervisor = self.make_supervisor()
        supervisor.on_person_detected(0.0)
        self.assertIsNone(supervisor.on_distance_update(28.0, DistanceConfidence.LOW, 0.0, 100.0))
        self.assertIsNone(supervisor.on_distance_update(28.0, DistanceConfidence.LOW, 1.0, 100.0))


if __name__ == "__main__":
    unittest.main()
