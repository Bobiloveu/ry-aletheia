import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:aletheia_mobile/features/manual_control/application/manual_control_controller.dart';
import 'package:aletheia_mobile/features/manual_control/data/manual_control_repository.dart';
import 'package:aletheia_mobile/features/manual_control/domain/vehicle_control_state.dart';
import 'package:aletheia_mobile/features/manual_control/presentation/manual_control_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';

void main() {
  testWidgets('requires explicit confirmation before entering manual control', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    final repository = _ManualControlFakeRepository();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _ConnectedController.new,
          ),
          manualControlRepositoryProvider.overrideWithValue(repository),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.light(),
          home: const Scaffold(body: ManualControlScreen()),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('开始手动控制'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('连续方向摇杆已锁定')), findsOneWidget);

    await tester.tap(find.text('开始手动控制'));
    await tester.pumpAndSettle();

    expect(find.text('确认进入手动控制？'), findsOneWidget);
    expect(repository.calls, ['status']);
    semantics.dispose();
  });

  testWidgets(
    'keeps the direction surface free of instructional copy and compass arrows',
    (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            robotConnectionControllerProvider.overrideWith(
              _ConnectedController.new,
            ),
            manualControlRepositoryProvider.overrideWithValue(
              _ManualControlFakeRepository(),
            ),
          ],
          child: MaterialApp(
            theme: AletheiaTheme.light(),
            home: const Scaffold(body: ManualControlScreen()),
          ),
        ),
      );
      await tester.pump();

      expect(find.text('方向'), findsOneWidget);
      expect(find.textContaining('摇杆与手指'), findsNothing);
      expect(find.byIcon(Icons.keyboard_arrow_up_rounded), findsNothing);
      expect(find.byIcon(Icons.keyboard_arrow_right_rounded), findsNothing);
    },
  );

  testWidgets(
    'enables the joystick only after backend confirms an active session',
    (tester) async {
      final semantics = tester.ensureSemantics();
      final repository = _ManualControlFakeRepository();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            robotConnectionControllerProvider.overrideWith(
              _ConnectedController.new,
            ),
            manualControlRepositoryProvider.overrideWithValue(repository),
          ],
          child: MaterialApp(
            theme: AletheiaTheme.light(),
            home: const Scaffold(body: ManualControlScreen()),
          ),
        ),
      );
      await tester.pump();
      await tester.tap(find.text('开始手动控制'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('进入控制'));
      await tester.pump();

      expect(find.bySemanticsLabel(RegExp('连续方向摇杆，当前停止')), findsOneWidget);
      expect(repository.calls, ['status', 'enter']);
      semantics.dispose();
    },
  );

  testWidgets('backgrounding an active manual page requests STOP then EXIT', (
    tester,
  ) async {
    final repository = _ManualControlFakeRepository();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _ConnectedController.new,
          ),
          manualControlRepositoryProvider.overrideWithValue(repository),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.light(),
          home: const Scaffold(body: ManualControlScreen()),
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('开始手动控制'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('进入控制'));
    await tester.pump();

    WidgetsBinding.instance.handleAppLifecycleStateChanged(
      AppLifecycleState.paused,
    );
    await tester.pump();

    expect(repository.calls, [
      'status',
      'enter',
      'stop:manual-session',
      'exit:manual-session',
    ]);
  });

  testWidgets('returning a held joystick to center requests STOP immediately', (
    tester,
  ) async {
    final repository = _ManualControlFakeRepository();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _ConnectedController.new,
          ),
          manualControlRepositoryProvider.overrideWithValue(repository),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.light(),
          home: const Scaffold(body: ManualControlScreen()),
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('开始手动控制'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('进入控制'));
    await tester.pump();

    final joystick = find.bySemanticsLabel(RegExp('连续方向摇杆，当前停止'));
    final center = tester.getCenter(joystick);
    final gesture = await tester.startGesture(center);
    await gesture.moveTo(center.translate(0, -80));
    await tester.pump();
    await gesture.moveTo(center);
    await tester.pump();

    expect(repository.calls, [
      'status',
      'enter',
      'vector:manual-session:1.0:0.0',
      'stop:manual-session',
    ]);

    await gesture.up();
  });

  testWidgets('exposes all three chassis parameters in the advanced panel', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final repository = _ManualControlFakeRepository();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _ConnectedController.new,
          ),
          manualControlRepositoryProvider.overrideWithValue(repository),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.light(),
          home: const Scaffold(body: ManualControlScreen()),
        ),
      ),
    );
    await tester.pump();

    final chassisEntry = find.byTooltip('编辑底盘参数');
    await tester.tap(chassisEntry);
    await tester.pumpAndSettle();

    expect(find.text('底盘压力'), findsOneWidget);
    expect(find.text('运动加速度'), findsOneWidget);
    expect(find.text('停止加速度'), findsOneWidget);
    expect(find.text('保存到车端'), findsOneWidget);
  });
}

class _ConnectedController extends RobotConnectionController {
  @override
  RobotConnectionState build() => RobotConnectionState(
    phase: ConnectionPhase.connected,
    endpoint: RobotEndpoint.parse('robot.local'),
  );
}

class _ManualControlFakeRepository extends ManualControlRepository {
  _ManualControlFakeRepository()
    : super(
        AletheiaApiClient(
          MockClient((_) async => throw StateError('unexpected HTTP request')),
        ),
      );

  final calls = <String>[];

  @override
  Future<VehicleControlState> status(RobotEndpoint endpoint) async {
    calls.add('status');
    return _status();
  }

  @override
  Future<VehicleControlState> enter(RobotEndpoint endpoint) async {
    calls.add('enter');
    return _status(sessionId: 'manual-session');
  }

  @override
  Future<VehicleControlState> command(
    RobotEndpoint endpoint,
    String sessionId,
    VehicleCommand command,
  ) async {
    calls.add('command:$sessionId:${command.wireName}');
    return _status(sessionId: sessionId);
  }

  @override
  Future<VehicleControlState> vector(
    RobotEndpoint endpoint,
    String sessionId,
    VehicleControlVector vector,
  ) async {
    calls.add('vector:$sessionId:${vector.linearRatio}:${vector.angularRatio}');
    return _status(sessionId: sessionId);
  }

  @override
  Future<VehicleControlState> stop(
    RobotEndpoint endpoint,
    String sessionId,
  ) async {
    calls.add('stop:$sessionId');
    return _status();
  }

  @override
  Future<VehicleControlState> exit(
    RobotEndpoint endpoint,
    String sessionId,
  ) async {
    calls.add('exit:$sessionId');
    return _status();
  }
}

VehicleControlState _status({String? sessionId}) =>
    VehicleControlState.fromJson({
      'runtime': 'ready',
      'actual_source': sessionId == null ? 'navigation' : 'miniapp',
      'manual_ready': sessionId != null,
      'can_begin_manual': sessionId == null,
      'session': {
        'present': sessionId != null,
        'state': sessionId == null ? 'none' : 'active',
        ...(sessionId == null ? const <String, Object?>{} : {'id': sessionId}),
      },
      'speed': {'linear_mps': .2, 'angular_radps': .3, 'min': .1, 'max': 1.0},
      'emergency_stop': {'state': 'normal', 'release': 'idle'},
      'chassis_parameters': {
        'press': 1400,
        'movement_acc': 1000,
        'stop_acc': 1200,
      },
    });
