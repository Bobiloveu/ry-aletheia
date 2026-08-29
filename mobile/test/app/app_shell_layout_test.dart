import 'package:aletheia_mobile/app/app_shell.dart';
import 'package:aletheia_mobile/app/branding/aletheia_brand_mark.dart';
import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('short landscape uses compact shell chrome', (tester) async {
    tester.view.physicalSize = const Size(2532, 1170);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _IdleRobotConnectionController.new,
          ),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const MediaQuery(
            data: MediaQueryData(size: Size(844, 390), devicePixelRatio: 3),
            child: AletheiaAppShell(
              location: '/robot',
              child: SizedBox.expand(),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    final appBar = tester.widget<AppBar>(find.byType(AppBar));
    expect(appBar.toolbarHeight, 44);
    expect(appBar.automaticallyImplyLeading, isFalse);
    expect(tester.getTopLeft(find.text('Aletheia')).dx, lessThan(56));
    expect(tester.getRect(find.text('未连接')).right, greaterThan(790));
    expect(find.byKey(const Key('compact-navigation-strip')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('compact-navigation-strip')),
        matching: find.byWidgetPredicate(
          (widget) =>
              widget is ColoredBox && widget.color == AletheiaTheme.canvas,
        ),
      ),
      findsOneWidget,
    );
    expect(
      tester.getSize(find.byKey(const Key('compact-navigation-strip'))).width,
      56,
    );
    expect(find.byType(NavigationRail), findsNothing);
    expect(find.byType(Tooltip), findsNWidgets(4));
  });

  testWidgets('compact rail keeps its controls clear of a leading safe area', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(2532, 1170);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _IdleRobotConnectionController.new,
          ),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const MediaQuery(
            data: MediaQueryData(
              size: Size(844, 390),
              devicePixelRatio: 3,
              padding: EdgeInsets.only(left: 44),
            ),
            child: AletheiaAppShell(
              location: '/robot',
              child: SizedBox.expand(),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(
      tester.getSize(find.byKey(const Key('compact-navigation-strip'))).width,
      100,
    );
    expect(
      tester
          .getTopLeft(find.byKey(const Key('compact-navigation-destination-0')))
          .dx,
      greaterThanOrEqualTo(44),
    );
  });

  testWidgets('disconnected observation shares the robot home identity', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _IdleRobotConnectionController.new,
          ),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const AletheiaAppShell(
            location: '/observation',
            child: SizedBox.expand(),
          ),
        ),
      ),
    );

    expect(find.text('Aletheia'), findsOneWidget);
    expect(find.byType(AletheiaBrandMark), findsOneWidget);
    expect(find.text('未连接'), findsOneWidget);
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    expect(scaffold.extendBodyBehindAppBar, isFalse);
    final appBar = tester.widget<AppBar>(find.byType(AppBar));
    expect(appBar.backgroundColor, AletheiaTheme.canvas);
  });

  testWidgets('tools root keeps the shared HMI product identity', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _IdleRobotConnectionController.new,
          ),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const AletheiaAppShell(
            location: '/tools',
            child: SizedBox.expand(),
          ),
        ),
      ),
    );

    expect(find.text('Aletheia'), findsOneWidget);
    expect(find.byType(AletheiaBrandMark), findsOneWidget);
  });

  testWidgets('settings is a separate app-level destination', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _IdleRobotConnectionController.new,
          ),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const AletheiaAppShell(
            location: '/settings',
            child: SizedBox.expand(),
          ),
        ),
      ),
    );

    // One label belongs to the root app bar and one to the primary navigation.
    expect(find.text('设置'), findsNWidgets(2));
    expect(find.byType(AletheiaBrandMark), findsNothing);
    expect(find.text('未连接'), findsNothing);
  });
}

class _IdleRobotConnectionController extends RobotConnectionController {
  @override
  RobotConnectionState build() {
    return const RobotConnectionState(phase: ConnectionPhase.idle);
  }
}
