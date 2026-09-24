import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
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

final nativeReportDetailProvider = AsyncNotifierProvider.autoDispose
    .family<NativeReportDetailController, NativeReportDetailState, String>(
      (reportId) => NativeReportDetailController(reportId),
    );

class NativeReportDetailController
    extends AsyncNotifier<NativeReportDetailState> {
  NativeReportDetailController(this._reportId);

  final String _reportId;
  RobotEndpoint? _endpoint;

  @override
  Future<NativeReportDetailState> build() async {
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select(
        (connection) => connection.isConnected ? connection.endpoint : null,
      ),
    );
    _endpoint = endpoint;
    if (endpoint == null) {
      throw StateError('请先连接机器人。');
    }
    final page = await ref
        .read(reportsRepositoryProvider)
        .loadNativeDetail(endpoint, _reportId);
    return NativeReportDetailState.fromFirstPage(page);
  }

  Future<void> loadNextPage() async {
    final current = state.asData?.value;
    final endpoint = _endpoint;
    final cursor = current?.nextCursor;
    if (endpoint == null ||
        current == null ||
        current.isLoadingMore ||
        cursor == null) {
      return;
    }

    state = AsyncData(current.loadingMore());
    try {
      final page = await ref
          .read(reportsRepositoryProvider)
          .loadNativeDetail(endpoint, _reportId, cursor: cursor);
      if (_endpoint != endpoint) return;
      state = AsyncData(current.append(page));
    } catch (error, stackTrace) {
      if (_endpoint != endpoint) return;
      state = AsyncData(current.appendError(error, stackTrace));
    }
  }
}

class NativeReportDetailState {
  const NativeReportDetailState({
    required this.report,
    required this.items,
    required this.nextCursor,
    this.isLoadingMore = false,
    this.loadMoreError,
    this.loadMoreStackTrace,
  });

  factory NativeReportDetailState.fromFirstPage(NativeReportDetailPage page) {
    return NativeReportDetailState(
      report: page.report,
      items: page.items,
      nextCursor: page.nextCursor,
    );
  }

  final NativeReportSummary report;
  final List<NativeReportItem> items;
  final String? nextCursor;
  final bool isLoadingMore;
  final Object? loadMoreError;
  final StackTrace? loadMoreStackTrace;

  NativeReportDetailState loadingMore() => NativeReportDetailState(
    report: report,
    items: items,
    nextCursor: nextCursor,
    isLoadingMore: true,
  );

  NativeReportDetailState append(NativeReportDetailPage page) =>
      NativeReportDetailState(
        report: page.report,
        items: [...items, ...page.items],
        nextCursor: page.nextCursor,
      );

  NativeReportDetailState appendError(Object error, StackTrace stackTrace) =>
      NativeReportDetailState(
        report: report,
        items: items,
        nextCursor: nextCursor,
        loadMoreError: error,
        loadMoreStackTrace: stackTrace,
      );
}
