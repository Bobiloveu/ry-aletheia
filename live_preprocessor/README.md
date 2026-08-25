# Aletheia 实时点云预处理节点

该节点只在实时观测开启时使用：以深度 1、best-effort 接收导航实际使用的 `/collision_voxel_layer/points` 最新帧，最多按 10 Hz 将标准 `float32 x/y/z` 点云投影到 `map` 坐标并均匀抽样为不超过 3000 点。主话题连续 500ms 未到达时，才回退读取 `/livox/lidar` 的原生 `livox_ros_driver2/CustomMsg`；两路不会混合。

预处理结果不会再发布 ROS hidden topic。点云和位姿各自写入独立的最新数据槽，再由后台线程经回环 UDP 发送给 Aletheia 专用遥测网关；网关只组装最新完整帧并通过 Binary WebSocket 交给浏览器。此链路没有 ACK、重传、历史队列或通用 ROS-Web Bridge，网络抖动时会直接恢复到最新数据。

它不使用 PCL、不缓存历史帧、不修改机器人导航数据。TF 不可用时会丢弃该帧而不是发布猜测坐标。

构建前需要小车 ROS2 环境具备 `ament_cmake`、`rclcpp`、`sensor_msgs`、`tf2_ros` 的 C++ 开发头文件：

```bash
source /opt/ry/install/setup.bash
colcon build --packages-select aletheia_live_preprocessor
```

运行示例：

```bash
ros2 run aletheia_live_preprocessor aletheia_live_cloud --ros-args \
  -p input_topic:=/collision_voxel_layer/points \
  -p rate_hz:=10.0 -p max_points:=3000 -p telemetry_udp_port:=8769
```
