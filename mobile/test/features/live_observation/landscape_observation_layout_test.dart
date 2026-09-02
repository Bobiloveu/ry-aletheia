import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/debug_ui/gallery_manifest.dart';
import 'package:aletheia_mobile/debug_ui/gallery_preview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'map and three-stream camera workspace remain usable in landscape',
    (tester) async {
      tester.view.physicalSize = const Size(2532, 1170);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      Future<void> pumpPreview(String id) async {
        await tester.pumpWidget(
          ProviderScope(
            child: MaterialApp(
              theme: AletheiaTheme.dark(),
              home: MediaQuery(
                data: const MediaQueryData(
                  size: Size(844, 390),
                  devicePixelRatio: 3,
                  padding: EdgeInsets.only(top: 20),
                  viewPadding: EdgeInsets.only(top: 20),
                ),
                child: DebugGalleryPreview(spec: galleryScreenById(id)),
              ),
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 120));
        expect(tester.takeException(), isNull);
      }

      await pumpPreview('observe_live');
      expect(find.byKey(const ValueKey('map-tool-rail')), findsOneWidget);
      expect(find.byTooltip('活动地图'), findsOneWidget);
      expect(find.text('实时位姿'), findsOneWidget);
      final mapRect = tester.getRect(
        find.byKey(const ValueKey('observation-map-workspace')),
      );
      expect(mapRect.width, greaterThan(700));
      final poseReadout = tester.getRect(find.text('实时位姿'));
      expect(poseReadout.top, greaterThanOrEqualTo(mapRect.top));
      expect(poseReadout.bottom, lessThanOrEqualTo(mapRect.bottom));
      final operationalReadout = tester.getRect(
        find.byKey(const ValueKey('map-operational-readout')),
      );
      expect(operationalReadout.right, lessThanOrEqualTo(mapRect.right));
      expect(operationalReadout.bottom, lessThanOrEqualTo(mapRect.bottom));
      expect(find.byTooltip('全屏查看地图'), findsOneWidget);

      await tester.tap(find.byTooltip('全屏查看地图'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 120));
      final exitFullscreen = find.byKey(
        const ValueKey('map-fullscreen-exit-action'),
        skipOffstage: false,
      );
      expect(exitFullscreen, findsOneWidget);
      expect(tester.getRect(exitFullscreen).size, isNot(Size.zero));
      expect(tester.widget<IconButton>(exitFullscreen).onPressed, isNotNull);
      expect(
        find.byKey(
          const ValueKey('map-operational-readout'),
          skipOffstage: false,
        ),
        findsOneWidget,
      );
      await tester.tap(exitFullscreen, warnIfMissed: false);
      await tester.pumpAndSettle();

      await pumpPreview('video_ready');
      expect(find.byKey(const ValueKey('video-control-rail')), findsOneWidget);
      expect(
        find.byKey(const ValueKey('video-stream-toggle-front_camera')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('video-auxiliary-feeds')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('video-auxiliary-tile-back_camera')),
        findsOneWidget,
      );
      await tester.tap(find.byTooltip('配置显示画面'));
      await tester.pumpAndSettle();
      expect(find.text('配置显示画面'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('video-display-slot-主画面')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('video-display-slot-辅助画面 1')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('video-display-slot-辅助画面 2')),
        findsOneWidget,
      );
    },
  );

  testWidgets('two-finger map zoom keeps the midpoint anchored', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(2532, 1170);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: MediaQuery(
            data: const MediaQueryData(
              size: Size(844, 390),
              devicePixelRatio: 3,
              padding: EdgeInsets.only(top: 20),
              viewPadding: EdgeInsets.only(top: 20),
            ),
            child: DebugGalleryPreview(spec: galleryScreenById('observe_live')),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 120));

    final mapFinder = find.byKey(const ValueKey('observation-map-workspace'));
    final transformFinder = find.byKey(const ValueKey('map-world-transform'));
    final gridFinder = find.byKey(const ValueKey('map-world-grid'));
    expect(mapFinder, findsOneWidget);
    expect(transformFinder, findsOneWidget);
    expect(gridFinder, findsOneWidget);
    expect(
      find.ancestor(of: gridFinder, matching: transformFinder),
      findsOneWidget,
    );

    final mapRect = tester.getRect(mapFinder);
    final initial = tester.widget<Transform>(transformFinder).transform.clone();
    final focalLocal = mapRect.size.center(Offset.zero);
    final initialScale = initial.storage[0];
    final anchoredMapPoint = Offset(
      (focalLocal.dx - initial.storage[12]) / initialScale,
      (focalLocal.dy - initial.storage[13]) / initialScale,
    );
    final focalGlobal = mapRect.topLeft + focalLocal;
    final first = await tester.createGesture(pointer: 1);
    final second = await tester.createGesture(pointer: 2);
    await first.down(focalGlobal + const Offset(-40, 0));
    await tester.pump();
    await second.down(focalGlobal + const Offset(40, 0));
    await tester.pump();
    await first.moveTo(focalGlobal + const Offset(-70, 10));
    await tester.pump();
    await second.moveTo(focalGlobal + const Offset(90, 10));
    await tester.pump();
    await first.moveTo(focalGlobal + const Offset(-90, 10));
    await tester.pump();

    final transformed = tester.widget<Transform>(transformFinder).transform;
    expect(transformed.storage[0], greaterThan(initialScale));
    final reprojected = Offset(
      anchoredMapPoint.dx * transformed.storage[0] + transformed.storage[12],
      anchoredMapPoint.dy * transformed.storage[5] + transformed.storage[13],
    );
    expect(
      (reprojected - (focalLocal + const Offset(0, 10))).distance,
      lessThan(2),
    );

    await first.up();
    await second.up();
    expect(tester.takeException(), isNull);
  });

  testWidgets('tall maps sit on a workspace canvas and accept one-finger pan', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(2532, 1170);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: MediaQuery(
            data: const MediaQueryData(
              size: Size(844, 390),
              devicePixelRatio: 3,
              padding: EdgeInsets.only(top: 20),
              viewPadding: EdgeInsets.only(top: 20),
            ),
            child: DebugGalleryPreview(spec: galleryScreenById('observe_live')),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 120));

    final mapFinder = find.byKey(const ValueKey('observation-map-workspace'));
    final transformFinder = find.byKey(const ValueKey('map-world-transform'));
    final canvasFinder = find.byKey(const ValueKey('map-workspace-canvas'));
    final scrollableFinder = find
        .ancestor(of: mapFinder, matching: find.byType(Scrollable))
        .first;
    final scrollPosition = tester
        .state<ScrollableState>(scrollableFinder)
        .position;
    final initialScrollOffset = scrollPosition.pixels;
    final mapRect = tester.getRect(mapFinder);
    final initial = tester.widget<Transform>(transformFinder).transform.clone();
    expect(tester.getSize(canvasFinder).width, greaterThan(mapRect.width));
    expect(tester.getSize(canvasFinder).height, greaterThan(mapRect.height));
    expect(find.byKey(const ValueKey('map-scale-reference')), findsOneWidget);
    final gesture = await tester.createGesture();
    await gesture.down(mapRect.center);
    await tester.pump();
    await gesture.moveBy(const Offset(0, -20));
    await tester.pump();
    await gesture.moveBy(const Offset(0, -50));
    await tester.pump();
    await gesture.moveBy(const Offset(48, -20));
    await tester.pump();
    await gesture.up();

    final transformed = tester.widget<Transform>(transformFinder).transform;
    expect(transformed.storage[12], isNot(initial.storage[12]));
    expect(transformed.storage[13], isNot(initial.storage[13]));
    expect(scrollPosition.pixels, closeTo(initialScrollOffset, .01));
    expect(tester.takeException(), isNull);
  });
}
