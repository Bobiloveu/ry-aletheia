# 最小小车构建依赖

本目录保存经授权可随源码交付的最小 ROS 2 构建覆盖层，不是完整的小车 `install/`。

当前压缩包只包含：

- `master_interfaces`：RY Aletheia 调用小车业务服务所需的 Python 接口和 ROSIDL 类型支持库；
- `livox_ros_driver2`：编译实时点云预处理节点所需的 Livox `CustomMsg` C++ 接口；
- 根 `setup.bash`、`local_setup.bash` 与加载工具。

接收方仍需要 Ubuntu 22.04 `amd64`、系统 ROS 2 Humble，以及 Pixi 管理的本工程通用工具链。

## 使用

在工程根目录执行：

```bash
(cd third_party/robot_build_deps && \
  sha256sum -c ry-aletheia-robot-build-deps-humble-amd64.tar.gz.sha256)
tar -xzf third_party/robot_build_deps/ry-aletheia-robot-build-deps-humble-amd64.tar.gz -C .
pixi install
pixi run frontend-install
pixi run bash ./build_binary.sh
```

## 更新依赖包

仅在已验证、与目标车匹配的参考小车上更新。执行前确认具有向本仓库分发 `master_interfaces` 和 `livox_ros_driver2` 的权限：

```bash
./export_robot_build_deps.sh \
  third_party/robot_build_deps/ry-aletheia-robot-build-deps-humble-amd64.tar.gz
```

该脚本同时生成同名 `.sha256` 校验文件。归档会排除 Python 缓存、Livox 启动脚本与设备 IP 配置；不得将完整 `install/`、地图、任务、日志或机器人配置放入本目录。
