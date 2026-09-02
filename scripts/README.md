# 根目录脚本

这些脚本是现有 Pixi、FVM 和 Mobile 打包脚本的薄入口；它们不引入第二套依赖管理器。

| 工作域 | 安装 | 检查 | 测试 / 构建 |
| --- | --- | --- | --- |
| Backend | `./scripts/bootstrap.sh backend` | `./scripts/doctor.sh --profile backend` | `./scripts/test-backend.sh` |
| Web | `./scripts/bootstrap.sh web` | `./scripts/doctor.sh --profile web` | `./scripts/test-web.sh` |
| Mobile Android | `./scripts/bootstrap.sh mobile-android` | `./scripts/doctor.sh --profile mobile-android` | `./scripts/test-mobile.sh`、`./scripts/build-mobile.sh --platform android` |
| Mobile iOS（macOS） | `./scripts/bootstrap.sh mobile-ios` | `./scripts/doctor.sh --profile mobile-ios` | `fvm flutter build ios --simulator --debug --no-codesign`（在 `mobile/`） |

`mobile` 是 `mobile-android` 的兼容别名，`all` 是 `full` 的兼容别名。所有 Flutter 命令必须通过 `fvm flutter` 执行，默认使用 Flutter/CustomPaint 渲染路径；不要传入 Unity engine 参数。

Windows 使用 PowerShell 执行 `./scripts/doctor.ps1 -Profile mobile-android`；其余 Mobile 命令在 `mobile/` 中直接执行 `fvm flutter pub get`、`fvm flutter analyze`、`fvm flutter test` 与 `fvm flutter build apk --debug`。Windows/Linux 不支持 iOS 构建，Doctor 会显示 `UNSUPPORTED` 而非环境失败。
