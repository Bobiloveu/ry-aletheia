import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/debug_ui/debug_ui_gallery_screen.dart';
import 'package:aletheia_mobile/debug_ui/gallery_manifest.dart';
import 'package:aletheia_mobile/debug_ui/gallery_preview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('phone Gallery starts from a full-size mock production page', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1206, 2622);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const DebugUiGalleryScreen(),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('界面检查'), findsNothing);
    expect(find.text('连接或确认机器人'), findsOneWidget);
    expect(find.byTooltip('选择界面状态 · 首页'), findsOneWidget);
    expect(find.byType(DebugGalleryPreview), findsOneWidget);
  });

  testWidgets('changing a Gallery state rebuilds its mock provider graph', (
    tester,
  ) async {
    var selected = galleryScreenById('robot_disconnected');
    late void Function(GalleryScreenSpec spec) select;

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: StatefulBuilder(
            builder: (context, setState) {
              select = (spec) => setState(() => selected = spec);
              return DebugGalleryPreview(spec: selected);
            },
          ),
        ),
      ),
    );
    await tester.pump();

    select(galleryScreenById('observe_live'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 120));

    expect(find.byTooltip('活动地图'), findsOneWidget);
    expect(find.text('先连接机器人'), findsNothing);
  });

  testWidgets('test run Gallery uses the production Supervisor readiness UI', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: DebugGalleryPreview(
            spec: galleryScreenById('test_supervisor_required_failure'),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('运行依赖'), findsOneWidget);
    expect(find.text('定位服务'), findsOneWidget);
    expect(find.text('异常退出'), findsOneWidget);
    expect(find.text('1 / 3 运行中'), findsOneWidget);
  });

  testWidgets(
    'phone landscape renders the selected production page at device size',
    (tester) async {
      tester.view.physicalSize = const Size(2622, 1206);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.resetPhysicalSize);

      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp(
            theme: AletheiaTheme.dark(),
            home: const DebugUiGalleryScreen(
              initialScreenId: 'observe_loading',
            ),
          ),
        ),
      );
      await tester.pump();

      expect(find.text('正在准备观测链路'), findsOneWidget);
      expect(find.text('界面检查'), findsNothing);
      expect(find.byTooltip('选择界面状态 · 实时观测'), findsOneWidget);
      expect(
        tester.getSize(
          find.byKey(const ValueKey('gallery-device-preview-observe_loading')),
        ),
        const Size(874, 402),
      );

      await tester.tap(find.byTooltip('选择界面状态 · 实时观测'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('完整状态预览'), findsOneWidget);
    },
  );

  testWidgets('wide landscape phone keeps the Debug quick switch', (
    tester,
  ) async {
    // A number of Android phones have a landscape long edge above 900dp.
    // They must not become the desktop review layout after rotation.
    tester.view.physicalSize = const Size(2880, 1296);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const DebugUiGalleryScreen(initialScreenId: 'observe_loading'),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('界面检查'), findsNothing);
    expect(find.byKey(const Key('gallery-quick-switch')), findsOneWidget);
    expect(
      tester.getSize(
        find.byKey(const ValueKey('gallery-device-preview-observe_loading')),
      ),
      const Size(960, 432),
    );

    tester.view.physicalSize = const Size(1296, 2880);
    await tester.pump();
    expect(find.byKey(const Key('gallery-quick-switch')), findsOneWidget);
  });

  testWidgets('phone preview follows its constrained canvas during rotation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(2622, 1206);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const MediaQuery(
            // Simulate a stale orientation report during an iOS rotation.
            data: MediaQueryData(size: Size(402, 874), devicePixelRatio: 3),
            child: DebugUiGalleryScreen(initialScreenId: 'observe_loading'),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('界面检查'), findsNothing);
    expect(
      find.byKey(const ValueKey('gallery-device-preview-observe_loading')),
      findsOneWidget,
    );

    // Recreate the real landscape → portrait transition. The state switcher
    // must remain above the production bottom navigation instead of ending up
    // under it after the constrained canvas changes shape.
    tester.view.physicalSize = const Size(1206, 2622);
    await tester.pump();

    final quickSwitch = tester.getRect(
      find.byKey(const Key('gallery-quick-switch')),
    );
    expect(quickSwitch.bottom, lessThanOrEqualTo(780));
  });
}
