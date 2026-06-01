#!/usr/bin/env python3
"""
摄像头服务器进程
用系统 Python 3.13 + picamera2
通过 TCP socket 发送 JPEG 帧
"""
import sys
import os
import time
import socket
import struct
import pickle

# 确保使用系统库
sys.path.insert(0, '/usr/lib/python3/dist-packages')

import numpy as np
from picamera2 import Picamera2

# 配置
FRAME_SIZE = (640, 480)
MAX_FPS = 20
HOST = '127.0.0.1'
PORT = 65432

def init_camera():
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

def send_frame(conn, frame):
    """通过 socket 发送帧"""
    try:
        # 序列化为 bytes
        data = pickle.dumps(frame)
        # 先发长度 (4字节)
        conn.sendall(struct.pack('!I', len(data)))
        # 再发数据
        conn.sendall(data)
        return True
    except Exception as e:
        print(f"[Camera] 发送失败: {e}")
        return False

def main():
    print("=" * 60)
    print("📷 Kid Supervisor - 摄像头服务器")
    print(f"Python: {sys.version}")
    print(f"监听: {HOST}:{PORT}")
    print("=" * 60)

    picam2 = init_camera()

    # 创建 socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(1)

    print(f"\n[Camera] 等待推理进程连接...")

    try:
        while True:
            conn, addr = sock.accept()
            print(f"[Camera] 已连接: {addr}")

            try:
                while True:
                    frame = picam2.capture_array()
                    if not send_frame(conn, frame):
                        break
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                print(f"[Camera] 连接断开，等待重连...")
            finally:
                try:
                    conn.close()
                except:
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
