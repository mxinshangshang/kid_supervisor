import enum
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _FakeLandmark:
    def __init__(self, x, y, visibility=1.0):
        self.x = x
        self.y = y
        self.visibility = visibility


class _FakeLandmarkList:
    def __init__(self, landmarks):
        self.landmark = landmarks


class _FakePoseResults:
    def __init__(self, landmarks):
        self.pose_landmarks = landmarks
        self.pose_world_landmarks = None


class _FakePoseLandmark(enum.IntEnum):
    NOSE = 0
    LEFT_EAR = 1
    RIGHT_EAR = 2
    LEFT_SHOULDER = 3
    RIGHT_SHOULDER = 4
    LEFT_HIP = 5
    RIGHT_HIP = 6


class _FakePose:
    def __init__(self, *args, **kwargs):
        pass

    def process(self, frame):
        return _FakePoseResults(None)

    def close(self):
        pass


class _FakeFaceMesh:
    def __init__(self, *args, **kwargs):
        pass

    def process(self, frame):
        return types.SimpleNamespace(multi_face_landmarks=None)

    def close(self):
        pass


class _FakeDrawingUtils:
    class DrawingSpec:
        def __init__(self, *args, **kwargs):
            pass

    def draw_landmarks(self, *args, **kwargs):
        pass


_fake_cv2 = types.SimpleNamespace(
    COLOR_BGR2RGB=1,
    IMREAD_COLOR=1,
    cvtColor=lambda frame, code: frame,
    imdecode=lambda arr, flag: None,
)

_fake_mp = types.SimpleNamespace(
    solutions=types.SimpleNamespace(
        pose=types.SimpleNamespace(Pose=_FakePose, PoseLandmark=_FakePoseLandmark, POSE_CONNECTIONS=[]),
        face_mesh=types.SimpleNamespace(FaceMesh=_FakeFaceMesh),
        drawing_utils=_FakeDrawingUtils(),
    )
)

sys.modules.setdefault("cv2", _fake_cv2)
sys.modules.setdefault("mediapipe", _fake_mp)

from vision.pose_detector import MediaPipePoseDetector  # noqa: E402


class PoseDetectorTests(unittest.TestCase):
    def make_detector(self, camera_view="front"):
        config = {
            "pose": {
                "camera_view": camera_view,
                "shoulder_roll_degree_threshold": 8.0,
                "head_down_ratio_threshold": 0.16,
                "lean_forward_ratio_threshold": 0.12,
                "head_forward_ratio_threshold": 0.12,
                "desk_proximity_ratio_threshold": 0.18,
                "landmark_visibility_threshold": 0.5,
                "min_quality_score": 0.55,
                "min_visible_keypoints": 4,
                "weights": {
                    "uneven_shoulders": 20.0,
                    "head_down": 35.0,
                    "head_tilt": 10.0,
                    "leaning_forward": 30.0,
                    "head_forward": 30.0,
                    "desk_proximity": 35.0,
                },
            },
            "distance": {
                "face_real_width_cm": 13.5,
                "camera_focal_length": 820.0,
                "min_cm": 25.0,
                "max_cm": 120.0,
                "smoothing_alpha": 0.35,
                "edge_reject_ratio": 0.35,
            },
        }
        return MediaPipePoseDetector(config=config)

    def make_landmarks(self, nose, left_ear, right_ear, left_shoulder, right_shoulder, left_hip, right_hip, vis=1.0):
        landmarks = [
            _FakeLandmark(*nose, vis),
            _FakeLandmark(*left_ear, vis),
            _FakeLandmark(*right_ear, vis),
            _FakeLandmark(*left_shoulder, vis),
            _FakeLandmark(*right_shoulder, vis),
            _FakeLandmark(*left_hip, vis),
            _FakeLandmark(*right_hip, vis),
        ]
        return _FakeLandmarkList(landmarks)

    def test_front_head_down_and_tilt(self):
        detector = self.make_detector("front")
        landmarks = self.make_landmarks(
            nose=(0.50, 0.70),
            left_ear=(0.42, 0.48),
            right_ear=(0.58, 0.56),
            left_shoulder=(0.40, 0.70),
            right_shoulder=(0.60, 0.71),
            left_hip=(0.40, 0.92),
            right_hip=(0.60, 0.93),
        )
        metrics = detector._analyze_pose_metrics(landmarks, (480, 640, 3))
        self.assertIn("Head Down", metrics.issues)
        self.assertIn("Head Tilted", metrics.issues)

    def test_front_level_posture_is_clean(self):
        detector = self.make_detector("front")
        landmarks = self.make_landmarks(
            nose=(0.50, 0.45),
            left_ear=(0.44, 0.48),
            right_ear=(0.56, 0.48),
            left_shoulder=(0.40, 0.70),
            right_shoulder=(0.60, 0.70),
            left_hip=(0.40, 0.93),
            right_hip=(0.60, 0.93),
        )
        metrics = detector._analyze_pose_metrics(landmarks, (480, 640, 3))
        self.assertNotIn("Head Down", metrics.issues)
        self.assertNotIn("Head Tilted", metrics.issues)
        self.assertNotIn("Leaning Forward", metrics.issues)

    def test_front_forward_lean_and_desk_proximity(self):
        detector = self.make_detector("front")
        landmarks = self.make_landmarks(
            nose=(0.56, 0.80),
            left_ear=(0.42, 0.48),
            right_ear=(0.58, 0.48),
            left_shoulder=(0.40, 0.68),
            right_shoulder=(0.60, 0.68),
            left_hip=(0.60, 0.92),
            right_hip=(0.80, 0.92),
        )
        metrics = detector._analyze_pose_metrics(landmarks, (480, 640, 3))
        self.assertIn("Leaning Forward", metrics.issues)
        self.assertNotIn("Too Close To Desk", metrics.issues)

    def test_side_torso_angle_and_head_forward(self):
        detector = self.make_detector("side")
        landmarks = self.make_landmarks(
            nose=(0.70, 0.48),
            left_ear=(0.62, 0.46),
            right_ear=(0.82, 0.46),
            left_shoulder=(0.48, 0.60),
            right_shoulder=(0.64, 0.60),
            left_hip=(0.42, 0.92),
            right_hip=(0.64, 0.92),
            vis=1.0,
        )
        landmarks.landmark[2].visibility = 0.1
        metrics = detector._analyze_pose_metrics(landmarks, (480, 640, 3))
        self.assertNotIn("Leaning Forward", metrics.issues)
        self.assertIn("Head Forward", metrics.issues)

    def test_side_level_is_clean(self):
        detector = self.make_detector("side")
        landmarks = self.make_landmarks(
            nose=(0.55, 0.47),
            left_ear=(0.48, 0.46),
            right_ear=(0.68, 0.46),
            left_shoulder=(0.40, 0.60),
            right_shoulder=(0.60, 0.60),
            left_hip=(0.32, 0.92),
            right_hip=(0.52, 0.92),
        )
        metrics = detector._analyze_pose_metrics(landmarks, (480, 640, 3))
        self.assertIn("Leaning Forward", metrics.issues)
        self.assertNotIn("Head Forward", metrics.issues)


if __name__ == "__main__":
    unittest.main()
