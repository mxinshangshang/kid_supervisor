"""
姿态检测器 - 基于 MediaPipe Pose
参考：Google 官方 MediaPipe RPi 优化
树莓派5 8G 可以跑 model_complexity=1 甚至 2
"""
import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from enum import Enum

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False


class PoseQuality(Enum):
    EXCELLENT = "excellent"
    OK = "ok"
    NEEDS_ATTENTION = "needs_attention"
    BAD = "bad"


@dataclass
class PoseMetrics:
    """姿态度量"""
    # 头部角度（估计）
    head_pitch: float = 0.0  # 俯仰
    head_yaw: float = 0.0    # 左右摆
    head_roll: float = 0.0   # 歪头

    # 躯干
    torso_lean: float = 0.0  # 前倾/后倾
    shoulder_level: float = 0.0  # 肩膀高低差

    # 整体评价
    overall_quality: PoseQuality = PoseQuality.EXCELLENT
    issues: list[str] = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


@dataclass
class DetectionResult:
    """检测结果"""
    timestamp: float
    success: bool = False
    pose_landmarks: Any = None
    face_landmarks: Any = None
    face_bbox: Optional[Tuple[int, int, int, int]] = None  # x,y,w,h
    estimated_distance_cm: Optional[float] = None
    pose_metrics: Optional[PoseMetrics] = None


class MediaPipePoseDetector:
    """
    MediaPipe Pose 检测器
    树莓派5 优化配置
    """

    def __init__(
        self,
        model_complexity: int = 1,  # 0=轻量, 1=平衡, 2=准确
        enable_segmentation: bool = False,
        smooth_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        if not MEDIAPIPE_AVAILABLE:
            raise ImportError("MediaPipe not installed!")

        self.mp_pose = mp.solutions.pose
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils

        # 初始化 Pose
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            smooth_landmarks=smooth_landmarks,
            enable_segmentation=enable_segmentation,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

        # 初始化 Face Mesh（可选，用于更准确的头部姿态）
        # 可以只在需要时初始化，节省内存
        self.face_mesh = None
        self._face_mesh_initialized = False

        # 人脸实际宽度（cm）用于距离估计
        # 这些值需要根据你的摄像头来校准
        self.face_real_width_cm = 15.0
        self.camera_focal_length = 800.0  # 增加焦距值，适应更广角的摄像头
        self.last_valid_distance = None  # 用于平滑距离读数
        self.distance_alpha = 0.3  # 平滑因子

    def _init_face_mesh(self):
        if not self._face_mesh_initialized:
            self.face_mesh = self.mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,  # 注意：这个更准但更重
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._face_mesh_initialized = True

    def detect(self, frame: np.ndarray, timestamp: float, analyze_face: bool = True, frame_is_rgb: bool = True) -> DetectionResult:
        """
        检测一帧
        frame_is_rgb: 传入的 frame 是否已经是 RGB（Picamera2 返回 RGB，OpenCV 返回 BGR）
        """
        result = DetectionResult(timestamp=timestamp)

        # 确保是 RGB（MediaPipe 需要 RGB）
        if frame_is_rgb:
            rgb_frame = frame
        else:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 检测姿态
        pose_results = self.pose.process(rgb_frame)

        if pose_results.pose_landmarks:
            result.success = True
            result.pose_landmarks = pose_results.pose_landmarks

            # 分析姿态
            result.pose_metrics = self._analyze_pose_metrics(pose_results.pose_landmarks, frame.shape)

            # 粗略的人脸 bbox（从姿态关键点）
            result.face_bbox = self._estimate_face_bbox(pose_results.pose_landmarks, frame.shape)

            # 距离估计
            if result.face_bbox:
                result.estimated_distance_cm = self._estimate_distance(result.face_bbox[2])

            # 可选：Face Mesh 做更精确的头部姿态
            if analyze_face:
                try:
                    self._init_face_mesh()
                    face_results = self.face_mesh.process(rgb_frame)
                    if face_results.multi_face_landmarks:
                        result.face_landmarks = face_results.multi_face_landmarks[0]
                        # 可以在这里用 Face Mesh 更准确地算头部姿态
                except Exception:
                    # Face Mesh 失败不影响主流程
                    pass

        return result

    def _analyze_pose_metrics(self, landmarks, frame_shape: Tuple[int, int, int]) -> PoseMetrics:
        """
        分析姿态指标 - 改进版
        - 更宽松的阈值
        - 支持侧身检测
        - 更鲁棒的判断
        """
        h, w, _ = frame_shape

        # 关键点简写
        lm = landmarks.landmark
        pose = self.mp_pose.PoseLandmark

        # 获取坐标（归一化 -> 像素）
        def get_p(enum_val):
            return (lm[enum_val.value].x * w, lm[enum_val.value].y * h)

        # 检查关键点可见性
        def is_visible(enum_val):
            return lm[enum_val.value].visibility > 0.5

        metrics = PoseMetrics()

        # ========== 获取关键点 ==========
        left_shoulder = get_p(pose.LEFT_SHOULDER)
        right_shoulder = get_p(pose.RIGHT_SHOULDER)
        left_hip = get_p(pose.LEFT_HIP)
        right_hip = get_p(pose.RIGHT_HIP)
        nose = get_p(pose.NOSE)
        left_ear = get_p(pose.LEFT_EAR)
        right_ear = get_p(pose.RIGHT_EAR)

        # ========== 检查关键点可见性 ==========
        left_shoulder_vis = is_visible(pose.LEFT_SHOULDER)
        right_shoulder_vis = is_visible(pose.RIGHT_SHOULDER)
        left_hip_vis = is_visible(pose.LEFT_HIP)
        right_hip_vis = is_visible(pose.RIGHT_HIP)
        left_ear_vis = is_visible(pose.LEFT_EAR)
        right_ear_vis = is_visible(pose.RIGHT_EAR)

        # ========== 肩膀检测（改进版） ==========
        if left_shoulder_vis and right_shoulder_vis:
            # 肩膀水平差（判断歪身子）
            shoulder_height_diff = abs(left_shoulder[1] - right_shoulder[1])
            metrics.shoulder_level = shoulder_height_diff

            # 更宽松的阈值：从 0.05 增加到 0.08
            if shoulder_height_diff > h * 0.08:
                metrics.issues.append("Uneven Shoulders")

        # ========== 头部姿态（改进版） ==========
        # 判断是否正面朝向
        front_facing = left_ear_vis and right_ear_vis
        # 判断是否侧身（只有一个耳朵可见）
        side_facing = (left_ear_vis and not right_ear_vis) or (right_ear_vis and not left_ear_vis)

        if front_facing:
            # 正面朝向：用鼻子和耳朵的关系
            ear_avg_y = (left_ear[1] + right_ear[1]) / 2
            # 更宽松的阈值：从 0.03 增加到 0.07
            if nose[1] > ear_avg_y + h * 0.07:
                metrics.head_pitch = (nose[1] - ear_avg_y) / h * 100
                metrics.issues.append("Head Down/Slouching")
        elif side_facing:
            # 侧身朝向：用鼻子和肩膀的关系
            shoulder_avg_y = (left_shoulder[1] + right_shoulder[1]) / 2 if (left_shoulder_vis and right_shoulder_vis) else (left_shoulder[1] if left_shoulder_vis else right_shoulder[1])
            # 侧身时更宽松
            if nose[1] > shoulder_avg_y - h * 0.1:
                pass  # 侧身时不做太严格的低头判断
        else:
            # 无法判断朝向，不做头部姿态检查
            pass

        # ========== 躯干前倾检测（改进版） ==========
        if (left_shoulder_vis or right_shoulder_vis) and (left_hip_vis or right_hip_vis):
            # 使用可见的肩膀和髋部
            visible_shoulder_y = left_shoulder[1] if left_shoulder_vis else right_shoulder[1]
            visible_hip_y = left_hip[1] if left_hip_vis else right_hip[1]

            # 更宽松的阈值：从 0.15 增加到 0.25
            if visible_shoulder_y > visible_hip_y - h * 0.25:
                metrics.issues.append("Leaning Forward")

        # ========== 整体评价（更宽松） ==========
        if len(metrics.issues) == 0:
            metrics.overall_quality = PoseQuality.EXCELLENT
        elif len(metrics.issues) == 1:
            metrics.overall_quality = PoseQuality.OK
        elif len(metrics.issues) == 2:
            metrics.overall_quality = PoseQuality.NEEDS_ATTENTION
        else:
            metrics.overall_quality = PoseQuality.BAD

        return metrics

    def _estimate_face_bbox(self, landmarks, frame_shape: Tuple[int, int, int]) -> Optional[Tuple[int, int, int, int]]:
        """从姿态关键点粗略估计人脸位置"""
        h, w, _ = frame_shape
        lm = landmarks.landmark
        pose = self.mp_pose.PoseLandmark

        nose = (lm[pose.NOSE.value].x * w, lm[pose.NOSE.value].y * h)

        # 简单用鼻子周围区域
        face_size = int(min(w, h) * 0.25)
        x = max(0, int(nose[0] - face_size / 2))
        y = max(0, int(nose[1] - face_size / 2))

        return (x, y, face_size, face_size)

    def _estimate_distance(self, face_width_pixel: int) -> float:
        """相似三角形估计距离 - 平滑版"""
        if face_width_pixel <= 0:
            return self.last_valid_distance

        # 计算原始距离
        raw_distance = (self.face_real_width_cm * self.camera_focal_length) / face_width_pixel

        # 限制合理范围（30cm 到 150cm）
        raw_distance = max(30.0, min(150.0, raw_distance))

        # 平滑处理
        if self.last_valid_distance is None:
            self.last_valid_distance = raw_distance
        else:
            self.last_valid_distance = (
                self.distance_alpha * raw_distance +
                (1 - self.distance_alpha) * self.last_valid_distance
            )

        return self.last_valid_distance

    def close(self):
        """释放资源"""
        self.pose.close()
        if self.face_mesh:
            self.face_mesh.close()
