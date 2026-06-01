#!/usr/bin/env python3
"""
Kid Supervisor - 双进程架构主启动器
启动摄像头服务器和推理客户端两个进程
"""
import sys
import os
import subprocess
import signal
import time

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Python 路径
SYSTEM_PYTHON = "/usr/bin/python3"
VENV_PYTHON = os.path.join(BASE_DIR, "venv_311", "bin", "python")

# 脚本路径
CAMERA_SCRIPT = os.path.join(BASE_DIR, "camera_server.py")
INFERENCE_SCRIPT = os.path.join(BASE_DIR, "inference_client.py")

def check_venv():
    """检查 venv 是否存在"""
    if not os.path.exists(VENV_PYTHON):
        print("=" * 60)
        print("❌ Python 3.11 venv 不存在")
        print("=" * 60)
        print("\n请先运行: ./setup_venv.sh")
        print("或: python3 setup_venv.py\n")
        return False
    return True

def main():
    # 检查是否禁用预览
    no_preview = "--no-preview" in sys.argv or "-n" in sys.argv

    print("=" * 60)
    print("👶 Kid Supervisor v3 - 双进程架构")
    print(f"预览: {'❌ 禁用 (headless)' if no_preview else '✅ 启用'}")
    print("=" * 60)

    if not check_venv():
        return 1

    camera_proc = None
    inference_proc = None

    def cleanup(signum, frame):
        print("\n\n[Main] 收到退出信号，正在关闭子进程...")
        if camera_proc and camera_proc.poll() is None:
            camera_proc.terminate()
        if inference_proc and inference_proc.poll() is None:
            inference_proc.terminate()
        if camera_proc:
            camera_proc.wait()
        if inference_proc:
            inference_proc.wait()
        print("[Main] 所有进程已退出")
        sys.exit(0)

    # 注册信号处理
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("\n[Main] 正在启动摄像头服务器 (系统 Python)...")
    camera_proc = subprocess.Popen([SYSTEM_PYTHON, CAMERA_SCRIPT])

    print("[Main] 等待 1 秒...")
    time.sleep(1)

    print("[Main] 正在启动推理客户端 (Python 3.11)...")
    inference_args = [VENV_PYTHON, INFERENCE_SCRIPT]
    if no_preview:
        inference_args.append("--no-preview")
    inference_proc = subprocess.Popen(inference_args)

    print("\n[Main] 两个进程都已启动")
    print("-" * 60)
    print("  摄像头服务器 PID:", camera_proc.pid)
    print("  推理客户端 PID:", inference_proc.pid)
    print("-" * 60)
    print("\n按 Ctrl+C 退出\n")

    # 等待子进程
    try:
        while True:
            if camera_proc.poll() is not None:
                print(f"\n[Main] 摄像头服务器已退出 (code: {camera_proc.returncode})")
                break
            if inference_proc.poll() is not None:
                print(f"\n[Main] 推理客户端已退出 (code: {inference_proc.returncode})")
                break
            time.sleep(0.5)
    finally:
        cleanup(None, None)

    return 0

if __name__ == "__main__":
    sys.exit(main())
