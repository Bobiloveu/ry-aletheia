import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/features/app_settings/domain/app_preferences.dart';
import 'package:aletheia_mobile/features/app_settings/presentation/app_settings_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('persists a language choice and immediately localizes settings', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const AppSettingsScreen(),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('应用设置'), findsOneWidget);
    expect(find.text('检查更新'), findsOneWidget);
    expect(find.text('运行平台'), findsNothing);
    await tester.tap(find.text('语言'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('English').first);
    await tester.pumpAndSettle();

    expect(find.text('App settings'), findsOneWidget);
    expect(find.text('Report a problem'), findsOneWidget);
  });

  testWidgets('offers exactly the default and daylight appearances', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const AppSettingsScreen(),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('HMI 深色'), findsOneWidget);
    await tester.tap(find.text('主题'));
    await tester.pumpAndSettle();
    expect(find.byType(RadioListTile<AppThemePreference>), findsNWidgets(2));
    expect(find.text('高对比深色'), findsNothing);
    await tester.tap(find.text('日间模式'));
    await tester.pumpAndSettle();

    expect(find.text('日间模式'), findsOneWidget);
  });
}
