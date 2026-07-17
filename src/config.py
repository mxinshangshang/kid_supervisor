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
        "baseline_face_width_px": 0,
        "too_close_relative_scale": 1.25,
        "prefer_relative_baseline": False,
    },
    "pose": {
        "camera_view": "front",
        "landmark_visibility_threshold": 0.5,
        "posture_window_s": 4.0,
        "posture_alert_threshold": 55.0,
        "min_quality_score": 0.55,
        "min_visible_keypoints": 4,
        "shoulder_roll_degree_threshold": 8.0,
        "head_down_ratio_threshold": 0.16,
        "lean_forward_ratio_threshold": 0.12,
        "head_forward_ratio_threshold": 0.12,
        "desk_proximity_ratio_threshold": 0.18,
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
        "too_close_severe_distance_margin_cm": 5.0,
        "too_close_severe_relative_multiplier": 1.25,
        "too_close_duration_s": 5.0,
        "distance_recovery_s": 1.5,
        "distance_confidence_grace_s": 1.5,
        "presence_grace_s": 2.0,
        "bad_posture_duration_s": 8.0,
        "posture_recovery_s": 2.0,
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
        "throttle_recover_margin_c": 5.0,
        "temp_check_interval_s": 10.0,
        "throttle_inference_fps": 8,
        "throttle_model_complexity": 0,
    },
    "process": {
        "status_log_interval_s": 10,
    },
    "preview": {
        "window_name": "Kid Supervisor",
        "show_help": True,
        "show_debug_hud": True,
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
        ("distance", "smoothing_alpha"),
        ("distance", "edge_reject_ratio"),
        ("distance", "too_close_relative_scale"),
        ("pose", "posture_window_s"),
        ("pose", "posture_alert_threshold"),
        ("pose", "min_quality_score"),
        ("pose", "min_visible_keypoints"),
        ("supervision", "too_close_threshold_cm"),
        ("supervision", "too_close_severe_distance_margin_cm"),
        ("supervision", "too_close_severe_relative_multiplier"),
        ("supervision", "too_close_duration_s"),
        ("supervision", "distance_recovery_s"),
        ("supervision", "distance_confidence_grace_s"),
        ("supervision", "presence_grace_s"),
        ("supervision", "bad_posture_duration_s"),
        ("supervision", "posture_recovery_s"),
        ("supervision", "max_study_duration_min"),
        ("supervision", "rest_duration_min"),
        ("supervision", "alert_cooldown_s"),
        ("supervision", "severity_mild_threshold"),
        ("supervision", "severity_moderate_threshold"),
        ("supervision", "severity_severe_threshold"),
        ("supervision", "presence_enter_frames"),
        ("supervision", "presence_exit_frames"),
        ("thermal", "temp_warn_c"),
        ("thermal", "temp_throttle_c"),
        ("thermal", "throttle_recover_margin_c"),
        ("thermal", "temp_check_interval_s"),
        ("thermal", "throttle_inference_fps"),
        ("process", "status_log_interval_s"),
    ]:
        _require_positive(config, section, key)

    camera_view = config["pose"]["camera_view"]
    if camera_view not in {"front", "side"}:
        raise ValueError("config.pose.camera_view must be 'front' or 'side'")

    if config["distance"]["max_cm"] <= config["distance"]["min_cm"]:
        raise ValueError("config.distance.max_cm must be greater than min_cm")

    if config["supervision"]["too_close_threshold_cm"] < config["distance"]["min_cm"]:
        raise ValueError("config.supervision.too_close_threshold_cm must be >= config.distance.min_cm")

    if config["supervision"]["too_close_severe_relative_multiplier"] < 1.0:
        raise ValueError("config.supervision.too_close_severe_relative_multiplier must be >= 1.0")


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
