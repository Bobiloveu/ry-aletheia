import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:http/http.dart' as http;

/// A receive-only WHEP session. It is intentionally separate from the HTTP
/// API repository: this object carries SDP, never camera data through Python.
class WhepSession {
  WhepSession(this._client);

  static const _httpTimeout = Duration(seconds: 5);
  static const _iceGatherTimeout = Duration(milliseconds: 1200);

  final http.Client _client;
  RTCPeerConnection? _peer;
  Uri? _sessionUri;

  Future<void> open(
    Uri endpoint, {
    required void Function(MediaStream stream) onRemoteStream,
    required void Function(RTCPeerConnectionState state) onConnectionState,
  }) async {
    await close();
    final peer = await createPeerConnection(const {'iceServers': <Object>[]});
    _peer = peer;
    peer.onTrack = (event) {
      if (_peer == peer &&
          event.track.kind == 'video' &&
          event.streams.isNotEmpty) {
        onRemoteStream(event.streams.first);
      }
    };
    peer.onConnectionState = (state) {
      if (_peer == peer) {
        onConnectionState(state);
      }
    };
    await peer.addTransceiver(
      kind: RTCRtpMediaType.RTCRtpMediaTypeVideo,
      init: RTCRtpTransceiverInit(direction: TransceiverDirection.RecvOnly),
    );
    if (_peer != peer) {
      return;
    }
    final offer = await peer.createOffer();
    if (_peer != peer) {
      return;
    }
    await peer.setLocalDescription(offer);
    if (_peer != peer) {
      return;
    }
    await _waitForIceGathering(peer);
    if (_peer != peer) {
      return;
    }
    final localDescription = await peer.getLocalDescription();
    final sdp = localDescription?.sdp;
    if (sdp == null || sdp.isEmpty) {
      throw const FormatException('WHEP offer SDP 为空。');
    }
    final response = await _client
        .post(
          endpoint,
          headers: const {
            'Accept': 'application/sdp',
            'Content-Type': 'application/sdp',
          },
          body: sdp,
        )
        .timeout(_httpTimeout);
    if (_peer != peer) {
      await _deleteRemoteSession(
        _sessionUriForResponse(endpoint, response.headers['location']),
      );
      return;
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw FormatException('WHEP 返回 HTTP ${response.statusCode}。');
    }
    _sessionUri = _sessionUriForResponse(
      endpoint,
      response.headers['location'],
    );
    if (_peer != peer) {
      return;
    }
    await peer.setRemoteDescription(
      RTCSessionDescription(response.body, 'answer'),
    );
  }

  Future<void> close() async {
    final sessionUri = _sessionUri;
    _sessionUri = null;
    final peer = _peer;
    _peer = null;
    if (peer != null) {
      peer.onTrack = null;
      peer.onConnectionState = null;
      peer.onIceGatheringState = null;
    }
    if (peer != null) {
      try {
        await peer.close();
      } on Object catch (error, stackTrace) {
        debugPrint('[WHEP] peer.close failed: $error');
        debugPrintStack(stackTrace: stackTrace);
      }
    }
    // Local peer release is the critical hand-off for a rapid camera switch.
    // MediaMTX also observes the closed transport; DELETE remains best effort
    // and must not keep the next selected camera waiting for a network timeout.
    unawaited(_deleteRemoteSession(sessionUri));
  }

  Uri? _sessionUriForResponse(Uri endpoint, String? location) =>
      location == null || location.isEmpty ? null : endpoint.resolve(location);

  Future<void> _deleteRemoteSession(Uri? sessionUri) async {
    if (sessionUri == null) {
      return;
    }
    try {
      await _client.delete(sessionUri).timeout(_httpTimeout);
    } on Object catch (error, stackTrace) {
      // A delete can race an already-lost transport, but retain the actual
      // diagnostic instead of silently swallowing it.
      debugPrint('[WHEP] session DELETE $sessionUri failed: $error');
      debugPrintStack(stackTrace: stackTrace);
    }
  }

  Future<void> _waitForIceGathering(RTCPeerConnection peer) async {
    if (peer.iceGatheringState ==
        RTCIceGatheringState.RTCIceGatheringStateComplete) {
      return;
    }
    final completion = Completer<void>();
    peer.onIceGatheringState = (state) {
      if (state == RTCIceGatheringState.RTCIceGatheringStateComplete &&
          !completion.isCompleted) {
        completion.complete();
      }
    };
    await completion.future.timeout(_iceGatherTimeout, onTimeout: () {});
  }
}
