"""
简单人脸检测器 v3.2 - 修复 OpenCV 兼容性
使用 OpenCV 自带 Haar 级联，轻量高效
"""
import cv2
import numpy as np
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class SimpleDetectionResult:
    """检测结果"""
    success: bool = False
    face_bbox: Optional[tuple] = None  # (x, y, w, h)
    estimated_distance_cm: Optional[float] = None
    issues: list = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


class SimpleFaceDetector:
    """简单人脸检测器"""

    def __init__(self):
        # 加载 OpenCV 自带的人脸检测模型
        self.face_cascade = None
        self.model_loaded = False

        # 尝试加载 Haar 级联分类器
        try:
            # 方法 1: cv2.data
            if hasattr(cv2, 'data'):
                xml_path = os.path.join(
                    cv2.data.haarcascades,
                    "haarcascade_frontalface_default.xml"
                )
                if os.path.exists(xml_path):
                    self.face_cascade = cv2.CascadeClassifier(xml_path)
                    self.model_loaded = True
        except Exception:
            pass

        if not self.model_loaded:
            # 方法 2: 尝试常见位置
            try:
                common_paths = [
                    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
                    "/usr/local/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
                    "/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml",
                ]
                for path in common_paths:
                    if os.path.exists(path):
                        self.face_cascade = cv2.CascadeClassifier(path)
                        self.model_loaded = True
                        break
            except Exception:
                pass

        if self.model_loaded:
            print("[Vision] 人脸检测模型加载成功")
        else:
            print("[Vision] 警告: 人脸检测模型未找到，将使用模拟模式")

        # 校准参数 - 用于距离估算
        self.face_real_width_cm = 15.0
        self.focal_length = 600.0

    def detect(self, frame: np.ndarray) -> SimpleDetectionResult:
        """
        检测人脸
        返回检测结果
        """
        result = SimpleDetectionResult()

        if frame is None:
            return result

        # 如果模型没加载成功，返回空结果
        if not self.model_loaded:
            return result

        # 转为灰度图
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        # 检测人脸
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(50, 50)
        )

        if len(faces) > 0:
            # 取最大的人脸
            face = max(faces, key=lambda f: f[2] * f[3])
            x, y, w, h = face

            result.success = True
            result.face_bbox = (int(x), int(y), int(w), int(h))

            # 估算距离
            result.estimated_distance_cm = (
                self.face_real_width_cm * self.focal_length / w
            )

            # 简单姿态检查：人脸位置如果太靠下，可能低头
            h_img, w_img = frame.shape[:2]
            center_y = y + h / 2
            if center_y / h_img > 0.7:
                result.issues.append("低头/驼背")

        return result
