"""
通知模块
支持飞书机器人通知，可发送文本和图片
"""
import os
import time
import json
import base64
import hashlib
import hmac
import re
import requests
from typing import Dict, Optional, Tuple
from PIL import Image
import io
from datetime import datetime

try:
    from supervision import Alert, AlertType
    HAS_ALERT = True
except Exception:
    HAS_ALERT = False


class Notifier:
    def __init__(self, config: dict = None):
        config = config or {}
        self.console_enabled = config.get("console_enabled", True)
        self.audio_enabled = config.get("audio_enabled", False)
        self.feishu_enabled = config.get("feishu_enabled", False)
        self.feishu_webhook = config.get("feishu_webhook", "")
        self.feishu_secret = config.get("feishu_secret", "")
        self.alert_cooldown = config.get("alert_cooldown_s", 45)

        # 最后发送时间记录，用于冷却
        self.last_send_time: Dict[str, float] = {}

        # OpenClaw 飞书配置缓存
        self.openclaw_cfg = None
        self.openclaw_receive_id = None
        self._load_openclaw_config()

    def _load_openclaw_config(self):
        """复用OpenClaw已打通的飞书App配置和最近会话ID"""
        config_path = "/home/mxin/.openclaw/openclaw.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                oc_cfg = json.load(f)
            feishu_cfg = oc_cfg.get("channels", {}).get("feishu", {})
            if not feishu_cfg.get("enabled"):
                return

            self.openclaw_cfg = feishu_cfg
            self.openclaw_receive_id = self._find_openclaw_feishu_receive_id()
        except Exception as e:
            pass

    def _find_openclaw_feishu_receive_id(self) -> Optional[str]:
        """从OpenClaw会话索引中提取最近的飞书open_id"""
        candidates = [
            "/home/mxin/.openclaw/agents/claude/sessions/sessions.json",
            "/home/mxin/.openclaw/agents/main/sessions/sessions.json",
        ]
        # 匹配两种格式：feishu:ou_xxx 或 feishu:direct:ou_xxx
        pattern = re.compile(r"feishu:(?:direct:|group:)?([A-Za-z0-9_\-]{20,})")
        for path in candidates:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                matches = pattern.findall(text)
                if matches:
                    # 过滤掉"direct"或"group"
                    valid_ids = [m for m in matches if m not in ("direct", "group")]
                    if valid_ids:
                        return valid_ids[-1]
            except Exception:
                continue
        return None

    def _openclaw_tenant_access_token(self) -> Optional[str]:
        if not self.openclaw_cfg:
            return None
        try:
            response = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.openclaw_cfg.get("app_id") or self.openclaw_cfg.get("appId"),
                    "app_secret": self.openclaw_cfg.get("app_secret") or self.openclaw_cfg.get("appSecret"),
                },
                timeout=10,
            )
            data = response.json()
            if data.get("code") == 0:
                return data.get("tenant_access_token")
        except Exception as e:
            pass
        return None

    def _openclaw_send_text(self, content: str) -> bool:
        if not self.openclaw_receive_id:
            return False
        token = self._openclaw_tenant_access_token()
        if not token:
            return False
        try:
            response = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "receive_id": self.openclaw_receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": content}, ensure_ascii=False),
                },
                timeout=10,
            )
            data = response.json()
            if data.get("code") == 0:
                return True
        except Exception as e:
            pass
        return False

    def _openclaw_upload_image(self, image_path: str) -> Optional[str]:
        token = self._openclaw_tenant_access_token()
        if not token:
            if self.console_enabled:
                print(f"[Notifier] _openclaw_upload_image: 无token")
            return None
        try:
            img_bytes = self._resize_image(image_path)
            files = {"image": (os.path.basename(image_path), img_bytes, "image/jpeg")}
            data = {"image_type": "message"}
            response = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                data=data,
                files=files,
                timeout=20,
            )
            payload = response.json()
            if payload.get("code") == 0:
                return payload.get("data", {}).get("image_key")
            else:
                if self.console_enabled:
                    print(f"[Notifier] _openclaw_upload_image: 上传失败: {payload}")
        except Exception as e:
            if self.console_enabled:
                print(f"[Notifier] _openclaw_upload_image: 异常: {e}")
        return None

    def _openclaw_send_image(self, image_path: str) -> bool:
        if not self.openclaw_receive_id or not os.path.exists(image_path):
            if self.console_enabled:
                print(f"[Notifier] _openclaw_send_image 检查失败: receive_id={bool(self.openclaw_receive_id)}, exists={os.path.exists(image_path)}")
            return False
        token = self._openclaw_tenant_access_token()
        if not token:
            if self.console_enabled:
                print(f"[Notifier] _openclaw_send_image: 无法获取token")
            return False
        image_key = self._openclaw_upload_image(image_path)
        if not image_key:
            if self.console_enabled:
                print(f"[Notifier] _openclaw_send_image: 无法上传图片获取image_key")
            return False
        try:
            response = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "receive_id": self.openclaw_receive_id,
                    "msg_type": "image",
                    "content": json.dumps({"image_key": image_key}),
                },
                timeout=10,
            )
            data = response.json()
            if data.get("code") == 0:
                return True
            else:
                if self.console_enabled:
                    print(f"[Notifier] _openclaw_send_image: 飞书API返回错误: {data}")
        except Exception as e:
            if self.console_enabled:
                print(f"[Notifier] _openclaw_send_image: 异常: {e}")
        return False

    def _resize_image(self, image_path: str, max_size: int = 10 * 1024 * 1024) -> bytes:
        """调整图片大小，确保不超过飞书限制"""
        with Image.open(image_path) as img:
            max_dimension = 1920
            if max(img.size) > max_dimension:
                ratio = max_dimension / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            quality = 85
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG', quality=quality)
            img_bytes = img_byte_arr.getvalue()

            while len(img_bytes) > max_size and quality > 10:
                quality -= 10
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=quality)
                img_bytes = img_byte_arr.getvalue()

            return img_bytes

    def _generate_feishu_sign(self, timestamp: int) -> str:
        """生成飞书签名"""
        if not self.feishu_secret:
            return ""
        string_to_sign = f"{timestamp}\n{self.feishu_secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        return sign

    def send_feishu_text(self, content: str) -> bool:
        """发送文本消息到飞书"""
        if self.feishu_enabled and self._openclaw_send_text(content):
            return True

        if not self.feishu_enabled or not self.feishu_webhook:
            return False

        timestamp = int(time.time())
        sign = self._generate_feishu_sign(timestamp)

        headers = {"Content-Type": "application/json"}
        payload = {
            "timestamp": str(timestamp),
            "sign": sign,
            "msg_type": "text",
            "content": {"text": content}
        }

        try:
            response = requests.post(
                self.feishu_webhook,
                headers=headers,
                data=json.dumps(payload),
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            return False

    def send_feishu_image(self, image_path: str, title: str = "") -> bool:
        """发送图片消息到飞书"""
        if self.console_enabled:
            print(f"[Notifier] 尝试发送图片: {image_path} (exists={os.path.exists(image_path)})")
        if self.feishu_enabled and self._openclaw_send_image(image_path):
            if self.console_enabled:
                print(f"[Notifier] ✅ 通过OpenClaw发送图片成功")
            return True

        if not self.feishu_enabled or not self.feishu_webhook or not os.path.exists(image_path):
            if self.console_enabled:
                print(f"[Notifier] ❌ 跳过: feishu_enabled={self.feishu_enabled}, webhook={bool(self.feishu_webhook)}, exists={os.path.exists(image_path)}")
            return False

        try:
            img_bytes = self._resize_image(image_path)
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")

            timestamp = int(time.time())
            sign = self._generate_feishu_sign(timestamp)

            headers = {"Content-Type": "application/json"}
            payload = {
                "timestamp": str(timestamp),
                "sign": sign,
                "msg_type": "image",
                "content": {"image": img_base64}
            }

            response = requests.post(
                self.feishu_webhook,
                headers=headers,
                data=json.dumps(payload),
                timeout=15
            )
            return response.status_code == 200
        except Exception as e:
            if self.console_enabled:
                print(f"[Notifier] ❌ 发送图片异常: {e}")
            return False

    def _should_send(self, event_type: str) -> bool:
        now = time.time()
        last_time = self.last_send_time.get(event_type, 0)
        if now - last_time < self.alert_cooldown:
            return False
        return True

    def _record_send(self, event_type: str):
        self.last_send_time[event_type] = time.time()

    def send_alert(self, alert, image_path: str = None):
        """发送告警通知"""
        if HAS_ALERT and isinstance(alert, Alert):
            # 先检查冷却
            event_type = alert.alert_type.value
            if not self._should_send(event_type):
                return

            # 构建消息
            icons = {
                AlertType.POSTURE_BAD: "💺",
                AlertType.TOO_CLOSE: "📏",
                AlertType.BREAK_NEEDED: "⏰",
                AlertType.BREAK_OVER: "✅",
            }
            icon = icons.get(alert.alert_type, "⚠️")
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            content = f"{icon} 学习提醒\n时间: {current_time}\n{alert.message}"

            if self.console_enabled:
                print(f"\n{content}")

            if self.feishu_enabled:
                self.send_feishu_text(content)
                # 发送图片（如果有）
                if image_path and os.path.exists(image_path):
                    try:
                        self.send_feishu_image(image_path)
                    except Exception as e:
                        if self.console_enabled:
                            print(f"[Warn] 发送告警图片失败: {e}")
                self._record_send(event_type)
        else:
            # 简单消息
            if self.console_enabled:
                print(f"[ALERT] {alert}")

    def send_info(self, message: str):
        """发送信息通知（开始/结束学习等）"""
        if self.console_enabled:
            print(f"[Info] {message}")

        if self.feishu_enabled:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            content = f"📢 学习状态\n时间: {current_time}\n{message}"
            self.send_feishu_text(content)

    def send_study_start(self, timestamp: float = None, image_path: str = None):
        """发送开始学习通知"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = f"🎯 开始学习\n时间: {current_time}\n加油！保持正确坐姿和用眼距离～"
        if self.console_enabled:
            print(f"\n{content}")
        if self.feishu_enabled:
            self.send_feishu_text(content)
            # 发送图片（如果有）
            if image_path and os.path.exists(image_path):
                try:
                    self.send_feishu_image(image_path)
                except Exception as e:
                    if self.console_enabled:
                        print(f"[Warn] 发送学习开始图片失败: {e}")
        self._record_send("study_start")

    def send_study_end(self, duration_seconds: float, image_path: str = None):
        """发送结束学习通知"""
        minutes = int(duration_seconds / 60)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = f"📚 学习结束\n时间: {current_time}\n本次学习时长: {minutes} 分钟\n辛苦了！休息一下吧～"
        if self.console_enabled:
            print(f"\n{content}")
        if self.feishu_enabled:
            self.send_feishu_text(content)
            # 发送图片（如果有）
            if image_path and os.path.exists(image_path):
                try:
                    self.send_feishu_image(image_path)
                except Exception as e:
                    if self.console_enabled:
                        print(f"[Warn] 发送学习结束图片失败: {e}")
        self._record_send("study_end")
