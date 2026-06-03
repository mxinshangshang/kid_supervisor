#!/usr/bin/env python3
"""Distance calibration tool using the same detector pipeline."""

import os
import sys
import time

import cv2
from picamera2 import Picamera2
import yaml

base_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(base_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from config import load_config
from vision.pose_detector import MediaPipePoseDetector


def save_focal_length(config_path: str, focal_length: float):
    with open(config_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("distance", {})["camera_focal_length"] = round(focal_length, 2)
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=False, sort_keys=False)


def main():
    config = load_config(base_dir)
    config_path = config["_meta"]["config_path"]
    detector = MediaPipePoseDetector(config=config)

    print("=" * 60)
    print("距离校准工具")
    print("请正对摄像头，在已知距离处保持 2-3 秒稳定")
    print("按 'c' 完成采样并写入 config.yaml，按 'q' 退出")
    print("=" * 60)

    picam2 = Picamera2()
    preview_config = picam2.create_preview_configuration(
        main={"format": config["camera"]["format"], "size": (config["camera"]["width"], config["camera"]["height"])},
        controls={"FrameRate": config["camera"]["fps"]},
    )
    picam2.configure(preview_config)
    picam2.start()
    time.sleep(1)

    sampled_widths = []
    try:
        while True:
            frame_rgb = picam2.capture_array()
            detection = detector.detect(frame_rgb, timestamp=time.time(), frame_is_rgb=True)
            preview = frame_rgb.copy()
            if detection.face_bbox:
                x, y, w, h = detection.face_bbox
                cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(preview, f"Face Width: {w}px", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                sampled_widths.append(w)
                sampled_widths = sampled_widths[-30:]
            cv2.putText(preview, "Press 'c' to calibrate | 'q' to quit", (10, preview.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.imshow("Calibration", preview)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("c") and sampled_widths:
                avg_width = sum(sampled_widths) / len(sampled_widths)
                print(f"\n平均人脸宽度: {avg_width:.1f}px")
                print("请输入当前真实距离(cm): ", end="")
                real_distance = float(input().strip())
                focal_length = (real_distance * avg_width) / config["distance"]["face_real_width_cm"]
                save_focal_length(config_path, focal_length)
                print(f"已写入 config.yaml: distance.camera_focal_length = {focal_length:.2f}")
                break
    finally:
        detector.close()
        cv2.destroyAllWindows()
        picam2.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
