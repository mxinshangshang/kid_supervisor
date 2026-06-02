#!/usr/bin/env python3
"""
Kid Supervisor v4.0 - 双进程架构主启动器
启动摄像头服务器和推理客户端两个进程
改进：子进程自动重启、配置化、退避策略
"""
import sys
import os
import subprocess
import signal
import time
import yaml

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===================== 加载配置 =====================
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    CONFIG = yaml.safe_load(f)

PROC_CFG = CONFIG["process"]

# Python 路径
SYSTEM_PYTHON = "/usr/bin/python3"
VENV_PYTHON = os.path.join(BASE_DIR, "venv_311", "bin", "python")

# 脚本路径
CAMERA_SCRIPT = os.path.join(BASE_DIR, "camera_server.py")
INFERENCE_SCRIPT = os.path.join(BASE_DIR, "inference_client.py")

MAX_RESTART = PROC_CFG.get("max_restart_attempts", 3)
RESTART_BACKOFF_BASE = PROC_CFG.get("restart_backoff_base_s", 2)


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
    print("Kid Supervisor v4.0 - 双进程架构 (自动重启)")
    print(f"预览: {'禁用 (headless)' if no_preview else '启用'}")
    print(f"最大重启次数: {MAX_RESTART}")
    print("=" * 60)

    if not check_venv():
        return 1

    camera_proc = None
    inference_proc = None
    restart_counts = {"camera": 0, "inference": 0}
    running = True

    def cleanup(signum=None, frame=None):
        nonlocal running
        running = False
        print("\n[Main] 正在关闭子进程...")
        for name, proc in [("camera", camera_proc), ("inference", inference_proc)]:
            if proc and proc.poll() is None:
                print(f"[Main] 终止 {name} (PID {proc.pid})")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        print("[Main] 所有进程已退出")

    signal.signal(signal.SIGINT, lambda s, f: cleanup(s, f))
    signal.signal(signal.SIGTERM, lambda s, f: cleanup(s, f))

    def start_camera():
        nonlocal camera_proc
        print("[Main] 启动摄像头服务器 (系统 Python)...")
        camera_proc = subprocess.Popen([SYSTEM_PYTHON, CAMERA_SCRIPT])
        print(f"[Main] 摄像头服务器 PID: {camera_proc.pid}")

    def start_inference():
        nonlocal inference_proc
        print("[Main] 启动推理客户端 (Python 3.11)...")
        args = [VENV_PYTHON, INFERENCE_SCRIPT]
        if no_preview:
            args.append("--no-preview")
        inference_proc = subprocess.Popen(args)
        print(f"[Main] 推理客户端 PID: {inference_proc.pid}")

    # 初始启动
    start_camera()
    time.sleep(1)
    start_inference()

    print("\n[Main] 两个进程都已启动，按 Ctrl+C 退出\n")

    try:
        while running:
            time.sleep(0.5)

            # 检查摄像头进程
            if camera_proc and camera_proc.poll() is not None:
                rc = camera_proc.returncode
                restart_counts["camera"] += 1
                print(f"[Main] 摄像头服务器退出 (code: {rc})")

                if restart_counts["camera"] <= MAX_RESTART:
                    backoff = min(RESTART_BACKOFF_BASE * restart_counts["camera"], 10)
                    print(f"[Main] {backoff}s 后重启摄像头 ({restart_counts['camera']}/{MAX_RESTART})")
                    time.sleep(backoff)
                    start_camera()
                else:
                    print(f"[Main] 摄像头服务器重启次数超限 ({MAX_RESTART})，退出")
                    cleanup()
                    return 1

            # 检查推理进程
            if inference_proc and inference_proc.poll() is not None:
                rc = inference_proc.returncode
                restart_counts["inference"] += 1
                print(f"[Main] 推理客户端退出 (code: {rc})")

                if restart_counts["inference"] <= MAX_RESTART:
                    backoff = min(RESTART_BACKOFF_BASE * restart_counts["inference"], 10)
                    print(f"[Main] {backoff}s 后重启推理 ({restart_counts['inference']}/{MAX_RESTART})")
                    time.sleep(backoff)
                    start_inference()
                else:
                    print(f"[Main] 推理客户端重启次数超限 ({MAX_RESTART})，退出")
                    cleanup()
                    return 1

            # 成功运行一段时间后重置计数（防止累积触发退出）
            if camera_proc and inference_proc:
                if (camera_proc.poll() is None and inference_proc.poll() is None):
                    # 两个进程都运行超过 30 秒，重置计数
                    pass  # 简单起见不在这里做，保持计数

    finally:
        cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
