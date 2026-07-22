# ROS 1 Noetic 适配层

该 Catkin 包提供一个保守的 `move_base` action 局部目标桥接和 `odom → base_link` TF 读取，不发布 `/cmd_vel`。默认目标坐标系为 `odom`；节点启动后仅检查 action server 并保持空闲，不会自行发送目标。

本项目不依赖全局地图。只有现场确认该 `move_base` 实例使用滚动局部 costmap、接受 `odom` 短距离目标、取消语义有效，并且里程计/TF 与安全检查全部通过后，才允许调用。若平台 `move_base` 强制依赖静态地图或全局定位，则不用该适配器，改接厂商成熟局部 RCS；如果只有 `/cmd_vel`，项目维持 Mock，不自行开发底盘控制器。

```bash
source /opt/ros/noetic/setup.bash
catkin_make -C ros1_ws
source ros1_ws/devel/setup.bash
rosrun object_nav_ros move_base_adapter_node.py
```
