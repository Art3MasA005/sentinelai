/// Lightweight read-only views over backend JSON. Field names follow docs/API.md.
library;

typedef Json = Map<String, dynamic>;

double? asDouble(Object? v) => v is num ? v.toDouble() : null;
int? asInt(Object? v) => v is num ? v.toInt() : null;
Json asJson(Object? v) => v is Map ? v.cast<String, dynamic>() : <String, dynamic>{};
List<Json> asJsonList(Object? v) => v is List ? v.map(asJson).toList() : <Json>[];

class PageOf<T> {
  PageOf(Object? raw, T Function(dynamic) make)
    : items = ((raw as Map)['items'] as List).map(make).toList(),
      total = raw['total'] as int,
      page = raw['page'] as int,
      pageSize = raw['page_size'] as int,
      dataOrigin = raw['data_origin'] as String?;

  final List<T> items;
  final int total;
  final int page;
  final int pageSize;
  final String? dataOrigin;

  int get pages => total == 0 ? 1 : ((total + pageSize - 1) ~/ pageSize);
}

class Dataset {
  Dataset(Object? raw) : j = asJson(raw);
  final Json j;
  String get id => j['id'] as String;
  String get name => j['name'] as String;
  bool get isDemo => j['is_demo'] == true;
  String? get detectedProfile => j['detected_profile'] as String?;
  int get sizeBytes => asInt(j['size_bytes']) ?? 0;
  Json? get lastValidation => j['last_validation'] == null ? null : asJson(j['last_validation']);
  bool get isValidated => lastValidation?['valid'] == true;
}

class Run {
  Run(Object? raw) : j = asJson(raw);
  final Json j;
  String get id => j['run_id'] as String;
  int get seq => asInt(j['seq']) ?? 0;
  String? get groupId => j['group_id'] as String?;
  int get seed => asInt(config['seed']) ?? 0;
  String get name => j['name'] as String? ?? '';
  String get status => j['status'] as String;
  String get method => j['method'] as String;
  String get datasetId => j['dataset_id'] as String;
  String? get dataOrigin => j['data_origin'] as String?;
  bool get isDemo => dataOrigin == 'demo';
  Json get config => asJson(j['config']);
  Json get progress => asJson(j['progress']);
  Json? get summary => j['summary'] == null ? null : asJson(j['summary']);
  Json get overall => asJson(summary?['overall']);
  String? get error => j['error'] as String?;
  String? get createdAt => j['created_at'] as String?;
  String? get startedAt => j['started_at'] as String?;
  String? get finishedAt => j['finished_at'] as String?;
  bool get isActive => status == 'running' || status == 'paused';
  bool get isBusy => isActive || status == 'queued';
  int get window => asInt(progress['window']) ?? 0;
  int get totalWindows => asInt(progress['total_windows']) ?? 0;

  Duration? get runtime {
    final s = DateTime.tryParse(startedAt ?? ''), f = DateTime.tryParse(finishedAt ?? '');
    return s == null || f == null ? null : f.difference(s);
  }
}

class NetFlow {
  NetFlow(Object? raw) : j = asJson(raw);
  final Json j;
  int get flowId => j['flow_id'] as int;
  int get window => j['window'] as int;
  String? get timestamp => j['timestamp'] as String?;
  String get trueLabel => j['true_label'] as String;
  String get predicted => j['predicted_label'] as String;
  String get decision => j['decision'] as String;
  double get confidence => asDouble(j['confidence']) ?? 0;
  double? get attackScore => asDouble(j['attack_score']);
  double? get noveltyScore => asDouble(j['novelty_score']);
  bool get isUnknown => j['is_unknown'] == true;
  String? get unknownReason => j['unknown_reason'] as String?;
  bool get isNovelClass => j['is_novel_class'] == true;
  int get modelVersion => j['model_version'] as int;
  String? get src => j['src'] as String?;
  String? get dst => j['dst'] as String?;
  String? get protocol => j['protocol'] as String?;
  Json get probabilities => asJson(j['probabilities']);
  Json? get features => j['features'] == null ? null : asJson(j['features']);
}

class Alert extends NetFlow {
  Alert(super.raw);
  String get alertId => j['alert_id'] as String;
  String get severity => j['severity'] as String;
  String get state => j['state'] as String;
  String? get note => j['note'] as String?;
}

class RunMetrics {
  RunMetrics(Object? raw) : j = asJson(raw);
  final Json j;
  String? get dataOrigin => j['data_origin'] as String?;
  Json get overall => asJson(j['overall']);
  Json get confusion => asJson(j['confusion_matrix']);
  List<Json> get windows => asJsonList(j['windows']);
  Json get definitions => asJson(j['definitions']);
  Json get provenance => asJson(j['provenance']);
}

class SystemStatus {
  SystemStatus(Object? raw) : j = asJson(raw);
  final Json j;
  double get cpu => asDouble(j['cpu_percent']) ?? 0;
  double get memory => asDouble(j['memory_percent']) ?? 0;
  double get disk => asDouble(j['disk_percent']) ?? 0;
  double get diskFreeGb => asDouble(j['disk_free_gb']) ?? 0;
  Json? get gpu => j['gpu'] == null ? null : asJson(j['gpu']);
  List<Json> get services => asJsonList(j['services']);
  Json get worker => asJson(j['worker']);
  List<Json> get diagnostics => asJsonList(j['diagnostics']);
}
