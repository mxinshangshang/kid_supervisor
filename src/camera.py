"""
摄像头管理模块 v5.0 - 完美颜色处理
Picamera2 返回 RGB，OpenCV 显示需要 BGR
"""
import time
import cv2
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class CameraConfig:
    width: int = 640
    height: int = 480
    fps: int = 10


class BaseCamera:
    def start(self) -> None:
        raise NotImplementedError()

    def read_frame(self) -> Optional[np.ndarray]:
        raise NotImplementedError()

    def stop(self) -> None:
        raise NotImplementedError()


class OpenCVCamera(BaseCamera):
    """USB 摄像头 - 返回 BGR"""

    def __init__(self, config: CameraConfig, device_id: int = 0):
        self.config = config
        self.device_id = device_id
        self.cap = None

    def start(self) -> None:
        print(f"[Camera] OpenCV: {self.device_id}")
        self.cap = cv2.VideoCapture(self.device_id)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.config.fps)

        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera {self.device_id}")

        for _ in range(5):
            self.cap.read()
        print(f"[Camera] OK: {self.config.width}x{self.config.height} @ {self.config.fps}fps")

    def read_frame(self) -> Optional[np.ndarray]:
        if self.cap is None or not self.cap.isOpened():
            return None
        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame  # BGR

    def stop(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            print("[Camera] Stopped")


class Picamera2Camera(BaseCamera):
    """树莓派原生摄像头 - 返回 RGB"""

    def __init__(self, config: CameraConfig):
        self.config = config
        self.picam2 = None

    def start(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError:
            raise RuntimeError("Picamera2 not installed")

        print(f"[Camera] Picamera2 (Raspberry Pi native)")
        self.picam2 = Picamera2()
        preview_config = self.picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (self.config.width, self.config.height)},
            controls={"FrameRate": self.config.fps},
        )
        self.picam2.configure(preview_config)
        self.picam2.start()
        time.sleep(2)
        print(f"[Camera] OK: {self.config.width}x{self.config.height} @ {self.config.fps}fps")

    def read_frame(self) -> Optional[np.ndarray]:
        if self.picam2 is None:
            return None
        return self.picam2.capture_array()  # RGB

    def stop(self) -> None:
        if self.picam2 is not None:
            self.picam2.stop()
            self.picam2 = None
            print("[Camera] Stopped")


def create_camera(config: CameraConfig = None, prefer_picamera: bool = True):
    """工厂函数，自动判断摄像头类型"""
    if config is None:
        config = CameraConfig()

    if prefer_picamera:
        try:
            from picamera2 import Picamera2
            print("[Camera] 尝试使用 Picamera2...")
            return Picamera2Camera(config)
        except Exception as e:
            print(f"[Camera] Picamera2 不可用: {e}")
            print("[Camera] 回退到 OpenCV")

    print(f"[Camera] 使用 OpenCV (设备 0)")
    return OpenCVCamera(config)
