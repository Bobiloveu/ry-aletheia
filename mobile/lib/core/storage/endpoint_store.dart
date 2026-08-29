import 'package:shared_preferences/shared_preferences.dart';

import '../connection/robot_endpoint.dart';

class EndpointStore {
  static const _key = 'robot_endpoint';

  Future<RobotEndpoint?> read() async {
    final preferences = await SharedPreferences.getInstance();
    final raw = preferences.getString(_key);
    if (raw == null) {
      return null;
    }
    try {
      return RobotEndpoint.parse(raw);
    } on FormatException {
      await preferences.remove(_key);
      return null;
    }
  }

  Future<void> write(RobotEndpoint endpoint) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_key, endpoint.toString());
  }
}
