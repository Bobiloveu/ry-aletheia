import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../core/connection/robot_connection_controller.dart';
import '../features/app_settings/application/app_preferences_controller.dart';
import '../features/app_settings/data/app_diagnostic_log.dart';
import '../features/app_settings/domain/app_preferences.dart';
import '../features/test_runs/application/test_runs_controller.dart';
import 'router.dart';
import 'theme/aletheia_theme.dart';

class AletheiaApp extends ConsumerStatefulWidget {
  const AletheiaApp({super.key});

  @override
  ConsumerState<AletheiaApp> createState() => _AletheiaAppState();
}

class _AletheiaAppState extends ConsumerState<AletheiaApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    ref.read(appDiagnosticLogProvider).record('app_started');
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    ref.read(appDiagnosticLogProvider).record('lifecycle_${state.name}');
    final controller = ref.read(robotConnectionControllerProvider.notifier);
    switch (state) {
      case AppLifecycleState.resumed:
        controller.resumeHeartbeats();
        ref.read(testRunsControllerProvider.notifier).resumePolling();
      case AppLifecycleState.inactive:
      case AppLifecycleState.hidden:
      case AppLifecycleState.paused:
      case AppLifecycleState.detached:
        controller.pauseHeartbeats();
        ref.read(testRunsControllerProvider.notifier).pausePolling();
    }
  }

  @override
  Widget build(BuildContext context) {
    final preferences = ref.watch(appPreferencesControllerProvider);
    return MaterialApp.router(
      title: 'Aletheia',
      debugShowCheckedModeBanner: false,
      locale: preferences.language.locale,
      supportedLocales: AppLanguage.values.map((value) => value.locale),
      localizationsDelegates: [
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ],
      theme: switch (preferences.theme) {
        AppThemePreference.hmiDark => AletheiaTheme.dark(),
        AppThemePreference.daylight => AletheiaTheme.light(),
        AppThemePreference.highContrastDark => AletheiaTheme.dark(
          highContrast: true,
        ),
      },
      routerConfig: ref.watch(appRouterProvider),
    );
  }
}
