import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../data/runtime_settings_repository.dart';
import '../domain/runtime_settings.dart';

final runtimeSettingsRepositoryProvider = Provider<RuntimeSettingsRepository>(
  (ref) => RuntimeSettingsRepository(ref.watch(aletheiaApiClientProvider)),
);

final runtimeSettingsProvider = FutureProvider.autoDispose<RuntimeSettings>((
  ref,
) async {
  final endpoint = ref.watch(
    robotConnectionControllerProvider.select(
      (state) => state.isConnected ? state.endpoint : null,
    ),
  );
  if (endpoint == null) {
    throw StateError('请先连接机器人。');
  }
  return ref.read(runtimeSettingsRepositoryProvider).load(endpoint);
});

final supervisorProcessesProvider =
    FutureProvider.autoDispose<List<SupervisorProcess>>((ref) async {
      final endpoint = ref.watch(
        robotConnectionControllerProvider.select(
          (state) => state.isConnected ? state.endpoint : null,
        ),
      );
      if (endpoint == null) {
        return const [];
      }
      return ref.read(runtimeSettingsRepositoryProvider).discover(endpoint);
    });
