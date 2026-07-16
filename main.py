#!/usr/bin/env python3
"""
Kid Supervisor v4.0 - 双进程架构主启动器
启动摄像头服务器和推理客户端两个进程
"""
import os
import signal
import subprocess
import sys
import time

from src.config import load_config

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===================== 加载配置 =====================
CONFIG = load_config(BASE_DIR)
PROC_CFG = CONFIG["process"]

# Python 路径
SYSTEM_PYTHON = "/usr/bin/python3"
VENV_PYTHON = os.path.join(BASE_DIR, "venv_311", "bin", "python")

# 脚本路径
CAMERA_SCRIPT = os.path.join(BASE_DIR, "camera_server.py")
INFERENCE_SCRIPT = os.path.join(BASE_DIR, "inference_client.py")

STATUS_LOG_INTERVAL = PROC_CFG.get("status_log_interval_s", 10)


def check_venv():
    """检查 venv 是否存在"""
    if not os.path.exists(VENV_PYTHON):
        print("=" * 60)
        print("Python 3.11 venv 不存在")
        print("=" * 60)
        print("\n请先运行: python3 setup_venv.py\n")
        return False
    return True


def main():
    no_preview = "--no-preview" in sys.argv or "-n" in sys.argv

    print("=" * 60)
    print("Kid Supervisor v4.0 - 双进程架构")
    print(f"预览: {'禁用 (headless)' if no_preview else '启用'}")
    print("退出: 按 q / ESC 或 Ctrl+C")
    print("=" * 60)

    if not check_venv():
        return 1

    camera_proc = None
    inference_proc = None
    camera_started_at = 0.0
    inference_started_at = 0.0
    running = True
    cleanup_done = False
    exit_code = 0
    last_status_log = 0.0

    def cleanup(signum=None, frame=None):
        nonlocal running, cleanup_done
        if cleanup_done:
            return
        cleanup_done = True
        running = False
        print("\n[Main] 正在关闭子进程...")
        for name, proc in [("camera", camera_proc), ("inference", inference_proc)]:
            if proc and proc.poll() is None:
                print(f"[Main] 终止 {name} (PID {proc.pid})")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"[Main] {name} 未及时退出，强制结束")
                    proc.kill()
                    proc.wait()
        print("[Main] 所有进程已退出")

    def start_camera():
        nonlocal camera_started_at
        print("[Main] 启动摄像头服务器 (系统 Python)...")
        proc = subprocess.Popen([SYSTEM_PYTHON, CAMERA_SCRIPT])
        camera_started_at = time.time()
        print(f"[Main] 摄像头服务器 PID: {proc.pid}")
        return proc

    def start_inference():
        nonlocal inference_started_at
        print("[Main] 启动推理客户端 (Python 3.11)...")
        args = [VENV_PYTHON, INFERENCE_SCRIPT]
        if no_preview:
            args.append("--no-preview")
        proc = subprocess.Popen(args)
        inference_started_at = time.time()
        print(f"[Main] 推理客户端 PID: {proc.pid}")
        return proc

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    camera_proc = start_camera()
    time.sleep(1)
    inference_proc = start_inference()

    print("\n[Main] 两个进程都已启动，等待退出\n")

    try:
        while running:
            time.sleep(0.5)
            now = time.time()

            if now - last_status_log >= STATUS_LOG_INTERVAL:
                cam_status = (
                    f"up {int(now - camera_started_at)}s"
                    if camera_proc and camera_proc.poll() is None
                    else f"down rc={camera_proc.returncode if camera_proc else 'N/A'}"
                )
                inf_status = (
                    f"up {int(now - inference_started_at)}s"
                    if inference_proc and inference_proc.poll() is None
                    else f"down rc={inference_proc.returncode if inference_proc else 'N/A'}"
                )
                print(f"[Main Status] camera={cam_status} | inference={inf_status}")
                last_status_log = now

            if camera_proc and camera_proc.poll() is not None:
                exit_code = camera_proc.returncode or 0
                print(f"[Main] 摄像头服务器退出 (code: {exit_code})")
                running = False
                break

            if inference_proc and inference_proc.poll() is not None:
                exit_code = inference_proc.returncode or 0
                print(f"[Main] 推理客户端退出 (code: {exit_code})")
                running = False
                break

    except KeyboardInterrupt:
        cleanup()
    finally:
        cleanup()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
