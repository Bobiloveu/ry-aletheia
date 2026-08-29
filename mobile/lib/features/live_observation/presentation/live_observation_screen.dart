import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/responsive_layout.dart';
import '../../../app/motion/aletheia_motion.dart';
import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../application/cloud_telemetry_provider.dart';
import '../application/live_observation_controller.dart';
import '../application/pose_telemetry_provider.dart';
import '../application/video_status_controller.dart';
import '../data/cloud_telemetry_client.dart';
import '../domain/cloud_frame.dart';
import '../domain/live_map.dart';
import '../domain/pose_frame.dart';
import '../domain/video_status.dart';
import 'whep_video_view.dart';

/// Optional debug-only replacement for map pixels.
///
/// Production always renders the map image returned by the robot. The Gallery
/// supplies a deterministic local map drawing through this seam, while the
/// real viewport, pose layer and point-cloud layer remain unchanged.
typedef LiveMapPreviewBuilder = Widget Function({required LiveMapAsset map});

final liveMapPreviewBuilderProvider = Provider<LiveMapPreviewBuilder?>(
  (ref) => null,
);

class LiveObservationScreen extends ConsumerStatefulWidget {
  const LiveObservationScreen({
    this.initialWorkspace = ObservationWorkspace.map,
    super.key,
  });

  static const routePath = '/observation';

  /// A presentation-only initial selection used by the Debug UI Gallery.
  /// Regular navigation always uses the map default.
  final ObservationWorkspace initialWorkspace;

  @override
  ConsumerState<LiveObservationScreen> createState() =>
      _LiveObservationScreenState();
}

class _LiveObservationScreenState extends ConsumerState<LiveObservationScreen>
    with WidgetsBindingObserver {
  late final LiveObservationController _observationController;

  @override
  void initState() {
    super.initState();
    _observationController = ref.read(
      liveObservationControllerProvider.notifier,
    );
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _observationController.activate();
      }
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _observationController.pauseMapPolling();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _observationController.activate();
    } else if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.hidden ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _observationController.pauseMapPolling();
    }
  }

  @override
  Widget build(BuildContext context) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    if (!connected) {
      return const _ConnectionRequired();
    }
    final state = ref.watch(liveObservationControllerProvider);
    return SafeArea(
      top: false,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final isLandscape = constraints.maxWidth > constraints.maxHeight;
          final workspaceHeight = observationWorkspaceHeight(
            viewportHeight: constraints.maxHeight,
            isLandscape: isLandscape,
          );
          return RefreshIndicator(
            onRefresh: () =>
                ref.read(liveObservationControllerProvider.notifier).refresh(),
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: EdgeInsets.fromLTRB(
                isLandscape ? 12 : 20,
                isLandscape ? 10 : 16,
                isLandscape ? 12 : 20,
                isLandscape ? 12 : 28,
              ),
              children: [
                Center(
                  // Center deliberately gives its child loose constraints.
                  // Give the HMI workspace an explicit bounded width instead
                  // of letting an AspectRatio map/video panel shrink-wrap it.
                  child: SizedBox(
                    width: math.min(constraints.maxWidth, 1240),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (!isLandscape) ...[
                          const _PageLabel(
                            icon: Icons.radar_outlined,
                            text: '实时观测',
                          ),
                          const SizedBox(height: 10),
                          Text(
                            '查看地图与相机',
                            style: Theme.of(context).textTheme.headlineSmall,
                          ),
                          SizedBox(height: 7),
                          Text(
                            '在这里切换查看地图、实时位置、点云和相机。',
                            style: TextStyle(
                              color: AletheiaTheme.textSecondary,
                              height: 1.4,
                            ),
                          ),
                          const SizedBox(height: 20),
                        ],
                        _ObservationBody(
                          state: state,
                          isLandscape: isLandscape,
                          workspaceHeight: workspaceHeight,
                          initialWorkspace: widget.initialWorkspace,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

enum ObservationWorkspace { map, camera }

class _ObservationBody extends ConsumerStatefulWidget {
  const _ObservationBody({
    required this.state,
    required this.isLandscape,
    required this.workspaceHeight,
    required this.initialWorkspace,
  });

  final LiveObservationState state;
  final bool isLandscape;
  final double workspaceHeight;
  final ObservationWorkspace initialWorkspace;

  @override
  ConsumerState<_ObservationBody> createState() => _ObservationBodyState();
}

class _ObservationBodyState extends ConsumerState<_ObservationBody> {
  late ObservationWorkspace _workspace;

  @override
  void initState() {
    super.initState();
    _workspace = widget.initialWorkspace;
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (!widget.isLandscape) ...[
          _WorkspaceSelector(
            workspace: _workspace,
            onChanged: _changeWorkspace,
          ),
          const SizedBox(height: 12),
        ],
        AletheiaFadeThrough(
          child: KeyedSubtree(
            key: ValueKey('observation-workspace-${_workspace.name}'),
            child: _workspace == ObservationWorkspace.camera
                ? _VideoPanel(
                    isLandscape: widget.isLandscape,
                    workspaceHeight: widget.workspaceHeight,
                    onWorkspaceChanged: _changeWorkspace,
                  )
                : _buildMapWorkspace(context),
          ),
        ),
      ],
    );
  }

  void _changeWorkspace(ObservationWorkspace workspace) {
    if (workspace != _workspace) {
      setState(() => _workspace = workspace);
    }
  }

  Widget _buildMapWorkspace(BuildContext context) {
    final controller = ref.read(liveObservationControllerProvider.notifier);
    final state = widget.state;
    if (state.phase == LiveObservationPhase.loading && state.map == null) {
      return const _StatePanel(
        icon: Icons.sync_rounded,
        title: '正在准备观测链路',
        detail: '正在准备实时数据与地图。',
        loading: true,
      );
    }
    if (state.phase == LiveObservationPhase.unavailable ||
        state.phase == LiveObservationPhase.failure) {
      return _StatePanel(
        icon: state.phase == LiveObservationPhase.failure
            ? Icons.error_outline_rounded
            : Icons.portable_wifi_off_rounded,
        title: state.phase == LiveObservationPhase.failure
            ? '无法读取实时观测'
            : '实时观测暂不可用',
        detail: state.message,
        error: state.phase == LiveObservationPhase.failure,
        actionLabel: '重新检查',
        onAction: controller.refresh,
      );
    }

    final map = state.map;
    if (map == null) {
      return _StatePanel(
        icon: Icons.map_outlined,
        title: '等待活动地图',
        detail: state.message,
        actionLabel: '刷新地图',
        onAction: controller.refresh,
      );
    }
    return _MapPanel(
      map: map,
      isRefreshing: state.isRefreshing,
      message: state.message,
      onRefresh: controller.refresh,
      isLandscape: widget.isLandscape,
      workspaceHeight: widget.workspaceHeight,
      onWorkspaceChanged: _changeWorkspace,
      onFullscreen: () => _openMapFullscreen(context, map, controller),
    );
  }

  Future<void> _openMapFullscreen(
    BuildContext context,
    LiveMapAsset map,
    LiveObservationController controller,
  ) {
    final container = ProviderScope.containerOf(context);
    return Navigator.of(context).push<void>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => UncontrolledProviderScope(
          container: container,
          child: _MapFullscreenScreen(
            map: map,
            onRefresh: controller.refresh,
            onShowCamera: () {
              Navigator.of(context).pop();
              _changeWorkspace(ObservationWorkspace.camera);
            },
          ),
        ),
      ),
    );
  }
}

class _WorkspaceSelector extends StatelessWidget {
  const _WorkspaceSelector({required this.workspace, required this.onChanged});

  final ObservationWorkspace workspace;
  final ValueChanged<ObservationWorkspace> onChanged;

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<ObservationWorkspace>(
      segments: const [
        ButtonSegment(
          value: ObservationWorkspace.map,
          icon: Icon(Icons.map_outlined),
          label: Text('地图'),
        ),
        ButtonSegment(
          value: ObservationWorkspace.camera,
          icon: Icon(Icons.videocam_outlined),
          label: Text('相机'),
        ),
      ],
      selected: {workspace},
      showSelectedIcon: false,
      onSelectionChanged: (selection) => onChanged(selection.first),
    );
  }
}

class _VideoPanel extends ConsumerStatefulWidget {
  const _VideoPanel({
    required this.isLandscape,
    required this.workspaceHeight,
    required this.onWorkspaceChanged,
  });

  final bool isLandscape;
  final double workspaceHeight;
  final ValueChanged<ObservationWorkspace> onWorkspaceChanged;

  @override
  ConsumerState<_VideoPanel> createState() => _VideoPanelState();
}

class _VideoPanelState extends ConsumerState<_VideoPanel>
    with WidgetsBindingObserver {
  bool _isForeground = true;
  late final VideoStatusController _videoController;

  @override
  void initState() {
    super.initState();
    _videoController = ref.read(videoStatusControllerProvider.notifier);
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _videoController.activate();
      }
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _videoController.pause();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      setState(() => _isForeground = true);
      _videoController.activate();
    } else if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.hidden ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      setState(() => _isForeground = false);
      _videoController.pause();
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(videoStatusControllerProvider);
    if (state.phase == VideoStatusPhase.loading && state.status == null) {
      return const _StatePanel(
        icon: Icons.videocam_outlined,
        title: '正在读取视频状态',
        detail: '正在检查可用相机。',
        loading: true,
      );
    }
    final status = state.status;
    final stream = state.selectedStream;
    if (status == null || stream == null) {
      return _StatePanel(
        icon: state.phase == VideoStatusPhase.failure
            ? Icons.error_outline_rounded
            : Icons.videocam_off_outlined,
        title: state.phase == VideoStatusPhase.failure
            ? '无法读取相机画面'
            : '没有可用的视频流',
        detail: state.message,
        error: state.phase == VideoStatusPhase.failure,
        actionLabel: '重新检查',
        onAction: _videoController.refresh,
      );
    }
    return _VideoCard(
      status: status,
      stream: stream,
      isChanging: state.isChangingStream,
      isForeground: _isForeground,
      message: state.message,
      onRefresh: _videoController.refresh,
      onToggle: _videoController.setSelectedStreamEnabled,
      onToggleStream: _videoController.setStreamEnabled,
      onSelect: _videoController.selectStream,
      isLandscape: widget.isLandscape,
      workspaceHeight: widget.workspaceHeight,
      onWorkspaceChanged: widget.onWorkspaceChanged,
    );
  }
}

class _VideoCard extends ConsumerWidget {
  const _VideoCard({
    required this.status,
    required this.stream,
    required this.isChanging,
    required this.isForeground,
    required this.message,
    required this.onRefresh,
    required this.onToggle,
    required this.onToggleStream,
    required this.onSelect,
    required this.isLandscape,
    required this.workspaceHeight,
    required this.onWorkspaceChanged,
  });

  final VideoStatus status;
  final VideoStream stream;
  final bool isChanging;
  final bool isForeground;
  final String message;
  final VoidCallback onRefresh;
  final ValueChanged<bool> onToggle;
  final Future<void> Function(String streamName, bool enabled) onToggleStream;
  final ValueChanged<String> onSelect;
  final bool isLandscape;
  final double workspaceHeight;
  final ValueChanged<ObservationWorkspace> onWorkspaceChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isEnabled = stream.enabled;
    final isReady = status.gateway.online && stream.isReadyForPlayback;
    final color = isReady ? AletheiaTheme.mint : AletheiaTheme.warning;
    final selector = _VideoStreamSelector(
      streams: status.streams,
      selectedName: stream.name,
      onSelected: isChanging ? null : onSelect,
      vertical: isLandscape,
    );
    final surface = _VideoSurface(
      stream: stream,
      isReady: isReady,
      isForeground: isForeground,
      gatewayOnline: status.gateway.online,
    );
    final auxiliaryStreams = _auxiliaryStreams(
      status.streams,
      selectedName: stream.name,
      gatewayOnline: status.gateway.online,
    );
    final readout = _TelemetryRow(
      compact: isLandscape,
      flat: isLandscape,
      icon: isReady
          ? Icons.wifi_tethering_rounded
          : Icons.videocam_off_outlined,
      title: isReady ? '视频已就绪' : _videoAvailabilityLabel(stream),
      detail: isReady
          ? stream.resolution
          : isEnabled
          ? '正在准备视频画面。'
          : '可随时启动此路视频。',
      color: color,
    );
    final toggle = FilledButton.icon(
      onPressed: isChanging ? null : () => onToggle(!isEnabled),
      icon: isChanging
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(
              isEnabled
                  ? Icons.stop_circle_outlined
                  : Icons.play_circle_outline_rounded,
            ),
      label: Text(isEnabled ? '停止此路视频' : '启动此路视频'),
    );
    if (isLandscape) {
      final compactLandscape = isCompactLandscape(
        viewportHeight: MediaQuery.sizeOf(context).height,
        isLandscape: true,
      );
      return _Panel(
        padding: const EdgeInsets.all(6),
        child: SizedBox(
          height: workspaceHeight,
          child: Padding(
            // The product header may float over the map canvas, but video
            // source controls and the auxiliary feeds must never sit under
            // that status bar or its connection chip.
            padding: EdgeInsets.only(
              top: compactLandscape ? 44 : kToolbarHeight,
            ),
            child: LayoutBuilder(
              builder: (context, constraints) {
                // Landscape is an operator workspace, including on a phone.
                // Keep source controls on the left and reserve the right edge
                // for two genuine auxiliary WHEP surfaces. The compact rail
                // reduces labels, not capability, on the narrower phone canvas.
                final compactControls = constraints.maxWidth < 760;
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(
                      // Keep the source rail narrow on a phone landscape
                      // workspace. Auxiliary video surfaces need their width;
                      // source controls gain readability from row height, not
                      // by consuming the camera canvas.
                      width: compactControls ? 112 : 144,
                      child: _VideoControlRail(
                        streams: status.streams,
                        isChanging: isChanging,
                        compact: compactControls,
                        onToggle: onToggleStream,
                        onShowMap: () =>
                            onWorkspaceChanged(ObservationWorkspace.map),
                        onRefresh: onRefresh,
                      ),
                    ),
                    VerticalDivider(
                      width: 7,
                      thickness: 1,
                      color: AletheiaTheme.border,
                    ),
                    Expanded(
                      flex: 3,
                      child: Center(
                        child: ConstrainedBox(
                          constraints: BoxConstraints(
                            maxWidth: workspaceHeight * 4 / 3,
                          ),
                          child: AspectRatio(
                            aspectRatio: 4 / 3,
                            child: surface,
                          ),
                        ),
                      ),
                    ),
                    VerticalDivider(
                      width: 7,
                      thickness: 1,
                      color: AletheiaTheme.border,
                    ),
                    SizedBox(
                      width: compactControls ? 144 : 196,
                      child: _VideoAuxiliaryFeeds(
                        streams: auxiliaryStreams,
                        isForeground: isForeground,
                        gatewayOnline: status.gateway.online,
                        onSelected: isChanging ? null : onSelect,
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      );
    }
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(
                Icons.videocam_outlined,
                color: AletheiaTheme.cyan,
                size: 18,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '相机',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              IconButton(
                tooltip: '刷新视频状态',
                onPressed: isChanging ? null : onRefresh,
                icon: Icon(Icons.refresh_rounded),
              ),
            ],
          ),
          SizedBox(height: 6),
          Text(
            '选择相机查看主画面',
            style: TextStyle(color: AletheiaTheme.textTertiary, fontSize: 12),
          ),
          const SizedBox(height: 12),
          SizedBox(height: 44, child: selector),
          const SizedBox(height: 12),
          AspectRatio(aspectRatio: 4 / 3, child: surface),
          const SizedBox(height: 12),
          readout,
          const SizedBox(height: 12),
          toggle,
          if (message.isNotEmpty) ...[
            const SizedBox(height: 12),
            _InlineNotice(text: message, isError: false),
          ],
        ],
      ),
    );
  }
}

List<VideoStream> _auxiliaryStreams(
  List<VideoStream> streams, {
  required String selectedName,
  required bool gatewayOnline,
}) {
  final candidates = streams
      .where((stream) => stream.name != selectedName)
      .toList(growable: false);
  candidates.sort((left, right) {
    final leftReady = gatewayOnline && left.isReadyForPlayback;
    final rightReady = gatewayOnline && right.isReadyForPlayback;
    if (leftReady == rightReady) {
      return 0;
    }
    return leftReady ? -1 : 1;
  });
  return candidates.take(2).toList(growable: false);
}

class _VideoControlRail extends StatelessWidget {
  const _VideoControlRail({
    required this.streams,
    required this.isChanging,
    required this.compact,
    required this.onToggle,
    required this.onShowMap,
    required this.onRefresh,
  });

  final List<VideoStream> streams;
  final bool isChanging;
  final bool compact;
  final Future<void> Function(String streamName, bool enabled) onToggle;
  final VoidCallback onShowMap;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    key: ValueKey('video-control-rail'),
    decoration: BoxDecoration(
      color: AletheiaTheme.surfaceMuted,
      border: Border.all(color: AletheiaTheme.border.withValues(alpha: .72)),
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (compact)
          Padding(
            padding: const EdgeInsets.fromLTRB(9, 8, 7, 7),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Icon(
                      Icons.videocam_outlined,
                      color: AletheiaTheme.cyan,
                      size: 16,
                    ),
                    SizedBox(width: 6),
                    Text(
                      '视频源',
                      style: TextStyle(
                        color: AletheiaTheme.textPrimary,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    _ControlRailAction(
                      tooltip: '切换到地图',
                      onPressed: onShowMap,
                      icon: Icons.map_outlined,
                    ),
                    const SizedBox(width: 4),
                    _ControlRailAction(
                      tooltip: '刷新视频状态',
                      onPressed: isChanging ? null : onRefresh,
                      icon: Icons.refresh_rounded,
                    ),
                  ],
                ),
              ],
            ),
          )
        else
          Padding(
            padding: const EdgeInsets.fromLTRB(9, 6, 4, 3),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      Icons.tune_rounded,
                      color: AletheiaTheme.cyan,
                      size: 15,
                    ),
                    SizedBox(width: 6),
                    Text(
                      '视频开关',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    IconButton(
                      tooltip: '切换到地图',
                      visualDensity: VisualDensity.compact,
                      onPressed: onShowMap,
                      icon: const Icon(Icons.map_outlined, size: 18),
                    ),
                    IconButton(
                      tooltip: '刷新视频状态',
                      visualDensity: VisualDensity.compact,
                      onPressed: isChanging ? null : onRefresh,
                      icon: const Icon(Icons.refresh_rounded, size: 18),
                    ),
                  ],
                ),
              ],
            ),
          ),
        if (!compact) const Divider(height: 1),
        Expanded(
          child: ListView.separated(
            padding: EdgeInsets.fromLTRB(
              compact ? 6 : 0,
              compact ? 5 : 3,
              compact ? 6 : 0,
              compact ? 7 : 3,
            ),
            itemCount: streams.length,
            separatorBuilder: (_, _) => SizedBox(height: compact ? 6 : 0),
            itemBuilder: (context, index) {
              final stream = streams[index];
              if (compact) {
                return _CompactVideoStreamToggle(
                  stream: stream,
                  isChanging: isChanging,
                  onToggle: onToggle,
                );
              }
              return Semantics(
                label: '${_videoStreamLabel(stream.name)}视频开关',
                child: Padding(
                  padding: const EdgeInsets.only(left: 8, right: 3),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          _videoStreamLabel(stream.name),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: AletheiaTheme.textSecondary,
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      Switch.adaptive(
                        value: stream.enabled,
                        onChanged: isChanging
                            ? null
                            : (enabled) => onToggle(stream.name, enabled),
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ],
    ),
  );
}

class _ControlRailAction extends StatelessWidget {
  const _ControlRailAction({
    required this.tooltip,
    required this.onPressed,
    required this.icon,
  });

  final String tooltip;
  final VoidCallback? onPressed;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Tooltip(
    message: tooltip,
    child: Material(
      color: AletheiaTheme.surfaceRaised,
      borderRadius: BorderRadius.circular(7),
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(7),
        child: SizedBox(width: 24, height: 24, child: Icon(icon, size: 15)),
      ),
    ),
  );
}

/// A phone-height landscape workspace cannot afford a labelled `Switch` for
/// six sources. It remains a real on/off control, but presents each source as
/// a compact control row rather than a dense settings table.
class _CompactVideoStreamToggle extends StatelessWidget {
  const _CompactVideoStreamToggle({
    required this.stream,
    required this.isChanging,
    required this.onToggle,
  });

  final VideoStream stream;
  final bool isChanging;
  final Future<void> Function(String streamName, bool enabled) onToggle;

  @override
  Widget build(BuildContext context) {
    final isOn = stream.enabled;
    final label = switch (stream.name) {
      'front_camera' => '前向相机',
      'back_camera' => '后向相机',
      'left_camera' => '左侧相机',
      'right_camera' => '右侧相机',
      'detection_camera' => '目标检测',
      'segmentation_overlay' => '区域分割',
      _ => _videoStreamLabel(stream.name),
    };
    return Semantics(
      label: '${_videoStreamLabel(stream.name)}视频开关',
      value: isOn ? '已开启' : '已关闭',
      button: true,
      child: Tooltip(
        message: '${_videoStreamLabel(stream.name)}：${isOn ? '已开启' : '已关闭'}',
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: isOn
                ? AletheiaTheme.mint.withValues(alpha: .09)
                : AletheiaTheme.surfaceSunken,
            border: Border.all(
              color: isOn
                  ? AletheiaTheme.mint.withValues(alpha: .26)
                  : AletheiaTheme.border.withValues(alpha: .48),
            ),
            borderRadius: BorderRadius.circular(8),
          ),
          child: SizedBox(
            // In compact landscape the source list is deliberately taller
            // than a settings list: operators can read and tap every source
            // without taking horizontal space from the live video tiles.
            height: 38,
            child: Material(
              key: ValueKey('video-stream-toggle-${stream.name}'),
              color: Colors.transparent,
              child: InkWell(
                onTap: isChanging ? null : () => onToggle(stream.name, !isOn),
                borderRadius: BorderRadius.circular(8),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          label,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: isOn
                                ? AletheiaTheme.textPrimary
                                : AletheiaTheme.textSecondary,
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      AnimatedContainer(
                        duration: AletheiaMotion.durationFor(
                          context,
                          AletheiaMotion.fast,
                        ),
                        curve: AletheiaMotion.easeOut,
                        width: 28,
                        height: 16,
                        padding: EdgeInsets.all(2),
                        alignment: isOn
                            ? Alignment.centerRight
                            : Alignment.centerLeft,
                        decoration: BoxDecoration(
                          color: isOn
                              ? AletheiaTheme.mint.withValues(alpha: .35)
                              : AletheiaTheme.border,
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: isOn
                                ? AletheiaTheme.mint
                                : AletheiaTheme.textTertiary,
                            shape: BoxShape.circle,
                          ),
                          child: const SizedBox(width: 12, height: 12),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _VideoAuxiliaryFeeds extends StatelessWidget {
  const _VideoAuxiliaryFeeds({
    required this.streams,
    required this.isForeground,
    required this.gatewayOnline,
    required this.onSelected,
  });

  final List<VideoStream> streams;
  final bool isForeground;
  final bool gatewayOnline;
  final ValueChanged<String>? onSelected;

  @override
  Widget build(BuildContext context) {
    if (streams.isEmpty) {
      return Center(
        child: Text(
          '没有其他相机',
          style: TextStyle(color: AletheiaTheme.textTertiary, fontSize: 12),
        ),
      );
    }
    return Column(
      key: ValueKey('video-auxiliary-feeds'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: EdgeInsets.only(bottom: 4),
          child: Text(
            '辅助画面',
            style: TextStyle(
              color: AletheiaTheme.textSecondary,
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        for (var index = 0; index < streams.length; index++) ...[
          Expanded(
            child: _AuxiliaryVideoTile(
              stream: streams[index],
              isForeground: isForeground,
              gatewayOnline: gatewayOnline,
              onTap: onSelected == null
                  ? null
                  : () => onSelected!(streams[index].name),
            ),
          ),
          if (index != streams.length - 1)
            Padding(
              padding: EdgeInsets.symmetric(vertical: 4),
              child: Divider(
                height: 1,
                thickness: 1,
                color: AletheiaTheme.border,
              ),
            ),
        ],
      ],
    );
  }
}

class _AuxiliaryVideoTile extends ConsumerWidget {
  const _AuxiliaryVideoTile({
    required this.stream,
    required this.isForeground,
    required this.gatewayOnline,
    required this.onTap,
  });

  final VideoStream stream;
  final bool isForeground;
  final bool gatewayOnline;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ready = gatewayOnline && stream.isReadyForPlayback;
    final previewBuilder = ref.watch(whepVideoPreviewBuilderProvider);
    final surface = ready && isForeground
        ? (previewBuilder?.call(
                endpoint: stream.whepUri!,
                resolution: stream.resolution,
              ) ??
              WhepVideoView(
                key: ValueKey('aux-${stream.whepUri}'),
                endpoint: stream.whepUri!,
                resolution: stream.resolution,
              ))
        : _VideoSurfaceStatus(
            stream: stream,
            gatewayOnline: gatewayOnline,
            isForeground: isForeground,
          );
    return Semantics(
      button: onTap != null,
      label: '${_videoStreamLabel(stream.name)}，点按切换为主画面',
      child: Material(
        key: ValueKey('video-auxiliary-tile-${stream.name}'),
        color: AletheiaTheme.surfaceSunken,
        shape: RoundedRectangleBorder(
          side: BorderSide(color: AletheiaTheme.border),
          borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Stack(
            fit: StackFit.expand,
            children: [
              surface,
              Positioned(
                left: 5,
                bottom: 5,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: AletheiaTheme.canvas.withValues(alpha: .84),
                    borderRadius: BorderRadius.circular(5),
                  ),
                  child: Padding(
                    padding: EdgeInsets.symmetric(horizontal: 5, vertical: 3),
                    child: Text(
                      _videoStreamLabel(stream.name),
                      style: TextStyle(
                        color: AletheiaTheme.textPrimary,
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _VideoStreamSelector extends StatelessWidget {
  const _VideoStreamSelector({
    required this.streams,
    required this.selectedName,
    required this.onSelected,
    required this.vertical,
  });

  final List<VideoStream> streams;
  final String selectedName;
  final ValueChanged<String>? onSelected;
  final bool vertical;

  @override
  Widget build(BuildContext context) {
    if (vertical) {
      return ListView.separated(
        padding: EdgeInsets.zero,
        itemCount: streams.length,
        separatorBuilder: (_, _) => const SizedBox(height: 4),
        itemBuilder: (context, index) {
          final stream = streams[index];
          return _VideoStreamOption(
            stream: stream,
            selected: stream.name == selectedName,
            onTap: onSelected == null ? null : () => onSelected!(stream.name),
            compact: true,
          );
        },
      );
    }
    return ListView.separated(
      scrollDirection: Axis.horizontal,
      padding: EdgeInsets.zero,
      itemCount: streams.length,
      separatorBuilder: (_, _) => const SizedBox(width: 8),
      itemBuilder: (context, index) {
        final stream = streams[index];
        return _VideoStreamOption(
          stream: stream,
          selected: stream.name == selectedName,
          onTap: onSelected == null ? null : () => onSelected!(stream.name),
        );
      },
    );
  }
}

class _VideoStreamOption extends StatelessWidget {
  const _VideoStreamOption({
    required this.stream,
    required this.selected,
    required this.onTap,
    this.compact = false,
  });

  final VideoStream stream;
  final bool selected;
  final VoidCallback? onTap;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final available = stream.isReadyForPlayback;
    final color = available ? AletheiaTheme.mint : AletheiaTheme.textTertiary;
    return Material(
      color: selected
          ? AletheiaTheme.cyan.withValues(alpha: .16)
          : AletheiaTheme.surfaceRaised,
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        child: Padding(
          padding: EdgeInsets.symmetric(
            horizontal: compact ? 8 : 10,
            vertical: compact ? 7 : 9,
          ),
          child: Row(
            mainAxisSize: compact ? MainAxisSize.max : MainAxisSize.min,
            children: [
              Icon(
                selected ? Icons.videocam_rounded : Icons.videocam_outlined,
                color: selected
                    ? AletheiaTheme.cyan
                    : AletheiaTheme.textSecondary,
                size: 17,
              ),
              SizedBox(width: 7),
              Flexible(
                child: Text(
                  _videoStreamLabel(stream.name),
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: selected
                        ? AletheiaTheme.textPrimary
                        : AletheiaTheme.textSecondary,
                    fontSize: 12,
                    fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(width: 6),
              Semantics(
                label: available ? '视频已就绪' : _videoAvailabilityLabel(stream),
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: color,
                    shape: BoxShape.circle,
                  ),
                  child: const SizedBox(width: 6, height: 6),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _VideoSurface extends ConsumerWidget {
  const _VideoSurface({
    required this.stream,
    required this.isReady,
    required this.isForeground,
    required this.gatewayOnline,
  });

  final VideoStream stream;
  final bool isReady;
  final bool isForeground;
  final bool gatewayOnline;

  @override
  Widget build(BuildContext context, WidgetRef ref) => DecoratedBox(
    decoration: BoxDecoration(
      border: Border.all(color: AletheiaTheme.border),
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
    ),
    child: ClipRRect(
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
      child: isReady && isForeground
          ? (ref
                    .watch(whepVideoPreviewBuilderProvider)
                    ?.call(
                      endpoint: stream.whepUri!,
                      resolution: stream.resolution,
                    ) ??
                WhepVideoView(
                  key: ValueKey(stream.whepUri),
                  endpoint: stream.whepUri!,
                  resolution: stream.resolution,
                ))
          : _VideoSurfaceStatus(
              stream: stream,
              gatewayOnline: gatewayOnline,
              isForeground: isForeground,
            ),
    ),
  );
}

class _VideoSurfaceStatus extends StatelessWidget {
  const _VideoSurfaceStatus({
    required this.stream,
    required this.gatewayOnline,
    required this.isForeground,
  });

  final VideoStream stream;
  final bool gatewayOnline;
  final bool isForeground;

  @override
  Widget build(BuildContext context) {
    final enabled = stream.enabled;
    final message = !isForeground
        ? '应用在后台，视频已暂停。'
        : !enabled
        ? '此路视频处于待机状态。'
        : !gatewayOnline
        ? '视频服务未就绪。'
        : stream.availability == VideoStreamAvailability.waiting
        ? '正在等待画面。'
        : '此路视频暂不可播放。';
    return ColoredBox(
      color: AletheiaTheme.surfaceSunken,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                enabled
                    ? Icons.hourglass_top_rounded
                    : Icons.videocam_off_outlined,
                color: enabled
                    ? AletheiaTheme.warning
                    : AletheiaTheme.textTertiary,
                size: 30,
              ),
              SizedBox(height: 10),
              Text(
                message,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  fontSize: 13,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MapPanel extends StatelessWidget {
  const _MapPanel({
    required this.map,
    required this.isRefreshing,
    required this.message,
    required this.onRefresh,
    required this.isLandscape,
    required this.workspaceHeight,
    required this.onWorkspaceChanged,
    required this.onFullscreen,
  });

  final LiveMapAsset map;
  final bool isRefreshing;
  final String message;
  final VoidCallback onRefresh;
  final bool isLandscape;
  final double workspaceHeight;
  final ValueChanged<ObservationWorkspace> onWorkspaceChanged;
  final VoidCallback onFullscreen;

  @override
  Widget build(BuildContext context) {
    return _Panel(
      padding: EdgeInsets.all(isLandscape ? 8 : 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            key: const ValueKey('observation-map-workspace'),
            height: workspaceHeight,
            child: _MapWorkspace(
              map: map,
              isRefreshing: isRefreshing,
              onRefresh: onRefresh,
              onShowCamera: () =>
                  onWorkspaceChanged(ObservationWorkspace.camera),
              onFullscreen: onFullscreen,
              useSideToolbar: isLandscape,
              toolbarTopInset: isLandscape
                  ? (isCompactLandscape(
                          viewportHeight: MediaQuery.sizeOf(context).height,
                          isLandscape: true,
                        )
                        ? 44
                        : kToolbarHeight)
                  : 0,
            ),
          ),
          if (message.isNotEmpty) ...[
            const SizedBox(height: 8),
            _InlineNotice(text: message, isError: false),
          ],
        ],
      ),
    );
  }
}

class _MapFullscreenScreen extends StatelessWidget {
  const _MapFullscreenScreen({
    required this.map,
    required this.onRefresh,
    required this.onShowCamera,
  });

  final LiveMapAsset map;
  final VoidCallback onRefresh;
  final VoidCallback onShowCamera;

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: AletheiaTheme.canvas,
    body: SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(6),
        child: _MapWorkspace(
          map: map,
          isRefreshing: false,
          onRefresh: onRefresh,
          onShowCamera: onShowCamera,
          onExitFullscreen: () => Navigator.of(context).pop(),
        ),
      ),
    ),
  );
}

class _MapWorkspace extends StatelessWidget {
  const _MapWorkspace({
    required this.map,
    required this.isRefreshing,
    required this.onRefresh,
    required this.onShowCamera,
    this.toolbarTopInset = 0,
    this.useSideToolbar = false,
    this.onFullscreen,
    this.onExitFullscreen,
  });

  final LiveMapAsset map;
  final bool isRefreshing;
  final VoidCallback onRefresh;
  final VoidCallback onShowCamera;
  final double toolbarTopInset;
  final bool useSideToolbar;
  final VoidCallback? onFullscreen;
  final VoidCallback? onExitFullscreen;

  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
    child: ColoredBox(
      color: AletheiaTheme.surfaceSunken,
      child: Stack(
        fit: StackFit.expand,
        children: [
          _MapViewport(key: ValueKey('${map.id}-viewport'), map: map),
          if (useSideToolbar)
            Positioned(
              top: 8 + toolbarTopInset,
              left: 8,
              child: _MapToolRail(
                isRefreshing: isRefreshing,
                onRefresh: onRefresh,
                onShowCamera: onShowCamera,
                onFullscreen: onFullscreen,
                onExitFullscreen: onExitFullscreen,
              ),
            )
          else
            Positioned(
              top: 8 + toolbarTopInset,
              left: 8,
              right: 8,
              child: _MapToolbar(
                isRefreshing: isRefreshing,
                onRefresh: onRefresh,
                onShowCamera: onShowCamera,
                onFullscreen: onFullscreen,
                onExitFullscreen: onExitFullscreen,
              ),
            ),
          Positioned(
            right: 8,
            bottom: 8,
            child: _MapOperationalReadout(metadata: map.metadata),
          ),
          const Positioned.fill(
            child: IgnorePointer(child: _CloudMetricsReporter()),
          ),
        ],
      ),
    ),
  );
}

class _MapToolbar extends StatelessWidget {
  const _MapToolbar({
    required this.isRefreshing,
    required this.onRefresh,
    required this.onShowCamera,
    this.onFullscreen,
    this.onExitFullscreen,
  });

  final bool isRefreshing;
  final VoidCallback onRefresh;
  final VoidCallback onShowCamera;
  final VoidCallback? onFullscreen;
  final VoidCallback? onExitFullscreen;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: AletheiaTheme.surfaceSunken.withValues(alpha: .9),
      border: Border.all(color: AletheiaTheme.border.withValues(alpha: .8)),
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
    ),
    child: Padding(
      padding: EdgeInsets.only(left: 10),
      child: Row(
        children: [
          Icon(Icons.map_outlined, color: AletheiaTheme.cyan, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text('活动地图', style: Theme.of(context).textTheme.labelLarge),
          ),
          IconButton(
            tooltip: '切换到相机',
            visualDensity: VisualDensity.compact,
            onPressed: onShowCamera,
            icon: const Icon(Icons.videocam_outlined),
          ),
          if (onFullscreen != null)
            IconButton(
              tooltip: '全屏查看地图',
              visualDensity: VisualDensity.compact,
              onPressed: onFullscreen,
              icon: const Icon(Icons.fullscreen_rounded),
            ),
          if (onExitFullscreen != null)
            IconButton(
              tooltip: '退出全屏地图',
              visualDensity: VisualDensity.compact,
              onPressed: onExitFullscreen,
              icon: const Icon(Icons.fullscreen_exit_rounded),
            ),
          IconButton(
            tooltip: '刷新活动地图',
            visualDensity: VisualDensity.compact,
            onPressed: isRefreshing ? null : onRefresh,
            icon: isRefreshing
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
    ),
  );
}

/// Landscape keeps map actions in a narrow left dock. A wide horizontal bar
/// obscures the highest-value portion of a live map exactly when the HMI has
/// the least vertical room.
class _MapToolRail extends StatelessWidget {
  const _MapToolRail({
    required this.isRefreshing,
    required this.onRefresh,
    required this.onShowCamera,
    this.onFullscreen,
    this.onExitFullscreen,
  });

  final bool isRefreshing;
  final VoidCallback onRefresh;
  final VoidCallback onShowCamera;
  final VoidCallback? onFullscreen;
  final VoidCallback? onExitFullscreen;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    key: ValueKey('map-tool-rail'),
    decoration: BoxDecoration(
      color: AletheiaTheme.surfaceSunken.withValues(alpha: .9),
      border: Border.all(color: AletheiaTheme.border.withValues(alpha: .8)),
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
    ),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Padding(
          padding: EdgeInsets.all(11),
          child: Tooltip(
            message: '活动地图',
            child: Icon(
              Icons.map_outlined,
              color: AletheiaTheme.cyan,
              size: 20,
            ),
          ),
        ),
        const Divider(height: 1),
        IconButton(
          tooltip: '切换到相机',
          visualDensity: VisualDensity.compact,
          onPressed: onShowCamera,
          icon: const Icon(Icons.videocam_outlined),
        ),
        if (onFullscreen != null)
          IconButton(
            tooltip: '全屏查看地图',
            visualDensity: VisualDensity.compact,
            onPressed: onFullscreen,
            icon: const Icon(Icons.fullscreen_rounded),
          ),
        if (onExitFullscreen != null)
          IconButton(
            tooltip: '退出全屏地图',
            visualDensity: VisualDensity.compact,
            onPressed: onExitFullscreen,
            icon: const Icon(Icons.fullscreen_exit_rounded),
          ),
        IconButton(
          tooltip: '刷新活动地图',
          visualDensity: VisualDensity.compact,
          onPressed: isRefreshing ? null : onRefresh,
          icon: isRefreshing
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.refresh_rounded),
        ),
      ],
    ),
  );
}

class _MapOperationalReadout extends ConsumerWidget {
  const _MapOperationalReadout({required this.metadata});

  final LiveMapMetadata metadata;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    final connectionColor = connected
        ? AletheiaTheme.mint
        : AletheiaTheme.warning;
    final pose = ref.watch(poseTelemetryProvider);
    final (poseIcon, poseColor, poseLabel, poseDetail) = pose.when(
      loading: () =>
          (Icons.sync_rounded, AletheiaTheme.textSecondary, '实时位姿', '正在连接'),
      error: (_, _) =>
          (Icons.location_off_outlined, AletheiaTheme.warning, '实时位姿', '正在重连'),
      data: (sample) {
        final frame = sample.frame;
        final inMap = metadata.contains(frame.x, frame.y);
        return (
          inMap ? Icons.navigation_rounded : Icons.location_off_outlined,
          inMap ? AletheiaTheme.mint : AletheiaTheme.warning,
          inMap ? '实时位姿' : '位姿在地图外',
          'x ${frame.x.toStringAsFixed(2)} · y ${frame.y.toStringAsFixed(2)} · ${_degrees(frame.yaw)}°',
        );
      },
    );
    return Semantics(
      label: '${connected ? '机器人已连接' : '机器人未连接'}，$poseLabel，$poseDetail',
      child: DecoratedBox(
        key: ValueKey('map-operational-readout'),
        decoration: BoxDecoration(
          color: AletheiaTheme.canvas.withValues(alpha: .9),
          border: Border.all(
            color: AletheiaTheme.border.withValues(alpha: .92),
          ),
          borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 6, 8, 7),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    connected
                        ? Icons.check_circle_outline_rounded
                        : Icons.link_off_rounded,
                    color: connectionColor,
                    size: 13,
                  ),
                  const SizedBox(width: 4),
                  Text(
                    connected ? '已连接' : '未连接',
                    style: TextStyle(
                      color: connectionColor,
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 5),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(poseIcon, color: poseColor, size: 14),
                  SizedBox(width: 5),
                  Text(
                    poseLabel,
                    style: TextStyle(
                      color: AletheiaTheme.textPrimary,
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              SizedBox(height: 2),
              Text(
                poseDetail,
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  fontSize: 10,
                  fontFeatures: [ui.FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MapViewport extends ConsumerStatefulWidget {
  const _MapViewport({required this.map, super.key});

  final LiveMapAsset map;

  @override
  ConsumerState<_MapViewport> createState() => _MapViewportState();
}

/// A direct map gesture surface rather than an [InteractiveViewer].
///
/// The map point under the two-finger midpoint is explicitly preserved for
/// every scale update. This makes pinch and two-finger pan one transform,
/// avoiding the centre-anchored jump that is especially noticeable on a
/// vehicle map.
class _MapViewportState extends ConsumerState<_MapViewport> {
  static const _minimumScale = 1.0;
  static const _maximumScale = 6.0;

  Size? _viewportSize;
  Size? _mapSize;
  Size? _workspaceCanvasSize;
  Offset _mapOriginInCanvas = Offset.zero;
  Offset _translation = Offset.zero;
  double _scale = _minimumScale;

  final Map<int, Offset> _pointerPositions = <int, Offset>{};
  int? _singlePanPointer;
  Offset _singlePanStart = Offset.zero;
  Offset _singlePanTranslationStart = Offset.zero;
  Offset _worldPointAtGestureStart = Offset.zero;
  double _scaleAtGestureStart = _minimumScale;
  double _pinchSpanAtGestureStart = 1;

  @override
  Widget build(BuildContext context) {
    final preview = ref.watch(liveMapPreviewBuilderProvider);
    return LayoutBuilder(
      builder: (context, constraints) {
        final viewport = constraints.biggest;
        if (viewport.isEmpty) {
          return const SizedBox.expand();
        }
        final mapSize = _mapSizeFor(viewport);
        final mapOrigin = _mapOriginFor(viewport);
        final workspaceCanvasSize = Size(
          mapSize.width + mapOrigin.dx * 2,
          mapSize.height + mapOrigin.dy * 2,
        );
        _synchroniseGeometry(viewport, mapSize, workspaceCanvasSize, mapOrigin);
        return RepaintBoundary(
          child: RawGestureDetector(
            key: const ValueKey('map-gesture-surface'),
            behavior: HitTestBehavior.opaque,
            // Claim the pointer sequence before the enclosing ListView.
            // Raw pointer positions below then drive the map exactly 1:1;
            // this avoids the recognizer arena changing a two-finger focal
            // point midway through a direct-manipulation gesture.
            gestures: <Type, GestureRecognizerFactory>{
              EagerGestureRecognizer:
                  GestureRecognizerFactoryWithHandlers<EagerGestureRecognizer>(
                    () => EagerGestureRecognizer(),
                    (recognizer) {},
                  ),
            },
            child: Listener(
              onPointerDown: _recordPointerDown,
              onPointerMove: _recordPointerMove,
              onPointerUp: _recordPointerEnd,
              onPointerCancel: _recordPointerEnd,
              child: ClipRect(
                child: ColoredBox(
                  color: AletheiaTheme.surfaceMuted,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Transform(
                        key: const ValueKey('map-world-transform'),
                        alignment: Alignment.topLeft,
                        transform: Matrix4.identity()
                          ..translateByDouble(
                            _translation.dx,
                            _translation.dy,
                            0,
                            1,
                          )
                          ..scaleByDouble(_scale, _scale, 1, 1),
                        // The world canvas—not the image—is the object being
                        // moved. The map and all map-relative overlays live
                        // within it at one shared transform.
                        child: OverflowBox(
                          alignment: Alignment.topLeft,
                          minWidth: workspaceCanvasSize.width,
                          maxWidth: workspaceCanvasSize.width,
                          minHeight: workspaceCanvasSize.height,
                          maxHeight: workspaceCanvasSize.height,
                          child: SizedBox(
                            key: const ValueKey('map-workspace-canvas'),
                            width: workspaceCanvasSize.width,
                            height: workspaceCanvasSize.height,
                            child: Stack(
                              children: [
                                const Positioned.fill(
                                  child: CustomPaint(
                                    painter: _WorkspaceCanvasPainter(),
                                  ),
                                ),
                                Positioned(
                                  left: mapOrigin.dx,
                                  top: mapOrigin.dy,
                                  width: mapSize.width,
                                  height: mapSize.height,
                                  child: Stack(
                                    fit: StackFit.expand,
                                    children: [
                                      RepaintBoundary(
                                        child:
                                            preview?.call(map: widget.map) ??
                                            Image.memory(
                                              widget.map.previewBytes,
                                              fit: BoxFit.fill,
                                              filterQuality: FilterQuality.none,
                                              errorBuilder:
                                                  (
                                                    context,
                                                    error,
                                                    stackTrace,
                                                  ) => Center(
                                                    child: Text(
                                                      '地图预览无法显示',
                                                      style: TextStyle(
                                                        color: AletheiaTheme
                                                            .textSecondary,
                                                      ),
                                                    ),
                                                  ),
                                            ),
                                      ),
                                      RepaintBoundary(
                                        child: _WorldGridMapLayer(
                                          metadata: widget.map.metadata,
                                          viewportScale: _scale,
                                        ),
                                      ),
                                      RepaintBoundary(
                                        child: _VirtualWallMapLayer(
                                          metadata: widget.map.metadata,
                                          walls: widget.map.virtualWalls,
                                          viewportScale: _scale,
                                        ),
                                      ),
                                      // A trajectory layer belongs here when the
                                      // app receives a real-time contract.
                                      RepaintBoundary(
                                        child: _CloudMapLayer(
                                          metadata: widget.map.metadata,
                                        ),
                                      ),
                                      RepaintBoundary(
                                        child: _PoseMapLayer(
                                          metadata: widget.map.metadata,
                                          footprint:
                                              widget.map.vehicleFootprint,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                      Positioned(
                        left: 8,
                        bottom: 8,
                        child: IgnorePointer(
                          child: _MapScaleReference(
                            metersPerGrid: _minorGridMetersFor(
                              (mapSize.width / widget.map.metadata.worldWidth) *
                                  _scale,
                            ),
                            pixelsPerMeter:
                                (mapSize.width /
                                    widget.map.metadata.worldWidth) *
                                _scale,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Size _mapSizeFor(Size viewport) {
    final metadata = widget.map.metadata;
    final mapAspect = metadata.width / metadata.height;
    final viewportAspect = viewport.width / viewport.height;
    // A vehicle HMI should open on a usable workspace, not a narrow strip of
    // a tall map surrounded by empty canvas. Cover the workspace without ever
    // changing the map aspect ratio; the overflow is intentionally available
    // to the operator through a one-finger pan.
    if (mapAspect > viewportAspect) {
      return Size(viewport.height * mapAspect, viewport.height);
    }
    return Size(viewport.width, viewport.width / mapAspect);
  }

  Offset _mapOriginFor(Size viewport) {
    // This is a bounded workspace around the map, not a blank black margin.
    // It leaves a full, useful drag area in every direction while keeping the
    // operator close enough to find the map again.
    final extent = math.max(120.0, math.min(480.0, viewport.longestSide * .6));
    return Offset(extent, extent);
  }

  void _synchroniseGeometry(
    Size viewport,
    Size mapSize,
    Size workspaceCanvasSize,
    Offset mapOrigin,
  ) {
    if (_viewportSize == viewport &&
        _mapSize == mapSize &&
        _workspaceCanvasSize == workspaceCanvasSize &&
        _mapOriginInCanvas == mapOrigin) {
      return;
    }
    final previousViewport = _viewportSize;
    final previousMapSize = _mapSize;
    final previousMapOrigin = _mapOriginInCanvas;
    final hasGeometry = previousViewport != null && previousMapSize != null;
    _viewportSize = viewport;
    _mapSize = mapSize;
    _workspaceCanvasSize = workspaceCanvasSize;
    _mapOriginInCanvas = mapOrigin;
    if (!hasGeometry) {
      _translation = _translationForMapPointAtViewportCentre(
        mapSize.center(mapOrigin),
      );
      return;
    }
    // Orientation changes alter local pixel sizes while the map's world
    // coordinates stay the same. Preserve the point under the old viewport
    // centre, including points just outside the map on the workspace canvas.
    final oldCentre = previousViewport.center(Offset.zero);
    final oldMapPoint =
        ((oldCentre - _translation) / _scale) - previousMapOrigin;
    final mapRelativePoint = Offset(
      oldMapPoint.dx / previousMapSize.width,
      oldMapPoint.dy / previousMapSize.height,
    );
    final nextCanvasPoint =
        mapOrigin +
        Offset(
          mapRelativePoint.dx * mapSize.width,
          mapRelativePoint.dy * mapSize.height,
        );
    _translation = _boundedTranslation(
      viewport.center(Offset.zero) - nextCanvasPoint * _scale,
      scale: _scale,
    );
  }

  Offset _translationForMapPointAtViewportCentre(Offset mapCanvasPoint) =>
      _boundedTranslation(
        _viewportSize!.center(Offset.zero) - mapCanvasPoint * _scale,
        scale: _scale,
      );

  void _recordPointerDown(PointerDownEvent event) {
    _pointerPositions[event.pointer] = event.localPosition;
    if (_pointerPositions.length == 1) {
      _singlePanPointer = event.pointer;
      _singlePanStart = event.localPosition;
      _singlePanTranslationStart = _translation;
      return;
    }
    if (_pointerPositions.length == 2) {
      _singlePanPointer = null;
      _setGestureAnchor(_pointerCentroid);
      _pinchSpanAtGestureStart = _pointerSpan;
    }
  }

  void _recordPointerMove(PointerMoveEvent event) {
    _pointerPositions[event.pointer] = event.localPosition;
    if (_pointerPositions.length == 1 && _singlePanPointer == event.pointer) {
      final nextTranslation =
          _singlePanTranslationStart + (event.localPosition - _singlePanStart);
      setState(() {
        _translation = _boundedTranslation(nextTranslation, scale: _scale);
      });
      return;
    }
    if (_pointerPositions.length < 2 || _pinchSpanAtGestureStart <= 0) {
      return;
    }
    final nextScale =
        (_scaleAtGestureStart * (_pointerSpan / _pinchSpanAtGestureStart))
            .clamp(_minimumScale, _maximumScale);
    final nextTranslation =
        _pointerCentroid - _worldPointAtGestureStart * nextScale;
    setState(() {
      _scale = nextScale;
      _translation = _boundedTranslation(nextTranslation, scale: nextScale);
    });
  }

  void _recordPointerEnd(PointerEvent event) {
    _pointerPositions.remove(event.pointer);
    if (_pointerPositions.length == 1) {
      final remaining = _pointerPositions.entries.single;
      _singlePanPointer = remaining.key;
      _singlePanStart = remaining.value;
      _singlePanTranslationStart = _translation;
    } else {
      _singlePanPointer = null;
    }
  }

  Offset get _pointerCentroid {
    var x = 0.0;
    var y = 0.0;
    for (final position in _pointerPositions.values) {
      x += position.dx;
      y += position.dy;
    }
    return Offset(x / _pointerPositions.length, y / _pointerPositions.length);
  }

  double get _pointerSpan {
    final positions = _pointerPositions.values.take(2).toList(growable: false);
    return (positions.first - positions.last).distance;
  }

  void _setGestureAnchor(Offset focalPoint) {
    _scaleAtGestureStart = _scale;
    _worldPointAtGestureStart =
        (focalPoint - _translation) / _scaleAtGestureStart;
  }

  Offset _boundedTranslation(Offset value, {required double scale}) {
    final viewport = _viewportSize!;
    final workspaceCanvasSize = _workspaceCanvasSize!;
    return Offset(
      _boundedAxis(
        value: value.dx,
        viewportExtent: viewport.width,
        contentExtent: workspaceCanvasSize.width * scale,
      ),
      _boundedAxis(
        value: value.dy,
        viewportExtent: viewport.height,
        contentExtent: workspaceCanvasSize.height * scale,
      ),
    );
  }

  double _boundedAxis({
    required double value,
    required double viewportExtent,
    required double contentExtent,
  }) {
    if (contentExtent <= viewportExtent) {
      return (viewportExtent - contentExtent) / 2;
    }
    // A small reveal makes a map edge feel intentional, but it can never
    // exceed half the available overflow or the clamp range would invert when
    // a pinch has only just crossed the fit-to-workspace scale.
    final edgeReveal = math.min(
      math.min(24.0, viewportExtent * .08),
      (contentExtent - viewportExtent) / 2,
    );
    return value
        .clamp(viewportExtent - contentExtent + edgeReveal, -edgeReveal)
        .toDouble();
  }
}

class _WorkspaceCanvasPainter extends CustomPainter {
  const _WorkspaceCanvasPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawColor(AletheiaTheme.surfaceMuted, BlendMode.srcOver);
    final grid = Paint()
      ..color = AletheiaTheme.divider.withValues(alpha: .48)
      ..strokeWidth = 1;
    const spacing = 48.0;
    for (double x = 0; x <= size.width; x += spacing) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (double y = 0; y <= size.height; y += spacing) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
  }

  @override
  bool shouldRepaint(covariant _WorkspaceCanvasPainter oldDelegate) => false;
}

double _minorGridMetersFor(double pixelsPerMeter) {
  for (final meters in const [0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]) {
    if (pixelsPerMeter * meters >= 26) {
      return meters;
    }
  }
  return 20;
}

String _formatMapDistance(double meters) {
  if (meters < 1) {
    return '${(meters * 100).round()} cm';
  }
  return meters == meters.roundToDouble()
      ? '${meters.toInt()} m'
      : '${meters.toStringAsFixed(1)} m';
}

class _MapScaleReference extends StatelessWidget {
  const _MapScaleReference({
    required this.metersPerGrid,
    required this.pixelsPerMeter,
  });

  final double metersPerGrid;
  final double pixelsPerMeter;

  @override
  Widget build(BuildContext context) {
    final barWidth = (metersPerGrid * pixelsPerMeter).clamp(30.0, 104.0);
    return Semantics(
      label: '${_formatMapDistance(metersPerGrid)} 每格',
      child: DecoratedBox(
        key: ValueKey('map-scale-reference'),
        decoration: BoxDecoration(
          color: AletheiaTheme.canvas.withValues(alpha: .88),
          border: Border.all(
            color: AletheiaTheme.divider.withValues(alpha: .88),
          ),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(7, 5, 7, 6),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${_formatMapDistance(metersPerGrid)} / 格',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: AletheiaTheme.textSecondary,
                  fontFeatures: const [ui.FontFeature.tabularFigures()],
                ),
              ),
              const SizedBox(height: 4),
              SizedBox(
                width: barWidth,
                height: 6,
                child: const CustomPaint(painter: _MapScaleBarPainter()),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MapScaleBarPainter extends CustomPainter {
  const _MapScaleBarPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AletheiaTheme.textSecondary
      ..strokeWidth = 1;
    final y = size.height - .5;
    canvas.drawLine(Offset.zero, Offset(size.width, y), paint);
    canvas.drawLine(Offset(0, 0), Offset(0, y), paint);
    canvas.drawLine(Offset(size.width, 0), Offset(size.width, y), paint);
  }

  @override
  bool shouldRepaint(covariant _MapScaleBarPainter oldDelegate) => false;
}

class _WorldGridMapLayer extends StatelessWidget {
  const _WorldGridMapLayer({
    required this.metadata,
    required this.viewportScale,
  });

  final LiveMapMetadata metadata;
  final double viewportScale;

  @override
  Widget build(BuildContext context) => IgnorePointer(
    child: CustomPaint(
      key: const ValueKey('map-world-grid'),
      painter: _WorldGridPainter(
        metadata: metadata,
        viewportScale: viewportScale,
      ),
      child: const SizedBox.expand(),
    ),
  );
}

class _WorldGridPainter extends CustomPainter {
  const _WorldGridPainter({
    required this.metadata,
    required this.viewportScale,
  });

  final LiveMapMetadata metadata;
  final double viewportScale;

  @override
  void paint(Canvas canvas, Size size) {
    final pixelsPerMeter = (size.width / metadata.worldWidth) * viewportScale;
    final minorMeters = _minorGridMetersFor(pixelsPerMeter);
    final majorMeters = minorMeters * 5;
    final minorPaint = Paint()
      ..color = AletheiaTheme.canvas.withValues(alpha: .11)
      ..strokeWidth = .7 / viewportScale;
    final majorPaint = Paint()
      ..color = AletheiaTheme.canvas.withValues(alpha: .2)
      ..strokeWidth = 1 / viewportScale;
    _drawVerticalGrid(canvas, size, minorMeters, minorPaint);
    _drawHorizontalGrid(canvas, size, minorMeters, minorPaint);
    _drawVerticalGrid(canvas, size, majorMeters, majorPaint);
    _drawHorizontalGrid(canvas, size, majorMeters, majorPaint);
  }

  void _drawVerticalGrid(Canvas canvas, Size size, double meters, Paint paint) {
    final end = metadata.originX + metadata.worldWidth;
    for (
      var worldX = (metadata.originX / meters).ceilToDouble() * meters;
      worldX <= end + .000001;
      worldX += meters
    ) {
      final x =
          ((worldX - metadata.originX) / metadata.worldWidth) * size.width;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
  }

  void _drawHorizontalGrid(
    Canvas canvas,
    Size size,
    double meters,
    Paint paint,
  ) {
    final end = metadata.originY + metadata.worldHeight;
    for (
      var worldY = (metadata.originY / meters).ceilToDouble() * meters;
      worldY <= end + .000001;
      worldY += meters
    ) {
      final y =
          (1 - ((worldY - metadata.originY) / metadata.worldHeight)) *
          size.height;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _WorldGridPainter oldDelegate) =>
      oldDelegate.metadata != metadata ||
      oldDelegate.viewportScale != viewportScale;
}

class _VirtualWallMapLayer extends StatelessWidget {
  const _VirtualWallMapLayer({
    required this.metadata,
    required this.walls,
    required this.viewportScale,
  });

  final LiveMapMetadata metadata;
  final List<LiveMapVirtualWall> walls;
  final double viewportScale;

  @override
  Widget build(BuildContext context) => IgnorePointer(
    child: CustomPaint(
      painter: _VirtualWallPainter(
        metadata: metadata,
        walls: walls,
        viewportScale: viewportScale,
      ),
      child: const SizedBox.expand(),
    ),
  );
}

class _VirtualWallPainter extends CustomPainter {
  const _VirtualWallPainter({
    required this.metadata,
    required this.walls,
    required this.viewportScale,
  });

  final LiveMapMetadata metadata;
  final List<LiveMapVirtualWall> walls;
  final double viewportScale;

  @override
  void paint(Canvas canvas, Size size) {
    if (walls.isEmpty) {
      return;
    }
    final paint = Paint()
      ..color = AletheiaTheme.mapVirtualWall
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      // A virtual wall is a precise map constraint, not a decorative route.
      // Counter-scale it so zooming never turns it into a broad red band.
      ..strokeWidth = 1.15 / viewportScale;
    for (final wall in walls) {
      final path = Path();
      for (var index = 0; index < wall.points.length; index++) {
        final point = wall.points[index];
        final worldX = wall.coordinateMode == VirtualWallCoordinateMode.world
            ? point.x
            : metadata.originX + point.x;
        final worldY = wall.coordinateMode == VirtualWallCoordinateMode.world
            ? point.y
            : metadata.originY + point.y;
        final x =
            ((worldX - metadata.originX) / metadata.worldWidth) * size.width;
        final y =
            (1 - ((worldY - metadata.originY) / metadata.worldHeight)) *
            size.height;
        if (index == 0) {
          path.moveTo(x, y);
        } else {
          path.lineTo(x, y);
        }
      }
      canvas.drawPath(path, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _VirtualWallPainter oldDelegate) =>
      oldDelegate.metadata != metadata ||
      oldDelegate.walls != walls ||
      oldDelegate.viewportScale != viewportScale;
}

/// Pose, cloud and map image are sibling layers to keep their update cadence
/// independent. A new scan never recreates the static map image.
class _CloudMapLayer extends ConsumerStatefulWidget {
  const _CloudMapLayer({required this.metadata});

  final LiveMapMetadata metadata;

  @override
  ConsumerState<_CloudMapLayer> createState() => _CloudMapLayerState();
}

class _CloudMapLayerState extends ConsumerState<_CloudMapLayer> {
  int? _mapSwitchFenceSequence;

  @override
  Widget build(BuildContext context) {
    final cloudState = ref.watch(cloudTelemetryProvider);
    final latestCloud = cloudState.maybeWhen(
      data: (value) => value.frame,
      orElse: () => null,
    );
    var cloudToDraw = latestCloud;
    if (_mapSwitchFenceSequence == null && latestCloud != null) {
      _mapSwitchFenceSequence = latestCloud.sequence;
      cloudToDraw = null;
    } else if (latestCloud?.sequence == _mapSwitchFenceSequence) {
      cloudToDraw = null;
    }
    return IgnorePointer(
      child: CustomPaint(
        painter: _CloudPainter(metadata: widget.metadata, cloud: cloudToDraw),
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _CloudPainter extends CustomPainter {
  const _CloudPainter({required this.metadata, required this.cloud});

  final LiveMapMetadata metadata;
  final CloudFrame? cloud;

  @override
  void paint(Canvas canvas, Size size) {
    final frame = cloud;
    if (frame == null || frame.packedMapPoints.isEmpty) {
      return;
    }
    final scaleX = size.width / metadata.worldWidth;
    final scaleY = size.height / metadata.worldHeight;
    final paint = Paint()
      ..color = AletheiaTheme.mapPointCloud
      ..strokeCap = StrokeCap.round
      // The painter works in world metres so point size remains visually
      // stable when a differently sized cached map is displayed.
      ..strokeWidth = 2.4 / math.max(scaleX, scaleY);
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    canvas.translate(
      -metadata.originX * scaleX,
      size.height + metadata.originY * scaleY,
    );
    canvas.scale(scaleX, -scaleY);
    // ``drawRawPoints`` consumes the already packed Float32List directly.
    // This removes the per-frame List<Offset> allocation hot path.
    canvas.drawRawPoints(ui.PointMode.points, frame.packedMapPoints, paint);
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _CloudPainter oldDelegate) =>
      oldDelegate.metadata != metadata ||
      oldDelegate.cloud?.sequence != cloud?.sequence;
}

class _PoseMapLayer extends ConsumerStatefulWidget {
  const _PoseMapLayer({required this.metadata, required this.footprint});

  final LiveMapMetadata metadata;
  final VehicleFootprint footprint;

  @override
  ConsumerState<_PoseMapLayer> createState() => _PoseMapLayerState();
}

class _PoseMapLayerState extends ConsumerState<_PoseMapLayer> {
  int? _mapSwitchFenceSequence;

  @override
  Widget build(BuildContext context) {
    final poseState = ref.watch(poseTelemetryProvider);
    final latestPose = poseState.maybeWhen(
      data: (value) => value.frame,
      orElse: () => null,
    );
    var poseToDraw = latestPose;
    if (_mapSwitchFenceSequence == null && latestPose != null) {
      _mapSwitchFenceSequence = latestPose.sequence;
      poseToDraw = null;
    } else if (latestPose?.sequence == _mapSwitchFenceSequence) {
      poseToDraw = null;
    }
    return IgnorePointer(
      child: CustomPaint(
        painter: _PosePainter(
          metadata: widget.metadata,
          footprint: widget.footprint,
          pose: poseToDraw,
        ),
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _PosePainter extends CustomPainter {
  const _PosePainter({
    required this.metadata,
    required this.footprint,
    required this.pose,
  });

  final LiveMapMetadata metadata;
  final VehicleFootprint footprint;
  final PoseFrame? pose;

  @override
  void paint(Canvas canvas, Size size) {
    final frame = pose;
    if (frame == null || !metadata.contains(frame.x, frame.y)) {
      return;
    }
    final x = ((frame.x - metadata.originX) / metadata.worldWidth) * size.width;
    final y =
        (1 - ((frame.y - metadata.originY) / metadata.worldHeight)) *
        size.height;
    final width = (footprint.widthMeters / metadata.worldWidth) * size.width;
    final length =
        (footprint.lengthMeters / metadata.worldHeight) * size.height;
    if (width <= 0 || length <= 0) {
      return;
    }
    final fill = Paint()
      ..color = AletheiaTheme.mapRobot.withValues(alpha: .92)
      ..style = PaintingStyle.fill;
    final outline = Paint()
      ..color = AletheiaTheme.mapRobotOutline
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6;
    final heading = Paint()
      ..color = AletheiaTheme.surfaceSunken
      ..strokeWidth = math.max(1, length * .07)
      ..strokeCap = StrokeCap.round;
    canvas.save();
    canvas.translate(x, y);
    // Matches the established PC world-to-screen vehicle orientation.
    canvas.rotate(math.pi / 2 - frame.yaw);
    final body = Rect.fromCenter(
      center: Offset.zero,
      width: width,
      height: length,
    );
    canvas.drawRect(body, fill);
    canvas.drawRect(body, outline);
    canvas.drawLine(
      Offset(-width * .24, -length * .34),
      Offset(width * .24, -length * .34),
      heading,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _PosePainter oldDelegate) =>
      oldDelegate.metadata != metadata ||
      oldDelegate.footprint.lengthMeters != footprint.lengthMeters ||
      oldDelegate.footprint.widthMeters != footprint.widthMeters ||
      oldDelegate.pose?.sequence != pose?.sequence ||
      oldDelegate.pose?.x != pose?.x ||
      oldDelegate.pose?.y != pose?.y ||
      oldDelegate.pose?.yaw != pose?.yaw;
}

class _CloudMetricsReporter extends ConsumerStatefulWidget {
  const _CloudMetricsReporter();

  @override
  ConsumerState<_CloudMetricsReporter> createState() =>
      _CloudMetricsReporterState();
}

class _CloudMetricsReporterState extends ConsumerState<_CloudMetricsReporter> {
  static const _metricsInterval = Duration(seconds: 5);

  DateTime _metricsStartedAt = DateTime.now();
  int _receivedPackets = 0;
  int _sourceAgeMilliseconds = 0;

  @override
  Widget build(BuildContext context) {
    ref.listen<AsyncValue<CloudTelemetrySample>>(cloudTelemetryProvider, (
      previous,
      next,
    ) {
      next.whenData(_recordSample);
    });
    ref.watch(cloudTelemetryProvider);
    return const SizedBox.shrink();
  }

  void _recordSample(CloudTelemetrySample sample) {
    _receivedPackets += sample.receivedPackets;
    _sourceAgeMilliseconds = sample.frame.sourceAgeMillisecondsAt(
      DateTime.now(),
    );
    final now = DateTime.now();
    final elapsed = now.difference(_metricsStartedAt);
    if (elapsed < _metricsInterval) {
      return;
    }
    final rate = _receivedPackets * 1000 / elapsed.inMilliseconds;
    _metricsStartedAt = now;
    _receivedPackets = 0;
    unawaited(
      _postMetrics(
        packetRate: rate.clamp(0, 120).toDouble(),
        sourceAgeMilliseconds: _sourceAgeMilliseconds.toDouble(),
      ),
    );
  }

  Future<void> _postMetrics({
    required double packetRate,
    required double sourceAgeMilliseconds,
  }) async {
    final connection = ref.read(robotConnectionControllerProvider);
    final endpoint = connection.endpoint;
    if (endpoint == null) {
      return;
    }
    try {
      await ref
          .read(aletheiaApiClientProvider)
          .postJson(
            endpoint,
            'api/observation/client-metrics',
            body: {
              'cloud_packet_rate_hz': packetRate,
              'cloud_source_age_ms': sourceAgeMilliseconds,
            },
          );
    } catch (_) {
      // Client metrics are diagnostic only and must not surface as an error.
    }
  }
}

class _TelemetryRow extends StatelessWidget {
  const _TelemetryRow({
    required this.icon,
    required this.title,
    required this.detail,
    required this.color,
    this.compact = false,
    this.flat = false,
  });

  final IconData icon;
  final String title;
  final String detail;
  final Color color;
  final bool compact;
  final bool flat;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: flat ? Colors.transparent : color.withValues(alpha: .09),
        border: flat ? null : Border.all(color: color.withValues(alpha: .28)),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: EdgeInsets.symmetric(
          horizontal: flat
              ? 4
              : compact
              ? 9
              : 12,
          vertical: flat
              ? 4
              : compact
              ? 7
              : 12,
        ),
        child: Row(
          children: [
            Icon(
              icon,
              color: color,
              size: flat
                  ? 16
                  : compact
                  ? 17
                  : 20,
            ),
            SizedBox(
              width: flat
                  ? 5
                  : compact
                  ? 7
                  : 10,
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  SizedBox(height: compact || flat ? 0 : 2),
                  Text(
                    detail,
                    maxLines: compact || flat ? 1 : null,
                    overflow: compact || flat ? TextOverflow.ellipsis : null,
                    style: TextStyle(
                      color: AletheiaTheme.textSecondary,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatePanel extends StatelessWidget {
  const _StatePanel({
    required this.icon,
    required this.title,
    required this.detail,
    this.loading = false,
    this.error = false,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String detail;
  final bool loading;
  final bool error;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final color = error ? AletheiaTheme.danger : AletheiaTheme.textTertiary;
    return _Panel(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (loading)
              const SizedBox(
                width: 28,
                height: 28,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              )
            else
              Icon(icon, color: color, size: 32),
            SizedBox(height: 12),
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            SizedBox(height: 6),
            Text(
              detail,
              textAlign: TextAlign.center,
              style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.4),
            ),
            if (actionLabel != null && onAction != null) ...[
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: onAction,
                icon: const Icon(Icons.refresh_rounded),
                label: Text(actionLabel!),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ConnectionRequired extends StatelessWidget {
  const _ConnectionRequired();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          key: ValueKey('observation-connection-required'),
          constraints: BoxConstraints(maxWidth: 320),
          child: SizedBox(
            width: double.infinity,
            child: _StatePanel(
              icon: Icons.lan_outlined,
              title: '先连接机器人',
              detail: '连接后即可查看地图与实时数据。',
            ),
          ),
        ),
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child, this.padding = const EdgeInsets.all(20)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surface,
        border: Border.all(color: AletheiaTheme.border),
        borderRadius: BorderRadius.circular(AletheiaTheme.panelRadius),
      ),
      child: Padding(padding: padding, child: child),
    );
  }
}

class _PageLabel extends StatelessWidget {
  const _PageLabel({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, color: AletheiaTheme.cyan, size: 17),
        SizedBox(width: 8),
        Text(
          text,
          style: TextStyle(
            color: AletheiaTheme.textSecondary,
            fontSize: 12,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

class _InlineNotice extends StatelessWidget {
  const _InlineNotice({required this.text, required this.isError});

  final String text;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final color = isError ? AletheiaTheme.danger : AletheiaTheme.warning;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              isError
                  ? Icons.error_outline_rounded
                  : Icons.info_outline_rounded,
              color: color,
              size: 18,
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Text(text, style: TextStyle(color: color, height: 1.35)),
            ),
          ],
        ),
      ),
    );
  }
}

String _videoStreamLabel(String name) => switch (name) {
  'front_camera' => '前向相机',
  'back_camera' => '后向相机',
  'left_camera' => '左侧相机',
  'right_camera' => '右侧相机',
  'detection_camera' => '目标检测',
  'segmentation_overlay' => '可通行区域分割',
  _ => name,
};

String _videoAvailabilityLabel(VideoStream stream) {
  if (!stream.enabled) {
    return '视频待机';
  }
  return switch (stream.availability) {
    VideoStreamAvailability.waiting => '正在准备画面',
    VideoStreamAvailability.offline => '视频服务未连接',
    VideoStreamAvailability.disabled => '视频待机',
    VideoStreamAvailability.online => '正在连接视频',
    VideoStreamAvailability.unknown => '视频状态未知',
  };
}

int _degrees(double radians) => (radians * 180 / math.pi).round();
