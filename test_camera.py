#!/usr/bin/env python3
"""
摄像头测试脚本
测试 OpenCV 和/或 Picamera2 是否能正常工作
"""
import sys
import time
import cv2

print("="*60)
print("摄像头测试")
print("="*60)
print()

# 1. 测试 OpenCV
print("[1/3] 测试 OpenCV (设备 0)...")
cap = cv2.VideoCapture(0)
if cap.isOpened():
    print("    ✅ OpenCV 摄像头打开成功")
    # 试读几帧
    success_count = 0
    for i in range(5):
        ret, frame = cap.read()
        if ret:
            success_count += 1
        time.sleep(0.05)
    print(f"    帧读取成功率: {success_count}/5")
    print(f"    分辨率: {int(cap.get(3))}x{int(cap.get(4))}")
    print(f"    FPS: {cap.get(5)}")
    cap.release()
else:
    print("    ❌ OpenCV 无法打开摄像头")

print()

# 2. 测试 Picamera2
print("[2/3] 测试 Picamera2...")
try:
    from picamera2 import Picamera2
    picam = Picamera2()
    picam.start()
    time.sleep(0.5)
    frame = picam.capture_array()
    print(f"    ✅ Picamera2 成功")
    print(f"    帧大小: {frame.shape}")
    picam.stop()
except Exception as e:
    print(f"    ❌ Picamera2 不可用: {e}")

print()

# 3. 测试 src.camera 模块
print("[3/3] 测试 src.camera 模块...")
try:
    from src.camera import create_camera, CameraConfig
    config = CameraConfig(width=640, height=480, fps=15)
    cam = create_camera(config, prefer_picamera=False)
    cam.start()
    time.sleep(0.5)
    frame = cam.read_frame()
    if frame is not None:
        print(f"    ✅ src.camera 成功")
        print(f"    帧大小: {frame.shape}")
    else:
        print(f"    ❌ src.camera 无法读取帧")
    cam.stop()
except Exception as e:
    print(f"    ❌ src.camera 失败: {e}")

print()
print("="*60)
print("测试完成")
print("="*60)
