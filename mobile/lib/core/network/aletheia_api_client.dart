import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../connection/observation_status.dart';
import '../connection/robot_endpoint.dart';
import 'api_exception.dart';

class AletheiaApiClient {
  AletheiaApiClient(this._client);

  static const _timeout = Duration(seconds: 5);

  final http.Client _client;

  Future<ObservationStatus> observation(RobotEndpoint endpoint) async {
    final json = await getJson(endpoint, 'api/observation');
    return ObservationStatus.fromJson(json);
  }

  Future<ObservationStatus> startObservation(RobotEndpoint endpoint) async {
    final json = await postJson(endpoint, 'api/observation/start');
    return ObservationStatus.fromJson(json);
  }

  Future<ObservationStatus> heartbeat(RobotEndpoint endpoint) async {
    final json = await postJson(endpoint, 'api/observation/heartbeat');
    return ObservationStatus.fromJson(json);
  }

  Future<Map<String, dynamic>> _get(Uri uri) =>
      _request(() => _client.get(uri, headers: _headers));

  Future<Map<String, dynamic>> getJson(
    RobotEndpoint endpoint,
    String path, {
    Map<String, String>? queryParameters,
  }) => _get(endpoint.apiUri(path, queryParameters: queryParameters));

  Future<List<int>> getBytes(RobotEndpoint endpoint, String path) async {
    try {
      final response = await _client
          .get(endpoint.apiUri(path), headers: _headers)
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final payload = _decode(response.bodyBytes);
        throw ApiException(
          _errorMessage(payload) ?? '机器人暂时无法响应，请稍后重试。',
          statusCode: response.statusCode,
        );
      }
      if (response.bodyBytes.isEmpty) {
        throw const ApiException('未找到可用的地图。');
      }
      return response.bodyBytes;
    } on TimeoutException {
      throw const ApiException('读取地图超时。请确认局域网连接稳定。');
    } on http.ClientException {
      throw const ApiException('无法读取机器人地图。');
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException('读取机器人地图失败。');
    }
  }

  /// Downloads a whitelisted console artefact. Callers only ever receive a
  /// server-issued route/name; they must not manufacture paths on the robot.
  Future<http.Response> download(
    RobotEndpoint endpoint,
    String path, {
    Map<String, String>? queryParameters,
  }) async {
    try {
      final response = await _client
          .get(
            endpoint.apiUri(path, queryParameters: queryParameters),
            headers: _headers,
          )
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final payload = _decode(response.bodyBytes);
        throw ApiException(
          _errorMessage(payload) ?? '下载文件失败，请稍后重试。',
          statusCode: response.statusCode,
        );
      }
      return response;
    } on TimeoutException {
      throw const ApiException('下载超时。请确认局域网连接稳定。');
    } on http.ClientException {
      throw const ApiException('无法连接机器人下载文件。');
    }
  }

  Future<String?> activeObservationMapId(RobotEndpoint endpoint) async {
    final json = await getJson(endpoint, 'api/observation/active-map');
    final value = json['active_map_id'];
    return value is String && value.isNotEmpty ? value : null;
  }

  Future<Map<String, dynamic>> observationMapLayers(
    RobotEndpoint endpoint,
    String mapId,
  ) => getJson(endpoint, 'api/observation/maps/$mapId/layers');

  Future<Map<String, dynamic>> postJson(
    RobotEndpoint endpoint,
    String path, {
    Map<String, dynamic>? body,
  }) {
    final headers = {
      ..._headers,
      if (body != null) 'Content-Type': 'application/json',
    };
    return _request(
      () => _client.post(
        endpoint.apiUri(path),
        headers: headers,
        body: body == null ? null : jsonEncode(body),
      ),
    );
  }

  Future<Map<String, dynamic>> deleteJson(
    RobotEndpoint endpoint,
    String path,
  ) => _request(() => _client.delete(endpoint.apiUri(path), headers: _headers));

  /// Uploads one user-selected file to a fixed existing console endpoint.
  /// The endpoint validates the actual filename/content; no local path is
  /// sent to the robot.
  Future<Map<String, dynamic>> postBytes(
    RobotEndpoint endpoint,
    String path, {
    required List<int> bytes,
    required String contentType,
    Map<String, String> headers = const {},
  }) {
    return _request(
      () => _client.post(
        endpoint.apiUri(path),
        headers: {..._headers, 'Content-Type': contentType, ...headers},
        body: bytes,
      ),
    );
  }

  Map<String, String> get _headers => const {
    'Accept': 'application/json',
    'Cache-Control': 'no-store',
  };

  Future<Map<String, dynamic>> _request(
    Future<http.Response> Function() request,
  ) async {
    try {
      final response = await request().timeout(_timeout);
      final payload = _decode(response.bodyBytes);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw ApiException(
          _errorMessage(payload) ?? '机器人暂时无法响应，请稍后重试。',
          statusCode: response.statusCode,
        );
      }
      if (payload == null) {
        throw const ApiException('机器人返回的数据暂时无法读取。');
      }
      final error = _errorMessage(payload);
      if (error != null) {
        throw ApiException(error, statusCode: response.statusCode);
      }
      return payload;
    } on TimeoutException {
      throw const ApiException('连接超时。请确认设备与机器人位于同一局域网。');
    } on http.ClientException {
      throw const ApiException('无法连接机器人。请检查地址和网络后重试。');
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException('连接失败。请检查网络后重试。');
    }
  }

  Map<String, dynamic>? _decode(List<int> bytes) {
    if (bytes.isEmpty) {
      return null;
    }
    try {
      final value = jsonDecode(utf8.decode(bytes));
      return value is Map
          ? value.map((key, item) => MapEntry(key.toString(), item))
          : null;
    } on FormatException {
      return null;
    }
  }

  String? _errorMessage(Map<String, dynamic>? payload) {
    final value = payload?['error'];
    return value is String && value.trim().isNotEmpty ? value : null;
  }
}
