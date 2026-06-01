"""
文字转语音模块 - TTS
社区推荐方案：
1. Piper (快! 效果好，完全离线，树莓派友好)
   https://github.com/rhasspy/piper
2. Coqui TTS (质量高，但慢一点)
3. eSpeak (轻量，但音质一般)
4. Edge-TTS (需要联网，但是音质最好)
"""
from typing import Optional
from abc import ABC, abstractmethod


class TTSProvider(ABC):
    """TTS 提供者抽象基类"""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """生成音频"""
        pass

    @abstractmethod
    def speak(self, text: str):
        """直接朗读"""
        pass


class DummyTTS(TTSProvider):
    """空实现"""

    def synthesize(self, text: str) -> bytes:
        print(f"[TTS] 会说: {text}")
        return b""

    def speak(self, text: str):
        print(f"[TTS] 会说: {text}")


class PiperTTS(TTSProvider):
    """
    Piper TTS - 推荐！非常快，完全离线

    安装:
        pip install piper-tts

    下载模型:
        https://github.com/rhasspy/piper/releases/tag/v0.0.2
        推荐中文: zh_CN-huayan-medium
    """

    def __init__(self, model_path: str, use_cuda: bool = False):
        try:
            from piper import PiperVoice
        except ImportError:
            raise ImportError("piper-tts not installed!")

        print(f"[TTS] Loading Piper model: {model_path}")
        self.voice = PiperVoice.load(model_path, use_cuda=use_cuda)

    def synthesize(self, text: str) -> bytes:
        # Piper 返回音频流
        audio_chunks = []
        for audio_bytes in self.voice.synthesize_stream_raw(text):
            audio_chunks.append(audio_bytes)
        return b"".join(audio_chunks)

    def speak(self, text: str):
        import wave
        import sys
        from io import BytesIO

        audio_bytes = self.synthesize(text)

        # 播放
        try:
            import sounddevice as sd
            import numpy as np

            with wave.open(BytesIO(audio_bytes), 'rb') as wf:
                sample_rate = wf.getframerate()
                sample_width = wf.getsampwidth()
                channels = wf.getnchannels()
                frames = wf.readframes(wf.getnframes())

                dtype = np.int16 if sample_width == 2 else np.int8
                audio_array = np.frombuffer(frames, dtype=dtype)

                sd.play(audio_array, samplerate=sample_rate)
                sd.wait()
        except Exception as e:
            print(f"[TTS] 播放失败: {e}")


class EdgeTTSTTS(TTSProvider):
    """
    Edge-TTS - 需要联网，但音质最好

    安装:
        pip install edge-tts
    """

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        try:
            import edge_tts
        except ImportError:
            raise ImportError("edge-tts not installed!")

        self.voice = voice

    def synthesize(self, text: str) -> bytes:
        import edge_tts
        import asyncio

        async def _synth():
            communicate = edge_tts.Communicate(text, self.voice)
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            return audio_data

        return asyncio.run(_synth())

    def speak(self, text: str):
        audio_bytes = self.synthesize(text)
        # 这里接播放逻辑...
        print(f"[TTS] Edge-TTS 生成了 {len(audio_bytes)} bytes")
