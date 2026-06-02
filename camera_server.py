#!/usr/bin/env python3
"""
摄像头服务器进程
用系统 Python 3.13 + picamera2
通过 TCP socket 发送 JPEG 编码帧（带 timestamp 和 frame_id）
"""
import sys
import os
import time
import socket
import struct
import yaml
import cv2
import numpy as np
from picamera2 import Picamera2

# 确保使用系统库
sys.path.insert(0, '/usr/lib/python3/dist-packages')

# ===================== 加载配置 =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    CONFIG = yaml.safe_load(f)

CAM = CONFIG["camera"]
NET = CONFIG["network"]

FRAME_SIZE = (CAM["width"], CAM["height"])
MAX_FPS = CAM["fps"]
JPEG_QUALITY = CAM["jpeg_quality"]
HOST = NET["host"]
PORT = NET["port"]


def init_camera():
    print("[Camera] 启动中 (picamera2)...")
    picam2 = Picamera2()

    print("[Camera] 可用的传感器模式:")
    try:
        for i, mode in enumerate(picam2.sensor_modes):
            print(f"  [{i}] {mode}")
    except Exception:
        print("  无法获取传感器模式列表")

    preview_config = picam2.create_preview_configuration(
        main={"format": CAM.get("format", "RGB888"), "size": FRAME_SIZE},
        controls={"FrameRate": MAX_FPS}
    )
    picam2.configure(preview_config)
    picam2.start()
    time.sleep(1)

    print(f"[Camera] 启动成功")
    print(f"[Camera] 当前配置: {picam2.camera_configuration()}")
    return picam2


def send_frame(conn, frame_id, timestamp, frame):
    """通过 socket 发送 JPEG 编码帧 + 元数据

    协议: [4B frame_id][8B timestamp][4B jpeg_len][jpeg_data]
    """
    try:
        # picamera2 输出 RGB，cv2.imencode 需要 BGR，所以转换一下
        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _, jpeg_data = cv2.imencode('.jpg', bgr_frame,
                                    [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        jpeg_bytes = jpeg_data.tobytes()

        # 先发元数据: frame_id(4B) + timestamp(8B double) + jpeg_len(4B)
        header = struct.pack('!IdI', frame_id, timestamp, len(jpeg_bytes))
        conn.sendall(header)
        # 再发 JPEG 数据
        conn.sendall(jpeg_bytes)
        return True
    except (BrokenPipeError, ConnectionResetError):
        # 连接断开是正常的，不用每次都打印
        return False
    except Exception as e:
        print(f"[Camera] 发送失败: {e}")
        return False


def main():
    print("=" * 60)
    print("Kid Supervisor - 摄像头服务器")
    print(f"Python: {sys.version}")
    print(f"监听: {HOST}:{PORT}")
    print(f"帧大小: {FRAME_SIZE[0]}x{FRAME_SIZE[1]} @ {MAX_FPS}FPS")
    print(f"JPEG 质量: {JPEG_QUALITY}")
    print("=" * 60)

    picam2 = init_camera()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(NET.get("send_timeout_s", 30))
    sock.bind((HOST, PORT))
    sock.listen(1)

    print(f"\n[Camera] 等待推理进程连接...")

    # 性能统计
    frame_id = 0
    stats_start = time.time()
    stats_frame_count = 0
    stats_bytes_sent = 0

    try:
        while True:
            conn, addr = sock.accept()
            print(f"[Camera] 已连接: {addr}")

            try:
                last_frame_time = time.time()
                while True:
                    frame = picam2.capture_array()
                    now = time.time()

                    if send_frame(conn, frame_id, now, frame):
                        frame_id += 1
                        stats_frame_count += 1
                        # 粗略估算发送字节 (header 16B + jpeg)
                        stats_bytes_sent += 16 + 10000  # 估算

                    # 帧间隔控制 - 更精确，避免睡过头
                    target_interval = 1.0 / MAX_FPS
                    elapsed_since_last = now - last_frame_time
                    if elapsed_since_last < target_interval:
                        time.sleep(target_interval - elapsed_since_last)
                    last_frame_time = now

                    # 每 10 秒输出一次统计
                    elapsed = now - stats_start
                    if elapsed >= 10.0:
                        fps = stats_frame_count / elapsed
                        print(f"[Camera Stats] fps={fps:.1f}  frames={stats_frame_count}  "
                              f"avg_bytes/frame~={stats_bytes_sent // max(stats_frame_count, 1)}")
                        stats_start = now
                        stats_frame_count = 0
                        stats_bytes_sent = 0

            except (BrokenPipeError, ConnectionResetError):
                print(f"[Camera] 连接断开，等待重连...")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    except KeyboardInterrupt:
        print("\n\n[Camera] 收到退出信号")
    finally:
        print("[Camera] 清理中...")
        try:
            picam2.stop()
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        print("[Camera] 退出")


if __name__ == "__main__":
    main()
