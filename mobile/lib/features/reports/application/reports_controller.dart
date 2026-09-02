import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../data/reports_repository.dart';
import '../domain/aletheia_report.dart';

final reportsRepositoryProvider = Provider<ReportsRepository>((ref) {
  return ReportsRepository(ref.watch(aletheiaApiClientProvider));
});

final reportsProvider = FutureProvider.autoDispose<List<AletheiaReport>>((
  ref,
) async {
  final endpoint = ref.watch(
    robotConnectionControllerProvider.select(
      (state) => state.isConnected ? state.endpoint : null,
    ),
  );
  if (endpoint == null) {
    return const [];
  }
  return ref.read(reportsRepositoryProvider).load(endpoint);
});
