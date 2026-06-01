"""
唤醒词检测模块 - 基于 OpenWakeWord
这是目前社区最火的离线唤醒词方案
https://github.com/dscripka/openwakeword
"""
import time
from typing import Optional, Callable
from abc import ABC, abstractmethod


class WakeWordDetector(ABC):
    """唤醒词检测器抽象基类"""

    @abstractmethod
    def start(self, on_detected_callback: Callable[[str], None]):
        """开始监听"""
        pass

    @abstractmethod
    def stop(self):
        """停止监听"""
        pass

    @abstractmethod
    def set_enabled(self, enabled: bool):
        """启用/禁用（学习时可以禁用，避免打扰）"""
        pass


class DummyWakeWordDetector(WakeWordDetector):
    """空实现（当前硬件未就绪）"""

    def __init__(self, wake_words: list[str] = None):
        self.wake_words = wake_words or ["小助手", "你好小助手"]
        self.enabled = False
        print(f"[WakeWord] Dummy init, wake words: {self.wake_words}")
        print("  等有麦了，装: pip install openwakeword")

    def start(self, on_detected_callback: Callable[[str], None]):
        self.enabled = True
        print("[WakeWord] 模拟启动（实际没有硬件）")

    def stop(self):
        self.enabled = False

    def set_enabled(self, enabled: bool):
        self.enabled = enabled


class OpenWakeWordDetector(WakeWordDetector):
    """
    真实 OpenWakeWord 实现（等有硬件再用）

    安装:
        pip install openwakeword

    用法:
        detector = OpenWakeWordDetector(wake_words=["小助手"])
        detector.start(on_detected_callback=lambda w: print(f"听到了: {w}"))
    """

    def __init__(self, wake_words: list[str] = None, model_path: str = None):
        try:
            import openwakeword
            self.oww = __import__("openwakeword")
        except ImportError:
            raise ImportError("openwakeword not installed!")

        self.wake_words = wake_words or ["hey_mycroft", "alexa"]
        self.model_path = model_path
        self.enabled = False
        self.running = False
        self.model = None
        self.stream = None

    def start(self, on_detected_callback: Callable[[str], None]):
        import openwakeword
        import pyaudio
        import numpy as np

        # 加载模型
        self.model = openwakeword.Model(wakeword_model_paths=self.wake_words)
        self.enabled = True
        self.running = True

        # 打开音频流
        self.stream = pyaudio.PyAudio().open(
            rate=16000,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=1280,
        )

        # 循环监听（实际用应该放后台线程）
        while self.running and self.enabled:
            audio_frame = np.frombuffer(self.stream.read(1280), dtype=np.int16)
            prediction = self.model.predict(audio_frame)

            for wake_word, score in prediction.items():
                if score > 0.5:
                    on_detected_callback(wake_word)
                    # 触发后冷却一下
                    time.sleep(2)

    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
