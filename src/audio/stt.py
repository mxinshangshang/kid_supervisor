"""
语音转文字模块 - STT
社区推荐方案：
1. Faster-Whisper (速度快，树莓派5可跑 small 模型)
2. Vosk (更轻量，离线)
3. Whisper (原版，稍重但质量高)

参考:
- https://github.com/guillaumekln/faster-whisper
- https://github.com/alphacep/vosk-api
"""
from typing import Optional
from abc import ABC, abstractmethod


class STTProvider(ABC):
    """STT 提供者抽象基类"""

    @abstractmethod
    def transcribe(self, audio_data: bytes) -> Optional[str]:
        """转音频为文字"""
        pass

    @abstractmethod
    def transcribe_file(self, audio_path: str) -> Optional[str]:
        """转文件为文字"""
        pass


class DummySTT(STTProvider):
    """空实现"""

    def transcribe(self, audio_data: bytes) -> Optional[str]:
        print("[STT] Dummy: 假装听到了一句话")
        return "这个字怎么念"

    def transcribe_file(self, audio_path: str) -> Optional[str]:
        return None


class FasterWhisperSTT(STTProvider):
    """
    Faster-Whisper 实现（推荐！）

    安装:
        pip install faster-whisper

    树莓派5 建议用:
    - tiny 模型 (~75MB)  - 极快
    - small 模型 (~500MB) - 平衡
    """

    def __init__(self, model_size: str = "tiny", device: str = "cpu", compute_type: str = "int8"):
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError("faster-whisper not installed!")

        print(f"[STT] Loading Faster-Whisper model: {model_size}")
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        self.model_size = model_size

    def transcribe(self, audio_data: bytes) -> Optional[str]:
        # 注意：需要把 bytes 转为合适的音频格式
        # faster-whisper 可以直接读 numpy array
        segments, info = self.model.transcribe(audio_data, language="zh")
        return "".join([s.text for s in segments])

    def transcribe_file(self, audio_path: str) -> Optional[str]:
        segments, info = self.model.transcribe(audio_path, language="zh")
        return "".join([s.text for s in segments])


class VoskSTT(STTProvider):
    """
    Vosk STT（更轻量，但需要下载中文模型）

    安装:
        pip install vosk

    下载模型:
        https://alphacephei.com/vosk/models
        推荐: vosk-model-small-cn-0.22
    """

    def __init__(self, model_path: str):
        try:
            from vosk import Model, KaldiRecognizer
        except ImportError:
            raise ImportError("vosk not installed!")

        print(f"[STT] Loading Vosk model: {model_path}")
        self.model = Model(model_path)
        self.model_path = model_path

    def transcribe(self, audio_data: bytes) -> Optional[str]:
        from vosk import KaldiRecognizer
        import json

        rec = KaldiRecognizer(self.model, 16000)
        rec.AcceptWaveform(audio_data)
        result = json.loads(rec.Result())
        return result.get("text", "")

    def transcribe_file(self, audio_path: str) -> Optional[str]:
        # 这里需要用 wave 模块读文件
        import wave
        from vosk import KaldiRecognizer
        import json

        wf = wave.open(audio_path, "rb")
        rec = KaldiRecognizer(self.model, wf.getframerate())

        result_text = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                result_text.append(result.get("text", ""))

        result = json.loads(rec.FinalResult())
        result_text.append(result.get("text", ""))

        return "".join(result_text)
