#!/bin/bash
# 用系统 Python 3.13 运行
cd "$(dirname "$0")"

echo "========================================"
echo "Kid Supervisor - 系统 Python 3.13"
echo "========================================"

# 检查 mediapipe 是否已安装
/usr/bin/python3 -c "import mediapipe" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "正在安装依赖..."
    /usr/bin/python3 -m pip install --user --break-system-packages mediapipe opencv-python numpy
fi

echo "启动..."
exec /usr/bin/python3 main_simple.py
