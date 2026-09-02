import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/debug_ui/gallery_manifest.dart';
import 'package:aletheia_mobile/debug_ui/gallery_preview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

/// Verifies the physical-device Unity renderer through Flutter's owning HMI
/// layer. This intentionally uses the deterministic `observe_stress` debug
/// route, so it has a full-resolution map, walls and live telemetry without a
/// robot on the LAN.
///
/// Do not use `pumpAndSettle` here: the stress screen intentionally produces
/// continuous pose and cloud frames, which means an HMI renderer should never
/// become completely idle.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Unity map remains interactive across fullscreen lifecycle', (
    tester,
  ) async {
    // Do not depend on a platform launch route here: XCTest's runner sets its
    // own default route before Flutter gets a chance to read AV_DEBUG_ROUTE.
    // The gallery preview is the production observation page plus its real
    // deterministic provider overrides, so it exercises the same map widget,
    // gesture surface, fullscreen route and continuous telemetry as the
    // physical Debug Gallery without involving route-launch plumbing.
    runApp(
      MaterialApp(
        theme: AletheiaTheme.dark(),
        home: DebugGalleryPreview(spec: galleryScreenById('observe_stress')),
      ),
    );
    await tester.pump(const Duration(seconds: 6));

    final mapSurface = _mapGestureSurface();
    expect(mapSurface, findsOneWidget);

    // A deliberate horizontal drag uses Flutter's overlay, which must win
    // against the embedded UIKit/Metal view and the containing page scroll.
    await _dragCanvas(
      tester,
      mapSurface,
      const Offset(88, 16),
      const Duration(milliseconds: 420),
    );
    await tester.pump(const Duration(milliseconds: 800));
    expect(mapSurface, findsOneWidget);

    // A single pass only catches the easy case. Native Unity hosts are torn
    // down and rebound at different points in each route transition, so run
    // the same flow repeatedly to cover the black/warped surface regression
    // that historically appeared only after a return to the card.
    for (var cycle = 0; cycle < 5; cycle++) {
      await tester.tap(find.byTooltip('全屏查看地图'));
      await tester.pump(const Duration(seconds: 2));
      expect(find.byTooltip('退出全屏地图'), findsOneWidget);
      expect(mapSurface, findsOneWidget);

      // Drag again after Unity's native surface has been resized/rebound.
      await _dragCanvas(
        tester,
        mapSurface,
        Offset(-72 + cycle * 4, 32),
        const Duration(milliseconds: 360),
      );
      await tester.pump(const Duration(milliseconds: 600));

      await tester.tap(find.byTooltip('退出全屏地图'));
      await tester.pump(const Duration(seconds: 2));
      expect(find.byTooltip('全屏查看地图'), findsOneWidget);
      expect(mapSurface, findsOneWidget);
    }
  });
}

/// The same end-to-end test deliberately runs in two build contracts:
/// physical Unity has the transparent Flutter gesture layer above the native
/// surface, while Simulator uses the permanent CustomPaint fallback. Both
/// must support exactly the same HMI interaction flow.
Finder _mapGestureSurface() {
  final unity = find.byKey(const ValueKey('unity-map-gesture-surface'));
  if (unity.evaluate().isNotEmpty) return unity;

  // The fallback owns the same interaction contract with a differently named
  // widget: the world canvas is inside Flutter's direct gesture surface.
  return find.byKey(const ValueKey('map-gesture-surface'));
}

Future<void> _dragCanvas(
  WidgetTester tester,
  Finder canvas,
  Offset delta,
  Duration duration,
) async {
  final gesture = await tester.startGesture(tester.getCenter(canvas));
  await tester.pump(duration ~/ 2);
  await gesture.moveBy(delta / 2);
  await tester.pump(duration ~/ 2);
  await gesture.moveBy(delta / 2);
  await gesture.up();
}
