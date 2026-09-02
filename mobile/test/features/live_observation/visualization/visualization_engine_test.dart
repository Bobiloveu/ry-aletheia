import 'dart:typed_data';

import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/debug_ui/gallery_manifest.dart';
import 'package:aletheia_mobile/debug_ui/gallery_preview.dart';
import 'package:aletheia_mobile/features/live_observation/domain/live_map.dart';
import 'package:aletheia_mobile/features/live_observation/presentation/live_observation_screen.dart';
import 'package:aletheia_mobile/features/live_observation/visualization/visualization_engine.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

LiveMapAsset _fakeMap() => LiveMapAsset(
  id: 'map-fixture',
  metadata: const LiveMapMetadata(
    width: 100,
    height: 100,
    resolution: 0.05,
    originX: 0,
    originY: 0,
    frameId: 'map',
  ),
  previewBytes: Uint8List(0),
);

class _StubEngine implements VisualizationEngine {
  const _StubEngine();

  @override
  Widget buildMapSurface({
    required LiveMapAsset map,
    required MapCameraFollowController cameraFollowController,
    required MapSurfaceActions actions,
  }) => const SizedBox(key: ValueKey('stub-visualization-surface'));
}

void main() {
  test('default engine is the Flutter renderer, kept as the fallback', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    final engine = container.read(visualizationEngineProvider);
    expect(engine, isA<FlutterVisualizationEngine>());

    final followController = MapCameraFollowController();
    addTearDown(followController.dispose);
    final surface = engine.buildMapSurface(
      map: _fakeMap(),
      cameraFollowController: followController,
      actions: MapSurfaceActions(
        onShowCamera: () {},
        onRecenter: () {},
        onToggleFullscreen: () {},
        onRefresh: () {},
      ),
    );
    expect(surface, isA<Widget>());
    expect(surface.key, const ValueKey('map-fixture-viewport'));
  });

  test('follow controller preserves the operator\'s direct manipulation', () {
    final controller = MapCameraFollowController();
    addTearDown(controller.dispose);

    expect(controller.isFollowing, isTrue);
    controller.pauseForDirectManipulation();
    expect(controller.isFollowing, isFalse);
    controller.recenterOnVehicle();
    expect(controller.isFollowing, isTrue);
  });

  test(
    'Unity camera snapshot restores the same relative zoom in a new host',
    () {
      final controller = MapCameraFollowController();
      addTearDown(controller.dispose);

      controller.saveUnitySnapshot(
        mapId: 'map-fixture',
        // The card host's map-cover overview has a scale of 2.5. The operator
        // pinched to 3x that overview. A fullscreen host has a different
        // map-cover overview (4.0), so it must receive 12.0 rather than replay
        // the card's absolute 7.5 camera scalar.
        scale: 7.5,
        offset: const Offset(4, -3),
        overviewScale: 2.5,
      );

      final snapshot = controller.snapshotForMap('map-fixture');
      expect(snapshot, isNotNull);
      expect(snapshot!.zoom, 3);
      expect(snapshot.scaleForOverview(4), 12);
      expect(snapshot.offset, const Offset(4, -3));
      expect(controller.snapshotForMap('another-map'), isNull);
    },
  );

  Future<void> pumpObservation(WidgetTester tester, ProviderScope scope) async {
    tester.view.physicalSize = const Size(1206, 2622);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(scope);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 120));
    expect(tester.takeException(), isNull);
  }

  Widget observationApp() => MaterialApp(
    theme: AletheiaTheme.dark(),
    home: DebugGalleryPreview(spec: galleryScreenById('observe_live')),
  );

  testWidgets('default engine renders the Flutter gesture surface', (
    tester,
  ) async {
    await pumpObservation(tester, ProviderScope(child: observationApp()));
    expect(find.byKey(const ValueKey('map-gesture-surface')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('stub-visualization-surface')),
      findsNothing,
    );
  });

  testWidgets('overriding the engine swaps only the map surface', (
    tester,
  ) async {
    await pumpObservation(
      tester,
      ProviderScope(
        overrides: [
          visualizationEngineProvider.overrideWithValue(const _StubEngine()),
        ],
        child: observationApp(),
      ),
    );
    expect(
      find.byKey(const ValueKey('stub-visualization-surface')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('map-gesture-surface')), findsNothing);
    // HMI chrome around the surface is unaffected by the engine swap.
    expect(
      find.byKey(const ValueKey('map-operational-readout')),
      findsOneWidget,
    );
  });
}
