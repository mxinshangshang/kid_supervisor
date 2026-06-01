#!/bin/bash
set -e

# Kid Supervisor v3 树莓派环境安装脚本
# 使用预编译Python3.12，不修改系统配置

echo "================================="
echo "Kid Supervisor v3 环境安装"
echo "================================="

# 1. 解压预编译Python3.12
echo "[1/4] 解压Python3.12预编译包..."
if [ ! -d "./python3.12" ]; then
    tar -xf cpython-3.12.5+20240814-aarch64-unknown-linux-gnu-install_only.tar.gz
    mv python ./python3.12
fi

# 2. 创建虚拟环境
echo "[2/4] 创建Python3.12虚拟环境..."
if [ ! -d "./venv" ]; then
    ./python3.12/bin/python3 -m venv ./venv
fi

# 3. 激活虚拟环境，升级工具
echo "[3/4] 升级pip和工具..."
source ./venv/bin/activate
pip install --upgrade pip wheel setuptools

# 4. 安装依赖，优先用arm64预编译包
echo "[4/4] 安装项目依赖..."
pip install --prefer-binary -r requirements.txt

# 验证安装
echo ""
echo "================================="
echo "安装完成，验证："
echo "================================="
python --version
python -c "import cv2; print('OpenCV版本:', cv2.__version__)"
python -c "import mediapipe as mp; print('MediaPipe版本:', mp.__version__)"
echo ""
echo "使用方法："
echo "  激活环境：source ./venv/bin/activate"
echo "  启动程序：python main.py"
echo ""
# 写启动脚本
cat > ./start.sh << 'EOF'
#!/bin/bash
source ./venv/bin/activate
python main.py
EOF
chmod +x ./start.sh
echo "已生成一键启动脚本：./start.sh"
