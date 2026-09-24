import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/app/motion/aletheia_interaction.dart';
import 'package:aletheia_mobile/debug_ui/gallery_manifest.dart';
import 'package:aletheia_mobile/debug_ui/gallery_preview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'restored connected endpoint is visible after the home tab rebuilds',
    (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp(
            theme: AletheiaTheme.dark(),
            home: DebugGalleryPreview(
              spec: galleryScreenById('robot_connected'),
            ),
          ),
        ),
      );
      await tester.pump();

      final field = tester.widget<TextField>(find.byType(TextField));
      expect(field.controller?.text, '192.168.1.20:8087');
    },
  );

  testWidgets('connected status uses a local keyed status transition', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: DebugGalleryPreview(spec: galleryScreenById('robot_connected')),
        ),
      ),
    );
    await tester.pump();

    expect(find.byType(AletheiaStatusTransition), findsOneWidget);
  });
}
