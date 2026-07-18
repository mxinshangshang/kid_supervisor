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
import signal
import cv2
import numpy as np
from picamera2 import Picamera2
from src.config import load_config


def sigterm_handler(signum, frame):
    """处理SIGTERM信号，复用KeyboardInterrupt路径"""
    raise KeyboardInterrupt()

# 确保使用系统库
sys.path.insert(0, '/usr/lib/python3/dist-packages')

# ===================== 加载配置 =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = load_config(BASE_DIR)

CAM = CONFIG["camera"]
NET = CONFIG["network"]

FRAME_SIZE = (CAM["width"], CAM["height"])
MAX_FPS = CAM["fps"]
JPEG_QUALITY = CAM["jpeg_quality"]
HOST = NET["host"]
PORT = NET["port"]
CAMERA_NUM = CAM.get("camera_num", 0)
HFLIP = CAM.get("hflip", False)
VFLIP = CAM.get("vflip", False)


def init_camera():
    print(f"[Camera] 启动中 (picamera2)... 摄像头编号: {CAMERA_NUM}")
    picam2 = Picamera2(camera_num=CAMERA_NUM)

    from libcamera import Transform
    transform = Transform(hflip=HFLIP, vflip=VFLIP)

    preview_config = picam2.create_preview_configuration(
        main={"format": CAM.get("format", "RGB888"), "size": FRAME_SIZE},
        controls={"FrameRate": MAX_FPS},
        transform=transform,
    )
    picam2.configure(preview_config)
    picam2.start()
    time.sleep(1)

    print(f"[Camera] 启动成功")
    print(f"[Camera] 翻转设置: hflip={HFLIP}, vflip={VFLIP}")
    print(f"[Camera] 当前配置: {picam2.camera_configuration()}")
    return picam2


def send_frame(conn, frame_id, timestamp, frame):
    """通过 socket 发送 JPEG 编码帧 + 元数据

    协议: [4B frame_id][8B timestamp][4B jpeg_len][jpeg_data]
    """
    try:
        # picamera2 输出 RGB，cv2.imencode 需要 BGR，所以转换一下
        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ok, jpeg_data = cv2.imencode('.jpg', bgr_frame,
                                     [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            return False, 0
        jpeg_bytes = jpeg_data.tobytes()

        # 先发元数据: frame_id(4B) + timestamp(8B double) + jpeg_len(4B)
        header = struct.pack('!IdI', frame_id, timestamp, len(jpeg_bytes))
        conn.sendall(header)
        conn.sendall(jpeg_bytes)
        return True, len(header) + len(jpeg_bytes)
    except (BrokenPipeError, ConnectionResetError, socket.timeout):
        return False, 0
    except Exception as e:
        print(f"[Camera] 发送失败: {e}")
        return False, 0


def main():
    signal.signal(signal.SIGTERM, sigterm_handler)

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
    sock.bind((HOST, PORT))
    sock.listen(1)

    print(f"\n[Camera] 等待推理进程连接...")
    print("[Camera] 当前为单客户端模式，后连接者需等待前一个连接释放")

    # 性能统计
    frame_id = 0
    stats_start = time.time()
    stats_frame_count = 0
    stats_bytes_sent = 0

    try:
        while True:
            conn, addr = sock.accept()
            conn.settimeout(NET.get("send_timeout_s", 5))
            print(f"[Camera] 已连接: {addr}")
            conn_stats_start = time.time()
            conn_frame_count = 0
            conn_bytes_sent = 0
            stats_start = conn_stats_start
            stats_frame_count = 0
            stats_bytes_sent = 0

            try:
                last_frame_time = time.time()
                while True:
                    frame = picam2.capture_array()
                    now = time.time()

                    sent_ok, bytes_sent = send_frame(conn, frame_id, now, frame)
                    if sent_ok:
                        frame_id += 1
                        stats_frame_count += 1
                        stats_bytes_sent += bytes_sent
                        conn_frame_count += 1
                        conn_bytes_sent += bytes_sent
                    else:
                        break

                    # 帧间隔控制 - 更精确，避免睡过头
                    target_interval = 1.0 / MAX_FPS
                    elapsed_since_last = now - last_frame_time
                    if elapsed_since_last < target_interval:
                        time.sleep(target_interval - elapsed_since_last)
                    last_frame_time = now

                    elapsed = now - stats_start
                    if elapsed >= 10.0:
                        fps = stats_frame_count / elapsed
                        print(f"[Camera Stats] fps={fps:.1f} frames={stats_frame_count} "
                              f"avg_bytes/frame~={stats_bytes_sent // max(stats_frame_count, 1)}")
                        stats_start = now
                        stats_frame_count = 0
                        stats_bytes_sent = 0

            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                print(f"[Camera] 连接断开，等待重连...")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
                if conn_frame_count > 0:
                    duration = max(time.time() - conn_stats_start, 1e-6)
                    print(
                        f"[Camera] 本次连接发送 {conn_frame_count} 帧，"
                        f"平均 {conn_frame_count / duration:.1f} fps，"
                        f"平均字节数 {conn_bytes_sent // conn_frame_count}"
                    )

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
