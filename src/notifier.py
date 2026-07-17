"""Alert delivery helpers."""

from supervision import Alert, AlertType


class Notifier:
    def __init__(self, console_enabled: bool = True, audio_enabled: bool = False, tts=None):
        self.console_enabled = console_enabled
        self.audio_enabled = audio_enabled
        self.tts = tts

    def send_alert(self, alert: Alert):
        if self.console_enabled:
            self._print_alert(alert)
        if self.audio_enabled and self.tts:
            self._speak_alert(alert)
        elif self.audio_enabled and self.console_enabled:
            print("[TTS] audio_enabled 已开启，但未注入 TTS 实现")

    def send_info(self, message: str):
        if self.console_enabled:
            print(f"[Info] {message}")

    def _print_alert(self, alert: Alert):
        icons = {
            AlertType.POSTURE_BAD: "[POSTURE]",
            AlertType.TOO_CLOSE: "[DISTANCE]",
            AlertType.BREAK_NEEDED: "[BREAK]",
            AlertType.BREAK_OVER: "[RESUME]",
        }
        print(f"{icons.get(alert.alert_type, '[ALERT]')} {alert.message}")

    def _speak_alert(self, alert: Alert):
        if self.tts:
            self.tts.speak(alert.message)
