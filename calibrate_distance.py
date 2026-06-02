#!/usr/bin/env python3
"""
距离校准工具
1. 运行这个脚本
2. 站在离摄像头已知距离（比如50cm）的地方
3. 按键盘上的数字键输入真实距离（比如按5，然后回车表示50cm）
4. 脚本会计算并显示需要设置的 camera_focal_length 值
"""
import sys
import os

# 添加src目录
base_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(base_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import cv2
import numpy as np
from picamera2 import Picamera2
import time

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False


def main():
    print("=" * 60)
    print("距离校准工具")
    print("=" * 60)

    if not MEDIAPIPE_AVAILABLE:
        print("需要安装 mediapipe！")
        return 1

    # 初始化摄像头
    print("\n正在启动摄像头...")
    picam2 = Picamera2()
    preview_config = picam2.create_preview_configuration(
        main={"format": "RGB888", "size": (640, 480)},
        controls={"FrameRate": 20}
    )
    picam2.configure(preview_config)
    picam2.start()
    time.sleep(1)

    # 初始化MediaPipe Pose
    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        min_detection_confidence=0.5
    )
    mp_drawing = mp.solutions.drawing_utils

    print("\n请站在摄像头前，保持正面")
    print("当检测到人脸时，按 'c' 键进行校准")
    print("按 'q' 键退出\n")

    last_face_width = None

    try:
        while True:
            frame = picam2.capture_array()
            frame_rgb = frame
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            # 检测姿态
            results = pose.process(frame_rgb)

            face_width = None

            if results.pose_landmarks:
                # 绘制骨架
                mp_drawing.draw_landmarks(
                    frame_bgr,
                    results.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS
                )

                # 估算人脸框
                lm = results.pose_landmarks.landmark
                nose = (lm[mp_pose.PoseLandmark.NOSE.value].x * 640,
                        lm[mp_pose.PoseLandmark.NOSE.value].y * 480)
                face_size = int(min(640, 480) * 0.25)
                x = max(0, int(nose[0] - face_size / 2))
                y = max(0, int(nose[1] - face_size / 2))

                # 画人脸框
                cv2.rectangle(frame_bgr, (x, y), (x + face_size, y + face_size), (0, 255, 0), 2)
                face_width = face_size
                last_face_width = face_width

                # 显示
                cv2.putText(frame_bgr, f"Face Width: {face_width}px", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # 显示提示
            if last_face_width:
                cv2.putText(frame_bgr, "Press 'c' to calibrate | 'q' to quit", (10, 450),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            else:
                cv2.putText(frame_bgr, "Move into frame...", (10, 450),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            cv2.imshow("Calibration", frame_bgr)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('c') and last_face_width:
                # 开始校准
                print(f"\n检测到人脸宽度: {last_face_width} 像素")
                print("请输入你当前距离摄像头的真实距离(cm): ", end="")
                real_distance = float(input().strip())

                # 计算焦距
                # distance = (real_width * focal_length) / pixel_width
                # focal_length = (distance * pixel_width) / real_width
                real_face_width_cm = 15.0  # 人脸真实宽度约15cm
                focal_length = (real_distance * last_face_width) / real_face_width_cm

                print("\n" + "=" * 60)
                print(f"校准完成！")
                print(f"真实距离: {real_distance} cm")
                print(f"人脸像素宽度: {last_face_width} px")
                print(f"计算出的焦距值: {focal_length:.1f}")
                print("\n请修改 src/vision/pose_detector.py 中的:")
                print(f"  self.camera_focal_length = {focal_length:.1f}")
                print("=" * 60 + "\n")

                # 显示计算的距离作为验证
                estimated = (real_face_width_cm * focal_length) / last_face_width
                print(f"验证 - 使用此焦距值时，当前距离检测为: {estimated:.1f}cm\n")

    finally:
        cv2.destroyAllWindows()
        picam2.stop()
        pose.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
