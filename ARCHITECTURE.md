# Kid Supervisor v3 - 架构设计

基于树莓派 5 8G + Camera Module 3 + SSD 的优化方案

---

## 🎯 核心改动

### 1. 检测引擎升级
- **v2**: Haar Cascade (保守)
- **v3**: **MediaPipe Pose + MediaPipe Face Mesh** (因为有 8G 内存！)
  - MediaPipe 在 RPi5 上有官方 NEON 优化
  - Face Mesh 可以做更准确的头部姿态估计
  - 可选：用 YOLOv8-Pose 做对比

### 2. 语音系统采用成熟开源组件
- 唤醒词：**OpenWakeWord**
- STT：**Faster-Whisper** (tiny/small 模型)
- TTS：**Piper** 或 **Coqui TTS**
- 都跑本地，保护隐私！

### 3. 模块化 + MQTT 事件总线
- 各组件通过 MQTT 通信（参考 Home Assistant / Frigate）
- 可以独立启动/重启某个模块
- 方便接入其他系统

---

## 📁 v3 目录结构

```
kid_supervisor_v3/
├── docker/              # Docker 支持（因为有 SSD，用 Docker 很方便）
│   └── docker-compose.yml
├── config/              # 配置文件目录
│   └── settings.yaml
├── src/
│   ├── camera/          # 摄像头服务
│   │   └── camera_service.py
│   ├── vision/          # 视觉分析（MediaPipe/YOLO）
│   │   ├── pose_detector.py
│   │   ├── face_analyzer.py
│   │   └── distance_estimator.py
│   ├── supervision/     # 监督逻辑
│   │   ├── posture_monitor.py
│   │   └── study_tracker.py
│   ├── audio/           # 音频模块
│   │   ├── wake_word.py      # OpenWakeWord
│   │   ├── stt.py            # Faster-Whisper
│   │   ├── tts.py            # Piper
│   │   └── audio_player.py
│   ├── skills/          # 对话技能
│   │   ├── chinese_dict.py
│   │   ├── translator.py
│   │   └── math_helper.py
│   ├── storage/         # 存储
│   │   ├── sqlite_repo.py
│   │   └── models.py
│   ├── api/             # Web API / UI
│   │   └── server.py
│   └── bus/             # 事件总线
│       └── mqtt_client.py
├── data/                # 数据目录（挂 SSD）
│   ├── db/
│   ├── media/
│   └── models/
├── main.py
└── requirements.txt
```

---

## 🔌 事件总线设计（MQTT）

```
# 检测事件
vision/pose/detected
vision/face/detected
vision/distance/too_close
vision/posture/bad

# 学习事件
study/session/started
study/session/ended
study/break/needed
study/break/ended

# 音频事件
audio/wakeword/detected
audio/query/ready
audio/response/ready

# 通知事件
notify/tts
notify/alert
notify/stats
```
