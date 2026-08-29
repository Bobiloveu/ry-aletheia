# Aletheia UI Review Infrastructure

`mobile/lib/debug_ui/gallery_manifest.dart` 是 Debug UI Gallery、Screen Inventory、Screen Map 与 Golden Test 的共同来源。

观测类 Gallery 状态会加载 `mobile/assets/debug_ui/` 中的本地地图 Fixture：由提供的 `map.pgm` 无损转换为原始 3480×10017 像素 PNG，不做下采样；并直接读取配套 `map.yaml` 与 `map_walls.yaml` 的世界坐标、原点和虚拟墙段。它只服务 Debug Gallery，不访问机器人或网络。

从 `mobile/` 运行：

```sh
flutter test --update-goldens test/debug_ui/gallery_golden_test.dart
dart run tool/generate_ui_docs.dart
```

截图只写入本目录的 `screens/`，不会进入 App assets。截图使用固定 iPhone 17 规格：402 × 874 逻辑像素、3× Pixel Ratio、深色主题、标准字体比例。

当前 Golden 基线以 macOS 的简体中文系统字体生成，使审阅图与目标 iPhone 的中文排版一致；因此截图任务需要在 macOS 上运行。

Debug 构建可通过 `/__debug/ui-gallery?screen=robot_connected` 打开指定状态；Release/Profile 不注册该 Route。

## 在 iPhone 17 Simulator 调试

保持模拟器启动，在 `mobile/` 中运行下列命令即可直接打开 Gallery：

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  flutter run --debug -d B77BE4F1-BC75-4837-A759-309D06AA9D20 \
  --route '/__debug/ui-gallery?screen=robot_disconnected'
```

命令窗口保持运行时，可用 `r` 热重载、`R` 热重启；Gallery 内选择“选择界面状态”即可切换所有 Mock 页面与状态。此处临时移除代理仅避免代理拦截本机 Dart VM WebSocket，不会改动系统代理。正常 App 则去掉 `--route` 启动。

在手机竖屏和横屏中，Gallery 都会直接显示所选的真实生产页面，不再嵌套审阅预览或改变页面比例；方格按钮仅用于打开 Mock 状态选择器，竖屏固定停靠在正式底部导航之上，横屏停靠在右下角。平板和桌面仍使用带 Screen Inventory 的审阅布局。它仅存在于 Debug 模式。
