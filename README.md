# Kid Supervisor - 儿童学习监督系统

基于树莓派 5 的本地化儿童学习监督系统，通过单摄像头实现存在检测、姿态监督、距离提醒和学习时长管理。

---

## 项目概述

Kid Supervisor 面向儿童书桌学习场景，强调三点：

1. 非侵入式监督：只依赖摄像头，不需要佩戴设备
2. 本地处理：全部在树莓派本地完成，保护隐私
3. 稳定可信：优先保证长期运行、低误报和可解释提醒

当前版本针对树莓派 5 + 单摄像头进行了收敛式优化，不追求大而全，而是聚焦核心监督需求。

---

## 核心能力

| 功能 | 说明 |
|------|------|
| 存在检测 | 检测孩子是否仍在学习位 |
| 姿态监督 | 检测低头、前倾、歪头、肩膀不平、头前伸等问题 |
| 距离提醒 | 正面机位下基于头部尺度估算距离 |
| 学习计时 | 自动记录学习会话并提醒休息 |
| 双进程架构 | 摄像头采集与推理解耦，解决 Python 版本冲突 |
| 温控降频 | 高温时自动降低推理负载 |
| 自动重启 | 子进程异常退出后自动恢复 |
| 机位模式 | 支持 `front` / `side` 两种书桌部署方式 |
| SQLite 持久化 | 保存学习会话统计 |
| 配置中心 | 所有关键参数统一由 `config.yaml` 管理 |

---

## 推荐硬件

| 组件 | 推荐 | 说明 |
|------|------|------|
| 主板 | Raspberry Pi 5 8GB | 推荐 8GB，长时间运行更稳 |
| 摄像头 | Camera Module 3 Wide | 近距离书桌场景更实用 |
| 存储 | SSD 或高速 MicroSD | 建议使用稳定存储介质 |
| 电源 | 官方 5V 5A | 避免供电不足 |
| 散热 | 主动或较强被动散热 | 长时间推理强烈建议配置 |

---

## 部署模式

### 1. 正面机位 `front`

适合：

1. 摄像头在屏幕上方
2. 摄像头在桌前偏上方

重点监督：

1. 距离过近
2. 低头
3. 歪头
4. 前倾
5. 双肩不平

### 2. 侧面机位 `side`

适合：

1. 摄像头在孩子座位侧面
2. 主要关注趴桌、头前伸、明显前倾

重点监督：

1. 头前伸
2. 趴桌/贴桌趋势
3. 躯干前倾

说明：

侧面模式不以距离值作为主要监督依据。

---

## 快速开始

### 1. 环境准备

```bash
cd /path/to/kid_supervisor-main
python3 setup_venv.py
```

### 2. 配置机位模式

编辑 `config.yaml`：

```yaml
pose:
  camera_view: front
```

或：

```yaml
pose:
  camera_view: side
```

### 3. 启动系统

```bash
/usr/bin/python3 main.py
```

无头模式：

```bash
/usr/bin/python3 main.py --no-preview
```

---

## 距离校准

正面机位下，建议首次部署完成后进行一次距离校准：

```bash
/usr/bin/python3 calibrate_distance.py
```

步骤：

1. 孩子正对摄像头坐在已知距离处，例如 `50cm`
2. 稳定保持 2-3 秒
3. 按 `c`
4. 输入真实距离数值
5. 工具自动写回 `config.yaml`

---

## 项目结构

```text
kid_supervisor-main/
├── main.py
├── camera_server.py
├── inference_client.py
├── calibrate_distance.py
├── config.yaml
├── src/
│   ├── config.py
│   ├── supervision.py
│   ├── notifier.py
│   ├── preview_renderer.py
│   ├── storage.py
│   └── vision/
│       └── pose_detector.py
└── docs/
```

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/requirements.md](docs/requirements.md) | 需求与验收目标 |
| [docs/architecture.md](docs/architecture.md) | 当前架构说明 |
| [docs/technical-details.md](docs/technical-details.md) | 关键实现细节 |
| [docs/deployment.md](docs/deployment.md) | 部署与配置指南 |
| [docs/debug-log.md](docs/debug-log.md) | 开发调试记录 |
| [docs/upgrade-plan-and-change-log.md](docs/upgrade-plan-and-change-log.md) | 本轮升级说明 |

---

## 当前实现边界

当前版本不做：

1. 多摄像头协同
2. 云端识别
3. Web 管理后台
4. 复杂语音交互
5. 重型模型替换全链路

原因是当前版本优先保证树莓派 5 单机部署下的可靠性、可信度和可维护性。

---

## 许可证

仅供学习与研究使用。
