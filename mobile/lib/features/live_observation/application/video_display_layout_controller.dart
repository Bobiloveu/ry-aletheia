import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/video_status.dart';

/// Local assignment of the three hardware-decoder slots in the camera HMI.
///
/// A robot can expose more than three enabled sources, but the App deliberately
/// opens at most three WHEP decoders at once. Server-side source switches and
/// client-side display placement are therefore separate concerns: enabling a
/// source asks the robot to publish it; this controller decides which three
/// published sources the operator currently sees.
final videoDisplayLayoutProvider =
    NotifierProvider<VideoDisplayLayoutController, List<String>>(
      VideoDisplayLayoutController.new,
    );

class VideoDisplayLayoutController extends Notifier<List<String>> {
  static const maxSlots = 3;

  @override
  List<String> build() => List<String>.filled(maxSlots, '');

  /// Produces a complete three-slot layout without mutating state during a
  /// widget build. Explicit operator choices retain their order; unused slots
  /// first fill from enabled sources, then from the remaining configured
  /// sources so every slot has a predictable, tappable target.
  List<String> resolve(
    List<VideoStream> streams, {
    required String primaryStreamName,
  }) {
    final available = streams.map((stream) => stream.name).toSet();
    final slots = List<String>.filled(maxSlots, '');
    final claimed = <String>{};

    for (var index = 0; index < maxSlots && index < state.length; index++) {
      final name = state[index];
      if (available.contains(name) && claimed.add(name)) {
        slots[index] = name;
      }
    }
    // The current primary is the visible focus. It always owns slot zero;
    // selecting a source explicitly also records that same assignment.
    if (slots[0] != primaryStreamName) {
      claimed.remove(slots[0]);
      final existing = slots.indexOf(primaryStreamName);
      if (existing > 0) slots[existing] = '';
      slots[0] = primaryStreamName;
      claimed.add(primaryStreamName);
    }

    final candidates = <VideoStream>[
      ...streams.where((stream) => stream.enabled),
      ...streams.where((stream) => !stream.enabled),
    ];
    for (var index = 0; index < maxSlots; index++) {
      if (slots[index].isNotEmpty) continue;
      for (final stream in candidates) {
        if (claimed.add(stream.name)) {
          slots[index] = stream.name;
          break;
        }
      }
    }
    return List.unmodifiable(slots.where((name) => name.isNotEmpty));
  }

  /// Places [streamName] in [slot]. If it is already visible, swap rather
  /// than duplicate it: each real decoder has exactly one visible surface.
  void assign({required int slot, required String streamName}) {
    if (slot < 0 || slot >= maxSlots || streamName.isEmpty) return;
    final next = List<String>.from(state);
    while (next.length < maxSlots) {
      next.add('');
    }
    final existing = next.indexOf(streamName);
    if (existing >= 0 && existing != slot) {
      next[existing] = next[slot];
    }
    next[slot] = streamName;
    state = List.unmodifiable(next.take(maxSlots));
  }
}
