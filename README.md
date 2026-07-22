# GM461-E1 文字目标导航与静态避障 Demo

这是一个默认安全、可重复的“目标可见条件下短距离局部导航与静态避障”原型。系统不建立、不加载也不依赖预建全局地图：只有目标已在当前视野连续三帧确认，才使用 RGB-D、短时里程计和滚动局部代价图生成短距离接近建议。当前视野无目标、目标丢失、局部路径被阻或安全状态未知时停止。文字和视觉不会直接发布 `/cmd_vel`；现场接口与安全条件通过前只使用 `MockNavigationAdapter`。

## 第一次下载项目（给协作者）

仓库包含两个固定版本的第三方 ROS 子模块，因此第一次下载要使用
`--recurse-submodules`：

```bash
git clone --recurse-submodules https://github.com/Orion-Xu/object-nav.git
cd object-nav
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pytest -q
```

如果已经普通克隆、发现子模块目录为空，可在项目目录补执行：

```bash
git submodule update --init --recursive
```

模型权重体积较大，不提交到 GitHub。需要真实 YOLO 推理时执行：

```bash
source .venv/bin/activate
python -m pip install -r requirements-vision.txt
python scripts/prepare_models.py
```

不下载模型也能运行固定随机种子的 Mock 闭环和自动化测试。

## 两人日常同步（简单方式）

开始修改前先获取对方的最新进度：

```bash
git pull --rebase
git submodule update --init --recursive
```

完成一小项并测试后提交：

```bash
git status
git add 你修改的文件
git commit -m "说明本次完成了什么"
git pull --rebase
git push
```

不要两个人同时修改同一段代码。`git status` 用来确认即将提交的文件；不要提交
`.venv/`、`models/`、日志、录制数据、账号信息或实习个人资料。首次在新电脑提交前设置自己的真实身份：

```bash
git config --local user.name "你的姓名"
git config --local user.email "你的 GitHub 邮箱"
```

## 已配置环境与 GUI

```bash
source scripts/activate_vision.zsh
object-nav-ui
```

GUI 提供中文指令解析、当前视野三帧确认的 Mock RGB-D 局部闭环、单张图片检测，以及摄像头/视频文件 YOLO-World 实时检测。实时模式将采集和推理解耦，只保留最新帧，显示检测框、推理 FPS、端到端延迟和目标确认进度。YOLO-World 按需加载到 GPU；实时检测只显示结果，不连接真实底盘，也不发布 `/cmd_vel`。

实时模式：

1. 点击“实时摄像头”，输入 OpenCV 设备编号（通常为 `0`）；或点击“实时视频”选择文件。
2. 如需三帧目标确认，先在指令框输入“寻找椅子”等合法指令；未输入时显示全部检测。
3. 点击“停止/复位”释放摄像头并停止推理。

GM461-E1 为 GigE 相机，通常不直接表现为 `/dev/video*`。当前实时 GUI 已完成可替换采集层；接入 GM461-E1 时需再将 Camport SDK/ROS 的 RGB 帧适配到同一最新帧接口，不能假定摄像头编号 `0` 就是 GM461-E1。

常用命令：

```bash
object-nav list
object-nav parse "帮我找一下椅子"
object-nav demo "寻找椅子" --log logs/demo.jsonl
.venv/bin/python -m pytest -q
.venv/bin/python -m object_nav_demo.cli doctor
```

完整视觉环境：

```bash
./scripts/install_vision_env.sh
source scripts/activate_vision.zsh
python scripts/prepare_models.py
object-nav doctor
```

ROS 环境使用 `source scripts/activate_ros.zsh`，不要同时激活 `.venv`。

GM461-E1 官方 Camport 驱动因宿主 Ubuntu 22.04 与 Noetic/Focal 的 PCL ABI 不同，使用已构建的隔离镜像：

```bash
./scripts/run_camport_container.sh
```

该命令只枚举相机。当前没有接入相机时显示 `Status: No devices found` 属于预期结果。真实采集仍需接上 GM461-E1 后确认 IP、深度单位、时间戳、对齐和外参。

也可不安装：

```bash
PYTHONPATH=src python3 -m object_nav_demo.cli demo "寻找椅子"
```

`demo` 使用固定随机种子的模拟 RGB-D、假检测器、`camera_link → base_link → odom` 模拟 TF 和 Mock 局部目标导航完成闭环。它不会访问地图观察点；当前视野在限定帧数内未确认目标即失败。日志为 JSONL，包含配置/模型版本、状态变化、检测、深度、局部目标、安全决策和导航结果。

ROS 1 Noetic 适配位于 `ros1_ws/src/object_nav_ros`。其中 `move_base` 仅作为可选的平台成熟控制器桥接：必须确认其可在 `odom` 局部目标和滚动 costmap 模式下运行且不依赖静态全局地图；否则使用厂商局部 RCS 或保持 Mock。适配层不包含速度发布器。现场门槛见 [docs/field_integration.md](docs/field_integration.md)。
