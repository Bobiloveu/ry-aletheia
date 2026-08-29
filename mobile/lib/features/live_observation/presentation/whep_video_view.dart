import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:http/http.dart' as http;

import '../../../app/theme/aletheia_theme.dart';
import '../data/whep_playback_coordinator.dart';
import '../data/whep_session.dart';

/// Optional replacement for the native playback surface.
///
/// Production deliberately leaves this unset. The debug UI gallery supplies a
/// deterministic mock frame through this narrow seam so it can render the
/// real camera card without opening WebRTC or a WHEP session.
typedef WhepVideoPreviewBuilder = Widget Function({
  required Uri endpoint,
  required String resolution,
});

final whepVideoPreviewBuilderProvider = Provider<WhepVideoPreviewBuilder?>(
  (ref) => null,
);

enum _WhepPlaybackPhase { initializing, connecting, playing, failure }

/// Renders one receive-only WHEP/WebRTC stream. The process-level coordinator
/// limits the camera workspace to three concurrent decoders; each peer, HTTP
/// WHEP session and native renderer is released when this widget leaves.
class WhepVideoView extends StatefulWidget {
  const WhepVideoView({
    required this.endpoint,
    required this.resolution,
    super.key,
  });

  final Uri endpoint;
  final String resolution;

  @override
  State<WhepVideoView> createState() => _WhepVideoViewState();
}

class _WhepVideoViewState extends State<WhepVideoView> {
  static const _retryDelay = Duration(seconds: 3);
  static final _playbackCoordinator = WhepPlaybackCoordinator(maxConcurrent: 3);

  final RTCVideoRenderer _renderer = RTCVideoRenderer();
  final http.Client _httpClient = http.Client();
  WhepSession? _session;
  Timer? _retryTimer;
  WhepPlaybackLease? _lease;
  Future<void> _lifecycle = Future<void>.value();
  int _generation = 0;
  bool _isDisposing = false;
  bool _rendererInitialized = false;
  bool _rendererReady = false;
  _WhepPlaybackPhase _phase = _WhepPlaybackPhase.initializing;
  String _detail = '正在准备原生视频渲染器…';

  @override
  void initState() {
    super.initState();
    unawaited(_enqueueLifecycle('initialize renderer', _initializeRenderer));
  }

  @override
  void didUpdateWidget(covariant WhepVideoView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.endpoint != widget.endpoint && _rendererReady) {
      _requestRestart();
    }
  }

  @override
  void dispose() {
    _isDisposing = true;
    _generation++;
    _retryTimer?.cancel();
    unawaited(_enqueueLifecycle('dispose renderer', _disposeResources));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final error = _phase == _WhepPlaybackPhase.failure;
    final showMessage = _phase != _WhepPlaybackPhase.playing;
    return ColoredBox(
      color: AletheiaTheme.surfaceSunken,
      child: Stack(
        fit: StackFit.expand,
        children: [
          RTCVideoView(
            _renderer,
            objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitContain,
            filterQuality: FilterQuality.low,
          ),
          if (showMessage)
            Center(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (!error)
                      const SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    else
                      Icon(
                        Icons.videocam_off_outlined,
                        color: AletheiaTheme.warning,
                        size: 28,
                      ),
                    SizedBox(height: 10),
                    Text(
                      _detail,
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: error
                            ? AletheiaTheme.warning
                            : AletheiaTheme.textSecondary,
                        fontSize: 12,
                        height: 1.35,
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _initializeRenderer() async {
    _lease = await _playbackCoordinator.acquire();
    if (_isDisposing) {
      _releaseLease();
      return;
    }
    try {
      await _renderer.initialize();
      _rendererInitialized = true;
      if (_isDisposing || !mounted) {
        return;
      }
      _rendererReady = true;
      await _restart(_generation);
    } on Object {
      _httpClient.close();
      _releaseLease();
      rethrow;
    }
  }

  void _requestRestart() {
    final generation = ++_generation;
    _retryTimer?.cancel();
    unawaited(
      _enqueueLifecycle('restart playback', () => _restart(generation)),
    );
  }

  Future<void> _restart(int generation) async {
    if (!_isActiveGeneration(generation)) {
      return;
    }
    await _closeCurrentSession();
    if (!_isActiveGeneration(generation)) {
      return;
    }
    setState(() {
      _phase = _WhepPlaybackPhase.connecting;
      _detail = '正在连接视频…';
    });
    final session = WhepSession(_httpClient);
    _session = session;
    try {
      await session.open(
        widget.endpoint,
        onRemoteStream: (stream) {
          unawaited(
            _enqueueLifecycle(
              'attach remote stream',
              () => _attachRemoteStream(generation, session, stream),
            ),
          );
        },
        onConnectionState: (state) {
          if (!_isActiveGeneration(generation) || _session != session) {
            return;
          }
          if (state == RTCPeerConnectionState.RTCPeerConnectionStateFailed ||
              state ==
                  RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
            unawaited(
              _enqueueLifecycle(
                'recover disconnected playback',
                () => _failAndRetry(generation, '视频连接中断，正在重连。'),
              ),
            );
          }
        },
      );
    } on Object catch (error, stackTrace) {
      _logExpectedPlaybackFailure('WHEP negotiation failed', error, stackTrace);
      await _failAndRetry(generation, '视频连接失败，正在重试。');
    }
  }

  Future<void> _attachRemoteStream(
    int generation,
    WhepSession session,
    MediaStream stream,
  ) async {
    if (!_isActiveGeneration(generation) || _session != session) {
      return;
    }
    await _renderer.setSrcObject(stream: stream);
    if (!_isActiveGeneration(generation) || _session != session) {
      await _renderer.setSrcObject();
      return;
    }
    setState(() {
      _phase = _WhepPlaybackPhase.playing;
      _detail = widget.resolution;
    });
  }

  Future<void> _failAndRetry(int generation, String detail) async {
    if (!_isActiveGeneration(generation)) {
      return;
    }
    await _closeCurrentSession();
    if (!_isActiveGeneration(generation)) {
      return;
    }
    setState(() {
      _phase = _WhepPlaybackPhase.failure;
      _detail = detail;
    });
    _retryTimer?.cancel();
    _retryTimer = Timer(_retryDelay, () {
      if (_isActiveGeneration(generation)) {
        _requestRestart();
      }
    });
  }

  Future<void> _closeCurrentSession() async {
    final session = _session;
    _session = null;
    if (_rendererInitialized) {
      await _renderer.setSrcObject();
    }
    await session?.close();
  }

  Future<void> _disposeResources() async {
    try {
      await _closeCurrentSession();
      _httpClient.close();
      if (_rendererInitialized) {
        await _renderer.dispose();
      }
    } finally {
      _releaseLease();
    }
  }

  Future<void> _enqueueLifecycle(
    String operation,
    Future<void> Function() action,
  ) {
    final next = _lifecycle.then((_) => action());
    _lifecycle = next.then<void>(
      (_) {},
      onError: (Object error, StackTrace stackTrace) {
        _reportLifecycleFailure(operation, error, stackTrace);
      },
    );
    return _lifecycle;
  }

  bool _isActiveGeneration(int generation) =>
      mounted && !_isDisposing && _rendererReady && generation == _generation;

  void _releaseLease() {
    _lease?.release();
    _lease = null;
  }

  void _logExpectedPlaybackFailure(
    String operation,
    Object error,
    StackTrace stackTrace,
  ) {
    debugPrint('[WHEP] $operation: $error');
    debugPrintStack(stackTrace: stackTrace);
  }

  void _reportLifecycleFailure(
    String operation,
    Object error,
    StackTrace stackTrace,
  ) {
    FlutterError.reportError(
      FlutterErrorDetails(
        exception: error,
        stack: stackTrace,
        library: 'Aletheia WHEP playback',
        context: ErrorDescription(operation),
      ),
    );
    if (mounted && !_isDisposing) {
      setState(() {
        _phase = _WhepPlaybackPhase.failure;
        _detail = '视频渲染器发生错误，请切换或重新打开相机。';
      });
    }
  }
}
