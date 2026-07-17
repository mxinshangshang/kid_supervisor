#!/usr/bin/env python3
"""Inference client process for supervision and preview."""

import os
import socket
import struct
import sys
import threading
import time
import signal
from dataclasses import dataclass
from typing import Optional


def sigterm_handler(signum, frame):
    """处理SIGTERM信号，复用KeyboardInterrupt路径"""
    raise KeyboardInterrupt()

import cv2
import numpy as np

base_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(base_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from config import load_config

CONFIG = load_config(base_dir)
NET = CONFIG["network"]
INF = CONFIG["inference"]
THERMAL = CONFIG["thermal"]
PROC = CONFIG["process"]
STORAGE = CONFIG["storage"]
NOTIFIER = CONFIG["notifier"]

HOST = NET["host"]
PORT = NET["port"]

try:
    from notifier import Notifier
    from preview_renderer import PreviewRenderer
    from storage import SessionStorage
    from supervision import Supervisor, SupervisionConfig
    from vision.pose_detector import DetectionResult, MediaPipePoseDetector

    MODULES_READY = True
except ImportError as exc:
    print(f"[Error] 模块导入失败: {exc}")
    MODULES_READY = False


@dataclass
class SharedFrame:
    frame_id: int | None = None
    source_timestamp: float | None = None
    rgb_frame: np.ndarray | None = None


@dataclass
class RuntimeStats:
    frames_received: int = 0
    frames_inferred: int = 0
    frames_dropped: int = 0
    decode_failures: int = 0
    recv_timeouts: int = 0
    reconnects: int = 0
    total_infer_ms: float = 0.0


@dataclass
class SocketState:
    sock: socket.socket | None = None


_warned_cpu_temp_failure = False


def recv_exact(conn: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = conn.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_frame(conn: socket.socket):
    header = recv_exact(conn, 16)
    frame_id, timestamp, jpeg_len = struct.unpack("!IdI", header)
    jpeg_bytes = recv_exact(conn, jpeg_len)
    jpeg_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    bgr_frame = cv2.imdecode(jpeg_array, cv2.IMREAD_COLOR)
    if bgr_frame is None:
        return None
    return frame_id, timestamp, cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)


def get_cpu_temp() -> float | None:
    global _warned_cpu_temp_failure
    temp_path = "/sys/class/thermal/thermal_zone0/temp"
    try:
        with open(temp_path, "r", encoding="utf-8") as handle:
            return float(handle.read().strip()) / 1000.0
    except Exception as exc:
        if not _warned_cpu_temp_failure:
            print(f"[Thermal] 无法读取 CPU 温度: {exc}")
            _warned_cpu_temp_failure = True
        return None


def connect_camera_server(stop_event: threading.Event) -> socket.socket | None:
    while not stop_event.is_set():
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(NET.get("recv_timeout_s", 0.2))
            sock.connect((HOST, PORT))
            return sock
        except ConnectionRefusedError:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            print("[Inference] 等待摄像头服务器启动...")
            if stop_event.wait(1.0):
                break
        except Exception:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            raise
    return None


def main():
    signal.signal(signal.SIGTERM, sigterm_handler)

    no_preview = "--no-preview" in sys.argv or "-n" in sys.argv

    print("=" * 60)
    print("Kid Supervisor - 推理客户端")
    print(f"Python: {sys.version}")
    print(f"连接: {HOST}:{PORT}")
    print(f"推理帧率目标: {INF['inference_fps']} FPS")
    print(f"显示帧率目标: {INF['display_fps']} FPS")
    print(f"机位模式: {CONFIG['pose']['camera_view']}")
    print(f"预览: {'禁用 (headless)' if no_preview else '启用'}")
    print("=" * 60)

    if not MODULES_READY:
        return 1

    detector = MediaPipePoseDetector(
        model_complexity=INF["model_complexity"],
        min_detection_confidence=INF["min_detection_confidence"],
        min_tracking_confidence=INF["min_tracking_confidence"],
        config=CONFIG,
    )
    supervisor = Supervisor(SupervisionConfig(CONFIG))
    renderer = PreviewRenderer(enabled=not no_preview, config=CONFIG)
    notifier = Notifier(NOTIFIER.get("console_enabled", True), NOTIFIER.get("audio_enabled", False))
    storage = SessionStorage(os.path.join(base_dir, STORAGE["sqlite_path"])) if STORAGE.get("enabled") else None

    stop_event = threading.Event()
    socket_state = SocketState(sock=connect_camera_server(stop_event))
    if socket_state.sock is None:
        return 1
    print("[Inference] 已连接到摄像头服务器")

    shared_frame = SharedFrame()
    frame_lock = threading.Lock()
    sock_lock = threading.Lock()
    stats = RuntimeStats()

    def receiver_loop():
        while not stop_event.is_set():
            try:
                with sock_lock:
                    active_sock = socket_state.sock
                if active_sock is None:
                    if stop_event.wait(0.05):
                        break
                    continue
                payload = recv_frame(active_sock)
                if payload is None:
                    stats.decode_failures += 1
                    continue
                frame_id, frame_ts, frame_rgb = payload
                with frame_lock:
                    if shared_frame.frame_id is not None and frame_id > shared_frame.frame_id + 1:
                        stats.frames_dropped += frame_id - shared_frame.frame_id - 1
                    shared_frame.frame_id = frame_id
                    shared_frame.source_timestamp = frame_ts
                    shared_frame.rgb_frame = frame_rgb
                stats.frames_received += 1
            except socket.timeout:
                stats.recv_timeouts += 1
            except Exception as exc:
                if stop_event.is_set():
                    break
                print(f"[Inference] 摄像头连接异常: {exc}，重连中...")
                stats.reconnects += 1
                try:
                    with sock_lock:
                        if socket_state.sock is not None:
                            socket_state.sock.close()
                            socket_state.sock = None
                except Exception:
                    pass
                new_sock = connect_camera_server(stop_event)
                with sock_lock:
                    socket_state.sock = new_sock

    receiver_thread = threading.Thread(target=receiver_loop, daemon=True)
    receiver_thread.start()

    person_detected = False
    person_counter = 0
    person_gone_counter = 0
    person_maybe_gone_since: float | None = None
    presence_grace_s = supervisor.config.presence_grace_s
    alerts = []
    last_detection = DetectionResult(timestamp=time.time())
    last_inference_time = 0.0
    last_display_time = 0.0
    last_stats_log = time.time()
    last_temp_check = 0.0
    current_temp = None
    is_throttled = False
    inference_interval = 1.0 / INF["inference_fps"]
    display_interval = 1.0 / INF["display_fps"]
    original_model_complexity = INF["model_complexity"]

    print("\n[Ready] 按 Q / ESC 退出\n")

    try:
        while True:
            now = time.time()

            if THERMAL.get("enabled") and now - last_temp_check >= THERMAL["temp_check_interval_s"]:
                current_temp = get_cpu_temp()
                last_temp_check = now
                if current_temp is not None:
                    if current_temp >= THERMAL["temp_throttle_c"] and not is_throttled:
                        print(f"[Thermal] CPU {current_temp:.1f}C >= {THERMAL['temp_throttle_c']}C, 降频中...")
                        is_throttled = True
                        inference_interval = 1.0 / THERMAL["throttle_inference_fps"]
                        detector.set_model_complexity(THERMAL["throttle_model_complexity"])
                    elif current_temp < THERMAL["temp_throttle_c"] - THERMAL.get("throttle_recover_margin_c", 5.0) and is_throttled:
                        print(f"[Thermal] CPU {current_temp:.1f}C, 恢复正常")
                        is_throttled = False
                        inference_interval = 1.0 / INF["inference_fps"]
                        detector.set_model_complexity(original_model_complexity)

            frame_id = None
            frame_ts = None
            frame_rgb = None
            with frame_lock:
                if shared_frame.rgb_frame is not None:
                    frame_id = shared_frame.frame_id
                    frame_ts = shared_frame.source_timestamp
                    frame_rgb = shared_frame.rgb_frame.copy()

            if frame_rgb is not None and now - last_inference_time >= inference_interval:
                infer_start = time.time()
                event_ts = frame_ts if frame_ts is not None else now
                detection_result = detector.detect(frame_rgb, timestamp=event_ts, analyze_face=INF.get("analyze_face", False), frame_is_rgb=True)
                detection_result.frame_id = frame_id
                detection_result.source_timestamp = frame_ts
                infer_ms = (time.time() - infer_start) * 1000.0

                last_detection = detection_result
                last_inference_time = now
                stats.frames_inferred += 1
                stats.total_infer_ms += infer_ms

                if detection_result.success:
                    person_gone_counter = 0
                    if person_maybe_gone_since is not None:
                        person_maybe_gone_since = None
                    person_counter = min(person_counter + 1, supervisor.config.presence_enter_frames)
                    if person_counter >= supervisor.config.presence_enter_frames and not person_detected:
                        person_detected = True
                        notifier.send_info("检测到人脸，学习开始")
                        supervisor.on_person_detected(event_ts)
                else:
                    person_counter = 0
                    if person_detected:
                        if person_maybe_gone_since is None:
                            person_maybe_gone_since = event_ts
                            person_gone_counter = 1
                        else:
                            person_gone_counter = min(person_gone_counter + 1, supervisor.config.presence_exit_frames)
                            grace_exceeded = (event_ts - person_maybe_gone_since) >= presence_grace_s
                            frames_exceeded = person_gone_counter >= supervisor.config.presence_exit_frames
                            if grace_exceeded and frames_exceeded:
                                person_detected = False
                                person_maybe_gone_since = None
                                notifier.send_info("人脸消失")
                                supervisor.on_person_left(event_ts)
                                # 会话结束即时保存
                                if storage and supervisor.session_history:
                                    storage.save_session(supervisor.session_history[-1], supervisor.config.camera_view)
                    else:
                        person_gone_counter = min(person_gone_counter + 1, supervisor.config.presence_exit_frames)

                alerts = []
                if person_detected and detection_result.pose_metrics:
                    posture_alert = supervisor.on_posture_update(detection_result.pose_metrics, event_ts)
                    if posture_alert:
                        alerts.append(posture_alert)
                    face_width_px = detection_result.distance_bbox[2] if detection_result.distance_bbox else None
                    distance_alert = supervisor.on_distance_update(
                        detection_result.estimated_distance_cm,
                        detection_result.distance_confidence,
                        event_ts,
                        face_width_px=face_width_px,
                    )
                    if distance_alert:
                        alerts.append(distance_alert)

                time_alert = supervisor.check_study_time(event_ts)
                if time_alert:
                    alerts.append(time_alert)
                    # 休息开始时会话已结束，即时保存
                    from supervision import AlertType
                    if time_alert.alert_type == AlertType.BREAK_NEEDED and storage and supervisor.session_history:
                        storage.save_session(supervisor.session_history[-1], supervisor.config.camera_view)

                for alert in alerts:
                    notifier.send_alert(alert)

            if now - last_display_time >= display_interval:
                temp_str = f"{current_temp:.1f}C" if current_temp is not None else "N/A"
                avg_ms = stats.total_infer_ms / max(stats.frames_inferred, 1)
                maybe_gone = person_maybe_gone_since is not None
                supervisor_state = {
                    "current_session": supervisor.current_session,
                    "is_resting": supervisor.is_resting,
                    "presence": f"P:{person_detected} maybe:{maybe_gone} in:{person_counter} out:{person_gone_counter}",
                    "runtime": f"infer:{stats.frames_inferred} avg:{avg_ms:.0f}ms drop:{stats.frames_dropped} temp:{temp_str}",
                }
                if no_preview:
                    if now - last_stats_log >= PROC["status_log_interval_s"]:
                        elapsed = max(now - last_stats_log, 1e-6)
                        recv_fps = stats.frames_received / elapsed
                        infer_fps = stats.frames_inferred / elapsed
                        avg_ms = stats.total_infer_ms / max(stats.frames_inferred, 1)
                        temp_str = f"{current_temp:.1f}C" if current_temp is not None else "N/A"
                        print(
                            f"[Stats] recv={recv_fps:.1f}fps infer={infer_fps:.1f}fps infer_ms={avg_ms:.0f} "
                            f"dropped={stats.frames_dropped} decode_fail={stats.decode_failures} reconnects={stats.reconnects} "
                            f"temp={temp_str} throttled={is_throttled}"
                        )
                        stats.frames_received = 0
                        stats.frames_inferred = 0
                        stats.frames_dropped = 0
                        stats.decode_failures = 0
                        stats.recv_timeouts = 0
                        stats.reconnects = 0
                        stats.total_infer_ms = 0.0
                        last_stats_log = now
                elif frame_rgb is not None:
                    display_frame = renderer.render(
                        frame=frame_rgb,
                        detection_result=last_detection,
                        supervisor_state=supervisor_state,
                        alerts=alerts,
                        pose=detector.mp_pose,
                        mp_drawing=detector.mp_drawing,
                    )
                    if not renderer.show(display_frame):
                        stop_event.set()
                        break
                last_display_time = now

            stop_event.wait(0.005)

    except KeyboardInterrupt:
        print("\n\n[Inference] 收到退出信号")
    finally:
        stop_event.set()
        try:
            with sock_lock:
                if socket_state.sock is not None:
                    socket_state.sock.close()
                    socket_state.sock = None
        except Exception:
            pass
        receiver_thread.join(timeout=1.0)
        exit_ts = time.time()
        if person_detected and supervisor.current_session is not None:
            supervisor.on_person_left(exit_ts)
        if storage:
            for session in supervisor.session_history:
                storage.save_session(session, supervisor.config.camera_view)
        try:
            detector.close()
        except Exception:
            pass
        try:
            renderer.close()
        except Exception:
            pass
        print("[Inference] 退出")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
