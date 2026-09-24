import 'package:aletheia_mobile/app/motion/aletheia_interaction.dart';
import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:aletheia_mobile/features/tools/presentation/tools_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'tool cards provide immediate press feedback without navigation',
    (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            robotConnectionControllerProvider.overrideWith(
              _DisconnectedConnectionController.new,
            ),
          ],
          child: MaterialApp(theme: AletheiaTheme.light(), home: ToolsScreen()),
        ),
      );

      expect(find.byType(AletheiaPressFeedback), findsWidgets);

      final card = find.text('手动控制');
      final gesture = await tester.startGesture(tester.getCenter(card));
      await tester.pump();

      final transform = tester.widget<Transform>(
        find.byKey(const ValueKey('aletheia-press-transform')).first,
      );
      expect(transform.transform.storage[0], lessThan(1));

      await gesture.cancel();
    },
  );
}

class _DisconnectedConnectionController extends RobotConnectionController {
  @override
  RobotConnectionState build() =>
      const RobotConnectionState(phase: ConnectionPhase.idle);
}
