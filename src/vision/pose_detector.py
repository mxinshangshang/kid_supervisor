"""Pose and distance detection tuned for Raspberry Pi."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import cv2
import math
import numpy as np

try:
    import mediapipe as mp

    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False


_DEFAULT_DIST_CFG = {
    "face_real_width_cm": 13.5,
    "camera_focal_length": 820.0,
    "min_cm": 25.0,
    "max_cm": 120.0,
    "smoothing_alpha": 0.35,
    "edge_reject_ratio": 0.35,
}
_DEFAULT_POSE_CFG = {
    "camera_view": "front",
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
}


class PoseQuality(Enum):
    EXCELLENT = "excellent"
    OK = "ok"
    NEEDS_ATTENTION = "needs_attention"
    BAD = "bad"


class DistanceConfidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class PoseMetrics:
    head_pitch: float = 0.0
    head_yaw: float = 0.0
    head_roll: float = 0.0
    torso_lean: float = 0.0
    shoulder_level: float = 0.0
    posture_score: float = 0.0
    quality_score: float = 1.0
    visible_keypoints: int = 0
    overall_quality: PoseQuality = PoseQuality.EXCELLENT
    issues: List[str] = field(default_factory=list)
    # 详细的每个问题的得分记录，用于维测
    issue_details: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class DetectionResult:
    timestamp: float
    success: bool = False
    pose_landmarks: object = None
    pose_world_landmarks: object = None
    face_landmarks: object = None
    face_bbox: Optional[Tuple[int, int, int, int]] = None
    estimated_distance_cm: Optional[float] = None
    distance_confidence: DistanceConfidence = DistanceConfidence.LOW
    pose_metrics: Optional[PoseMetrics] = None
    frame_id: Optional[int] = None
    source_timestamp: Optional[float] = None
    issues: List[str] = field(default_factory=list)
    distance_bbox: Optional[Tuple[int, int, int, int]] = None


class MediaPipePoseDetector:
    def __init__(
        self,
        model_complexity: int = 1,
        enable_segmentation: bool = False,
        smooth_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        config: Optional[Dict[str, Any]] = None,
    ):
        if not MEDIAPIPE_AVAILABLE:
            raise ImportError("MediaPipe not installed!")

        self.mp_pose = mp.solutions.pose
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils

        self._load_config(config)
        self._model_complexity = model_complexity
        self._init_kwargs = {
            "smooth_landmarks": smooth_landmarks,
            "enable_segmentation": enable_segmentation,
            "min_detection_confidence": min_detection_confidence,
            "min_tracking_confidence": min_tracking_confidence,
        }
        self._init_pose(model_complexity, **self._init_kwargs)

        self.face_mesh = None
        self._face_mesh_initialized = False

        self.face_real_width_cm = self._dist_cfg["face_real_width_cm"]
        self.camera_focal_length = self._dist_cfg["camera_focal_length"]
        self.distance_min = self._dist_cfg["min_cm"]
        self.distance_max = self._dist_cfg["max_cm"]
        self.distance_alpha = self._dist_cfg["smoothing_alpha"]
        self.edge_reject_ratio = self._dist_cfg["edge_reject_ratio"]
        self.camera_view = self._pose_cfg.get("camera_view", "front")
        self.last_valid_distance = None

    def _load_config(self, config: Optional[Dict[str, Any]]):
        if config:
            self._dist_cfg = {**_DEFAULT_DIST_CFG, **config.get("distance", {})}
            self._pose_cfg = {**_DEFAULT_POSE_CFG, **config.get("pose", {})}
            return

        self._dist_cfg = _DEFAULT_DIST_CFG.copy()
        self._pose_cfg = _DEFAULT_POSE_CFG.copy()

    def _init_pose(self, model_complexity, smooth_landmarks, enable_segmentation, min_detection_confidence, min_tracking_confidence):
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            smooth_landmarks=smooth_landmarks,
            enable_segmentation=enable_segmentation,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def set_model_complexity(self, complexity: int):
        if complexity != self._model_complexity:
            print(f"[Vision] 模型复杂度 {self._model_complexity} -> {complexity}")
            self._model_complexity = complexity
            self.pose.close()
            self._init_pose(complexity, **self._init_kwargs)

    def _init_face_mesh(self):
        if not self._face_mesh_initialized:
            self.face_mesh = self.mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=self._init_kwargs["min_detection_confidence"],
                min_tracking_confidence=self._init_kwargs["min_tracking_confidence"],
            )
            self._face_mesh_initialized = True

    def detect(self, frame: np.ndarray, timestamp: float, analyze_face: bool = False, frame_is_rgb: bool = True) -> DetectionResult:
        result = DetectionResult(timestamp=timestamp)
        rgb_frame = frame if frame_is_rgb else cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pose_results = self.pose.process(rgb_frame)

        if pose_results.pose_landmarks:
            result.success = True
            result.pose_landmarks = pose_results.pose_landmarks
            result.pose_world_landmarks = getattr(pose_results, "pose_world_landmarks", None)
            result.pose_metrics = self._analyze_pose_metrics(pose_results.pose_landmarks, frame.shape)
            result.face_bbox = self._estimate_face_bbox(pose_results.pose_landmarks, frame.shape, include_shoulders=True)
            result.distance_bbox = self._estimate_face_bbox(pose_results.pose_landmarks, frame.shape, include_shoulders=False)
            if result.pose_metrics:
                result.issues = list(result.pose_metrics.issues)

            if result.distance_bbox and self.camera_view == "front":
                result.estimated_distance_cm, result.distance_confidence = self._estimate_distance(result.distance_bbox, frame.shape)

            if analyze_face:
                try:
                    self._init_face_mesh()
                    face_results = self.face_mesh.process(rgb_frame)
                    if face_results.multi_face_landmarks:
                        result.face_landmarks = face_results.multi_face_landmarks[0]
                except Exception:
                    pass

        return result

    def _analyze_pose_metrics(self, landmarks, frame_shape: Tuple[int, int, int]) -> PoseMetrics:
        h, w, _ = frame_shape
        lm = landmarks.landmark
        pose = self.mp_pose.PoseLandmark
        vis_thresh = self._pose_cfg["landmark_visibility_threshold"]
        weights = self._pose_cfg.get("weights", {})

        def get_p(enum_val):
            return (lm[enum_val.value].x * w, lm[enum_val.value].y * h)

        def is_visible(enum_val):
            return lm[enum_val.value].visibility > vis_thresh

        metrics = PoseMetrics()

        left_shoulder = get_p(pose.LEFT_SHOULDER)
        right_shoulder = get_p(pose.RIGHT_SHOULDER)
        left_hip = get_p(pose.LEFT_HIP)
        right_hip = get_p(pose.RIGHT_HIP)
        nose = get_p(pose.NOSE)
        left_ear = get_p(pose.LEFT_EAR)
        right_ear = get_p(pose.RIGHT_EAR)

        left_shoulder_vis = is_visible(pose.LEFT_SHOULDER)
        right_shoulder_vis = is_visible(pose.RIGHT_SHOULDER)
        left_hip_vis = is_visible(pose.LEFT_HIP)
        right_hip_vis = is_visible(pose.RIGHT_HIP)
        left_ear_vis = is_visible(pose.LEFT_EAR)
        right_ear_vis = is_visible(pose.RIGHT_EAR)

        visibility_points = [
            pose.NOSE,
            pose.LEFT_EAR,
            pose.RIGHT_EAR,
            pose.LEFT_SHOULDER,
            pose.RIGHT_SHOULDER,
            pose.LEFT_HIP,
            pose.RIGHT_HIP,
        ]
        visible_scores = [lm[p.value].visibility for p in visibility_points]
        metrics.visible_keypoints = sum(1 for score in visible_scores if score > vis_thresh)
        metrics.quality_score = sum(visible_scores) / len(visible_scores)

        issue_score = 0.0
        is_front = self.camera_view == "front"
        is_side = self.camera_view == "side"

        def _safe_ratio(numerator: float, denominator: float) -> float:
            return numerator / denominator if denominator and abs(denominator) > 1e-6 else 0.0

        def _safe_angle(dx: float, dy: float) -> float:
            return abs(math.degrees(math.atan2(abs(dy), abs(dx)))) if abs(dx) > 1e-6 or abs(dy) > 1e-6 else 0.0

        shoulder_width_px = abs(right_shoulder[0] - left_shoulder[0])
        ear_width_px = abs(right_ear[0] - left_ear[0])
        head_width_px = ear_width_px if ear_width_px > 1 else shoulder_width_px

        shoulder_roll_angle = 0.0
        if is_front and left_shoulder_vis and right_shoulder_vis:
            shoulder_roll_angle = _safe_angle(right_shoulder[0] - left_shoulder[0], right_shoulder[1] - left_shoulder[1])
            metrics.shoulder_level = shoulder_roll_angle

        front_facing = left_ear_vis and right_ear_vis
        side_facing = (left_ear_vis and not right_ear_vis) or (right_ear_vis and not left_ear_vis)

        if is_front and front_facing:
            nose_to_ear_ratio = _safe_ratio(nose[1] - ((left_ear[1] + right_ear[1]) / 2), max(head_width_px, 1.0))
            head_down_threshold = self._pose_cfg["head_down_ratio_threshold"]
            if nose_to_ear_ratio > head_down_threshold:
                deviation = (nose_to_ear_ratio - head_down_threshold) / head_down_threshold
                severity = min(1.0, deviation)
                metrics.head_pitch = nose_to_ear_ratio * 100
                score = severity * weights.get("head_down", 35.0)
                issue_score += score
                metrics.issues.append("低头")
                metrics.issue_details["低头"] = {
                    "score": score,
                    "raw_ratio": nose_to_ear_ratio,
                    "threshold": head_down_threshold,
                    "deviation": deviation
                }

            ear_dx = right_ear[0] - left_ear[0]
            ear_dy = right_ear[1] - left_ear[1]
            roll_angle = _safe_angle(ear_dx, ear_dy)
            metrics.head_roll = roll_angle
            if roll_angle > 12.0:
                severity = min(1.0, (roll_angle - 12.0) / 18.0)
                score = severity * weights.get("head_tilt", 10.0)
                issue_score += score
                metrics.issues.append("歪头")
                metrics.issue_details["歪头"] = {
                    "score": score,
                    "raw_angle": roll_angle,
                    "threshold": 12.0
                }

            shoulder_roll_threshold = self._pose_cfg["shoulder_roll_degree_threshold"]
            if left_shoulder_vis and right_shoulder_vis and shoulder_roll_angle > shoulder_roll_threshold:
                severity = min(1.0, (shoulder_roll_angle - shoulder_roll_threshold) / shoulder_roll_threshold)
                score = severity * weights.get("uneven_shoulders", 20.0)
                issue_score += score
                metrics.issues.append("肩膀不平")
                metrics.issue_details["肩膀不平"] = {
                    "score": score,
                    "raw_angle": shoulder_roll_angle,
                    "threshold": shoulder_roll_threshold
                }

            lean_ratio = _safe_ratio(abs(nose[0] - ((left_shoulder[0] + right_shoulder[0]) / 2)), shoulder_width_px)
            if lean_ratio > self._pose_cfg["lean_forward_ratio_threshold"]:
                severity = min(1.0, (lean_ratio - self._pose_cfg["lean_forward_ratio_threshold"]) / self._pose_cfg["lean_forward_ratio_threshold"])
                score = severity * weights.get("leaning_forward", 30.0)
                issue_score += score
                metrics.issues.append("前倾")
                metrics.issue_details["前倾"] = {
                    "score": score,
                    "raw_ratio": lean_ratio,
                    "threshold": self._pose_cfg["lean_forward_ratio_threshold"]
                }

        if is_side and (left_shoulder_vis or right_shoulder_vis) and (left_hip_vis or right_hip_vis):
            visible_shoulder = left_shoulder if left_shoulder_vis else right_shoulder
            visible_hip = left_hip if left_hip_vis else right_hip
            torso_dx = visible_shoulder[0] - visible_hip[0]
            torso_dy = visible_hip[1] - visible_shoulder[1]
            torso_angle = abs(math.degrees(math.atan2(abs(torso_dx), abs(torso_dy)))) if abs(torso_dx) > 1e-6 or abs(torso_dy) > 1e-6 else 0.0
            metrics.torso_lean = torso_angle
            if torso_angle > 18.0:
                severity = min(1.0, (torso_angle - 18.0) / 20.0)
                score = severity * weights.get("leaning_forward", 30.0)
                issue_score += score
                metrics.issues.append("前倾")
                metrics.issue_details["前倾"] = {
                    "score": score,
                    "raw_angle": torso_angle,
                    "threshold": 18.0
                }

        if is_side and side_facing and (left_shoulder_vis or right_shoulder_vis):
            visible_shoulder_x = left_shoulder[0] if left_shoulder_vis else right_shoulder[0]
            shoulder_dx = abs(nose[0] - visible_shoulder_x)
            head_forward_ratio = _safe_ratio(shoulder_dx, shoulder_width_px)
            if head_forward_ratio > self._pose_cfg["head_forward_ratio_threshold"]:
                severity = min(1.0, (head_forward_ratio - self._pose_cfg["head_forward_ratio_threshold"]) / self._pose_cfg["head_forward_ratio_threshold"])
                score = severity * weights.get("head_forward", 30.0)
                issue_score += score
                metrics.issues.append("头前伸")
                metrics.issue_details["头前伸"] = {
                    "score": score,
                    "raw_ratio": head_forward_ratio,
                    "threshold": self._pose_cfg["head_forward_ratio_threshold"]
                }

            shoulder_y = left_shoulder[1] if left_shoulder_vis else right_shoulder[1]
            desk_ratio = _safe_ratio(nose[1] - shoulder_y, shoulder_width_px)
            if desk_ratio > self._pose_cfg["desk_proximity_ratio_threshold"]:
                severity = min(1.0, (desk_ratio - self._pose_cfg["desk_proximity_ratio_threshold"]) / self._pose_cfg["desk_proximity_ratio_threshold"])
                score = severity * weights.get("desk_proximity", 35.0)
                issue_score += score
                metrics.issues.append("离桌太近")
                metrics.issue_details["离桌太近"] = {
                    "score": score,
                    "raw_ratio": desk_ratio,
                    "threshold": self._pose_cfg["desk_proximity_ratio_threshold"]
                }

        metrics.posture_score = min(100.0, issue_score)
        if issue_score == 0:
            metrics.overall_quality = PoseQuality.EXCELLENT
        elif issue_score < 30:
            metrics.overall_quality = PoseQuality.OK
        elif issue_score < 60:
            metrics.overall_quality = PoseQuality.NEEDS_ATTENTION
        else:
            metrics.overall_quality = PoseQuality.BAD
        return metrics

    def _estimate_face_bbox(self, landmarks, frame_shape: Tuple[int, int, int], include_shoulders: bool) -> Optional[Tuple[int, int, int, int]]:
        h, w, _ = frame_shape
        lm = landmarks.landmark
        pose = self.mp_pose.PoseLandmark
        points = []
        indices = [pose.NOSE.value, pose.LEFT_EAR.value, pose.RIGHT_EAR.value]
        if include_shoulders:
            indices.extend([pose.LEFT_SHOULDER.value, pose.RIGHT_SHOULDER.value])
        for idx in indices:
            landmark = lm[idx]
            if landmark.visibility > self._pose_cfg["landmark_visibility_threshold"]:
                points.append((landmark.x * w, landmark.y * h))

        if len(points) < 3:
            return None

        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        pad_x = 0.08 * w if include_shoulders else 0.03 * w
        pad_top = 0.12 * h if include_shoulders else 0.08 * h
        pad_bottom = 0.04 * h if include_shoulders else 0.02 * h
        min_x = max(0, int(min(xs) - pad_x))
        max_x = min(w, int(max(xs) + pad_x))
        min_y = max(0, int(min(ys) - pad_top))
        max_y = min(h, int(max(ys) + pad_bottom))
        face_width = max_x - min_x
        face_height = max_y - min_y
        if face_width < 20 or face_height < 20:
            return None
        return (min_x, min_y, face_width, face_height)

    def _estimate_distance(self, face_bbox: Tuple[int, int, int, int], frame_shape: Tuple[int, int, int]) -> Tuple[Optional[float], DistanceConfidence]:
        h, w, _ = frame_shape
        x, y, fw, fh = face_bbox
        if fw <= 0:
            return self.last_valid_distance, DistanceConfidence.LOW

        face_cx = x + fw / 2
        face_cy = y + fh / 2
        dx = abs(face_cx - w / 2) / (w / 2)
        dy = abs(face_cy - h / 2) / (h / 2)
        offset_ratio = max(dx, dy)

        face_size_ratio = fw / max(w, 1)
        if face_size_ratio < 0.06:
            confidence = DistanceConfidence.LOW
        elif offset_ratio < self.edge_reject_ratio:
            confidence = DistanceConfidence.HIGH
        elif offset_ratio < self.edge_reject_ratio * 1.5:
            confidence = DistanceConfidence.MEDIUM
        else:
            confidence = DistanceConfidence.LOW

        raw_distance = (self.face_real_width_cm * self.camera_focal_length) / fw
        raw_distance = max(self.distance_min, min(self.distance_max, raw_distance))

        if confidence == DistanceConfidence.LOW:
            return self.last_valid_distance, confidence

        if self.last_valid_distance is None:
            self.last_valid_distance = raw_distance
        else:
            self.last_valid_distance = self.distance_alpha * raw_distance + (1 - self.distance_alpha) * self.last_valid_distance
        return self.last_valid_distance, confidence

    def close(self):
        self.pose.close()
        if self.face_mesh:
            self.face_mesh.close()
