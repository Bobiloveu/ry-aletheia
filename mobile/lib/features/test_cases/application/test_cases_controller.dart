import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_connection_state.dart';
import '../data/test_cases_repository.dart';

final testCasesRepositoryProvider = Provider<TestCasesRepository>((ref) {
  return TestCasesRepository(ref.watch(aletheiaApiClientProvider));
});

final caseCatalogProvider =
    AsyncNotifierProvider<CaseCatalogController, CaseCatalog>(
      CaseCatalogController.new,
    );

class CaseCatalogController extends AsyncNotifier<CaseCatalog> {
  @override
  Future<CaseCatalog> build() async {
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select(
        (state) => state.isConnected ? state.endpoint : null,
      ),
    );
    if (endpoint == null) {
      return const CaseCatalog.empty();
    }
    return ref.read(testCasesRepositoryProvider).load(endpoint);
  }

  Future<void> refresh() async {
    final connection = ref.read(robotConnectionControllerProvider);
    if (connection.phase != ConnectionPhase.connected ||
        connection.endpoint == null) {
      state = const AsyncData(CaseCatalog.empty());
      return;
    }
    state = const AsyncLoading();
    state = await AsyncValue.guard(
      () => ref.read(testCasesRepositoryProvider).load(connection.endpoint!),
    );
  }
}

final selectedCaseIdProvider =
    NotifierProvider<SelectedCaseIdController, String?>(
      SelectedCaseIdController.new,
    );

class SelectedCaseIdController extends Notifier<String?> {
  @override
  String? build() => null;

  void select(String? caseId) => state = caseId;
}
