# 开发调试记录

## 1. 项目历史

### 1.1 版本演进

| 版本 | 主要变化 | 时间 |
|------|---------|------|
| v1 | 初始版本，Haar Cascade 人脸检测 | 2026-05 |
| v2 | 模块化重构，预留 MediaPipe 接口 | 2026-05 |
| v3 | 双进程架构，MediaPipe Pose 实现 | 2026-06-01 |

---

## 2. 关键技术决策记录

### 2.1 检测引擎选择

**问题**：选择什么样的检测方案？

**选项对比**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| Haar Cascade | 轻量，系统自带 | 精度低，特别是对姿态 |
| MediaPipe Face Mesh | 精度高，人脸关键点全 | 无法分析全身姿态 |
| MediaPipe Pose | 全身 33 个关键点，可分析姿态 | 计算量稍大 |
| MoveNet + TFLite | 轻量，针对移动设备优化 | 需更多适配工作 |

**决策**：选择 **MediaPipe Pose**

- 树莓派 5 8GB 性能足够
- 姿态分析是核心需求
- MediaPipe 有预编译包（Python 3.11）

### 2.2 Python 版本冲突解决方案

**问题**：
- picamera2 仅支持系统 Python 3.13
- mediapipe 没有 Python 3.13 的预编译 wheel

**尝试过的方案**：

1. **源码编译 MediaPipe for 3.13**
   - 结果：依赖复杂，编译失败，放弃

2. **换用其他检测库**
   - 结果：要么精度不够，要么同样有版本问题

3. **双进程架构**
   - 结果：验证可行，最终采用

**最终方案**：双进程 + Socket 通信

---

## 3. 调试问题与解决方案

### 3.1 颜色空间问题

**问题现象**：
- 画面颜色异常，肤色偏紫/偏红

**原因分析**：
- Picamera2 输出 RGB888
- OpenCV 期望 BGR
- 直接传递导致颜色通道错位

**解决方案**：
```python
# 接收 RGB 帧后，渲染时转换为 BGR
frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
```

### 3.2 GLib-GObject 警告

**问题现象**：
```
GLib-GObject-CRITICAL **: ...: assertion 'G_IS_OBJECT (object)' failed
```

**原因分析**：
- OpenCV 窗口销毁时的清理顺序问题
- 不影响核心功能

**缓解方案**：
```python
try:
    cv2.destroyWindow(window_name)
    cv2.destroyAllWindows()
except Exception:
    pass  # 忽略清理错误
```

### 3.3 人脸检测抖动

**问题现象**：
- 存在检测频繁跳变，导致计时频繁启停

**原因分析**：
- 检测不是 100% 可靠，偶尔漏检
- 无防抖机制

**解决方案**：
```python
# 检测到人：2 帧确认
# 人离开：3 帧确认
person_counter = min(person_counter + 1, 3)
if person_counter >= 2 and not person_detected:
    # 确认存在
person_gone_counter = min(person_gone_counter + 1, 5)
if person_gone_counter >= 3 and person_detected:
    # 确认离开
```

### 3.4 提醒过于频繁

**问题现象**：
- 同一问题反复提醒，打扰用户

**解决方案**：
- 增加提醒冷却机制（30 秒）
- 需要不良状态持续一段时间才提醒（姿态 5 秒，距离 3 秒）

---

## 4. 测试记录

### 4.1 功能测试

| 测试项 | 结果 | 备注 |
|--------|------|------|
| 人脸检测 | ✓ 通过 | 正常光照下可靠 |
| 姿态检测 | ✓ 通过 | 能识别预设的不良姿态 |
| 距离估算 | ✓ 通过 | 相对准确，可接受 |
| 学习计时 | ✓ 通过 | 自动启停正常 |
| 提醒功能 | ✓ 通过 | 按预期触发 |
| 双进程通信 | ✓ 通过 | 稳定可靠 |

### 4.2 性能测试

| 指标 | 结果 | 备注 |
|------|------|------|
| 帧率 | ~15-20 FPS | 640x480, model_complexity=1 |
| 内存占用 | ~300-400MB | 两个进程合计 |
| CPU 占用 | ~60-80% | 4 核占用 |
| 温度 | 正常 | 有散热片情况下 |

---

## 5. 已知限制

1. **光线依赖**：MediaPipe 在光线不足时检测率下降
2. **角度限制**：摄像头需要正对人体，侧面检测效果下降
3. **距离估算精度**：基于人脸大小的估算有一定误差，仅供参考
4. **无自动重启**：推理进程意外退出后需要手动重启
5. **无数据持久化**：当前版本不保存历史记录

---

## 6. 未来改进方向

### 6.1 短期改进

- [ ] 添加数据持久化（SQLite）
- [ ] 实现进程崩溃自动重启
- [ ] 增加更多姿态检测规则
- [ ] 添加 TTS 语音提醒

### 6.2 长期改进

- [ ] Web UI 查看历史统计
- [ ] Home Assistant 集成
- [ ] MQTT 事件总线
- [ ] Docker 容器化部署
- [ ] 多摄像头支持

---

## 7. 参考资料

- [MediaPipe Pose 官方文档](https://developers.google.com/mediapipe/solutions/vision/pose_landmarker)
- [Picamera2 文档](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)
- [树莓派 Camera Module 3 规格](https://www.raspberrypi.com/products/camera-module-3/)

---

*文档版本：v1.0*  
*最后更新：2026-06-01*
