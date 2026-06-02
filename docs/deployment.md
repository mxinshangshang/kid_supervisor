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
sudo apt install -y python3-opencv python3-picamera2 python3-numpy python3-yaml

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
3. 安装推理端依赖（mediapipe, opencv-python, numpy, pyyaml）

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
/usr/bin/python3 -c "import picamera2; import yaml; print('Camera dependencies OK')"

# 检查推理端依赖
venv_311/bin/python -c "import mediapipe; import yaml; print('Inference dependencies OK')"
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

## 4. 配置说明 (v4.0 更新)

### 4.1 config.yaml 配置文件

v4.0 使用统一的配置文件 `config.yaml`，所有参数集中管理，无需修改代码：

```bash
# 编辑配置文件
nano config.yaml
```

配置文件结构见 [architecture.md](architecture.md)，或直接查看文件内注释。

### 4.2 常用配置调整

#### 降低/提高摄像头分辨率和帧率

```yaml
camera:
  width: 480       # 从 640 改小，降低 CPU/带宽
  height: 360      # 从 480 改小
  fps: 15          # 从 20 改小
  jpeg_quality: 70 # 从 80 改小，降低带宽
```

#### 调整姿态提醒灵敏度

```yaml
pose:
  shoulder_diff_threshold: 0.10  # 肩膀不平阈值，改大=不容易提醒
  head_down_threshold: 0.08      # 低头阈值，改大=不容易提醒
  lean_forward_threshold: 0.30   # 前倾阈值，改大=不容易提醒
  posture_alert_threshold: 70    # 评分阈值，改大=不容易提醒

supervision:
  bad_posture_duration_s: 10.0   # 持续时间，改大=不容易提醒
```

#### 调整距离提醒阈值

```yaml
distance:
  face_real_width_cm: 15.0       # 人脸实际宽度（小孩可能是 13-14）
  camera_focal_length: 800.0     # 焦距（需校准）
  edge_reject_ratio: 0.4         # 边缘拒绝比例

supervision:
  too_close_threshold_cm: 35.0   # 过近距离阈值，改大=更容易提醒
```

#### 禁用/调整温控降频

```yaml
thermal:
  enabled: true                  # 改为 false 禁用温控
  temp_warn_c: 70.0              # 警告阈值
  temp_throttle_c: 80.0          # 降频阈值
```

#### 调整子进程重启策略

```yaml
process:
  max_restart_attempts: 5        # 最多重启 5 次（默认 3）
  restart_backoff_base_s: 3      # 退避基数 3 秒（默认 2）
```

### 4.3 距离校准

如需更精确的距离估算：

1. 运行程序，让人站在已知距离 `D_known` 处（建议 50cm / 100cm）
2. 确保人脸在画面中心区域（距离显示无 `[?]` 标记）
3. 记录人脸像素宽度 `P_measured`（可在代码中添加日志输出）
4. 计算焦距：`f = (P_measured × D_known) / W`，其中 W=15cm
5. 更新 `config.yaml` 中的 `distance.camera_focal_length`

详细校准方法见 [technical-details.md](technical-details.md)。

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

# 或修改 config.yaml 中的 network.port
```

**问题 4：预览窗口无法显示 / 颜色异常**

如果是 SSH 连接：
```bash
# 使用 X11 转发
ssh -X pi@<树莓派IP>

# 或使用无头模式
/usr/bin/python3 main.py --no-preview
```

颜色异常：v4.0 已修复，如果仍有问题请确认代码是最新版本。

**问题 5：帧率过低**

解决：
```yaml
# 在 config.yaml 中调整
camera:
  width: 480
  height: 360
  fps: 15
  jpeg_quality: 70

inference:
  model_complexity: 0  # 使用轻量模型
  inference_fps: 8
```

**问题 6：pyyaml 安装失败**

```
错误：ERROR: Could not build wheels for pyyaml
```

解决：
```bash
# 先安装系统包
sudo apt install -y python3-yaml

# 或者使用清华源（如果网络问题）
pip install pyyaml -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120

# 或者直接从系统复制到 venv
cp -r /usr/lib/python3/dist-packages/yaml* venv_311/lib/python3.11/site-packages/
```

**问题 7：子进程频繁重启**

检查：
1. 是否有代码错误导致进程崩溃
2. 查看日志输出
3. 调整 `config.yaml` 中的 `process.max_restart_attempts` 放宽限制

**问题 8：姿态/距离误报太多**

调整：
```yaml
# 提高提醒阈值
supervision:
  posture_alert_threshold: 70
  bad_posture_duration_s: 10.0
  too_close_duration_s: 8.0
  alert_cooldown_s: 60.0

# 降低姿态问题评分权重
pose:
  shoulder_diff_threshold: 0.10
  head_down_threshold: 0.09
```

---

### 5.2 日志与调试 (v4.0 更新)

两个进程都会输出日志到 stdout：

```
============================================================
Kid Supervisor v4.0 - Dual process architecture
预览: 启用
最大重启次数: 3
============================================================
[Main] 启动摄像头服务器 (系统 Python)...
[Main] 摄像头服务器 PID: 12345
[Main] 启动推理客户端 (Python 3.11)...
[Main] 推理客户端 PID: 12346
[Main] 两个进程都已启动，按 Ctrl+C 退出

============================================================
摄像头服务器
============================================================
[Camera] 启动中 (picamera2)...
[Camera] 可用的传感器模式: [...]
[Camera] 启动成功
[Camera] 当前配置: {...}
[Camera] 等待推理进程连接...
[Camera] 已连接: ('127.0.0.1', ...)
[Camera Stats] fps=18.6 frames=186 avg_bytes/frame~=10016

============================================================
推理客户端 v4.0
============================================================
[Inference] 正在连接摄像头服务器...
[Inference] 已连接到摄像头服务器
[Vision] MediaPipe Pose 初始化成功
[Supervisor] 监督逻辑初始化成功
[Renderer] 预览渲染器初始化: 启用
[Ready] 按 Q / ESC 退出

[Info] 检测到人脸，学习开始
[Alert] Too Close: 28 cm
[Stats] recv=18.5fps infer=9.8fps latency=42ms dropped=3 temp=62.1'C throttled=False
```

**日志级别说明**：
- `[Camera]` / `[Inference]` / `[Main]`：进程标识
- `[Info]`：状态变化
- `[Alert]`：提醒事件
- `[Stats]`：性能统计（每 10 秒）
- `[Thermal]`：温控相关（如果启用）

---

## 6. 开机自启动（可选）

### 6.1 使用 systemd 服务 (v4.0 更新)

创建服务文件 `/etc/systemd/system/kid-supervisor.service`：

```ini
[Unit]
Description=Kid Supervisor Service
After=multi-user.target network.target

[Service]
Type=simple
User=mxin
WorkingDirectory=/home/mxin/.openclaw/workspace/kid_supervisor_v3
ExecStart=/usr/bin/python3 main.py --no-preview
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kid-supervisor

# 可选：资源限制
Nice=-5
IOSchedulingClass=best-effort
IOSchedulingPriority=4

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

# 停止/禁用服务
sudo systemctl stop kid-supervisor.service
sudo systemctl disable kid-supervisor.service
```

注意：v4.0 main.py 已有子进程自动重启机制，systemd 的 `Restart=always` 作为最后防线。

---

## 7. 性能调优建议 (v4.0 更新)

### 7.1 树莓派 5 配置

在 `/boot/firmware/config.txt` 中可以调整（谨慎操作）：

```ini
# 超频（可选，注意散热）
arm_freq=2800
gpu_freq=800

# 分配更多 GPU 内存（如果需要）
gpu_mem=256

# 主动散热风扇控制
dtoverlay=gpio-fan,temp=60000,gpiopin=14,hyst=5000
```

### 7.2 应用层调优

根据使用场景调整 `config.yaml`：

**平衡模式（默认）**：
```yaml
camera:
  width: 640
  height: 480
  fps: 20
  jpeg_quality: 80
inference:
  model_complexity: 1
  inference_fps: 10
thermal:
  enabled: true
  temp_throttle_c: 75
```

**高性能模式**：
```yaml
camera:
  width: 800
  height: 600
  fps: 25
  jpeg_quality: 90
inference:
  model_complexity: 2
  inference_fps: 15
thermal:
  enabled: true
  temp_throttle_c: 80
```

**低功耗模式**：
```yaml
camera:
  width: 480
  height: 360
  fps: 15
  jpeg_quality: 60
inference:
  model_complexity: 0
  inference_fps: 8
thermal:
  enabled: true
  temp_throttle_c: 70
```

### 7.3 性能监控

```bash
# 查看 CPU 使用率
htop

# 查看内存使用
free -h

# 查看温度
vcgencmd measure_temp

# 查看系统日志
journalctl -f
```

### 7.4 v4.0 性能参考值（树莓派 5）

| 指标 | 平衡模式 | 低功耗模式 | 高性能模式 |
|------|---------|----------|---------|
| 摄像头端 CPU | ~15% | ~10% | ~20% |
| 推理端 CPU | ~40-50% | ~25-35% | ~60-70% |
| 总 CPU | ~55-65% | ~35-45% | ~80-90% |
| 内存占用 | ~200MB | ~150MB | ~280MB |
| 推理帧率 | ~10FPS | ~15FPS | ~7FPS |
| 典型温度 | ~55-65°C | ~50-58°C | ~65-75°C |

---

## 8. 版本升级 (v3 → v4)

### 8.1 升级步骤

1. 备份旧配置（如果修改过代码）
2. 拉取/复制新版本
3. 检查新依赖 `pyyaml` 是否已安装
4. 根据需要调整 `config.yaml`
5. 测试运行

### 8.2 注意事项

- v4.0 不再支持代码中硬编码配置，全部迁移到 `config.yaml`
- 如有自定义修改，请参考 git diff 迁移
- 子进程重启机制已内置到 main.py，无需额外配置

---

## 9. 附录

### 9.1 文件结构说明

```
kid_supervisor_v3/
├── main.py                    # 主启动器 (v4.0)
├── camera_server.py           # 摄像头服务器 (v4.0)
├── inference_client.py        # 推理客户端 (v4.0)
├── config.yaml                # 统一配置文件 (v4.0 新增)
├── requirements-camera.txt    # 摄像头端依赖
├── requirements-inference.txt # 推理端依赖
├── requirements.txt           # 完整依赖列表
├── start.sh                   # 一键启动脚本
├── start_headless.sh          # 无头模式启动脚本
├── src/
│   ├── vision/
│   │   └── pose_detector.py   # 姿态检测器 (v4.0)
│   ├── supervision.py         # 监督逻辑 (v4.0)
│   └── preview_renderer.py    # 预览渲染器 (v4.0)
├── docs/                      # 文档目录
│   ├── requirements.md
│   ├── architecture.md
│   ├── technical-details.md
│   ├── deployment.md          # 本文件
│   └── debug-log.md
└── venv_311/                  # Python 3.11 虚拟环境
```

### 9.2 进程架构总结

```
main.py (主启动器)
    ├─→ camera_server.py (系统 Python 3.13)
    │   └─→ picamera2 采集 → JPEG 压缩 → Socket 发送
    │
    └─→ inference_client.py (Python 3.11 venv)
        └─→ Socket 接收 → JPEG 解码 → MediaPipe 推理 → 监督逻辑 → 预览显示

两个子进程独立管理，任一崩溃会自动重启（带退避策略）
```

---

*文档版本：v4.0*  
*最后更新：2026-06-02*
