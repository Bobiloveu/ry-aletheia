@Tags(['golden'])
library;

import 'dart:io';

import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/debug_ui/gallery_manifest.dart';
import 'package:aletheia_mobile/debug_ui/gallery_preview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Golden coverage is intentionally driven by the same manifest as the
/// in-app gallery and the Markdown Screen Inventory. Add a new spec there to
/// make it discoverable here automatically.
void main() {
  const logicalSize = Size(402, 874);
  const pixelRatio = 3.0;
  const goldenFontFamily = 'AletheiaGoldenCjk';

  setUpAll(() async {
    await DebugGalleryPreview.preloadSampleMap();
    const fontPath = '/System/Library/Fonts/STHeiti Medium.ttc';
    final font = File(fontPath);
    if (!font.existsSync()) {
      throw StateError('UI Golden 截图需要 macOS 简体中文系统字体：$fontPath');
    }
    final loader = FontLoader(goldenFontFamily)..addFont(_fontData(font));
    await loader.load();
    final iconLoader = FontLoader('MaterialIcons')
      ..addFont(_materialIconFont());
    await iconLoader.load();
  });

  for (final spec in galleryScreenManifest.where(
    (item) => item.hasScreenshot,
  )) {
    testWidgets('UI gallery · ${spec.id}', (tester) async {
      tester.view.physicalSize = const Size(1206, 2622);
      tester.view.devicePixelRatio = pixelRatio;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        ProviderScope(
          child: RepaintBoundary(
            key: ValueKey('gallery-preview-${spec.id}'),
            child: MaterialApp(
              debugShowCheckedModeBanner: false,
              theme: _goldenTheme(goldenFontFamily, spec.appearance),
              home: MediaQuery(
                data: const MediaQueryData(
                  size: logicalSize,
                  devicePixelRatio: pixelRatio,
                  padding: EdgeInsets.only(top: 59, bottom: 34),
                  viewPadding: EdgeInsets.only(top: 59, bottom: 34),
                ),
                child: DebugGalleryPreview(spec: spec),
              ),
            ),
          ),
        ),
      );

      // Do not use pumpAndSettle: indeterminate progress indicators are a
      // legitimate state in this inventory and keep scheduling frames.
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 120));
      // Some production previews intentionally open a sheet after their
      // asynchronous page data has rendered. This third frame captures that
      // real route instead of a background page one frame too early.
      await tester.pump();

      await expectLater(
        find.byKey(ValueKey('gallery-preview-${spec.id}')),
        matchesGoldenFile('../../../docs/ui/screens/${spec.screenshotPath}'),
      );
    });
  }
}

ThemeData _goldenTheme(String fontFamily, GalleryAppearance appearance) {
  final theme = switch (appearance) {
    GalleryAppearance.hmiDark => AletheiaTheme.dark(),
    GalleryAppearance.daylight => AletheiaTheme.light(),
  };
  final textTheme = theme.textTheme.apply(fontFamily: fontFamily);
  return theme.copyWith(
    textTheme: textTheme,
    primaryTextTheme: theme.primaryTextTheme.apply(fontFamily: fontFamily),
    appBarTheme: theme.appBarTheme.copyWith(
      titleTextStyle: theme.appBarTheme.titleTextStyle?.copyWith(
        fontFamily: fontFamily,
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: theme.filledButtonTheme.style?.copyWith(
        textStyle: WidgetStatePropertyAll(textTheme.labelLarge),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: theme.outlinedButtonTheme.style?.copyWith(
        textStyle: WidgetStatePropertyAll(textTheme.labelLarge),
      ),
    ),
    navigationRailTheme: theme.navigationRailTheme.copyWith(
      selectedLabelTextStyle: theme.navigationRailTheme.selectedLabelTextStyle
          ?.copyWith(fontFamily: fontFamily),
      unselectedLabelTextStyle: theme
          .navigationRailTheme
          .unselectedLabelTextStyle
          ?.copyWith(fontFamily: fontFamily),
    ),
    navigationBarTheme: theme.navigationBarTheme.copyWith(
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => textTheme.labelMedium!.copyWith(
          color: states.contains(WidgetState.selected)
              ? AletheiaTheme.cyan
              : AletheiaTheme.textTertiary,
        ),
      ),
    ),
  );
}

Future<ByteData> _fontData(File font) async {
  final bytes = await font.readAsBytes();
  return ByteData.sublistView(bytes);
}

Future<ByteData> _materialIconFont() {
  final flutterRoot = File(Platform.resolvedExecutable)
      .parent
      .parent
      .parent
      .parent
      .parent
      .parent;
  final font = File(
    '${flutterRoot.path}/bin/cache/artifacts/material_fonts/'
    'MaterialIcons-Regular.otf',
  );
  if (!font.existsSync()) {
    throw StateError('找不到 Flutter Material Icons 字体：${font.path}');
  }
  return _fontData(font);
}
