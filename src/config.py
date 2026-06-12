"""Shared configuration loading and validation."""

from __future__ import annotations

import copy
import os
from typing import Any, Dict

import yaml


DEFAULT_CONFIG: Dict[str, Dict[str, Any]] = {
    "camera": {
        "width": 640,
        "height": 480,
        "fps": 20,
        "jpeg_quality": 80,
        "format": "RGB888",
    },
    "network": {
        "host": "127.0.0.1",
        "port": 65432,
        "recv_timeout_s": 0.2,
        "send_timeout_s": 5.0,
    },
    "inference": {
        "model_complexity": 1,
        "min_detection_confidence": 0.5,
        "min_tracking_confidence": 0.5,
        "analyze_face": False,
        "inference_fps": 10,
        "display_fps": 15,
    },
    "distance": {
        "face_real_width_cm": 13.5,
        "camera_focal_length": 820.0,
        "min_cm": 25.0,
        "max_cm": 120.0,
        "smoothing_alpha": 0.35,
        "edge_reject_ratio": 0.35,
    },
    "pose": {
        "camera_view": "front",
        "landmark_visibility_threshold": 0.5,
        "posture_window_s": 4.0,
        "posture_alert_threshold": 55.0,
        "shoulder_diff_threshold": 0.08,
        "head_down_threshold": 0.07,
        "lean_forward_threshold": 0.22,
        "head_forward_threshold": 0.12,
        "desk_proximity_threshold": 0.18,
        "weights": {
            "uneven_shoulders": 20.0,
            "head_down": 35.0,
            "head_tilt": 10.0,
            "leaning_forward": 30.0,
            "head_forward": 30.0,
            "desk_proximity": 35.0,
        },
    },
    "supervision": {
        "too_close_threshold_cm": 30.0,
        "too_close_duration_s": 5.0,
        "distance_confidence_grace_s": 1.5,
        "bad_posture_duration_s": 8.0,
        "max_study_duration_min": 45,
        "rest_duration_min": 10,
        "alert_cooldown_s": 45.0,
        "severity_mild_threshold": 30.0,
        "severity_moderate_threshold": 60.0,
        "severity_severe_threshold": 80.0,
        "presence_enter_frames": 5,
        "presence_exit_frames": 15,
    },
    "thermal": {
        "enabled": True,
        "temp_warn_c": 65.0,
        "temp_throttle_c": 75.0,
        "temp_check_interval_s": 10.0,
        "throttle_inference_fps": 8,
        "throttle_model_complexity": 0,
    },
    "process": {
        "max_restart_attempts": 3,
        "restart_backoff_base_s": 2,
        "restart_reset_after_s": 60,
        "status_log_interval_s": 10,
    },
    "preview": {
        "window_name": "Kid Supervisor",
        "show_help": True,
    },
    "storage": {
        "enabled": True,
        "sqlite_path": "data/kid_supervisor.db",
    },
    "notifier": {
        "console_enabled": True,
        "audio_enabled": False,
    },
}


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _require_positive(config: Dict[str, Any], section: str, key: str):
    value = config[section][key]
    if value <= 0:
        raise ValueError(f"config.{section}.{key} must be > 0, got {value!r}")


def _validate(config: Dict[str, Any]):
    for section, key in [
        ("camera", "width"),
        ("camera", "height"),
        ("camera", "fps"),
        ("network", "port"),
        ("network", "recv_timeout_s"),
        ("network", "send_timeout_s"),
        ("inference", "inference_fps"),
        ("inference", "display_fps"),
        ("distance", "face_real_width_cm"),
        ("distance", "camera_focal_length"),
        ("distance", "min_cm"),
        ("distance", "max_cm"),
        ("pose", "posture_window_s"),
        ("supervision", "too_close_duration_s"),
        ("supervision", "bad_posture_duration_s"),
        ("process", "max_restart_attempts"),
        ("process", "restart_backoff_base_s"),
        ("process", "restart_reset_after_s"),
        ("process", "status_log_interval_s"),
    ]:
        _require_positive(config, section, key)

    camera_view = config["pose"]["camera_view"]
    if camera_view not in {"front", "side"}:
        raise ValueError("config.pose.camera_view must be 'front' or 'side'")

    if config["distance"]["max_cm"] <= config["distance"]["min_cm"]:
        raise ValueError("config.distance.max_cm must be greater than min_cm")


def load_config(base_dir: str) -> Dict[str, Any]:
    config_path = os.path.join(base_dir, "config.yaml")
    file_config: Dict[str, Any] = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as handle:
            file_config = yaml.safe_load(handle) or {}
    else:
        print(f"[Config] {config_path} 未找到，使用默认配置")

    config = _deep_merge(DEFAULT_CONFIG, file_config)
    _validate(config)
    config["_meta"] = {"config_path": config_path, "config_exists": os.path.exists(config_path)}
    return config
