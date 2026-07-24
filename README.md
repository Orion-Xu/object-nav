# GM461-E1 文字目标导航与静态避障 Demo

这是一个默认安全、可重复的“目标可见条件下短距离局部导航与静态避障”原型。系统不建立、不加载也不依赖预建全局地图：只有目标已在当前视野连续三帧确认，才使用 RGB-D、短时里程计和滚动局部代价图生成短距离接近建议。当前视野无目标、目标丢失、局部路径被阻或安全状态未知时停止。文字和视觉不会直接发布 `/cmd_vel`；现场接口与安全条件通过前只使用 `MockNavigationAdapter`。

## 协作者首次安装：从空电脑到运行 YOLO-World

下面以一台 Ubuntu 22.04 电脑为例。请按顺序逐条执行，不要跳过错误继续往下运行。
本项目当前基准环境是 Python 3.10、PyTorch 2.11.0、CUDA 12.8 运行库和
Ultralytics 8.4.102。NVIDIA 驱动由电脑系统提供，不放在 Python 虚拟环境中。

### 第 0 步：获得协作权限

仓库是公开仓库，任何人都可以查看和下载。但是公开不等于任何人都能向 `main`
推送代码。仓库所有者仍需在 GitHub 网页执行：

1. 打开 `https://github.com/Orion-Xu/object-nav`。
2. 进入 `Settings`。
3. 进入 `Collaborators`。
4. 点击 `Add people`，输入协作者的 GitHub 用户名。
5. 被邀请账号在 GitHub 通知或邮箱中接受邀请。

只想运行、不需要提交代码的人可以跳过协作者邀请。

### 第 1 步：检查操作系统、Python 和显卡

打开终端，执行：

```bash
lsb_release -ds
python3 --version
nvidia-smi
```

期望看到 Ubuntu 22.04、Python 3.10，并且 `nvidia-smi` 能列出 NVIDIA 显卡。
设备的显卡型号不必与 RTX 4060 完全相同，但驱动必须足够新，能够运行项目安装的
CUDA 12.8 PyTorch。如果 `nvidia-smi` 本身报错，应先安装或修复 NVIDIA 驱动，
不要先排查 YOLO-World。

### 第 2 步：安装系统基础软件

```bash
sudo apt update
sudo apt install -y git curl zsh python3 python3-venv python3-tk libgl1 libglib2.0-0
```

这些软件分别用于下载源码、下载测试图片、进入与本项目一致的 Zsh 环境、创建隔离的
Python 环境、打开 Tkinter GUI，以及支持 OpenCV 图形库。系统询问密码时输入当前
Ubuntu 账号的登录密码；输入密码时终端不显示字符是正常现象。

### 第 3 步：下载完整源码和第三方子模块

先进入希望保存项目的位置，例如桌面：

```bash
cd ~/桌面
git clone --recurse-submodules https://github.com/Orion-Xu/object-nav.git
cd object-nav
```

`--recurse-submodules` 会同时下载 `navigation_msgs` 和官方 `camport_ros` 的固定版本。
下载完成后检查：

```bash
git submodule status
git status
```

两个子模块行首应显示提交编号，`git status` 应显示工作区没有需要提交的修改。如果之前
忘记写 `--recurse-submodules`，进入项目目录后补执行：

```bash
git submodule update --init --recursive
```

### 第 4 步：配置当前提交者的 Git 姓名和邮箱

下面的占位内容必须替换为实际提交者的信息，不能沿用其他人的身份：

```bash
git config --local user.name "实际姓名"
git config --local user.email "GitHub 邮箱"
```

检查是否写入成功：

```bash
git config --local --get user.name
git config --local --get user.email
```

`--local` 表示配置只对当前项目生效，不会影响这台电脑上的其他仓库。

### 第 5 步：安装完整 YOLO-World 视觉环境

必须位于 `object-nav` 项目根目录，然后执行：

```bash
./scripts/install_vision_env.sh
```

该脚本会自动完成以下工作：

1. 创建项目专用的 `.venv`，避免污染系统 Python。
2. 安装 PyTorch 2.11.0 和 CUDA 12.8 版本运行库。
3. 安装固定版本的 Ultralytics、ONNX Runtime、OpenCV、Open3D 和 pytest。
4. 从 OpenAI 官方仓库安装固定提交版本的 CLIP。
5. 以可编辑模式安装本项目的 `object-nav` 和 `object-nav-ui` 命令。

PyTorch 和视觉依赖体积较大，安装过程可能需要较长时间。只要终端仍在下载或安装，
就不要关闭窗口。脚本安装完成后会重新生成环境清单，其中含有当前电脑的本地路径；
为了避免把本机路径误提交到 GitHub，执行：

```bash
git restore environment.lock.txt
```

### 第 6 步：进入项目视觉环境

安装脚本结束后进入 Zsh，再激活项目环境：

```bash
zsh
source scripts/activate_vision.zsh
```

看到类似下面的输出表示激活成功：

```text
ObjectNav vision environment: .../object-nav/.venv
```

检查当前 Python 是否来自项目目录：

```bash
which python
python --version
```

`which python` 的结果应包含 `object-nav/.venv/bin/python`。以后每次新开终端，都要先
进入项目并重新执行：

```bash
cd ~/桌面/object-nav
zsh
source scripts/activate_vision.zsh
```

如果项目没有放在桌面，请把 `~/桌面/object-nav` 换成实际路径。

### 第 7 步：下载并生成所有模型文件

确认视觉环境已激活，然后执行：

```bash
python scripts/prepare_models.py
```

脚本会下载 YOLOv8s-Worldv2、YOLOv8n 和 CLIP ViT-B/32，并生成本项目离线词表模型
和 YOLOv8n ONNX 降级模型。模型很大，因此不会提交到 GitHub，每台电脑都需要单独
执行一次。完成后检查：

```bash
ls -lh models/
```

至少应该看到：

```text
yolov8s-worldv2.pt
yolov8s-worldv2-objectnav.pt
yolov8n.pt
yolov8n.onnx
manifest.json
clip/
```

### 第 8 步：验证 CUDA 和全部视觉后端

先下载一张公开测试图片到 Git 已忽略的数据目录：

```bash
curl -L https://ultralytics.com/images/bus.jpg -o data/input/bus.jpg
```

再运行完整视觉检查：

```bash
python scripts/verify_vision.py data/input/bus.jpg
```

输出是 JSON。重点检查：

- `cuda.available` 应为 `true`。
- `cuda.device` 应为 `cuda:0`。
- `yolo_world` 应输出模型名称和检测结果。
- `onnx_cpu` 应显示 `CPUExecutionProvider`。
- `clip_cpu` 应输出两个分数。
- `open3d.point_count` 应为 `1`。

也可以单独检查 PyTorch 是否识别显卡：

```bash
python -c 'import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU")'
```

如果显示 `False`，先对比 `nvidia-smi` 是否正常；这通常是驱动问题，不是词表或 GUI
问题。没有可用 NVIDIA GPU 时仍可使用 CPU，但速度不会与你的 GPU 电脑一致。

### 第 9 步：运行自动化测试和 Mock 闭环

```bash
python -m pytest -q
object-nav parse "帮我找一下椅子"
object-nav demo "寻找椅子" --log logs/demo.jsonl
```

当前预期是测试全部通过，解析结果包含 `"accepted": true`，Mock 闭环最终包含
`"state": "ARRIVED"`。Mock 只操作模拟导航适配器，不连接机器人，也不发布
`/cmd_vel`。

### 第 10 步：启动 YOLO-World GUI

```bash
object-nav-ui
```

窗口打开后按以下顺序测试：

1. 查看顶部是否显示“YOLO-World GPU 已就绪”。
2. 在输入框输入“寻找椅子”。
3. 点击“只解析”，确认状态不是 `FAILED`。
4. 点击“用 YOLO-World 检测图片”，选择 `data/input/bus.jpg`。
5. 检测完成后确认界面显示模型检测结果和 `YOLO-World cuda`。
6. 如电脑连接了普通 USB 摄像头，点击“实时摄像头”，先输入编号 `0`。
7. 结束实时检测时点击“停止/复位”，确保摄像头被释放。

GM461-E1 是 GigE 深度相机，一般不会显示成 OpenCV 编号 `0`。USB 摄像头或视频模式
成功，只能证明 YOLO-World GUI 正常；GM461-E1 还需通过 Camport SDK/ROS 适配层
提供 RGB、Depth、CameraInfo 和点云。

### GM461-E1 真机 RGB-D、YOLO-World 与滚动地图

先关闭 Percipio Viewer，避免它与 ROS 驱动同时占用相机。构建并启动只读桥接：

```bash
./scripts/build_camport_container.sh
./scripts/run_percipio_bridge.sh
```

另开终端激活视觉环境，运行 30 秒联合验收：

```bash
.venv/bin/python scripts/verify_percipio_live.py --duration 30
```

数据默认保存在仓库内已忽略的 `data/recordings/`，不会进入 Git。也可以把录制目录
复制到项目外长期归档。离线回放：

```bash
.venv/bin/python scripts/verify_percipio_recording.py \
  data/recordings/<时间戳>
```

GUI 在桥接运行时可点击“GM461 RGB-D”。桥接只订阅 RGB、CameraInfo 和注册点云，
只监听本机回环地址；项目仍不发布 `/cmd_vel`。在
`configs/system.yaml` 中将 `camera.extrinsics.calibrated` 设为 `true` 前，滚动地图
只以 `camera_optical_xz_diagnostic` 标识进行静态诊断，不能当作已标定的
`base_link` 安全地图。

### 第 11 步：最后检查 Git 工作区

```bash
git status
```

`.venv/`、`models/`、`data/input/`、`data/recordings/` 和日志已被忽略，不应该进入提交。如果状态中出现
账号、模型、图片、录制数据或个人资料，不要执行 `git add .`，先确认文件是否应该提交。

## 两人日常同步：每次修改代码都按这个顺序

本项目目前采用简单的 `main` 协作方式。两个人开始工作前先在聊天中说明准备修改的
文件，尽量不要同时修改同一个文件或同一段代码。

### 开始工作前

```bash
cd ~/桌面/object-nav
git pull --rebase
git submodule update --init --recursive
git status
```

`git pull --rebase` 获取对方刚推送的进度；`git status` 应确认当前工作区干净。

### 修改完成后

先运行测试：

```bash
source .venv/bin/activate
python -m pytest -q
```

查看具体修改，不要直接盲目提交所有文件：

```bash
git status
git diff
```

只添加本次真正修改的文件，例如：

```bash
git add README.md src/object_nav_demo/command_parser.py tests/test_core.py
git status
```

提交信息应直白说明完成了什么：

```bash
git commit -m "完善中文目标解析测试"
```

推送前再同步一次，避免覆盖对方的新提交：

```bash
git pull --rebase
git push
```

如果 `git pull --rebase` 提示冲突，不要删除对方代码，也不要使用 `git reset --hard`。
先执行下面的命令退出本次变基，再与对方确认由谁处理冲突：

```bash
git rebase --abort
```

## 常见安装问题

### `Permission denied`，安装脚本不能执行

```bash
chmod +x scripts/install_vision_env.sh
./scripts/install_vision_env.sh
```

### 子模块目录为空

```bash
git submodule update --init --recursive
```

### 终端提示找不到 `object-nav-ui`

```bash
source .venv/bin/activate
python -m pip install -e . --no-deps
```

### Tkinter 报错或 GUI 无法创建窗口

```bash
sudo apt install -y python3-tk
```

需要在有图形桌面的本机终端启动 GUI；纯 SSH 或无显示器环境还需要额外的图形转发。

### 摄像头编号 `0` 打不开

```bash
ls -l /dev/video*
```

如果存在 `/dev/video1`，可在 GUI 中尝试编号 `1`。GM461-E1 是 GigE 相机，不应通过
不断更换 OpenCV 编号来接入。

### 每次打开新终端后模块又找不到

虚拟环境不会跨终端自动保持。重新执行：

```bash
cd ~/桌面/object-nav
source .venv/bin/activate
```

## 禁止上传的内容

不要提交 `.venv/`、`models/`、模型权重、日志、相机录制、客户资料、个人实习材料、
GitHub Token、设备密码、内部网络地址或含敏感内容的图片。公开仓库中的任何提交都可能
被他人复制；即使之后删除文件，敏感内容仍可能保留在 Git 历史中。

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
