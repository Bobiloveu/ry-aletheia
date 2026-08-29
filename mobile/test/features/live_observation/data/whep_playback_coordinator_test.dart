import 'package:aletheia_mobile/features/live_observation/data/whep_playback_coordinator.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('WHEP playback leases serialize a rapid decoder hand-off', () async {
    final coordinator = WhepPlaybackCoordinator();
    final first = await coordinator.acquire();
    var secondGranted = false;

    final secondFuture = coordinator.acquire().then((lease) {
      secondGranted = true;
      return lease;
    });
    await Future<void>.delayed(Duration.zero);
    expect(secondGranted, isFalse);

    first.release();
    final second = await secondFuture;
    expect(secondGranted, isTrue);
    second.release();
  });

  test('three decoder leases are available before a fourth waits', () async {
    final coordinator = WhepPlaybackCoordinator(maxConcurrent: 3);
    final first = await coordinator.acquire();
    final second = await coordinator.acquire();
    final third = await coordinator.acquire();
    var fourthGranted = false;
    final fourthFuture = coordinator.acquire().then((lease) {
      fourthGranted = true;
      return lease;
    });

    await Future<void>.delayed(Duration.zero);
    expect(fourthGranted, isFalse);

    second.release();
    final fourth = await fourthFuture;
    expect(fourthGranted, isTrue);
    first.release();
    third.release();
    fourth.release();
  });
}
