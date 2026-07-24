# GM461-E1 真机 RGB-D 联合验证（2026-07-23）

## 已验证

- Camport 4.2.10 在隔离的 ROS Noetic/Focal 容器中识别 GM461-E1。
- 新增只读同步桥接，向宿主提供 BGR、注册米制 XYZ、CameraInfo、帧 ID 和时间戳。
- 实测输出为 640×480，帧 ID 为 `camera_rgb_optical_frame`；RGB 与注册点云时间差为
  0 秒，短测平均有效深度比例约 66%。
- 30 秒真机录制取得 63 帧；YOLO-World CUDA 检测到 `book` 30 次、`chair` 24 次。
- 使用同一录制离线回放，检测计数完全一致，滚动栅格正常生成。
- 检测框中央区域的米制深度统计与相机坐标反投影能够成功；推理后超过 0.5 秒的
  数据按安全规则拒绝为 `stale_frame`。
- 因为 `camera_rgb_optical_frame → base_link → odom` 尚未确认，真机验收不得把
  相机坐标冒充局部目标位姿；TF 缺失时必须拒绝输出局部导航目标。
- 接入后审查与补充测试：28 passed，20 subtests passed。
- 全部真机与回放验证的运动命令计数均为 0。

## 当前限制

- 相机已固定但尚未测量 `camera_rgb_optical_frame → base_link` 静态外参，因此真机地图
  当前明确标记为 `camera_optical_xz_diagnostic`，只用于静态数据链路和地图更新验证。
- 没有机器人 odom、动态 TF、激光和安全链路；不得启用真实导航或把诊断地图用于运动。
- Viewer 与 Camport ROS 驱动需要独占相机，联调时先停止 Viewer 服务。
