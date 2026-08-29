import 'dart:io';

import 'package:aletheia_mobile/debug_ui/gallery_manifest.dart';

/// Rebuilds the human-readable UI inventory from the gallery manifest.
///
/// Run from `mobile/`:
/// `dart run tool/generate_ui_docs.dart`
void main() {
  final repositoryRoot = Directory.current.parent;
  final uiDocs = Directory('${repositoryRoot.path}/docs/ui')
    ..createSync(recursive: true);
  final screenshots = Directory('${uiDocs.path}/screens')
    ..createSync(recursive: true);

  File('${uiDocs.path}/SCREEN_INVENTORY.md')
      .writeAsStringSync(_inventoryMarkdown(screenshots));
  File('${uiDocs.path}/SCREEN_MAP.md')
      .writeAsStringSync(_screenMapMarkdown(screenshots));
}

String _inventoryMarkdown(Directory screenshots) {
  final buffer = StringBuffer()
    ..writeln('# Aletheia Screen Inventory')
    ..writeln()
    ..writeln('此清单由 `mobile/lib/debug_ui/gallery_manifest.dart` 自动生成。')
    ..writeln('每一行都是可在仅 Debug Gallery 中复现的真实页面或真实组件状态。')
    ..writeln()
    ..writeln('| 一级模块 | 页面 | Route | 状态 | 真实触发条件 | Gallery | Screenshot |')
    ..writeln('| --- | --- | --- | --- | --- | --- | --- |');
  for (final spec in galleryScreenManifest) {
    final screenshot = File('${screenshots.path}/${spec.screenshotPath}')
        .existsSync();
    buffer.writeln(
      '| ${spec.module.label} | ${_cell(spec.title)} | `${spec.route}` | '
      '${_cell(spec.state)} | ${_cell(spec.trigger)} | 可预览 | '
      '${screenshot ? '[已生成](screens/${spec.screenshotPath})' : '待生成'} |',
    );
  }
  buffer
    ..writeln()
    ..writeln('## 维护规则')
    ..writeln()
    ..writeln('- 新增页面或关键 UI 状态时，先在 Gallery Manifest 增加一项。')
    ..writeln('- 为该项选择真实页面或组件的 Mock Provider 状态，不重复实现页面。')
    ..writeln(
      '- 执行 `flutter test --update-goldens test/debug_ui/gallery_golden_test.dart` 后重新生成本文档。',
    );
  return buffer.toString();
}

String _screenMapMarkdown(Directory screenshots) {
  final buffer = StringBuffer()
    ..writeln('# Aletheia Screen Map / UI Overview')
    ..writeln()
    ..writeln('固定预览规格：iPhone 17 逻辑尺寸 402 × 874，Pixel Ratio 3，深色主题，标准字体比例。')
    ..writeln()
    ..writeln('正式一级信息架构：**首页 / 观测 / 工具 / 设置**。')
    ..writeln('测试、用例、日志和报告属于“工具”下的二级流程。')
    ..writeln('详细 Route、状态和触发条件请参阅 [Screen Inventory](SCREEN_INVENTORY.md)。')
    ..writeln();
  for (final module in GalleryModule.values) {
    final specs = galleryScreenManifest
        .where((item) => item.module == module)
        .toList(growable: false);
    buffer
      ..writeln('## ${module.label}')
      ..writeln()
      ..writeln('<table>');
    for (var index = 0; index < specs.length; index += 3) {
      final row = specs.skip(index).take(3).toList(growable: false);
      buffer
        ..writeln('<tr>')
        ..writeln(
          row
              .map((spec) => '<td>${_screenCell(spec, screenshots)}</td>')
              .join(),
        );
      for (var empty = row.length; empty < 3; empty++) {
        buffer.writeln('<td></td>');
      }
      buffer.writeln('</tr>');
    }
    buffer
      ..writeln('</table>')
      ..writeln();
  }
  buffer
    ..writeln('## 复查流程')
    ..writeln()
    ..writeln('1. Debug 运行时打开 `/__debug/ui-gallery`，逐项检查。')
    ..writeln('2. 运行 Golden Test 更新截图。')
    ..writeln('3. 重新生成 Inventory 与 Screen Map，审查本次 diff。');
  return buffer.toString();
}

String _screenCell(GalleryScreenSpec spec, Directory screenshots) {
  final image = File('${screenshots.path}/${spec.screenshotPath}');
  final caption = '<strong>${spec.title}</strong><br>${spec.state}';
  if (!image.existsSync()) {
    return '$caption<br><code>截图待生成</code>';
  }
  return '<a href="screens/${spec.screenshotPath}">'
      '<img src="screens/${spec.screenshotPath}" width="180" alt="${spec.title} · ${spec.state}"><br>'
      '$caption</a>';
}

String _cell(String value) =>
    value.replaceAll('|', r'\|').replaceAll('\n', '<br>');
