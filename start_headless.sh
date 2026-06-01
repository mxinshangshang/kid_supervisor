#!/bin/bash
# Kid Supervisor - 无预览模式启动脚本
cd "$(dirname "$0")"

echo "👶 Kid Supervisor v3 - 无预览模式 (Headless)"
echo "================================================"

# 检查 venv 是否存在
if [ ! -f "venv_311/bin/python" ]; then
    echo ""
    echo "🔧 首次运行，正在设置 Python 3.11 venv..."
    python3 setup_venv.py
    if [ $? -ne 0 ]; then
        echo ""
        echo "❌ 环境设置失败，请检查上面的错误信息"
        exit 1
    fi
fi

echo ""
echo "🚀 启动双进程 (无预览模式)..."
echo "  - 摄像头服务器: 系统 Python 3.13 + picamera2"
echo "  - 推理客户端:   Python 3.11 + mediapipe"
echo ""
echo "ℹ️  提醒信息将打印到控制台"
echo "按 Ctrl+C 退出"
echo ""

exec /usr/bin/python3 main.py --no-preview
