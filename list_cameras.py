#!/usr/bin/env python3

import sys
sys.path.insert(0, '/usr/lib/python3/dist-packages')

from picamera2 import Picamera2

print("Picamera2.global_camera_info():")
try:
    cams = Picamera2.global_camera_info()
    print(f"Found {len(cams)} cameras:")
    for i, cam in enumerate(cams):
        print(f"  [{i}] {cam}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("Trying to enumerate via other means...")

import ctypes
libcamera = ctypes.CDLL('libcamera.so.0.2', use_errno=True)
print("libcamera loaded")
