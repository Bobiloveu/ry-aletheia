import 'dart:collection';

import 'package:flutter_riverpod/flutter_riverpod.dart';

/// A small, in-memory record of app-only session events.
///
/// It records no robot endpoint, telemetry, map/video payload, request body
/// or user-entered form text. The buffer disappears when the app process exits
/// and is exposed only through the feedback submission boundary.
class AppDiagnosticLog {
  static const _maxEntries = 40;
  final Queue<String> _events = Queue<String>();

  void record(String event) {
    _events.add(_safeEvent(event));
    while (_events.length > _maxEntries) {
      _events.removeFirst();
    }
  }

  List<String> snapshot() => List.unmodifiable(_events);

  String _safeEvent(String event) => event
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim()
      .replaceAll(RegExp(r'https?://\S+'), '[redacted-url]');
}

final appDiagnosticLogProvider = Provider<AppDiagnosticLog>(
  (ref) => AppDiagnosticLog(),
);
