/// The one source of truth for an Aletheia robot console address.
///
/// The current robot service exposes a fixed HTTP control port. Keeping port
/// construction here prevents future REST, telemetry and video features from
/// each implementing IPv4/IPv6 handling differently.
class RobotEndpoint {
  const RobotEndpoint._(this.host);

  static const int consolePort = 8087;
  static const int telemetryPort = 8768;

  final String host;

  factory RobotEndpoint.parse(String raw) {
    final input = raw.trim();
    if (input.isEmpty) {
      throw const FormatException('请输入机器人地址。');
    }

    final withScheme = input.contains('://') ? input : 'http://$input';
    final uri = Uri.tryParse(withScheme);
    if (uri == null || uri.host.isEmpty) {
      throw const FormatException('地址格式无效。请输入机器人 IP 或主机名。');
    }
    if (uri.scheme != 'http') {
      throw const FormatException('请输入机器人地址，不支持 https 页面地址。');
    }
    if (uri.path.isNotEmpty && uri.path != '/') {
      throw const FormatException('请输入机器人主机地址，不要包含页面路径。');
    }
    if (uri.hasQuery || uri.hasFragment) {
      throw const FormatException('机器人地址不能包含查询参数或锚点。');
    }
    if (uri.hasPort && uri.port != consolePort) {
      throw const FormatException('请输入机器人地址，不要附加其他内容。');
    }
    return RobotEndpoint._(uri.host);
  }

  Uri apiUri(String path, {Map<String, String>? queryParameters}) => Uri(
    scheme: 'http',
    host: host,
    port: consolePort,
    path: path.startsWith('/') ? path.substring(1) : path,
    queryParameters: queryParameters,
  );

  Uri telemetryUri(int port, String path) => Uri(
    scheme: 'ws',
    host: host,
    port: port,
    path: path.startsWith('/') ? path.substring(1) : path,
  );

  Uri get consoleUri => apiUri('');

  String get displayAddress {
    final readableHost = host.contains(':') ? '[$host]' : host;
    return '$readableHost:$consolePort';
  }

  @override
  String toString() => consoleUri.toString();

  @override
  bool operator ==(Object other) =>
      other is RobotEndpoint && other.host == host;

  @override
  int get hashCode => host.hashCode;
}
