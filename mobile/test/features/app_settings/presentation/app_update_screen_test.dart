import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/features/app_settings/presentation/app_update_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('update check is explicit when no distribution service exists', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const AppUpdateScreen(),
        ),
      ),
    );

    expect(find.text('检查更新'), findsOneWidget);
    expect(find.text('运行平台'), findsNothing);
    await tester.tap(find.text('立即检查'));
    await tester.pump();

    expect(find.text('当前开发版本尚未接入在线更新服务。'), findsOneWidget);
  });
}
