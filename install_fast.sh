#!/bin/bash
set -e

# Kid Supervisor v3 快速安装脚本
# 用系统Python3（3.13，兼容mediapipe），不修改系统配置

echo "================================="
echo "Kid Supervisor v3 快速安装"
echo "================================="

# 1. 安装系统依赖（只安装必要的，不修改Python）
echo "[1/4] 安装系统依赖..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev libopencv-dev

# 2. 创建虚拟环境
echo "[2/4] 创建虚拟环境..."
if [ ! -d "./venv" ]; then
    python3 -m venv ./venv --system-site-packages
fi

# 3. 升级工具
echo "[3/4] 升级pip..."
source ./venv/bin/activate
pip install --upgrade pip wheel setuptools

# 4. 安装项目依赖，优先用预编译包
echo "[4/4] 安装依赖..."
pip install --prefer-binary -r requirements.txt

# 验证
echo ""
echo "================================="
echo "安装完成！"
echo "================================="
python --version
python -c "import cv2; print('OpenCV版本:', cv2.__version__)"
python -c "import mediapipe as mp; print('MediaPipe版本:', mp.__version__)"
echo ""
# 生成启动脚本
cat > ./start.sh << 'EOF'
#!/bin/bash
source ./venv/bin/activate
python main.py
EOF
chmod +x ./start.sh
echo "一键启动：./start.sh"
