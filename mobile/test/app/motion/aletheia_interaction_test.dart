import 'package:aletheia_mobile/app/motion/aletheia_interaction.dart';
import 'package:aletheia_mobile/app/motion/aletheia_motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('press feedback contracts immediately and restores on cancel', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Center(
            child: AletheiaPressFeedback(
              child: SizedBox(
                key: ValueKey('press-target'),
                width: 44,
                height: 44,
              ),
            ),
          ),
        ),
      ),
    );

    final gesture = await tester.startGesture(
      tester.getCenter(find.byKey(const ValueKey('press-target'))),
    );
    await tester.pump();

    final pressed = tester.widget<Transform>(
      find.byKey(const ValueKey('aletheia-press-transform')),
    );
    expect(pressed.transform.storage[0], lessThan(1));

    await gesture.cancel();
    await tester.pumpAndSettle();

    final restored = tester.widget<Transform>(
      find.byKey(const ValueKey('aletheia-press-transform')),
    );
    expect(restored.transform.storage[0], 1);
  });

  testWidgets('press feedback restores when a finger leaves the card', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Center(
            child: AletheiaPressFeedback(
              child: SizedBox(
                key: ValueKey('press-exit-target'),
                width: 44,
                height: 44,
              ),
            ),
          ),
        ),
      ),
    );

    final gesture = await tester.startGesture(
      tester.getCenter(find.byKey(const ValueKey('press-exit-target'))),
    );
    await tester.pump();
    await gesture.moveBy(const Offset(80, 0));
    await tester.pumpAndSettle();

    final restored = tester.widget<Transform>(
      find.byKey(const ValueKey('aletheia-press-transform')),
    );
    expect(restored.transform.storage[0], 1);
    await gesture.up();
  });

  testWidgets('reduced motion preserves the original press scale', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MediaQuery(
        data: MediaQueryData(disableAnimations: true),
        child: MaterialApp(
          home: Scaffold(
            body: Center(
              child: AletheiaPressFeedback(
                child: SizedBox(
                  key: ValueKey('reduced-motion-target'),
                  width: 44,
                  height: 44,
                ),
              ),
            ),
          ),
        ),
      ),
    );

    final gesture = await tester.startGesture(
      tester.getCenter(find.byKey(const ValueKey('reduced-motion-target'))),
    );
    await tester.pump();

    final transform = tester.widget<Transform>(
      find.byKey(const ValueKey('aletheia-press-transform')),
    );
    expect(transform.transform.storage[0], 1);
    await gesture.cancel();
  });

  testWidgets('theme changes never animate the whole HMI tree', (tester) async {
    late Duration duration;
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(disableAnimations: true),
        child: Builder(
          builder: (context) {
            duration = AletheiaMotion.themeAnimationDuration(context);
            return const SizedBox();
          },
        ),
      ),
    );

    expect(duration, Duration.zero);
  });

  testWidgets('status replacement removes the previous label immediately', (
    tester,
  ) async {
    var isConnected = false;
    late StateSetter setState;

    await tester.pumpWidget(
      MaterialApp(
        home: StatefulBuilder(
          builder: (context, stateSetter) {
            setState = stateSetter;
            return AletheiaStatusTransition(
              stateKey: isConnected ? 'connected' : 'connecting',
              child: Text(isConnected ? '已连接' : '连接中'),
            );
          },
        ),
      ),
    );

    setState(() => isConnected = true);
    await tester.pump();

    expect(find.text('已连接'), findsOneWidget);
    expect(find.text('连接中'), findsNothing);
  });

  test('haptic gate emits one event until it is reset', () async {
    var emissions = 0;
    final gate = AletheiaHapticGate();

    await gate.triggerOnce('manual-ready:session-1', () async => emissions++);
    await gate.triggerOnce('manual-ready:session-1', () async => emissions++);

    expect(emissions, 1);

    gate.reset();
    await gate.triggerOnce('manual-ready:session-1', () async => emissions++);
    expect(emissions, 2);
  });
}
