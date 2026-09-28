import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
import '../data/reports_repository.dart';
import '../domain/aletheia_report.dart';
import '../domain/native_report_trajectory.dart';

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

final nativeReportTrajectoryProvider = AsyncNotifierProvider.autoDispose
    .family<
      NativeReportTrajectoryController,
      NativeReportTrajectoryState,
      NativeReportTrajectoryKey
    >((key) => NativeReportTrajectoryController(key));

/// The only image source a report trajectory workspace may render. The URL is
/// derived from the validated report-scoped identifiers, never supplied by
/// report JSON. Gallery can override this provider with an in-memory raster.
final nativeReportTrajectoryMapImageProvider = Provider.autoDispose
    .family<ImageProvider?, NativeReportTrajectoryKey>((ref, key) {
      final endpoint = ref.watch(
        robotConnectionControllerProvider.select(
          (connection) => connection.isConnected ? connection.endpoint : null,
        ),
      );
      if (endpoint == null) return null;
      final uri = ref
          .read(reportsRepositoryProvider)
          .nativeTrajectoryMapUri(endpoint, key.reportId, key.trajectoryId);
      return NetworkImage(uri.toString());
    });

class NativeReportTrajectoryKey {
  const NativeReportTrajectoryKey({
    required this.reportId,
    required this.trajectoryId,
  });

  final String reportId;
  final String trajectoryId;

  @override
  bool operator ==(Object other) =>
      other is NativeReportTrajectoryKey &&
      other.reportId == reportId &&
      other.trajectoryId == trajectoryId;

  @override
  int get hashCode => Object.hash(reportId, trajectoryId);
}

class NativeReportTrajectoryController
    extends AsyncNotifier<NativeReportTrajectoryState> {
  NativeReportTrajectoryController(this._key);

  final NativeReportTrajectoryKey _key;
  RobotEndpoint? _endpoint;

  @override
  Future<NativeReportTrajectoryState> build() async {
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select(
        (connection) => connection.isConnected ? connection.endpoint : null,
      ),
    );
    _endpoint = endpoint;
    if (endpoint == null) {
      throw StateError('请先连接机器人。');
    }
    final trajectory = await ref
        .read(reportsRepositoryProvider)
        .loadNativeTrajectory(endpoint, _key.reportId, _key.trajectoryId);
    return NativeReportTrajectoryState.fromTrajectory(trajectory);
  }

  Future<void> loadMoreSamples() async {
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
          .loadNativeTrajectorySamples(
            endpoint,
            _key.reportId,
            _key.trajectoryId,
            cursor: cursor,
          );
      if (_endpoint != endpoint) return;
      state = AsyncData(current.append(page));
    } catch (error, stackTrace) {
      if (_endpoint != endpoint) return;
      state = AsyncData(current.appendError(error, stackTrace));
    }
  }
}

class NativeReportTrajectoryState {
  const NativeReportTrajectoryState({
    required this.trajectory,
    required this.samples,
    required this.nextCursor,
    this.isLoadingMore = false,
    this.loadMoreError,
    this.loadMoreStackTrace,
  });

  factory NativeReportTrajectoryState.fromTrajectory(
    NativeReportTrajectory trajectory,
  ) => NativeReportTrajectoryState(
    trajectory: trajectory,
    samples: const [],
    nextCursor: trajectory.samplesNextCursor,
  );

  final NativeReportTrajectory trajectory;
  final List<NativeTrajectorySample> samples;
  final String? nextCursor;
  final bool isLoadingMore;
  final Object? loadMoreError;
  final StackTrace? loadMoreStackTrace;

  NativeReportTrajectoryState loadingMore() => NativeReportTrajectoryState(
    trajectory: trajectory,
    samples: samples,
    nextCursor: nextCursor,
    isLoadingMore: true,
  );

  NativeReportTrajectoryState append(NativeTrajectorySamplePage page) {
    if (samples.isNotEmpty &&
        page.samples.isNotEmpty &&
        page.samples.first.sampleIndex <= samples.last.sampleIndex) {
      throw const FormatException('原生轨迹样本分页顺序无效。');
    }
    return NativeReportTrajectoryState(
      trajectory: trajectory,
      samples: [...samples, ...page.samples],
      nextCursor: page.nextCursor,
    );
  }

  NativeReportTrajectoryState appendError(
    Object error,
    StackTrace stackTrace,
  ) => NativeReportTrajectoryState(
    trajectory: trajectory,
    samples: samples,
    nextCursor: nextCursor,
    loadMoreError: error,
    loadMoreStackTrace: stackTrace,
  );
}

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
