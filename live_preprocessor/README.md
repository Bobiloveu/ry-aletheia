# Aletheia 实时点云预处理节点

该节点只在实时观测开启时使用：以深度 1、best-effort 接收导航实际使用的 `/collision_voxel_layer/points` 最新帧，最多按 10 Hz 将标准 `float32 x/y/z` 点云转换到 `map` 坐标并均匀抽样为不超过 5000 点的 `/_aletheia/live_points`。主话题连续 500ms 未到达时，才回退读取 `/livox/lidar` 的原生 `livox_ros_driver2/CustomMsg`；两路不会混合。输出话题使用 reliable、depth 1，以兼容 Foxglove Bridge 的可靠订阅，同时不积压历史扫描。`/_aletheia/*` 是 ROS 2 hidden 命名空间，默认不在 RViz 的常规话题列表显示。

它不使用 PCL、不缓存历史帧、不修改机器人导航数据。TF 不可用时会丢弃该帧而不是发布猜测坐标。

构建前需要小车 ROS2 环境具备 `ament_cmake`、`rclcpp`、`sensor_msgs`、`tf2_ros` 的 C++ 开发头文件：

```bash
source /opt/ry/install/setup.bash
colcon build --packages-select aletheia_live_preprocessor
```

运行示例：

```bash
ros2 run aletheia_live_preprocessor aletheia_live_cloud --ros-args \
  -p input_topic:=/collision_voxel_layer/points -p output_topic:=/_aletheia/live_points \
  -p rate_hz:=10.0 -p max_points:=5000
```
