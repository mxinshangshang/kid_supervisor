#!/usr/bin/env python3
"""
Kid Supervisor - 简单单进程版本
用系统 Python 3.13 + picamera2 + mediapipe
"""
import sys
import time
import cv2
import numpy as np
import os
import mediapipe as mp

# 全局配置
ENABLE_MEDIAPIPE = True
FRAME_SIZE = (640, 480)
MAX_FPS = 20

def get_face_cascade():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(base_dir, "haarcascade_frontalface_default.xml")
    cascade = cv2.CascadeClassifier(model_path)
    if not cascade.empty():
        return cascade
    return None

def init_mediapipe():
    try:
        mp_face_detection = mp.solutions.face_detection
        face_detection = mp_face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.5
        )
        print("[Vision] MediaPipe 人脸检测加载成功")
        return face_detection
    except Exception as e:
        print(f"[Warn] MediaPipe 加载失败，回退到Haar级联: {e}")
        return None

def init_camera():
    from picamera2 import Picamera2
    print("[Camera] 启动中 (picamera2)...")
    picam2 = Picamera2()
    preview_config = picam2.create_preview_configuration(
        main={"format": "RGB888", "size": FRAME_SIZE},
        controls={"FrameRate": MAX_FPS}
    )
    picam2.configure(preview_config)
    picam2.start()
    time.sleep(1)
    print("[Camera] 启动成功")
    return picam2

def main():
    print("=" * 60)
    print("📚 Kid Supervisor - MediaPipe 版")
    print(f"Python: {sys.version}")
    print("=" * 60)

    picam2 = init_camera()
    mp_detector = init_mediapipe() if ENABLE_MEDIAPIPE else None
    face_cascade = get_face_cascade() if not mp_detector else None
    use_mediapipe = mp_detector is not None

    person_detected = False
    person_counter = 0
    learning_start_time = None
    frame_count = 0
    fps_start = time.time()
    current_fps = 0

    print("\n[Ready] 按 q 或 ESC 退出\n")
    print(f"[Info] 使用{'MediaPipe' if use_mediapipe else 'Haar级联'}检测引擎")

    try:
        cv2.namedWindow("Kid Supervisor", cv2.WINDOW_AUTOSIZE)

        while True:
            current_time = time.time()
            frame_count += 1

            if current_time - fps_start >= 1:
                current_fps = frame_count / (current_time - fps_start)
                frame_count = 0
                fps_start = current_time

            frame = picam2.capture_array()
            display_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            h, w = frame.shape[:2]

            detected_faces = []

            if use_mediapipe:
                results = mp_detector.process(frame)
                if results.detections:
                    for detection in results.detections:
                        bbox = detection.location_data.relative_bounding_box
                        x = int(bbox.xmin * w)
                        y = int(bbox.ymin * h)
                        fw = int(bbox.width * w)
                        fh = int(bbox.height * h)
                        detected_faces.append((x, y, fw, fh))
            else:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(80, 80))
                detected_faces = faces

            if len(detected_faces) > 0:
                person_counter = min(person_counter + 1, 2)
                if person_counter >= 2 and not person_detected:
                    person_detected = True
                    learning_start_time = current_time
                    print(f"[Info] 检测到人脸!")
            else:
                person_counter = max(person_counter - 1, 0)
                if person_counter == 0 and person_detected:
                    person_detected = False
                    if learning_start_time:
                        duration = current_time - learning_start_time
                        print(f"[Info] 人脸消失 - 学习了 {duration:.0f}秒")
                        learning_start_time = None

            for (x, y, fw, fh) in detected_faces:
                cv2.rectangle(display_frame, (x, y), (x + fw, y + fh), (0, 255, 0), 2)
                cv2.putText(display_frame, "FACE", (x, y - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            if person_detected and learning_start_time:
                duration = current_time - learning_start_time
                status_color = (0, 255, 0)
                status_text = f"Learning: {duration:.0f}s"
            else:
                status_color = (255, 255, 255)
                status_text = "Waiting..."

            cv2.putText(display_frame, status_text, (20, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
            cv2.putText(display_frame, f"Faces: {len(detected_faces)}", (20, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(display_frame, f"FPS: {current_fps:.1f}", (w - 120, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(display_frame, f"Engine: {'MediaPipe' if use_mediapipe else 'Haar'}", (w - 180, h - 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

            cv2.imshow("Kid Supervisor", display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break

    except KeyboardInterrupt:
        print("\n\n[Info] 正在退出...")
    finally:
        print("[Cleanup] 关闭中...")
        try:
            picam2.stop()
        except Exception:
            pass
        try:
            if mp_detector:
                mp_detector.close()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        print("[Done] Bye!")

if __name__ == "__main__":
    main()
