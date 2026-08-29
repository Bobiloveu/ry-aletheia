import 'package:aletheia_mobile/app/app.dart';
import 'package:aletheia_mobile/features/app_settings/application/app_preferences_controller.dart';
import 'package:aletheia_mobile/features/app_settings/data/app_preferences_store.dart';
import 'package:aletheia_mobile/features/app_settings/domain/app_preferences.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('root app provides Material localizations for the saved locale', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appPreferencesStoreProvider.overrideWithValue(
            _FixedPreferencesStore(),
          ),
        ],
        child: const AletheiaApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });

  testWidgets('root app applies the saved daylight appearance', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appPreferencesStoreProvider.overrideWithValue(
            _FixedPreferencesStore(
              const AppPreferences(theme: AppThemePreference.daylight),
            ),
          ),
        ],
        child: const AletheiaApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      Theme.of(tester.element(find.byType(Scaffold).first)).brightness,
      Brightness.light,
    );
  });
}

class _FixedPreferencesStore extends AppPreferencesStore {
  _FixedPreferencesStore([
    this.preferences = const AppPreferences(language: AppLanguage.chinese),
  ]);

  final AppPreferences preferences;

  @override
  Future<AppPreferences> read() async => preferences;
}
