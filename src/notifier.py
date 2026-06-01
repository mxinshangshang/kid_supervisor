"""
通知模块 - 控制台/音频/等
"""
from typing import Optional
from .supervision import Alert, AlertType


class Notifier:
    """通知器"""

    def __init__(self, console_enabled: bool = True, audio_enabled: bool = False):
        self.console_enabled = console_enabled
        self.audio_enabled = audio_enabled
        self.tts = None  # 等有硬件再设置

    def send_alert(self, alert: Alert):
        """发送提醒"""
        if self.console_enabled:
            self._print_alert(alert)

        if self.audio_enabled and self.tts:
            self._speak_alert(alert)

    def send_info(self, message: str):
        """发送信息"""
        if self.console_enabled:
            print(f"[Info] {message}")

    def _print_alert(self, alert: Alert):
        """打印到控制台"""
        icons = {
            AlertType.POSTURE_BAD: "🧘",
            AlertType.TOO_CLOSE: "👀",
            AlertType.BREAK_NEEDED: "⏰",
            AlertType.BREAK_OVER: "✅",
        }
        icon = icons.get(alert.alert_type, "⚠️")
        print(f"{icon} {alert.message}")

    def _speak_alert(self, alert: Alert):
        """语音朗读（预留）"""
        if self.tts:
            self.tts.speak(alert.message)
