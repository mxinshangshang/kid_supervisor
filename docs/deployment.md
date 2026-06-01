# 部署与配置指南

## 1. 环境准备

### 1.1 系统要求

- **操作系统**：Raspberry Pi OS (Debian Bookworm 或更高)
- **硬件**：树莓派 5 (推荐 8GB 版本)
- **Python 版本**：
  - 系统 Python：3.13（用于 picamera2）
  - 推理 Python：3.11（用于 mediapipe，通过 venv 管理）

### 1.2 检查摄像头

首先确认摄像头正常工作：

```bash
libcamera-hello
```

如果能看到画面，说明摄像头正常。

### 1.3 安装系统依赖

```bash
# 更新包列表
sudo apt update

# 安装必要的系统依赖（通常已预装）
sudo apt install -y python3-opencv python3-picamera2 python3-numpy

# 检查 Python 版本
python3 --version
```

---

## 2. 安装步骤

### 2.1 克隆或获取项目

```bash
cd /home/mxin/.openclaw/workspace/kid_supervisor_v3
```

### 2.2 设置虚拟环境

运行提供的设置脚本：

```bash
python3 setup_venv.py
```

该脚本会：
1. 检查系统是否有 Python 3.11
2. 创建 `venv_311/` 虚拟环境
3. 安装推理端依赖（mediapipe, opencv-python, numpy）

如果自动设置失败，可以手动设置：

```bash
# 使用 pyenv 安装 Python 3.11（如果需要）
curl https://pyenv.run | bash
# 重新加载终端配置后
pyenv install 3.11.9

# 创建虚拟环境
python3.11 -m venv venv_311

# 安装依赖
venv_311/bin/pip install -r requirements-inference.txt
```

### 2.3 检查安装

```bash
# 检查摄像头端依赖
/usr/bin/python3 -c "import picamera2; print('Picamera2 OK')"

# 检查推理端依赖
venv_311/bin/python -c "import mediapipe; print('MediaPipe OK')"
```

---

## 3. 运行系统

### 3.1 一键启动（推荐）

```bash
./start.sh
```

### 3.2 使用主启动器

```bash
/usr/bin/python3 main.py
```

### 3.3 无头模式（无预览窗口）

适合 SSH 远程运行：

```bash
/usr/bin/python3 main.py --no-preview
```

### 3.4 分别启动（调试用）

终端 1 - 启动摄像头服务器：
```bash
/usr/bin/python3 camera_server.py
```

终端 2 - 启动推理客户端：
```bash
venv_311/bin/python inference_client.py
# 或无头模式
venv_311/bin/python inference_client.py --no-preview
```

---

## 4. 配置说明

### 4.1 修改配置参数

配置参数分散在各个模块中，根据需要修改：

**摄像头配置** (camera_server.py)：
```python
FRAME_SIZE = (640, 480)  # 可以改 (1280, 720) 或更小
MAX_FPS = 20
PORT = 65432
```

**监督配置** (src/supervision.py - SupervisionConfig)：
```python
too_close_threshold_cm = 35.0       # 过近距离阈值
too_close_duration = 3.0            # 过近持续时间
bad_posture_duration = 5.0          # 不良姿态持续时间
max_study_duration = 45 * 60        # 最大学习时长
rest_duration = 10 * 60             # 休息时长
alert_cooldown = 30.0               # 提醒冷却时间
```

**检测器配置** (src/vision/pose_detector.py)：
```python
model_complexity = 1                # 0=轻量, 1=平衡, 2=准确
min_detection_confidence = 0.5
min_tracking_confidence = 0.5
face_real_width_cm = 15.0           # 实际人脸宽度
camera_focal_length = 600.0         # 焦距（可校准）
```

### 4.2 距离校准

如需更精确的距离估算：

1. 修改 `src/vision/pose_detector.py` 中的 `camera_focal_length`
2. 参考 [technical-details.md](technical-details.md) 中的校准方法

---

## 5. 故障排除

### 5.1 常见问题

**问题 1：虚拟环境创建失败**

```
错误：Python 3.11 not found
```

解决：
```bash
# 安装 pyenv
curl https://pyenv.run | bash

# 按照提示更新 shell 配置，然后
pyenv install 3.11.9
pyenv global 3.11.9

# 重新运行 setup
python3 setup_venv.py
```

**问题 2：摄像头无法启动**

```
错误：Picamera2 初始化失败
```

解决：
```bash
# 检查摄像头是否被其他程序占用
lsof /dev/video0

# 检查 libcamera 是否工作
libcamera-hello

# 确认使用系统 Python，而不是 venv
/usr/bin/python3 --version
```

**问题 3：端口被占用**

```
错误：Address already in use
```

解决：
```bash
# 查找占用端口的进程
lsof -i :65432

# 杀掉进程
kill -9 <PID>

# 或修改代码中的 PORT 常量
```

**问题 4：预览窗口无法显示**

如果是 SSH 连接：
```bash
# 使用 X11 转发
ssh -X pi@<树莓派IP>

# 或使用无头模式
/usr/bin/python3 main.py --no-preview
```

**问题 5：帧率过低**

解决：
```python
# 在 camera_server.py 中降低分辨率
FRAME_SIZE = (480, 360)  # 更小的分辨率

# 在 inference_client.py / pose_detector.py 中降低模型复杂度
model_complexity = 0  # 轻量模型
```

### 5.2 日志与调试

两个进程都会输出日志到 stdout：

```
[Main] 正在启动摄像头服务器...
[Camera] 启动中 (picamera2)...
[Camera] 启动成功
[Camera] 等待推理进程连接...
[Inference] 正在连接摄像头服务器...
[Camera] 已连接: ('127.0.0.1', ...)
[Vision] MediaPipe Pose 初始化成功
[Supervisor] 监督逻辑初始化成功
[Ready] 按 Q / ESC to exit
```

---

## 6. 开机自启动（可选）

### 6.1 使用 systemd 服务

创建服务文件 `/etc/systemd/system/kid-supervisor.service`：

```ini
[Unit]
Description=Kid Supervisor Service
After=multi-user.target

[Service]
Type=simple
User=mxin
WorkingDirectory=/home/mxin/.openclaw/workspace/kid_supervisor_v3
ExecStart=/usr/bin/python3 main.py --no-preview
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable kid-supervisor.service
sudo systemctl start kid-supervisor.service

# 查看状态
sudo systemctl status kid-supervisor.service

# 查看日志
sudo journalctl -u kid-supervisor.service -f
```

---

## 7. 性能调优建议

### 7.1 树莓派 5 配置

在 `/boot/firmware/config.txt` 中可以调整（谨慎操作）：

```ini
# 超频（可选，注意散热）
arm_freq=2800
gpu_freq=800

# 分配更多 GPU 内存（如果需要）
gpu_mem=256
```

### 7.2 性能监控

```bash
# 查看 CPU 使用率
htop

# 查看内存使用
free -h

# 查看温度
vcgencmd measure_temp
```

---

*文档版本：v1.0*  
*最后更新：2026-06-01*
