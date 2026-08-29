import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/debug_ui/gallery_manifest.dart';
import 'package:aletheia_mobile/debug_ui/gallery_preview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('disconnected observation uses a compact, bounded empty state', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1206, 2622);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: DebugGalleryPreview(
            spec: galleryScreenById('observe_disconnected'),
          ),
        ),
      ),
    );
    await tester.pump();

    final panel = tester.getSize(
      find.byKey(const ValueKey('observation-connection-required')),
    );
    expect(panel.width, 320);
    expect(panel.height, lessThan(190));
    expect(find.text('先连接机器人'), findsOneWidget);
  });
}
