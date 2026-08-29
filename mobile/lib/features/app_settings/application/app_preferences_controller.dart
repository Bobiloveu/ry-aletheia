import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/app_preferences_store.dart';
import '../domain/app_preferences.dart';

final appPreferencesStoreProvider = Provider<AppPreferencesStore>(
  (ref) => AppPreferencesStore(),
);

final appPreferencesControllerProvider =
    NotifierProvider<AppPreferencesController, AppPreferences>(
      AppPreferencesController.new,
    );

class AppPreferencesController extends Notifier<AppPreferences> {
  @override
  AppPreferences build() {
    Future<void>.microtask(_restore);
    return const AppPreferences();
  }

  Future<void> _restore() async {
    try {
      state = await ref.read(appPreferencesStoreProvider).read();
    } catch (_) {
      // Preferences are a local convenience. A storage failure must never
      // prevent entering the HMI or connecting to a robot.
    }
  }

  Future<void> setLanguage(AppLanguage value) =>
      _save(state.copyWith(language: value));

  Future<void> setTheme(AppThemePreference value) =>
      _save(state.copyWith(theme: value));

  Future<void> _save(AppPreferences next) async {
    state = next;
    try {
      await ref.read(appPreferencesStoreProvider).write(next);
    } catch (_) {
      // Keep the current-session choice even when durable storage is absent.
    }
  }
}
