import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.status});
  final String message;
  final int? status;

  bool get isOffline => status == null;

  @override
  String toString() => status == null ? message : '$message (HTTP $status)';
}

/// Thin JSON client for the SentinelAI FastAPI backend (`/api/v1`).
class ApiClient {
  ApiClient({required this.baseUrl, this.timeout = const Duration(seconds: 10), this.token, http.Client? client})
    : _http = client ?? http.Client();

  final String baseUrl;
  final Duration timeout;

  /// Session token from sign-in; sent as `Authorization: Bearer`.
  final String? token;
  final http.Client _http;

  /// Same backend and session, different timeout (long jobs such as importing a multi-GB dataset).
  ApiClient withTimeout(Duration t) => ApiClient(baseUrl: baseUrl, timeout: t, token: token, client: _http);

  Map<String, String> get _auth => token == null ? const {} : {'authorization': 'Bearer $token'};
  Map<String, String> get _json => {'content-type': 'application/json', ..._auth};

  static const prefix = '/api/v1';

  Uri uri(String path, [Map<String, Object?>? query]) {
    final q = <String, String>{
      for (final e in (query ?? const {}).entries)
        if (e.value != null) e.key: '${e.value}',
    };
    final base = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    return Uri.parse('$base$prefix$path').replace(queryParameters: q.isEmpty ? null : q);
  }

  Future<dynamic> _send(Future<http.Response> Function() call) async {
    final http.Response res;
    try {
      res = await call().timeout(timeout);
    } on TimeoutException {
      throw ApiException('Backend did not answer within ${timeout.inSeconds}s');
    } catch (e) {
      throw ApiException('Cannot reach backend at $baseUrl');
    }
    final body = res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    if (res.statusCode >= 400) {
      throw ApiException(_detail(body is Map ? body['detail'] : null), status: res.statusCode);
    }
    return body;
  }

  /// FastAPI errors: a string, or a list of field errors ({loc, msg}) for 422s.
  static String _detail(Object? detail) {
    if (detail is String) return detail;
    if (detail is List && detail.isNotEmpty && detail.first is Map) {
      final msg = '${(detail.first as Map)['msg'] ?? ''}'.replaceFirst('Value error, ', '');
      return msg.isEmpty ? 'Invalid input' : msg;
    }
    return 'Request failed';
  }

  Future<dynamic> get(String path, [Map<String, Object?>? query]) =>
      _send(() => _http.get(uri(path, query), headers: _auth));

  Future<dynamic> post(String path, [Object? body]) =>
      _send(() => _http.post(uri(path), headers: _json, body: jsonEncode(body ?? const {})));

  Future<dynamic> put(String path, Object body) =>
      _send(() => _http.put(uri(path), headers: _json, body: jsonEncode(body)));

  Future<dynamic> patch(String path, Object body) =>
      _send(() => _http.patch(uri(path), headers: _json, body: jsonEncode(body)));

  // ---------- auth ----------
  Future<Json> authConfig() async => await get('/auth/config') as Json;
  Future<Json> signup(Json body) async => await post('/auth/signup', body) as Json;
  Future<Json> login(String email, String password, {bool remember = false}) async =>
      await post('/auth/login', {'email': email, 'password': password, 'remember': remember}) as Json;
  Future<Json> googleLogin(String idToken) async => await post('/auth/google', {'id_token': idToken}) as Json;
  Future<Json> googleDesktop(String code, String redirectUri, String verifier) async =>
      await post('/auth/google/desktop', {'code': code, 'redirect_uri': redirectUri, 'code_verifier': verifier})
          as Json;
  Future<void> logout() async => post('/auth/logout');
  Future<Json> me() async => await get('/auth/me') as Json;
  Future<Json> updateMe(Json body) async => await put('/auth/me', body) as Json;
  Future<Json> uploadAvatar(List<int> bytes) async =>
      await _send(
            () => _http.put(
              uri('/auth/me/avatar'),
              headers: {'content-type': 'application/octet-stream', ..._auth},
              body: bytes,
            ),
          )
          as Json;

  /// Raw avatar bytes, or null when the user has no photo.
  Future<List<int>?> avatar() async {
    try {
      final res = await _http.get(uri('/auth/me/avatar'), headers: _auth).timeout(timeout);
      return res.statusCode == 200 ? res.bodyBytes : null;
    } catch (_) {
      return null;
    }
  }

  // ---------- typed helpers ----------
  Future<Json> health() async => await get('/health') as Json;
  Future<SystemStatus> system() async => SystemStatus(await get('/system'));

  Future<List<Dataset>> datasets() async =>
      ((await get('/datasets', {'page_size': 500}) as Json)['items'] as List).map((e) => Dataset(e)).toList();
  Future<Json> validateDataset(String id) async => await post('/datasets/validate', {'dataset_id': id}) as Json;
  Future<Json> importDataset(String source, String name, {String? profile}) async =>
      await post('/datasets/import', {'source': source, 'name': name, 'profile': profile}) as Json;
  Future<Json> createDemo() async => await post('/datasets/demo', {'rows': 30000}) as Json;

  Future<PageOf<Run>> runs({String? status, int page = 1, int pageSize = 200}) async =>
      PageOf(await get('/experiments', {'status': status, 'page': page, 'page_size': pageSize}), Run.new);
  Future<Run> run(String id) async => Run(await get('/experiments/$id'));
  Future<Run> createRun(Json config) async => Run(await post('/experiments', config));
  Future<Run> startRun(String id) async => Run(await post('/experiments/$id/start'));
  Future<Json> createBatch(Json body) async => await post('/experiments/batch', body) as Json;
  Future<void> deleteRun(String id) async => _send(() => _http.delete(uri('/experiments/$id'), headers: _auth));
  Future<Json> control(String id, String action) async => await post('/experiments/$id/$action') as Json;

  Future<Json> overview(String id) async => await get('/experiments/$id/overview') as Json;
  Future<RunMetrics> metrics(String id) async => RunMetrics(await get('/experiments/$id/metrics'));
  Future<Json> classDistribution(String id) async => await get('/experiments/$id/class-distribution') as Json;
  Future<PageOf<NetFlow>> flows(String id, Map<String, Object?> query) async =>
      PageOf(await get('/experiments/$id/flows', query), NetFlow.new);
  Future<NetFlow> flow(String id, int flowId) async => NetFlow(await get('/experiments/$id/flows/$flowId'));
  Future<PageOf<Json>> driftEvents(String id) async =>
      PageOf(await get('/experiments/$id/drift-events', {'page_size': 500}), (e) => e as Json);
  Future<PageOf<Json>> adaptationEvents(String id) async =>
      PageOf(await get('/experiments/$id/adaptation-events', {'page_size': 500}), (e) => e as Json);
  Future<List<Json>> models(String id) async => ((await get('/experiments/$id/models')) as List).cast<Json>();
  Future<List<String>> logs(String id, {int tail = 200}) async =>
      (((await get('/experiments/$id/logs', {'tail': tail})) as Json)['lines'] as List).cast<String>();

  Future<PageOf<Alert>> alerts(String id, Map<String, Object?> query) async =>
      PageOf(await get('/experiments/$id/alerts', query), Alert.new);
  Future<Json> alertSummary(String id) async => await get('/experiments/$id/alerts/summary') as Json;
  Future<Json> alertDetail(String id, int flowId) async => await get('/experiments/$id/alerts/$flowId') as Json;
  Future<Json> updateAlert(String id, int flowId, String state, String? note) async =>
      await patch('/experiments/$id/alerts/$flowId', {'state': state, 'note': note}) as Json;

  Future<List<Json>> policies() async => ((await get('/policies')) as List).cast<Json>();
  Future<Json> activePolicy() async => await get('/policies/active') as Json;
  Future<Json> savePolicy(Json body, String note) async =>
      await post('/policies', {'body': body, 'note': note}) as Json;

  Future<Json> compare(List<String> ids) async => await get('/experiments/compare', {'run_ids': ids.join(',')}) as Json;
  Future<Json> reportStats() async => await get('/reports/stats') as Json;

  Uri compareFiguresUri(List<String> ids) =>
      uri('/experiments/compare/figures', {'run_ids': ids.join(','), 'token': token});

  /// Browser downloads cannot send headers, so the session token rides along as a query parameter.
  Uri exportUri(String id, String format, {String? kind}) =>
      uri('/experiments/$id/export', {'format': format, 'kind': kind, 'token': token});
}
