import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../data/scenario_setup_repository.dart';
import '../domain/scenario_setup.dart';

final scenarioSetupRepositoryProvider = Provider<ScenarioSetupRepository>(
  (ref) => ScenarioSetupRepository(ref.watch(aletheiaApiClientProvider)),
);

final scenarioSetupProvider = FutureProvider.autoDispose<ScenarioSetupStatus>((
  ref,
) async {
  final endpoint = ref.watch(
    robotConnectionControllerProvider.select(
      (state) => state.isConnected ? state.endpoint : null,
    ),
  );
  if (endpoint == null) throw StateError('请先连接机器人。');
  return ref.read(scenarioSetupRepositoryProvider).load(endpoint);
});
