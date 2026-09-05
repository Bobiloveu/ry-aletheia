import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/widgets.dart';
import 'package:go_router/go_router.dart';

import 'app_shell.dart';
import 'motion/aletheia_motion.dart';
import '../debug_ui/debug_ui_gallery_screen.dart';
import '../features/robot_connection/presentation/robot_connection_screen.dart';
import '../features/reports/presentation/reports_screen.dart';
import '../features/live_observation/presentation/live_observation_screen.dart';
import '../features/manual_control/presentation/manual_control_screen.dart';
import '../features/test_cases/presentation/test_cases_screen.dart';
import '../features/test_runs/presentation/test_runs_screen.dart';
import '../features/tool_logs/presentation/tool_logs_screen.dart';
import '../features/tools/presentation/tools_screen.dart';
import '../features/runtime_settings/presentation/runtime_settings_screen.dart';
import '../features/scenario_setup/presentation/scenario_setup_screen.dart';
import '../features/system_maintenance/presentation/system_maintenance_screen.dart';
import '../features/app_settings/presentation/app_settings_screen.dart';
import '../features/app_settings/presentation/app_update_screen.dart';
import '../features/app_settings/presentation/feedback_screen.dart';

/// An explicit, build-time-only test seam for device validation of a
/// production-mode Unity library. It defaults to false and is never supplied
/// by the normal packaging scripts, so the gallery remains absent from every
/// distributable build.
const _includeDeviceValidationGallery = bool.fromEnvironment(
  'AV_ENABLE_DEVICE_VALIDATION_GALLERY',
);

final appRouterProvider = Provider<GoRouter>((ref) {
  final router = GoRouter(
    // `flutter run --route /__debug/ui-gallery?...` is the repeatable way to
    // exercise live-map stress states without a robot. GoRouter does not read
    // Flutter's platform route automatically when an explicit
    // [initialLocation] is supplied, so honour it in Debug only. A separate
    // explicit device-validation define exists solely to exercise the final
    // Release Unity binary against deterministic local map data.
    initialLocation: _initialLocation(),
    routes: [
      if (kDebugMode || _includeDeviceValidationGallery)
        GoRoute(
          path: DebugUiGalleryScreen.routePath,
          pageBuilder: (context, state) => AletheiaMotion.rootPage(
            key: state.pageKey,
            child: DebugUiGalleryScreen(
              initialScreenId: state.uri.queryParameters['screen'],
            ),
          ),
        ),
      GoRoute(
        path: '/',
        redirect: (context, state) => RobotConnectionScreen.routePath,
      ),
      GoRoute(
        path: RobotConnectionScreen.legacyRoutePath,
        redirect: (context, state) => RobotConnectionScreen.routePath,
      ),
      GoRoute(
        path: TestCasesScreen.legacyRoutePath,
        redirect: (context, state) => TestCasesScreen.routePath,
      ),
      GoRoute(
        path: TestRunsScreen.legacyRoutePath,
        redirect: (context, state) => TestRunsScreen.routePath,
      ),
      GoRoute(
        path: '/tools/app-settings',
        redirect: (context, state) => AppSettingsScreen.routePath,
      ),
      ShellRoute(
        builder: (context, state, child) =>
            AletheiaAppShell(location: state.uri.path, child: child),
        routes: [
          GoRoute(
            path: RobotConnectionScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.rootPage(
              key: state.pageKey,
              child: const RobotConnectionScreen(embedded: true),
            ),
          ),
          GoRoute(
            path: LiveObservationScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.rootPage(
              key: state.pageKey,
              child: const LiveObservationScreen(),
            ),
          ),
          GoRoute(
            path: ToolsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.rootPage(
              key: state.pageKey,
              child: const ToolsScreen(),
            ),
          ),
          GoRoute(
            path: ManualControlScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const ManualControlScreen(),
            ),
          ),
          GoRoute(
            path: TestCasesScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const TestCasesScreen(),
            ),
          ),
          GoRoute(
            path: TestRunsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const TestRunsScreen(),
            ),
          ),
          GoRoute(
            path: ToolLogsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const ToolLogsScreen(),
            ),
          ),
          GoRoute(
            path: ReportsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const ReportsScreen(),
            ),
          ),
          GoRoute(
            path: RuntimeSettingsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const RuntimeSettingsScreen(),
            ),
          ),
          GoRoute(
            path: ScenarioSetupScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const ScenarioSetupScreen(),
            ),
          ),
          GoRoute(
            path: SystemMaintenanceScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const SystemMaintenanceScreen(),
            ),
          ),
          GoRoute(
            path: AppSettingsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.rootPage(
              key: state.pageKey,
              child: const AppSettingsScreen(embedded: true),
            ),
          ),
          GoRoute(
            path: AppFeedbackScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const AppFeedbackScreen(),
            ),
          ),
          GoRoute(
            path: AppUpdateScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const AppUpdateScreen(),
            ),
          ),
        ],
      ),
    ],
  );
  ref.onDispose(router.dispose);
  return router;
});

String _initialLocation() {
  if (!kDebugMode && !_includeDeviceValidationGallery) {
    return RobotConnectionScreen.routePath;
  }
  // Unlike Android/iOS engine launch arguments, this compile-time debug
  // define works for `flutter build` + `simctl/devicectl launch` too. It is
  // intentionally ignored outside Debug unless the explicit local
  // device-validation build flag is present. Normal release packaging never
  // supplies that flag, so it cannot become a production entry point.
  const debugRoute = String.fromEnvironment('AV_DEBUG_ROUTE');
  if (debugRoute.startsWith('/')) return debugRoute;
  final route = WidgetsBinding.instance.platformDispatcher.defaultRouteName;
  return route.startsWith('/') && route != '/'
      ? route
      : RobotConnectionScreen.routePath;
}
