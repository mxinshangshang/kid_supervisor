#!/usr/bin/env python3
"""
推理客户端进程 - 完整版
用 Python 3.11 + mediapipe
功能：人脸检测 + 姿态检测 + 距离估算 + 监督逻辑 + 预览渲染
"""
import sys
import os
import time
import socket
import struct
import pickle
import cv2
import numpy as np

# 添加src目录到路径
base_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(base_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# 导入v3现有模块
try:
    import mediapipe as mp
    from vision.pose_detector import MediaPipePoseDetector, DetectionResult
    from supervision import Supervisor, SupervisionConfig, AlertType
    from preview_renderer import PreviewRenderer
    MODULES_READY = True
except ImportError as e:
    print(f"[Error] 模块导入失败: {e}")
    MODULES_READY = False

# 配置
FRAME_SIZE = (640, 480)
HOST = "127.0.0.1"
PORT = 65432


def recv_frame(conn):
    """从 socket 接收帧"""
    try:
        # 先接收长度
        data_len = conn.recv(4)
        if len(data_len) < 4:
            return None
        length = struct.unpack("!I", data_len)[0]

        # 再接收数据
        data = b""
        while len(data) < length:
            packet = conn.recv(length - len(data))
            if not packet:
                return None
            data += packet

        return pickle.loads(data)
    except Exception as e:
        print(f"[Inference] 接收失败: {e}")
        return None


def main():
    # 检查是否禁用预览
    no_preview = "--no-preview" in sys.argv or "-n" in sys.argv

    print("=" * 60)
    print("🧠 Kid Supervisor - 推理客户端 (完整版)")
    print(f"Python: {sys.version}")
    print(f"连接: {HOST}:{PORT}")
    print(f"预览: {'❌ 禁用 (headless)' if no_preview else '✅ 启用'}")
    print("=" * 60)

    if not MODULES_READY:
        print("[Error] 必需模块未就绪，请检查:")
        print("  - mediapipe")
        print("  - src/vision/pose_detector.py")
        print("  - src/supervision.py")
        print("  - src/preview_renderer.py")
        return 1

    # 初始化检测器
    try:
        detector = MediaPipePoseDetector(
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        print("[Vision] MediaPipe Pose 初始化成功")
    except Exception as e:
        print(f"[Error] MediaPipe 初始化失败: {e}")
        return 1

    # 初始化监督逻辑
    supervisor = Supervisor()
    print("[Supervisor] 监督逻辑初始化成功")

    # 初始化预览渲染器
    renderer = PreviewRenderer(enabled=not no_preview)
    print(f"[Renderer] 预览渲染器初始化: {'禁用' if no_preview else '启用'}")

    # 连接到摄像头服务器
    print(f"\n[Inference] 正在连接摄像头服务器...")

    sock = None
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((HOST, PORT))
            print(f"[Inference] 已连接到摄像头服务器")
            break
        except ConnectionRefusedError:
            print(f"[Inference] 等待摄像头服务器启动...")
            time.sleep(1)

    # 状态变量
    person_detected = False
    person_counter = 0
    person_gone_counter = 0
    alerts = []
    current_session_info = None

    print("\n[Ready] 按 Q / ESC 退出\n")

    try:
        while True:
            current_time = time.time()

            # 接收帧
            frame_rgb = recv_frame(sock)
            if frame_rgb is None:
                print(f"[Inference] 摄像头断开，退出")
                break

            # ========== 1. 检测 ==========
            detection_result = detector.detect(
                frame_rgb,
                timestamp=current_time,
                analyze_face=True,
                frame_is_rgb=True
            )

            # ========== 2. 存在检测防抖 ==========
            if detection_result.success:
                person_gone_counter = 0
                person_counter = min(person_counter + 1, 3)

                if person_counter >= 2 and not person_detected:
                    # 检测到有人
                    person_detected = True
                    print(f"[Info] 检测到人脸，学习开始")
                    supervisor.on_person_detected(current_time)
            else:
                person_counter = 0
                person_gone_counter = min(person_gone_counter + 1, 5)

                if person_gone_counter >= 3 and person_detected:
                    # 人离开
                    person_detected = False
                    print(f"[Info] 人脸消失")
                    supervisor.on_person_left(current_time)

            # ========== 3. 监督逻辑更新 ==========
            alerts = []

            if person_detected and detection_result.pose_metrics:
                # 姿态更新
                is_bad = len(detection_result.pose_metrics.issues) > 0
                issues = detection_result.pose_metrics.issues
                posture_alert = supervisor.on_posture_update(
                    is_bad, issues, current_time
                )
                if posture_alert:
                    alerts.append(posture_alert)

                # 距离更新
                distance_alert = supervisor.on_distance_update(
                    detection_result.estimated_distance_cm, current_time
                )
                if distance_alert:
                    alerts.append(distance_alert)

            # 学习时长检查
            time_alert = supervisor.check_study_time(current_time)
            if time_alert:
                alerts.append(time_alert)

            # ========== 4. 准备渲染数据 ==========
            supervisor_state = {
                "current_session": supervisor.current_session,
                "is_resting": supervisor.is_resting
            }

            # 兼容 PreviewRenderer 的预期格式
            # 动态添加 issues 字段
            render_result = detection_result
            render_result.issues = []
            if detection_result.pose_metrics:
                render_result.issues = detection_result.pose_metrics.issues

            # ========== 5. 渲染预览 / 无预览日志 ==========
            if no_preview:
                # 无预览模式：打印关键状态
                if detection_result.success:
                    # 有人
                    dist_str = f"{detection_result.estimated_distance_cm:.1f}cm" if detection_result.estimated_distance_cm else "N/A"
                    issues_str = ",".join(detection_result.pose_metrics.issues) if detection_result.pose_metrics and detection_result.pose_metrics.issues else "OK"

                    # 有提醒时打印
                    if alerts:
                        print(f"[Alert] {alerts[-1].message}")
                else:
                    # 无人
                    pass
            else:
                # 预览模式
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                display_frame = renderer.render(
                    frame=frame_bgr,
                    detection_result=render_result,
                    supervisor_state=supervisor_state,
                    alerts=alerts,
                    pose=detector.mp_pose if hasattr(detector, 'mp_pose') else None,
                    mp_drawing=detector.mp_drawing if hasattr(detector, 'mp_drawing') else None
                )
                if not renderer.show(display_frame):
                    break

    except KeyboardInterrupt:
        print("\n\n[Inference] 收到退出信号")
    finally:
        print("[Inference] 清理中...")
        try:
            detector.close()
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        try:
            renderer.close()
        except Exception:
            pass
        print("[Inference] 退出")


if __name__ == "__main__":
    main()
