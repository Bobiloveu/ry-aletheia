import 'package:aletheia_visualization/aletheia_visualization.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const channel = MethodChannel('aletheia_visualization/surface_42');

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  testWidgets('waits for the native Unity scene readiness handshake', (
    tester,
  ) async {
    var reads = 0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          if (call.method == 'isReady') {
            reads++;
            return reads >= 2;
          }
          return null;
        });

    final controller = VisualizationController(42);
    final ready = await tester.runAsync(
      () => controller.waitUntilReady(
        timeout: const Duration(milliseconds: 200),
      ),
    );
    expect(ready, isTrue);
    expect(reads, greaterThanOrEqualTo(2));
    await controller.dispose();
  });

  testWidgets('surface disposal pauses once instead of unloading Unity', (
    tester,
  ) async {
    final calls = <String>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          calls.add(call.method);
          return null;
        });

    final controller = VisualizationController(42);
    await controller.dispose();
    await controller.dispose();

    expect(calls, ['pause']);
  });
}
