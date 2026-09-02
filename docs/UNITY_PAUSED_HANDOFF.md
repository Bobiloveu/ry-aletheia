# Unity 嵌入渲染：暂停交接说明

**状态：暂停。** 自 2026-09-02 起，移动端主线固定使用 Flutter `CustomPaint` 渲染地图、虚拟墙、点云、格栅、车辆与比例尺。当前正式包不加载 Unity runtime，也不显示 Unity 启动标识。

## 当前边界

- Flutter 继续持有机器人连接、地图/点云/位姿数据、手势、全屏状态、视频和所有 HMI 业务逻辑。
- Unity 代码仅保留为未来的渲染性能 PoC；不得在没有完整回归验证的情况下作为默认渲染器。
- `mobile/tool/build_mobile_packages.sh` 默认构建 Flutter；只有显式传入 `--engine unity` 才会走原型构建路径。
- `mobile/lib/app/app.dart` 不再挂载 `UnityStartupSplash`，`live_observation_screen.dart` 的渲染器 provider 被固定为 `FlutterVisualizationEngine`。

## 保留的 Unity 资产与入口

| 位置 | 作用 |
| --- | --- |
| `unity/aletheia_viz/` | Unity 工程、场景生成器、地图/点云/车辆 shader 与桥接脚本。 |
| `mobile/packages/aletheia_visualization/` | Flutter plugin、Android/iOS PlatformView 与 FFI bridge。 |
| `mobile/lib/features/live_observation/visualization/unity_visualization_engine.dart` | Flutter 到 Unity 的渲染器适配层。 |
| `mobile/test/features/live_observation/visualization/unity_camera_restore_contract_test.dart` | Unity session/camera 共享状态的静态回归契约。 |
| `unity/README.md` | Unity 环境、导出、地图与点云 fixture 校验步骤。 |

## 暂停原因与已知风险

Unity-as-a-Library 在 Android 的 `SurfaceView` / Flutter PlatformView 宿主重建期间，曾在“卡片地图 → 全屏或横屏 → 返回”后出现 viewport 尺寸、相机缓存与 surface buffer 不一致。症状包括地图缩放畸变、黑屏、触控卡顿或宿主重建后的状态竞争。

问题不属于机器人数据协议：Flutter 的 `CustomPaint` 路径能够稳定显示同一张地图和点云。未来若重启 Unity，优先解决 **单一渲染 surface 的尺寸生命周期**，不要再通过增添业务层、额外 Unity runtime 或真机反复试错来掩盖问题。

## 恢复 Unity 前的最小流程

1. 先保持默认 Flutter 包可构建、可运行；在独立分支恢复 Unity，不修改 Flutter 默认 provider。
2. 在 Android 模拟器建立可重复的压力测试：至少 20 次“进入地图 → 改变窗口尺寸/横竖屏 → 全屏 → 返回”，逐次校验地图的纵横比、相机中心、格栅和覆盖层坐标一致。
3. 为 PlatformView 记录每次创建、尺寸变化、dispose 与 session owner；只有确认同一时刻存在一个可绘制 surface 后，才允许向 Unity 回放相机状态。
4. 在模拟器稳定后，分别进行 Android 和 iOS 真机验证；不得以 iOS 成功推断 Android 生命周期正确，反之亦然。
5. 仅在以下项目均通过后才允许显式构建 Unity 包：
   - Flutter 全量测试、静态分析与 Flutter 默认包构建；
   - Unity full-resolution map fixture（`3480 × 10017`）与点云上限 fixture；
   - Android/iOS 的全屏、横竖屏、返回、后台前台切换压力测试；
   - Unity 包中 framework/Data/so 的完整性与签名检查。

## Unity 原型构建（仅恢复验证时使用）

```sh
cd mobile
./tool/build_mobile_packages.sh --engine unity --platform all --ios-export development
```

此命令会显式启用 `ALETHEIA_UNITY_ENABLED=1` 及 Unity 相关 Dart defines。它不是当前发布流程；如果 Android/iOS 的 Unity 导出、framework 或 `Data` 不完整，脚本应失败，而不是生成降级或混合包。

## 当前正式发布流程

```sh
cd mobile
./tool/build_mobile_packages.sh --engine flutter --platform all --ios-export development
```

产物输出到 `mobile/build/artifacts/`，并附带 SHA-256。Android 如未配置发布 keystore，会输出明确标为 `internal-debug-signed` 的 Release 包；不得将其描述为商店或正式签名包。
