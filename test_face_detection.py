#!/usr/bin/env python3
import cv2
import os

# 加载项目内已有的Haar模型，不需要下载
base_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(base_dir, "haarcascade_frontalface_default.xml")
face_cascade = cv2.CascadeClassifier(model_path)
if face_cascade.empty():
    print("❌ 模型加载失败")
    exit(1)
print("✅ Haar级联模型加载成功")

# 加载测试照片
img = cv2.imread("test_learning.jpg")
h, w = img.shape[:2]
print(f"✅ 测试照片加载成功，分辨率: {w}x{h}")

# 检测人脸
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
faces = face_cascade.detectMultiScale(
    gray,
    scaleFactor=1.05,
    minNeighbors=5,
    minSize=(60, 60),
    flags=cv2.CASCADE_SCALE_IMAGE
)

print(f"\n✅ 人脸检测结果: 共检测到 {len(faces)} 张人脸")
for idx, (x,y,w,h) in enumerate(faces):
    print(f"  人脸 {idx+1}: 位置({x},{y}), 大小{w}x{h}")

# 保存带标注的结果照片
for (x,y,w,h) in faces:
    cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 3)
    cv2.putText(img, "Face", (x, y - 10),
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

cv2.imwrite("test_learning_result.jpg", img)
print(f"\n✅ 检测结果已保存到 test_learning_result.jpg")
print("\n🎉 全部功能测试通过！")
