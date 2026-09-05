import 'package:aletheia_mobile/app/app.dart';
import 'package:aletheia_mobile/features/app_settings/application/app_preferences_controller.dart';
import 'package:aletheia_mobile/features/app_settings/data/app_preferences_store.dart';
import 'package:aletheia_mobile/features/app_settings/domain/app_preferences.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'theme switching rebuilds the shell app bar with the new palette',
    (tester) async {
      final container = ProviderContainer(
        overrides: [
          appPreferencesStoreProvider.overrideWithValue(
            _MemoryPreferencesStore(),
          ),
        ],
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const AletheiaApp(),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        tester.widget<AppBar>(find.byType(AppBar)).backgroundColor,
        const Color(0xFF101415),
      );

      await container
          .read(appPreferencesControllerProvider.notifier)
          .setTheme(AppThemePreference.daylight);
      await tester.pumpAndSettle();

      expect(
        tester.widget<AppBar>(find.byType(AppBar)).backgroundColor,
        const Color(0xFFF5F8FC),
      );
      expect(
        Theme.of(tester.element(find.byType(Scaffold).first)).brightness,
        Brightness.light,
      );
    },
  );
}

class _MemoryPreferencesStore extends AppPreferencesStore {
  AppPreferences value = const AppPreferences();

  @override
  Future<AppPreferences> read() async => value;

  @override
  Future<void> write(AppPreferences next) async {
    value = next;
  }
}
