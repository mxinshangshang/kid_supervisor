# Kid Supervisor v3 - 儿童学习监督系统

基于树莓派 5 的智能学习监督系统，通过机器视觉实现人脸检测、姿态估计、距离测量和学习时长统计。

---

## 目录

- [项目概述](#项目概述)
- [功能特性](#功能特性)
- [硬件配置](#硬件配置)
- [快速开始](#快速开始)
- [距离校准](#距离校准)
- [文档索引](#文档索引)
- [更新日志](#更新日志)

---

## 项目概述

Kid Supervisor v3 是一个专为儿童学习场景设计的智能监督系统。使用树莓派 5 + Camera Module 3 作为硬件平台，通过 MediaPipe 机器视觉技术实现实时的人脸检测、姿态分析和距离测量。

### 设计目标

1. **非侵入式监督**：纯视觉方案，无需佩戴设备
2. **本地处理**：所有计算在树莓派本地完成，保护隐私
3. **实时反馈**：实时检测并提醒不良学习姿势和过近距离
4. **学习时长管理**：自动记录学习时长，提醒休息

---

## 功能特性

### 已实现功能

| 功能 | 说明 |
|------|------|
| 人脸检测 | 检测是否有人在屏幕前 |
| 姿态估计 | MediaPipe Pose 检测 33 个人体关键点 |
| 姿态分析 | 检测低头/驼背、肩膀不平、身体前倾等问题 |
| 距离估算 | 基于人脸大小估算观看距离（支持平滑滤波） |
| 学习计时 | 自动记录学习会话时长 |
| 智能提醒 | 不良姿态/过近距离/学习超时提醒 |
| 防抖机制 | 存在检测 2 帧确认，离开检测 3 帧确认 |
| 双进程架构 | 摄像头采集与推理分离，解决 Python 版本冲突 |
| **正面/侧身检测** | 支持不同机位角度的姿态判断 |
| **距离校准工具** | 支持自定义摄像头参数校准 |

### 技术亮点

- **双进程架构**：解决 picamera2 (Python 3.13) 与 mediapipe (Python 3.11) 的版本冲突
- **MediaPipe 优化**：树莓派 5 NEON 指令集优化，model_complexity=1 可达良好性能
- **TCP Socket 通信**：轻量级进程间通信，低延迟帧传输
- **鲁棒姿态检测**：可见性检查 + 宽松阈值，减少误报

---

## 硬件配置

| 组件 | 型号/规格 | 说明 |
|------|-----------|------|
| 主板 | 树莓派 5 8GB | 推荐 8GB 版本以流畅运行 MediaPipe |
| 摄像头 | Camera Module 3 Wide | 广角摄像头，适合近距离场景 |
| 存储 | MicroSD / SSD | 推荐 SSD 以获得更好的性能 |
| 电源 | 5V 5A USB-C | 树莓派 5 官方电源 |

---

## 快速开始

### 1. 环境准备

```bash
# 克隆或进入项目目录
cd /home/mxin/.openclaw/workspace/kid_supervisor_v3

# 设置 Python 3.11 虚拟环境
python3 setup_venv.py
```

### 2. 启动系统

```bash
# 一键启动（推荐，带预览窗口）
./start.sh

# 或使用 Python 直接启动
/usr/bin/python3 main.py

# 无头模式（无预览窗口，正式运行推荐）
./start_headless.sh
# 或
/usr/bin/python3 main.py --no-preview
```

### 3. 操作说明

| 按键 | 功能 |
|------|------|
| `q` / `ESC` | 退出程序 |

---

## 距离校准

如果距离读数不准确，可以使用距离校准工具：

```bash
cd /home/mxin/.openclaw/workspace/kid_supervisor_v3
./calibrate_distance.py
```

步骤：
1. 运行校准工具
2. 站在离摄像头已知距离处（如 50cm）
3. 按 `c` 键开始校准
4. 输入真实距离值
5. 将显示的焦距值更新到 `src/vision/pose_detector.py` 中的 `self.camera_focal_length`

---

## 文档索引

详细文档请查看 `docs/` 目录：

| 文档 | 说明 |
|------|------|
| [docs/requirements.md](docs/requirements.md) | 需求规格说明 |
| [docs/architecture.md](docs/architecture.md) | 架构设计文档 |
| [docs/technical-details.md](docs/technical-details.md) | 技术实现细节 |
| [docs/deployment.md](docs/deployment.md) | 部署与配置指南 |
| [docs/debug-log.md](docs/debug-log.md) | 开发调试记录 |

---

## 项目结构

```
kid_supervisor_v3/
├── main.py                    # 主启动器
├── camera_server.py           # 摄像头服务器 (系统 Python 3.13)
├── inference_client.py        # 推理客户端 (Python 3.11 venv)
├── setup_venv.py              # 虚拟环境设置脚本
├── start.sh                   # 一键启动脚本（带预览）
├── start_headless.sh          # 无头模式启动脚本（正式运行）
├── calibrate_distance.py      # 距离校准工具
├── requirements-camera.txt    # 摄像头端依赖
├── requirements-inference.txt # 推理端依赖
├── src/
│   ├── vision/
│   │   └── pose_detector.py   # MediaPipe 姿态检测器
│   ├── supervision.py         # 监督逻辑模块
│   ├── preview_renderer.py    # 预览渲染器
│   ├── camera.py              # 摄像头模块（旧版）
│   ├── simple_detector.py     # 简单检测器（旧版）
│   ├── notifier.py            # 通知模块（预留）
│   └── audio/                 # 音频模块（预留）
├── docs/                      # 文档目录
├── archive/                   # 归档文件
└── venv_311/                  # Python 3.11 虚拟环境
```

---

## 更新日志

### v3.1 (2026-06-02)
- **修复**：OpenCV 显示中文时出现问号的问题，改为英文提示
- **改进**：姿态检测更宽松、更鲁棒：
  - 支持正面/侧身机位检测
  - 增加关键点可见性检查
  - 放宽判断阈值
- **改进**：距离估计平滑滤波，读数更稳定
- **改进**：监督参数更宽松，减少误报
- **新增**：距离校准工具 `calibrate_distance.py`

---

## 许可证

本项目仅供学习和研究使用。

---

*最后更新：2026-06-02*
