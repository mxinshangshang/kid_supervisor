# Kid Supervisor v3 - 树莓派5 优化版

基于 GitHub 社区成熟方案重新设计，充分发挥 **树莓派5 8G + SSD** 的性能！

---

## 🎯 推荐方案对比

| 方案 | v1 (旧) | v2 (模块化) | **v3 (推荐)** |
|------|---------|-------------|---------------|
| 检测引擎 | Haar Cascade | Haar/MediaPipe 可选 | **MediaPipe Pose + Face Mesh** |
| 语音框架 | 无 | 预留 Dummy 接口 | **OpenWakeWord + Faster-Whisper + Piper** |
| 架构 | 单文件 | 模块化 | **事件驱动 + 可选 MQTT** |
| 数据持久化 | 内存 | SQLite | SQLite + 可选上传 |
| 硬件要求 | 低 | 中 | **树莓派 4/5 (8G)** |

---

## 🏗️ 技术选型理由（基于社区最佳实践）

### 视觉检测：MediaPipe (Google 官方)
- ✅ 有针对 ARM64 的 NEON 优化
- ✅ RPi5 上可达 **15-20 FPS** (model_complexity=1)
- ✅ 提供 33 个精确的人体关键点
- ✅ Face Mesh 可做准确的头部姿态估计
- 参考: https://github.com/google/mediapipe

### 唤醒词：OpenWakeWord
- ✅ 完全离线，无需联网
- ✅ 非常轻量，几乎不占 CPU
- ✅ 社区超火，模型丰富
- 参考: https://github.com/dscripka/openwakeword

### STT：Faster-Whisper
- ✅ 比原版 Whisper 快 2-4 倍
- ✅ 树莓派5 能跑 `small` 模型
- ✅ 支持中文
- 参考: https://github.com/guillaumekln/faster-whisper

### TTS：Piper
- ✅ 非常快！树莓派上实时生成
- ✅ 音质好，有中文模型
- ✅ 完全离线
- 参考: https://github.com/rhasspy/piper

---

## 📦 目录结构

```
kid_supervisor_v3/
├── ARCHITECTURE.md     # 详细架构设计
├── README.md           # 本文件
├── requirements.txt    # 依赖列表
├── config/
│   └── settings.yaml   # 配置文件
└── src/
    ├── vision/         # 视觉模块
    │   └── pose_detector.py
    ├── audio/          # 音频模块
    │   ├── wake_word.py  # OpenWakeWord
    │   ├── stt.py        # Faster-Whisper/Vosk
    │   └── tts.py        # Piper/Edge-TTS
    ├── supervision/    # 监督逻辑
    ├── storage/        # 数据存储
    └── bus/            # 事件总线
```

---

## 🚀 快速开始（当前阶段 - 视觉优先）

你的硬件还没音频输入输出，先跑视觉部分：

```bash
cd /home/mxin/.openclaw/workspace/kid_supervisor_v3/

# 安装依赖
pip install opencv-python numpy mediapipe

# 先测试 MediaPipe 能不能跑
python -c "import mediapipe; print('MediaPipe OK!')"
```

---

## 📈 演进路线

### Phase 1: 视觉监督 (现在)
- ✅ MediaPipe Pose 检测
- ✅ 坐姿/距离/时长统计
- ✅ SQLite 持久化

### Phase 2: 音频提醒 (加喇叭)
- 安装 Piper TTS
- 实现语音提醒 ("请坐好" / "离远点")

### Phase 3: 完整对话 (加麦)
- 安装 OpenWakeWord
- 安装 Faster-Whisper
- 实现唤醒 -> 对话 -> 技能处理

### Phase 4: 锦上添花 (可选)
- Web UI 看统计
- MQTT 接入 Home Assistant
- Docker 部署
- YOLOv8-Pose 对比测试

---

## 💡 为什么这个方案比之前好？

| 维度 | v2 问题 | v3 改进 |
|------|---------|---------|
| **检测精度** | Haar 太粗糙 | MediaPipe 有真实关键点 |
| **未来扩展** | Dummy 只是占位 | 直接预留了集成成熟方案的接口 |
| **社区生态** | 自己造轮子 | 全是社区验证过的方案 |
| **硬件利用** | 太保守，浪费 8G | 直接上 MediaPipe model_complexity=1 |

---

## 📚 参考项目

| 项目 | 用途 |
|------|------|
| google/mediapipe | 视觉检测 |
| dscripka/openwakeword | 唤醒词 |
| guillaumekln/faster-whisper | STT |
| rhasspy/piper | TTS |
| rhasspy/rhasspy | 完整语音助手参考 |
| blakeblackshear/frigate | NVR 架构参考 |
