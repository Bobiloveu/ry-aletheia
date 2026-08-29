import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../data/tool_logs_repository.dart';
import '../domain/tool_log_entry.dart';

final toolLogsRepositoryProvider = Provider<ToolLogsRepository>((ref) {
  return ToolLogsRepository(ref.watch(aletheiaApiClientProvider));
});

final toolLogScopeProvider =
    NotifierProvider<ToolLogScopeController, ToolLogScope>(
      ToolLogScopeController.new,
    );

class ToolLogScopeController extends Notifier<ToolLogScope> {
  @override
  ToolLogScope build() => ToolLogScope.all;

  void select(ToolLogScope scope) => state = scope;
}

final toolLogEntriesProvider = FutureProvider.autoDispose<List<ToolLogEntry>>((
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
  final scope = ref.watch(toolLogScopeProvider);
  return ref.read(toolLogsRepositoryProvider).load(endpoint, scope);
});

final diagnosticFilesProvider =
    FutureProvider.autoDispose<List<DiagnosticFile>>((ref) async {
      final endpoint = ref.watch(
        robotConnectionControllerProvider.select(
          (state) => state.isConnected ? state.endpoint : null,
        ),
      );
      if (endpoint == null) return const [];
      return ref.read(toolLogsRepositoryProvider).files(endpoint);
    });
