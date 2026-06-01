# Kid Supervisor v3 - 设计与调试记录

## 项目概述

使用树莓派5 + Camera Module 3 Wide 实现小孩学习监控：
- 人脸检测与存在感知
- 学习时长统计
- 距离估算（基于人脸大小）
- 预留智能音箱对话功能扩展

---

## 硬件配置

| 组件 | 型号 |
|------|------|
| 主板 | 树莓派5 8GB |
| 摄像头 | Camera Module 3 Wide |
| 存储 | 树莓派M.2 HAT SSD 512GB |

---

## 调试历史与关键决策

### 1. 颜色空间问题

**问题现象**：
- Picamera2 输出 RGB888 格式
- cv2.imshow() 期望 BGR 格式
- 直接显示会导致肤色偏紫/偏红

**测试过程**：
```bash
python3 test_colors.py
```
通过 `test_colors.py` 对比测试发现：
- **MODE 0 (RGB 原样)**：肤色显示正常 ✅
- **MODE 1 (RGB→BGR)**：颜色异常 ❌

**最终决策**：使用 Picamera2 RGB888 直接传给 cv2.imshow，不做颜色转换。

---

### 2. 人脸检测模型集成

**错误方案**：
- 尝试通过 `sudo apt install opencv-data` 安装到系统路径
- 尝试在 `/usr/share/opencv4/haarcascades/` 等系统路径查找
- 不稳定且依赖环境配置

**正确方案**：
- 将 `haarcascade_frontalface_default.xml` 直接提交到项目根目录
- 代码中使用相对路径加载：
```python
base_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(base_dir, "haarcascade_frontalface_default.xml")
cascade = cv2.CascadeClassifier(model_path)
```

**验证结果**：
```bash
python3 test_headless.py
```
✅ 成功检测到人脸输出：
```
[Frame 27] ✅ 检测到 1 个人脸:
  人脸 1: (392, 289) 57x57
```

**人脸检测参数调优**：
| 参数 | 值 | 说明 |
|------|-----|------|
| scaleFactor | 1.05 | 图像缩放比例，越小越慢但召回率越高 |
| minNeighbors | 4-5 | 每个候选矩形需要保持的邻居数，越高越准确 |
| minSize | (40, 40) 或 (60, 60) | 最小人脸尺寸 |

---

### 3. GLib-GObject 警告

**错误信息**：
```
GLib-GObject-CRITICAL **: ...: assertion 'G_IS_OBJECT (object)' failed
```

**原因**：OpenCV 窗口销毁时的清理顺序问题，不影响核心功能。

**缓解方案**：
```python
try:
    cv2.destroyWindow("Kid Supervisor")
except Exception:
    pass
try:
    cv2.destroyAllWindows()
except Exception:
    pass
```

---

### 4. 姿态检测方案选型

| 方案 | 树莓派5 ARM64 | 推荐度 |
|------|--------------|--------|
| MediaPipe | ❌ 无预编译包，需源码编译 | ⭐ |
| MoveNet + TensorFlow Lite | ✅ 有预编译包，轻量 | ⭐⭐⭐⭐⭐ |
| 简化方案（仅人脸） | ✅ 原生支持 | ⭐⭐⭐ |

**当前阶段**：先实现简化方案（人脸检测 + 距离估算），后续可迁移到 MoveNet。

---

## 项目文件结构

```
kid_supervisor_v3/
├── DESIGN.md                          # 本文档 - 设计与调试记录
├── ARCHITECTURE.md                    # 架构设计（预留）
├── README.md                          # 使用说明
├── requirements.txt                   # 依赖列表
├── main.py                            # 主程序
├── haarcascade_frontalface_default.xml  # 人脸检测模型（已集成）
├── check_camera.py                    # 摄像头检查工具
├── test_colors.py                     # 颜色格式测试工具
├── test_face_only.py                  # 仅人脸检测测试工具
├── test_headless.py                   # 无头模式测试（无GUI）
├── test_display.py                    # 显示模式测试（RGB vs BGR）
└── src/                               # 模块化代码（待迁移）
    ├── camera.py
    ├── detector.py
    └── preview_renderer.py
```

---

## 当前功能（v3 阶段）

### 已实现
- ✅ Picamera2 摄像头采集（RGB888, 640x480@10fps）
- ✅ 本地 Haar Cascade 人脸检测
- ✅ 人脸存在检测与防抖（3帧确认）
- ✅ 学习时长统计
- ✅ GUI 预览（人脸框 + 状态信息）

### 待实现
- ⏳ 距离估算（基于人脸像素大小）
- ⏳ 姿态简化判断（基于人脸位置）
- ⏳ 数据持久化与统计
- ⏳ 后台静默模式（无GUI）
- ⏳ 智能音箱预留接口

---

## 距离估算原理

基于 Camera Module 3 Wide 的已知参数：

```
已知人脸实际宽度 ≈ 14 cm
焦距 f = (人脸像素宽度 × 距离) / 实际人脸宽度

反过来：
距离 = (f × 实际人脸宽度) / 人脸像素宽度
```

需要先做一次校准：让用户站在已知距离（比如50cm）处，计算出 f 的值。

---

## 快速开始

### 运行主程序
```bash
cd /home/mxin/.openclaw/workspace/kid_supervisor_v3
python3 main.py
```

### 测试工具
```bash
# 仅测试人脸检测（有GUI）
python3 test_face_only.py

# 无头测试（无GUI，打印检测结果）
python3 test_headless.py

# 颜色格式测试
python3 test_colors.py
```

### 依赖安装
```bash
# OpenCV 和 Picamera2 通常系统已预装
sudo apt install -y python3-opencv python3-picamera2
```

---

## 预留扩展：智能音箱对话

### 预留模块位置
```
src/
├── wake_word/           # 唤醒词检测（预留，如 porcupine / openWakeWord）
├── asr/                 # 语音转文字（预留，如 Whisper / Vosk）
├── llm/                 # 对话逻辑（预留）
└── tts/                 # 文字转语音（预留，如 Piper / eSpeak）
```

### 预留接口设计
- 检测到学习姿势问题时，可触发语音提醒
- 预留语音交互入口，支持问答（如"这个字怎么读"）

---

## 已知问题与注意事项

1. **GLib-GObject 警告**：可忽略，不影响功能
2. **人脸检测准确率**：Haar Cascade 不如深度学习方法，光线不佳时可能漏检
3. **MediaPipe 安装**：树莓派 ARM64 无预编译包，暂不推荐
4. **摄像头角度**：Camera Module 3 Wide 是广角，注意安装角度避免画面畸变

---

## 下一步计划

1. 完善距离估算功能
2. 添加姿势简化判断逻辑
3. 实现数据保存到本地 SQLite
4. 添加后台运行模式
5. （可选）接入 MoveNet + TFLite 实现完整姿态检测

---

## 调试命令速查

```bash
# 检查摄像头设备
libcamera-hello

# 检查 Python 包
python3 -c "import cv2; print(cv2.__version__)"
python3 -c "import picamera2; print('Picamera2 OK')"

# 测试模型文件
python3 -c "import cv2; c=cv2.CascadeClassifier('haarcascade_frontalface_default.xml'); print('Model empty:', c.empty())"
```

---
文档生成时间：2026-05-30
