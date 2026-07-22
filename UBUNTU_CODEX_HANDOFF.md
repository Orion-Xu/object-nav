# Ubuntu / Codex 项目交接说明

更新时间：2026-07-22

## 当前项目目标

使用屈膝升降式移动机器人和图漾 GM461-E1，实现“目标可见条件下的短距离局部导航与静态避障”Demo。

系统不建立、不加载也不依赖预建全局地图，不使用 AMCL，不访问地图观察点，不承担跨房间 ObjectNav/VLN 或未知环境探索。允许的闭环是：

```text
受控中文指令
→ YAML 词表与物体策略
→ 当前视野 YOLO-World 检测
→ RGB-D 局部三维定位
→ 连续三帧确认
→ odom 局部停靠点
→ 深度/激光滚动局部代价图
→ 短路径、分段执行和滚动重规划
→ ARRIVED 或安全停止
```

目标在任何运动前必须可见并完成三帧确认。当前视野无目标、目标丢失、里程计/TF 失效、局部窗口内无安全路径或安全状态未知时，停止并进入 `STOP/FAILED`。

## 事实与边界

- 平台事实和安全条件以 `新版实习计划VLN/26014-MCM2609-屈膝式类人双臂_四臂机器人（V2-263）.docx` 及现场记录为准，不修改该原始协议。
- 两份当前计划文件已迁移为无地图局部导航：
  - `新版实习计划VLN/实习计划书1 -徐锦彦.docx`
  - `新版实习计划VLN/GM461-E1文字目标导航与静态避障_一个月完整技术路径.docx`
- `旧版实习计划/` 是历史归档，不作为当前实现依据。
- 项目使用 ROS 1 Noetic，而不是 ROS 2/Nav2。
- 仍需要短时 `odom → base_link → camera_link`、实时激光、机器人外形/运动学、制动数据和平台安全链路。
- 视觉模型只能生成目标和局部障碍建议，不能直接控制电机或代替安全信号。

## 当前实现

- `command_ui`：Tkinter 中文指令、Mock 闭环、真实图片 YOLO-World 检测预览。
- `vocabulary_manager` / `command_parser`：配置词表、别名和 `approach/detect_only/disabled` 策略。
- `detector`：假检测器与本地 Ultralytics 权重适配。
- `frame_source`：可注入无效深度、不同步、过期、缺内参和中断的 Mock RGB-D。
- `target_localizer`：中央 ROI 有效深度中位数，输出 `odom` 局部目标。
- `search_manager`：当前视野连续三帧确认；没有地图观察点或导航调用。
- `goal_builder`：在相同局部坐标系内生成朝向目标的停靠点。
- `local_mapping`：当前为短时障碍记忆原型；后续需补完整滚动栅格、射线清空、膨胀和局部路径规划。
- `navigation_adapter`：默认 Mock。ROS `move_base` 仅保留为可选 `odom` 局部目标桥接。
- `safety_arbiter`：安全未知、相机失效、里程计异常、导航异常或路径不安全时拒绝运动。
- `telemetry`：JSONL 状态、检测、局部目标、安全和导航记录。

状态机：

```text
IDLE → PARSE → LOCAL_SEARCH → TARGET_CONFIRMED → LOCAL_PLAN → APPROACH → ARRIVED
```

其中 `LOCAL_SEARCH` 只是限定帧数内的当前视野确认，不产生搜索运动。终态必须显式复位。

## 环境状态

- Ubuntu 22.04.5，Python 3.10.12。
- ROS 1 Noetic 位于 `/opt/ros/noetic`。
- `.venv` 已安装 PyTorch 2.11.0+cu128、Ultralytics、ONNX Runtime、OpenCV、Open3D、CLIP 和测试依赖。
- RTX 4060 Laptop GPU 已通过 CUDA 推理验证。
- `models/yolov8s-worldv2-objectnav.pt`、`models/yolov8n.onnx` 和 CLIP 权重已准备，模型目录不提交 Git。
- GM461-E1 官方 Camport 源码位于 `vendor/camport_ros`。宿主 PCL ABI 不兼容，使用 `object-nav/camport-noetic:local` 容器；驱动已编译并能执行设备枚举，当前没有连接相机。
- `ros1_ws` 已编译。没有机器人 ROS Master，也没有任何实机运动批准。

## 常用命令

视觉与 GUI：

```bash
source scripts/activate_vision.zsh
object-nav-ui
object-nav demo "寻找椅子" --log logs/demo.jsonl
.venv/bin/python -m pytest -q
```

ROS 只读检查：

```bash
source scripts/activate_ros.zsh
scripts/ros1_readonly_inspect.sh
```

相机只读枚举：

```bash
./scripts/run_camport_container.sh
```

## 下一步优先级

1. 接入真实 GM461-E1，记录 RGB、Depth、CameraInfo、点云、深度单位、无效值、同步和帧率。
2. 标定并验证 `camera_link → base_link`，确认底盘 `odom → base_link` 和时间戳。
3. 在离线回放中实现完整 8 m × 8 m 滚动局部栅格：高度过滤、射线清空、0.5—1 s 衰减、0.5 m 起步的保守膨胀。
4. 实现局部 A* 或接入平台成熟局部控制器；每执行 0.3—0.5 m 重新感知、重定位目标和重规划。
5. 增加 `TARGET_NOT_VISIBLE`、`LOCAL_PATH_BLOCKED`、目标丢失、里程计丢失和相机超时测试。
6. 只有急停×2、触边、抱闸、人工接管、声光、激光停障、里程计失效停止、目标丢失停止和局部路径阻塞停止全部通过后，才申请短距离低速运动。

## 安全红线

- 不运行 `rostopic pub /cmd_vel`，不新增绕过平台安全层的速度发布器。
- 不因为取消全局地图就自行开发完整底盘控制器。
- 不在目标未确认时自主前进，不猜测局部窗口之外的路线。
- 不让人员成为自主接近目标。
- 不关闭急停、触边、抱闸、激光停障或人工接管。
- 实机条件不满足时，正式交付离线回放、Mock 局部导航和路径可视化。
