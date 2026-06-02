"""
姿态检测器 v4.0 - 基于 MediaPipe Pose
改进：距离置信度、边缘区域拒绝、配置化阈值、动态模型复杂度
"""
import os
import yaml
import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any
from enum import Enum

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False

# 默认配置（当 config.yaml 加载失败时使用）
_DEFAULT_DIST_CFG = {
    "face_real_width_cm": 15.0,
    "camera_focal_length": 800.0,
    "min_cm": 30.0,
    "max_cm": 150.0,
    "smoothing_alpha": 0.3,
    "edge_reject_ratio": 0.4,
}
_DEFAULT_POSE_CFG = {
    "shoulder_diff_threshold": 0.08,
    "head_down_threshold": 0.07,
    "lean_forward_threshold": 0.25,
    "landmark_visibility_threshold": 0.5,
}


class PoseQuality(Enum):
    EXCELLENT = "excellent"
    OK = "ok"
    NEEDS_ATTENTION = "needs_attention"
    BAD = "bad"


class DistanceConfidence(Enum):
    HIGH = "high"          # 人脸在画面中心，可信度高
    MEDIUM = "medium"      # 人脸偏离中心，有一定误差
    LOW = "low"            # 人脸在边缘或太小，不建议用于提醒


@dataclass
class PoseMetrics:
    """姿态度量"""
    head_pitch: float = 0.0
    head_yaw: float = 0.0
    head_roll: float = 0.0
    torso_lean: float = 0.0
    shoulder_level: float = 0.0
    posture_score: float = 0.0   # 0-100, 越高越差
    overall_quality: PoseQuality = PoseQuality.EXCELLENT
    issues: List[str] = field(default_factory=list)


@dataclass
class DetectionResult:
    """检测结果"""
    timestamp: float
    success: bool = False
    pose_landmarks: object = None
    face_landmarks: object = None
    face_bbox: Optional[Tuple[int, int, int, int]] = None
    estimated_distance_cm: Optional[float] = None
    distance_confidence: DistanceConfidence = DistanceConfidence.LOW
    pose_metrics: Optional[PoseMetrics] = None


class MediaPipePoseDetector:
    """MediaPipe Pose 检测器 - 树莓派5 优化"""

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

        # 加载配置（优先使用传入的 config，其次尝试 config.yaml，最后用默认值）
        self._load_config(config)

        self._model_complexity = model_complexity
        self._init_pose(model_complexity, smooth_landmarks, enable_segmentation,
                        min_detection_confidence, min_tracking_confidence)

        # Face Mesh（可选，当前未使用其输出，按需开启）
        self.face_mesh = None
        self._face_mesh_initialized = False

        # 距离估算参数
        self.face_real_width_cm = self._dist_cfg["face_real_width_cm"]
        self.camera_focal_length = self._dist_cfg["camera_focal_length"]
        self.distance_min = self._dist_cfg["min_cm"]
        self.distance_max = self._dist_cfg["max_cm"]
        self.distance_alpha = self._dist_cfg["smoothing_alpha"]
        self.edge_reject_ratio = self._dist_cfg["edge_reject_ratio"]
        self.last_valid_distance = None

    def _load_config(self, config: Optional[Dict[str, Any]]):
        """加载配置，带默认值回退"""
        if config:
            # 使用传入的配置
            self._dist_cfg = {**_DEFAULT_DIST_CFG, **config.get("distance", {})}
            self._pose_cfg = {**_DEFAULT_POSE_CFG, **config.get("pose", {})}
            return

        # 尝试从文件加载
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(base_dir, "config.yaml")
            with open(config_path, 'r', encoding='utf-8') as f:
                file_config = yaml.safe_load(f)
            self._dist_cfg = {**_DEFAULT_DIST_CFG, **file_config.get("distance", {})}
            self._pose_cfg = {**_DEFAULT_POSE_CFG, **file_config.get("pose", {})}
        except Exception:
            # 文件加载失败，使用默认值
            self._dist_cfg = _DEFAULT_DIST_CFG.copy()
            self._pose_cfg = _DEFAULT_POSE_CFG.copy()

    def _init_pose(self, model_complexity, smooth_landmarks, enable_segmentation,
                   min_detection_confidence, min_tracking_confidence):
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            smooth_landmarks=smooth_landmarks,
            enable_segmentation=enable_segmentation,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def set_model_complexity(self, complexity: int):
        """动态切换模型复杂度（温控降频用）"""
        if complexity != self._model_complexity:
            print(f"[Vision] 模型复杂度 {self._model_complexity} -> {complexity}")
            self._model_complexity = complexity
            # 需要重新初始化 Pose
            self.pose.close()
            self._init_pose(complexity, True, False, 0.5, 0.5)

    def _init_face_mesh(self):
        if not self._face_mesh_initialized:
            self.face_mesh = self.mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._face_mesh_initialized = True

    def detect(self, frame: np.ndarray, timestamp: float,
               analyze_face: bool = False, frame_is_rgb: bool = True) -> DetectionResult:
        """检测一帧"""
        result = DetectionResult(timestamp=timestamp)

        if frame_is_rgb:
            rgb_frame = frame
        else:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        pose_results = self.pose.process(rgb_frame)

        if pose_results.pose_landmarks:
            result.success = True
            result.pose_landmarks = pose_results.pose_landmarks
            result.pose_metrics = self._analyze_pose_metrics(pose_results.pose_landmarks, frame.shape)
            result.face_bbox = self._estimate_face_bbox(pose_results.pose_landmarks, frame.shape)

            # 距离估算 + 置信度
            if result.face_bbox:
                result.estimated_distance_cm, result.distance_confidence = \
                    self._estimate_distance(result.face_bbox, frame.shape)

            # Face Mesh（可选）
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
        """分析姿态指标 - 带评分"""
        h, w, _ = frame_shape
        lm = landmarks.landmark
        pose = self.mp_pose.PoseLandmark
        vis_thresh = self._pose_cfg["landmark_visibility_threshold"]

        def get_p(enum_val):
            return (lm[enum_val.value].x * w, lm[enum_val.value].y * h)

        def is_visible(enum_val):
            return lm[enum_val.value].visibility > vis_thresh

        metrics = PoseMetrics()

        # 获取关键点
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

        issue_score = 0  # 累计扣分

        # ---- 肩膀不平 ----
        if left_shoulder_vis and right_shoulder_vis:
            shoulder_height_diff = abs(left_shoulder[1] - right_shoulder[1])
            metrics.shoulder_level = shoulder_height_diff
            threshold = h * self._pose_cfg["shoulder_diff_threshold"]
            if shoulder_height_diff > threshold:
                severity = min(1.0, (shoulder_height_diff - threshold) / threshold)
                issue_score += severity * 25
                metrics.issues.append("Uneven Shoulders")

        # ---- 头部姿态 ----
        front_facing = left_ear_vis and right_ear_vis
        side_facing = (left_ear_vis and not right_ear_vis) or (right_ear_vis and not left_ear_vis)

        if front_facing:
            ear_avg_y = (left_ear[1] + right_ear[1]) / 2
            head_down_threshold = h * self._pose_cfg["head_down_threshold"]
            if nose[1] > ear_avg_y + head_down_threshold:
                deviation = (nose[1] - ear_avg_y - head_down_threshold) / head_down_threshold
                severity = min(1.0, deviation)
                metrics.head_pitch = deviation * 50
                issue_score += severity * 35
                metrics.issues.append("Head Down/Slouching")

            # 歪头检测（head_roll）
            ear_dx = right_ear[0] - left_ear[0]
            ear_dy = right_ear[1] - left_ear[1]
            if abs(ear_dx) > 1:  # 防除零
                roll_angle = abs(ear_dy / ear_dx) * 100
                if roll_angle > 15:  # 超过约 8.5 度
                    severity = min(1.0, (roll_angle - 15) / 20)
                    issue_score += severity * 15
                    metrics.issues.append("Head Tilted")
                metrics.head_roll = roll_angle

        elif side_facing:
            # 侧身时放宽阈值
            shoulder_avg_y = (left_shoulder[1] + right_shoulder[1]) / 2 if (left_shoulder_vis and right_shoulder_vis) else (left_shoulder[1] if left_shoulder_vis else right_shoulder[1])
            if nose[1] > shoulder_avg_y - h * 0.1:
                pass  # 侧身不做严格判断

        # ---- 躯干前倾 ----
        if (left_shoulder_vis or right_shoulder_vis) and (left_hip_vis or right_hip_vis):
            visible_shoulder_y = left_shoulder[1] if left_shoulder_vis else right_shoulder[1]
            visible_hip_y = left_hip[1] if left_hip_vis else right_hip[1]
            lean_threshold = h * self._pose_cfg["lean_forward_threshold"]

            if visible_shoulder_y > visible_hip_y - lean_threshold:
                deviation = (visible_shoulder_y - (visible_hip_y - lean_threshold)) / lean_threshold
                severity = min(1.0, deviation)
                issue_score += severity * 30
                metrics.issues.append("Leaning Forward")

        # ---- 驼背检测：鼻子-肩膀-髋部垂直偏离 ----
        if left_shoulder_vis and right_shoulder_vis and (left_hip_vis or right_hip_vis):
            shoulder_center_y = (left_shoulder[1] + right_shoulder[1]) / 2
            shoulder_center_x = (left_shoulder[0] + right_shoulder[0]) / 2
            hip_y = left_hip[1] if left_hip_vis else right_hip[1]

            spine_length = abs(hip_y - shoulder_center_y)
            if spine_length > 10:  # 有效脊柱长度
                # 鼻子相对于肩膀-髋部连线的偏移
                nose_offset_x = nose[0] - shoulder_center_x
                # 肩膀宽度作为参考
                shoulder_width = abs(right_shoulder[0] - left_shoulder[0])
                if shoulder_width > 10:
                    hunch_ratio = abs(nose_offset_x) / shoulder_width
                    if hunch_ratio > 0.3:
                        severity = min(1.0, (hunch_ratio - 0.3) / 0.3)
                        issue_score += severity * 20
                        metrics.issues.append("Hunching")

        # ---- 整体评分 (0-100) ----
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

    def _estimate_face_bbox(self, landmarks, frame_shape: Tuple[int, int, int]) -> Optional[Tuple[int, int, int, int]]:
        """从姿态关键点估计人脸位置"""
        h, w, _ = frame_shape
        lm = landmarks.landmark
        pose = self.mp_pose.PoseLandmark

        nose = (lm[pose.NOSE.value].x * w, lm[pose.NOSE.value].y * h)

        face_size = int(min(w, h) * 0.25)
        x = max(0, int(nose[0] - face_size / 2))
        y = max(0, int(nose[1] - face_size / 2))

        return (x, y, face_size, face_size)

    def _estimate_distance(self, face_bbox: Tuple[int, int, int, int],
                           frame_shape: Tuple[int, int, int]) -> Tuple[Optional[float], DistanceConfidence]:
        """相似三角形估计距离 + 置信度"""
        h, w, _ = frame_shape
        x, y, fw, fh = face_bbox

        if fw <= 0:
            return self.last_valid_distance, DistanceConfidence.LOW

        # 计算人脸中心距画面中心的偏移
        face_cx = x + fw / 2
        face_cy = y + fh / 2
        dx = abs(face_cx - w / 2) / (w / 2)
        dy = abs(face_cy - h / 2) / (h / 2)
        offset_ratio = max(dx, dy)

        # 判断置信度
        if offset_ratio < self.edge_reject_ratio:
            confidence = DistanceConfidence.HIGH
        elif offset_ratio < self.edge_reject_ratio * 1.5:
            confidence = DistanceConfidence.MEDIUM
        else:
            confidence = DistanceConfidence.LOW

        # 相似三角形
        raw_distance = (self.face_real_width_cm * self.camera_focal_length) / fw
        raw_distance = max(self.distance_min, min(self.distance_max, raw_distance))

        # EMA 平滑
        if self.last_valid_distance is None:
            self.last_valid_distance = raw_distance
        else:
            self.last_valid_distance = (
                self.distance_alpha * raw_distance +
                (1 - self.distance_alpha) * self.last_valid_distance
            )

        return self.last_valid_distance, confidence

    def close(self):
        """释放资源"""
        self.pose.close()
        if self.face_mesh:
            self.face_mesh.close()
