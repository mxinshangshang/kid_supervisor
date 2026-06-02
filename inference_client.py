#!/usr/bin/env python3
"""
推理客户端进程 - v4.0
用 Python 3.11 + mediapipe
功能：姿态检测 + 距离估算 + 监督逻辑 + 预览渲染
改进：帧 timestamp 丢弃旧帧、推理/显示频率解耦、温控降频、性能日志
"""
import sys
import os
import time
import socket
import struct
import subprocess
import yaml
import cv2
import numpy as np

# 添加 src 目录到路径
base_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(base_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# ===================== 加载配置 =====================
CONFIG_PATH = os.path.join(base_dir, "config.yaml")

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    CONFIG = yaml.safe_load(f)

CAM = CONFIG["camera"]
NET = CONFIG["network"]
INF = CONFIG["inference"]
DIST = CONFIG["distance"]
THERMAL = CONFIG["thermal"]
PROC = CONFIG["process"]

FRAME_SIZE = (CAM["width"], CAM["height"])
HOST = NET["host"]
PORT = NET["port"]

# 导入 v3 模块
try:
    import mediapipe as mp
    from vision.pose_detector import MediaPipePoseDetector, DetectionResult
    from supervision import Supervisor, SupervisionConfig, AlertType
    from preview_renderer import PreviewRenderer
    MODULES_READY = True
except ImportError as e:
    print(f"[Error] 模块导入失败: {e}")
    MODULES_READY = False


def recv_frame(conn):
    """从 socket 接收帧（带元数据）

    协议: [4B frame_id][8B timestamp][4B jpeg_len][jpeg_data]
    """
    try:
        # 接收元数据: frame_id(4B) + timestamp(8B) + jpeg_len(4B) = 16B
        header = b""
        while len(header) < 16:
            chunk = conn.recv(16 - len(header))
            if not chunk:
                return None, None, None, None
            header += chunk

        frame_id, timestamp, jpeg_len = struct.unpack('!IdI', header)

        # 接收 JPEG 数据
        data = b""
        while len(data) < jpeg_len:
            packet = conn.recv(jpeg_len - len(data))
            if not packet:
                return None, None, None, None
            data += packet

        # JPEG 解码 - 得到 BGR
        jpeg_array = np.frombuffer(data, dtype=np.uint8)
        bgr_frame = cv2.imdecode(jpeg_array, cv2.IMREAD_COLOR)
        if bgr_frame is None:
            return None, None, None, None

        # 转 RGB 用于推理
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)

        return frame_id, timestamp, rgb_frame, bgr_frame

    except socket.timeout:
        # 超时是正常的，不打印
        return None, None, None, None
    except Exception as e:
        print(f"[Inference] 接收失败: {e}")
        return None, None, None, None


def get_cpu_temp():
    """获取 CPU 温度（树莓派）"""
    try:
        result = subprocess.run(
            ['vcgencmd', 'measure_temp'],
            capture_output=True, text=True, timeout=2
        )
        # 输出格式: temp=42.8'C
        temp_str = result.stdout.strip()
        if '=' in temp_str:
            return float(temp_str.split('=')[1].replace("'C", ''))
    except Exception:
        pass
    return None


def main():
    no_preview = "--no-preview" in sys.argv or "-n" in sys.argv

    print("=" * 60)
    print("Kid Supervisor - 推理客户端 v4.0")
    print(f"Python: {sys.version}")
    print(f"连接: {HOST}:{PORT}")
    print(f"推理帧率目标: {INF['inference_fps']} FPS")
    print(f"显示帧率目标: {INF['display_fps']} FPS")
    print(f"预览: {'禁用 (headless)' if no_preview else '启用'}")
    print("=" * 60)

    if not MODULES_READY:
        print("[Error] 必需模块未就绪")
        return 1

    # 初始化检测器
    try:
        detector = MediaPipePoseDetector(
            model_complexity=INF["model_complexity"],
            min_detection_confidence=INF["min_detection_confidence"],
            min_tracking_confidence=INF["min_tracking_confidence"],
            config=CONFIG,
        )
        print("[Vision] MediaPipe Pose 初始化成功")
    except Exception as e:
        print(f"[Error] MediaPipe 初始化失败: {e}")
        return 1

    # 初始化监督逻辑（加载配置）
    supervision_config = SupervisionConfig(CONFIG)
    supervisor = Supervisor(supervision_config)
    print("[Supervisor] 监督逻辑初始化成功")

    # 初始化预览渲染器
    renderer = PreviewRenderer(enabled=not no_preview, config=CONFIG)
    print(f"[Renderer] 预览渲染器初始化: {'禁用' if no_preview else '启用'}")

    # 连接到摄像头服务器
    print(f"\n[Inference] 正在连接摄像头服务器...")

    sock = None
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(NET.get("recv_timeout_s", 5))
            sock.connect((HOST, PORT))
            print(f"[Inference] 已连接到摄像头服务器")
            break
        except ConnectionRefusedError:
            print(f"[Inference] 等待摄像头服务器启动...")
            time.sleep(1)

    # ---- 状态变量 ----
    person_detected = False
    person_counter = 0
    person_gone_counter = 0
    alerts = []

    # ---- 帧管理 ----
    latest_frame = None          # 最新未处理的帧 (RGB for inference)
    latest_frame_bgr = None      # 最新未处理的帧 (BGR for preview)
    latest_frame_id = None
    latest_frame_ts = None
    last_detection = None        # 上次推理结果（供显示复用）
    last_detection_ts = 0

    # ---- 频率控制 ----
    inference_interval = 1.0 / INF["inference_fps"]
    display_interval = 1.0 / INF["display_fps"]
    last_inference_time = 0
    last_display_time = 0

    # ---- 温控 ----
    last_temp_check = 0
    current_temp = None
    is_throttled = False
    original_model_complexity = INF["model_complexity"]

    # ---- 性能统计 ----
    stats_start = time.time()
    stats_frames_received = 0
    stats_frames_inferred = 0
    stats_frames_dropped = 0
    stats_total_infer_ms = 0

    print("\n[Ready] 按 Q / ESC 退出\n")

    try:
        while True:
            current_time = time.time()

            # ========== 1. 接收帧（非阻塞尝试）==========
            try:
                frame_id, frame_ts, frame_rgb, frame_bgr = recv_frame(sock)
                if frame_rgb is None:
                    # 可能是超时，检查连接
                    continue
                latest_frame = frame_rgb
                latest_frame_bgr = frame_bgr
                latest_frame_id = frame_id
                latest_frame_ts = frame_ts
                stats_frames_received += 1
            except socket.timeout:
                # 接收超时，继续循环
                pass
            except Exception as e:
                print(f"[Inference] 摄像头断开: {e}")
                break

            # ========== 2. 温度检查 ==========
            if THERMAL.get("enabled") and current_time - last_temp_check > THERMAL["temp_check_interval_s"]:
                current_temp = get_cpu_temp()
                last_temp_check = current_time

                if current_temp is not None:
                    if current_temp >= THERMAL["temp_throttle_c"] and not is_throttled:
                        print(f"[Thermal] CPU {current_temp:.1f}C >= {THERMAL['temp_throttle_c']}C, 降频中...")
                        is_throttled = True
                        # 降频：降低推理帧率和模型复杂度
                        inference_interval = 1.0 / THERMAL["throttle_inference_fps"]
                        detector.set_model_complexity(THERMAL["throttle_model_complexity"])
                    elif current_temp < THERMAL["temp_throttle_c"] - 5 and is_throttled:
                        print(f"[Thermal] CPU {current_temp:.1f}C, 恢复正常")
                        is_throttled = False
                        inference_interval = 1.0 / INF["inference_fps"]
                        detector.set_model_complexity(original_model_complexity)

            # ========== 3. 推理（按频率控制）==========
            if latest_frame is not None and current_time - last_inference_time >= inference_interval:
                # 丢弃旧帧：如果最新帧的 frame_id 已经被跳过多次，说明积压了
                if last_detection is not None and latest_frame_id is not None:
                    frame_gap = latest_frame_id - getattr(last_detection, '_frame_id', 0)
                    if frame_gap > 2:
                        stats_frames_dropped += 1
                        # 仍然用最新帧推理（不是旧帧），只是记录了跳过

                infer_start = time.time()
                detection_result = detector.detect(
                    latest_frame,
                    timestamp=current_time,
                    analyze_face=INF.get("analyze_face", False),
                    frame_is_rgb=True,
                )
                detection_result._frame_id = latest_frame_id
                infer_ms = (time.time() - infer_start) * 1000

                last_detection = detection_result
                last_detection_ts = current_time
                last_inference_time = current_time
                stats_frames_inferred += 1
                stats_total_infer_ms += infer_ms

                # ========== 4. 存在检测防抖 ==========
                if detection_result.success:
                    person_gone_counter = 0
                    person_counter = min(person_counter + 1, 3)

                    if person_counter >= 2 and not person_detected:
                        person_detected = True
                        print(f"[Info] 检测到人脸，学习开始")
                        supervisor.on_person_detected(current_time)
                else:
                    person_counter = 0
                    person_gone_counter = min(person_gone_counter + 1, 5)

                    if person_gone_counter >= 3 and person_detected:
                        person_detected = False
                        print(f"[Info] 人脸消失")
                        supervisor.on_person_left(current_time)

                # ========== 5. 监督逻辑 ==========
                alerts = []

                if person_detected and detection_result.pose_metrics:
                    posture_alert = supervisor.on_posture_update(
                        detection_result.pose_metrics, current_time
                    )
                    if posture_alert:
                        alerts.append(posture_alert)

                    distance_alert = supervisor.on_distance_update(
                        detection_result.estimated_distance_cm,
                        detection_result.distance_confidence,
                        current_time,
                    )
                    if distance_alert:
                        alerts.append(distance_alert)

                time_alert = supervisor.check_study_time(current_time)
                if time_alert:
                    alerts.append(time_alert)

            # ========== 6. 渲染预览（按频率控制）==========
            if current_time - last_display_time >= display_interval:
                display_result = last_detection
                if display_result is None:
                    display_result = DetectionResult(timestamp=current_time)

                supervisor_state = {
                    "current_session": supervisor.current_session,
                    "is_resting": supervisor.is_resting,
                }

                # 动态添加 issues 字段
                render_result = display_result
                render_result.issues = []
                if display_result.pose_metrics:
                    render_result.issues = display_result.pose_metrics.issues

                if no_preview:
                    # 无预览模式：每 10 秒打印一次状态
                    if stats_frames_inferred > 0 and current_time - stats_start >= 10.0:
                        elapsed = current_time - stats_start
                        recv_fps = stats_frames_received / elapsed
                        infer_fps = stats_frames_inferred / elapsed
                        avg_ms = stats_total_infer_ms / max(stats_frames_inferred, 1)
                        temp_str = f"{current_temp:.1f}C" if current_temp else "N/A"
                        print(f"[Stats] recv={recv_fps:.1f}fps  infer={infer_fps:.1f}fps  "
                              f"latency={avg_ms:.0f}ms  dropped={stats_frames_dropped}  "
                              f"temp={temp_str}  throttled={is_throttled}")
                        stats_start = current_time
                        stats_frames_received = 0
                        stats_frames_inferred = 0
                        stats_frames_dropped = 0
                        stats_total_infer_ms = 0

                    if alerts:
                        print(f"[Alert] {alerts[-1].message}")
                else:
                    # 预览模式 - 转 RGB 给 cv2.imshow（实测此环境下颜色才对）
                    if 'latest_frame_bgr' in locals() and latest_frame_bgr is not None:
                        frame_for_preview = cv2.cvtColor(latest_frame_bgr, cv2.COLOR_BGR2RGB)
                        display_frame = renderer.render(
                            frame=frame_for_preview,
                            detection_result=render_result,
                            supervisor_state=supervisor_state,
                            alerts=alerts,
                            pose=detector.mp_pose if hasattr(detector, 'mp_pose') else None,
                            mp_drawing=detector.mp_drawing if hasattr(detector, 'mp_drawing') else None,
                        )
                        if not renderer.show(display_frame):
                            break

                last_display_time = current_time

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
    sys.exit(main() or 0)
