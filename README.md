# RY Aletheia 自动测试平台

RY Aletheia 是部署在机器人小车本机的离线自动测试平台，用于管理测试用例、恢复受控运行依赖、执行多轮任务、记录多地图轨迹，并生成可离线查看的测试报告。

它不替代小车已有的导航、定位、地图或安全控制系统；实时页面仅用于只读观察地图、车体、虚拟墙、点云和按需图像。

## 快速开始

目标小车应已具备 ROS 2 Humble 基础运行环境。首次安装完整离线包后，以普通账户启动：

```bash
sudo dpkg -i ./ry-aletheia_<版本号>_amd64.deb
ry-aletheia
```

测试电脑与小车连接同一 Wi-Fi 后，在浏览器打开：

```text
http://<小车IP>:8087
```

已部署旧版本时，优先在“运行配置 → 工具离线升级”上传 `ry-aletheia_<版本号>.zip`；无需重新安装 DEB。

完整安装、移动端使用、页面操作、人工恢复、升级和常见问题请阅读 [USER_GUIDE.md](USER_GUIDE.md)。

## 版本与发布

当前正式版本为 `v1.0.0`。发布包仅通过 [GitHub Releases](https://github.com/Bobiloveu/ry-aletheia/releases) 交付：

- `ry-aletheia_1.0.0.zip`：已安装工具的小车在网页中离线升级使用。
- `ry-aletheia_1.0.0_amd64.deb`：新小车首次部署或需要完整重装时使用。

仓库中的 `releases/` 是本地构建输出目录，默认不纳入版本控制；不要将 ZIP、DEB、日志、报告或车辆配置提交到源码仓库。

## 主要能力

- 测试用例导入、校验、别名管理及跨车用例包交付。
- 多轮串行测试、场景前置参数受控替换、Supervisor 依赖编排与人工恢复。
- 多地图轨迹、理想路径与虚拟墙证据，以及 HTML/CSV 离线报告。
- 低延迟实时二维观测：地图、车体、点云、虚拟墙和按需图像。
- PC 桌面布局与独立移动端界面；手机实时观测支持横竖屏全屏地图。
- 完整离线 DEB 可内置工具私有 Foxglove Bridge，不改写系统已有 Bridge 或 ROS 环境。

## 系统结构

```text
浏览器（PC / 手机）
  ├─ HTTP :8087：控制台、任务、报告与配置
  └─ WebSocket :8767：实时观测直连
             │
RY Aletheia（小车普通账户）
  ├─ Python 控制台与测试编排
  ├─ C++ 实时预处理：/livox/points 或 /livox/lidar → 网页专用点云/位姿流
  └─ 工具私有 Foxglove Bridge（按需启动）
             │
小车已有 ROS 2 Humble、定位、地图、导航与传感器节点
```

实时位姿和点云分别使用网页专用流，浏览器侧采用独立连接与“只保留最新帧”策略，避免大点云帧拖慢车体显示。

## 文档

| 文档 | 面向对象 | 内容 |
| --- | --- | --- |
| [USER_GUIDE.md](USER_GUIDE.md) | 测试人员、部署人员 | 安装、启动、页面操作、手机端、执行测试、升级、卸载与常见问题。 |
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | 开发、维护人员 | 架构、数据边界、实时链路、构建、测试与现场排障。 |
| [live_preprocessor/README.md](live_preprocessor/README.md) | C++ 模块维护人员 | 实时点云/位姿预处理节点的构建与运行参数。 |
| [GitHub Releases](https://github.com/Bobiloveu/ry-aletheia/releases) | 发布与部署人员 | 下载正式 ZIP 与 DEB 发布包。 |

## 仓库结构

```text
autodrive_console/  Python 业务模块、正式网页资源与移动端壳层
frontend/            Vue/Vite 前端源码
live_preprocessor/   ROS 2 C++ 实时点云与位姿预处理节点
tests/               自动化回归测试
docs/images/         用户操作指南配图
packaging/           Debian 安装、启动与卸载脚本
build_*.sh           构建离线依赖、二进制和 DEB 的脚本
make_upgrade.sh      生成网页升级 ZIP 与完整离线 DEB 的发布入口
```

## 开发与验证

开发和构建依赖小车导出的 ROS 2 Humble 离线环境。完整前置条件、命令和发布检查表见 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)。代码修改后的基础验证：

```bash
python3 -m pytest -q tests
cd frontend && npm run check
```

## 支持与反馈

提交问题时请附上工具版本、复现步骤、页面截图和“工具日志”导出的诊断文件。日志可能包含内部节点、端口和运行信息，请勿公开其中的敏感环境数据。
