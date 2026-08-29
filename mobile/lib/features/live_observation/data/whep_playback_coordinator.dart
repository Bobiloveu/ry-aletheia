import 'dart:async';

/// Limits native WHEP decoders while preserving safe async teardown.
///
/// A camera switch replaces one widget with another before Flutter can await
/// the departing widget's asynchronous native teardown. The coordinator keeps
/// the concurrent receive-only decoder budget explicit and makes a fourth
/// renderer wait until a departing renderer has closed its PeerConnection.
class WhepPlaybackCoordinator {
  WhepPlaybackCoordinator({this.maxConcurrent = 1}) : assert(maxConcurrent > 0);

  final int maxConcurrent;
  final List<Completer<WhepPlaybackLease>> _waiting =
      <Completer<WhepPlaybackLease>>[];
  var _activeLeases = 0;

  Future<WhepPlaybackLease> acquire() {
    final request = Completer<WhepPlaybackLease>();
    _waiting.add(request);
    _grantWaitingLeases();
    return request.future;
  }

  void _grantWaitingLeases() {
    while (_activeLeases < maxConcurrent && _waiting.isNotEmpty) {
      final request = _waiting.removeAt(0);
      _activeLeases++;
      request.complete(
        WhepPlaybackLease._(() {
          _activeLeases--;
          _grantWaitingLeases();
        }),
      );
    }
  }
}

class WhepPlaybackLease {
  WhepPlaybackLease._(this._onRelease);

  final VoidCallback _onRelease;
  bool _released = false;

  void release() {
    if (_released) {
      return;
    }
    _released = true;
    _onRelease();
  }
}

typedef VoidCallback = void Function();
