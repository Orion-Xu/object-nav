# 环境验证记录（2026-07-21）

- Python 3.10.12；虚拟环境 `.venv`；冻结依赖见 `environment.lock.txt`。
- PyTorch 2.11.0+cu128：`torch.cuda.is_available() == True`。
- GPU：NVIDIA GeForce RTX 4060 Laptop GPU，驱动 575.57.08，显存 8188 MiB。
- Ultralytics 8.4.102；YOLOv8s-worldv2 离线词表模型已生成。
- 官方 `bus.jpg` 冒烟测试：YOLO-World 在 `cuda:0` 检出 4 个 person 候选。
- YOLOv8n ONNX：ONNX Runtime CPUExecutionProvider 推理成功，输出形状 `[1, 84, 8400]`。
- CLIP ViT-B/32 CPU：图像与 `a photo of a bus` 的两类归一化分数为 0.99998。
- Open3D 0.19.0：点云对象创建成功。
- 自动化测试：初始环境验收 15 passed；2026-07-22 无地图范围及实时检测变更后为 17 passed，20 subtests passed。
- ROS 1 Catkin：`move_base_msgs`、`map_msgs`、`object_nav_ros` 编译通过；`move_base` 仅保留为可选 `odom` 局部目标桥接，不作为全局地图依赖。
- 安全扫描：未发现 `/cmd_vel` Publisher 或发布命令。
- Camport Noetic 容器：官方驱动编译通过；枚举程序正常启动；当前未连接设备。
- Tkinter GUI：窗口 `GM461-E1 文字目标 Demo（离线）` 已启动并由 X11 窗口树确认，尺寸 980×720。
- Tkinter 实时检测：已增加 OpenCV 摄像头和视频文件入口；采集线程仅保留最新帧，推理线程显示检测框、推理 FPS、端到端延迟及目标连续确认计数。
- 实时链路冒烟测试：使用 45 帧合成 MJPEG 视频和本地 `YOLOv8s-worldv2-objectnav.pt` 在 CPU 上完成采集、最新帧读取和推理。

2026-07-22 已将项目边界改为目标可见条件下的短距离无地图局部导航：不加载全局地图、不访问观察点，使用 `odom → base_link → camera_link`、滚动局部图和分段重规划。

尚未验收：真实 GM461-E1 数据及其实时 SDK/ROS 图像适配、机器人 ROS Master、里程计/局部 TF、滚动局部代价图、成熟局部控制器或厂商 RCS 写接口，以及全部平台安全链路。因此真实导航保持禁用。
