# ShmSDK 四路物理相机接入试运行记录（2.3.8）

> 状态：**试运行中，不是正式架构定版。**
>
> 记录日期：2026-08-31。适用范围仅为 RY Aletheia 的低延迟视频旁路；不改变小车自动驾驶、相机驱动、`mempool`、目标检测、可通行区域分割、MediaMTX、WebRTC、地图、点云、位姿、任务或报告。

## 1. 本次试运行的目的与边界

小车的下列四个原 ROS 图像话题已无数据输出：

- `/front_camera/image_raw`
- `/back_camera/image_raw`
- `/left_camera/image_raw`
- `/right_camera/image_raw`

2.3.8 只将 Aletheia 视频旁路的四路**输入**改为读取已安装 ShmSDK 2.0 的最新图像：

| Aletheia 流 | ShmSDK 固定通道 | 读取方式 |
| --- | --- | --- |
| `front_camera` | `CamFront` | `GetLastCamImage`，只保留最新帧 |
| `back_camera` | `CamBack` | `GetLastCamImage`，只保留最新帧 |
| `left_camera` | `CamLeft` | `GetLastCamImage`，只保留最新帧 |
| `right_camera` | `CamRight` | `GetLastCamImage`，只保留最新帧 |

接入程序只读打开 ShmSDK 通道，取得 JPEG 后在 Aletheia 自身进程内解码成 RGB，随后沿用既有 `rawvideoparse → videoconvert → VAAPI H.264 → MediaMTX → WHEP/WebRTC` 链路。

### 明确不在本次范围内

- 不启动、停止、配置或重启 `mempool`；
- 不打开 USB 设备、不使用 `/dev/video*`、不维护 V4L2 映射；
- 不修改 ROS 相机驱动、定位、导航、雷达、底盘或 Supervisor；
- 不修改 `/rfdetr_detect`（目标检测）和 `/segmentation/overlay`（可通行区域分割）的 ROS 图像输入；
- 不修改实时观测点云/位姿、地图、任务、报告、HTTP API、MediaMTX 或 WebRTC 协议。

## 2. 已完成的接入验证

现场已手动将小车控制台升级为 **2.3.8**，并确认：

- `/api/system/upgrade` 返回 `current_version: 2.3.8`；
- 四路物理流进程分别以 `--input-kind shmsdk --shm-channel CamFront|CamBack|CamLeft|CamRight` 启动；
- `detection_camera` 与 `segmentation_overlay` 仍以 `--input-kind ros` 订阅原有的 `/rfdetr_detect`、`/segmentation/overlay`；
- `/api/video/status` 显示六路流在线，MediaMTX 的六个 H.264 path 均为 `ready` 且持续有入站数据；
- 视频运行日志已记录 ShmSDK 通道打开、首帧的编码/分辨率和输入就绪信息。

这些结果只证明“当前接入可工作”，不代表长期稳定性、CPU 预算、断开恢复能力或所有相机状态已经通过验收。

## 3. 试运行观察清单

每次观察前先确认没有执行中或待恢复的测试。只通过网页打开所需视频流；关闭最后一路后确认视频旁路进程被回收。

| 观察项 | 应有表现 | 异常时先保留的证据 |
| --- | --- | --- |
| 四路物理画面 | 各自对应正确方向；无长期黑屏、半幅、花屏、错帧或冻结 | 出现时间、流名称、浏览器截图、工具日志下载包 |
| 重复开关视频 | 多次开启/关闭后仍能在合理等待时间内恢复最新画面 | `/api/video/status`、`logs/video-runtime.log` |
| 六路同时开启 | 四路物理画面与检测/分割均保持可用；单路异常不影响其他路 | MediaMTX path 状态、各路编码器状态 |
| 检测/分割隔离 | `/rfdetr_detect`、`/segmentation/overlay` 仍按原 ROS 输入工作 | 对应 ROS 图像话题、视频日志 |
| 资源 | 以小车本机 `htop` 记录 Aletheia 主进程、各视频输入进程和 MediaMTX 的 CPU/内存；不以浏览器电脑数据代替 | `htop` 截图、视频开启路数、观察时长 |
| 关闭视频后的恢复 | 视频旁路资源被回收；地图、点云、位姿、任务页面不受影响 | `ry-aletheia-status --once`、工具日志 |

## 4. 停止试运行与回退条件

出现下列任一情况，不要尝试通过改动相机驱动或 `mempool` 自行修复；先关闭视频、导出日志并通知维护人员：

1. 任一路持续黑屏、花屏、冻结或显示了错误相机画面；
2. 重复开关后无法恢复，或视频进程持续异常退出；
3. 同时开启多路后明显影响自动驾驶相关进程、导航安全或系统稳定性；
4. ShmSDK 日志持续报告无法打开通道、持续没有新图像或 JPEG 解码失败；
5. 检测/分割、地图、点云、位姿、任务或报告出现与本次接入有直接关联的回归。

## 5. 已准备的安全回退

回退基线是升级前在小车上保留的 **2.3.7** 程序二进制。已核对该备份与本地正式发布包中的 `ry-aletheia` 二进制完全一致，因此无需为本次试运行另行制作包；直接保留并使用既有的已签名正式 ZIP：

```text
releases/2.3.7/ry-aletheia_2.3.7.zip
```

核对记录：小车备份与该 ZIP 内二进制的 SHA-256 均为 `9c86e48c8f86cda598a6aa34ebb1b5132f7aa42508a929f448806e3e38d64d00`，大小均为 `69,827,600` Byte。该 ZIP 本身的 SHA-256 为 `1118cac64cd7f4eca6c1c50d1ff42f9bbeaa9ca6d6e7da243a2dce0097169e80`，并已通过 ZIP 结构和 Ed25519 签名校验。ZIP 仅包含 `manifest.json` 和 `ry-aletheia`；不会包含小车配置、视频配置、日志、地图或私钥。

### 回退操作（现场人员）

1. 确认没有 `running`、`cancelling` 或 `awaiting_recovery` 的测试；若有，先按页面流程结束或恢复。
2. 关闭所有低延迟视频流，等待页面显示视频已关闭。
3. 打开“运行配置 → 工具离线升级”，上传 `releases/2.3.7/ry-aletheia_2.3.7.zip`；**不要解压 ZIP**。
4. 点击“校验并应用升级”，等待签名和 SHA-256 校验完成、控制台自动重启。
5. 刷新浏览器并确认版本显示为 `2.3.7`；再由维护人员核对四路物理相机已恢复为原 ROS 输入方式。

升级器会先原子保存当前 2.3.8 为唯一 `updates/backups/ry-aletheia.bak`，再替换为 2.3.7。因此回退后仍保有返回 2.3.8 的一个受控备份。不要手工覆盖 `dist/ry-aletheia`，不要删除 `updates/backups/`，不要复制系统库，也不要停止小车已有相机驱动、`mempool`、定位、导航或 Supervisor。

## 6. 构建记录与维护要求

- 2.3.8 试运行包经过项目 Python 测试、前端生产构建、C++ `aletheia_video_ingest` 编译、ZIP 结构与 Ed25519 签名验证；
- 回退包必须由与当前控制台内置公钥匹配的发布私钥签名。任何未签名、自行解压重打包或来自其他分支的 ZIP 都会被拒绝；
- 回退包生成后，维护人员必须执行 `unzip -t`、核对清单版本/哈希/签名，并在隔离临时目录通过 `UpgradeManager` 验证；
- 本试运行记录、`config/video.json` 的输入契约和实际升级版本需要一同保留，直到现场明确验收或明确回退。

## 7. 验收后的后续动作

现场验收通过后，仍需单独评审是否将 ShmSDK 接入转为正式基线；评审至少应包含稳定性、CPU/内存、开关恢复、六路共存和回退演练。未完成该评审前，后续维护必须继续将其标记为“试运行”。
