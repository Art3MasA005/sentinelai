import 'package:intl/intl.dart';

final _int = NumberFormat.decimalPattern('en_US');

String fmtInt(num? v) => v == null ? '—' : _int.format(v);

String fmtNum(num? v, [int digits = 3]) => v == null ? '—' : v.toStringAsFixed(digits);

/// 0.028 -> "2.8%".
String fmtPct(num? v, [int digits = 1]) => v == null ? '—' : '${(v * 100).toStringAsFixed(digits)}%';

/// Percentage points: 0.031 -> "3.1 pp".
String fmtPp(num? v, [int digits = 1]) => v == null ? '—' : '${(v * 100).toStringAsFixed(digits)} pp';

String fmtSigned(num? v, [int digits = 3]) => v == null ? '—' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(digits)}';

String fmtBytes(num? b) {
  if (b == null) return '—';
  if (b < 1024) return '$b B';
  if (b < 1 << 20) return '${(b / 1024).toStringAsFixed(1)} KB';
  if (b < 1 << 30) return '${(b / (1 << 20)).toStringAsFixed(1)} MB';
  return '${(b / (1 << 30)).toStringAsFixed(2)} GB';
}

String fmtSeconds(num? s) {
  if (s == null) return '—';
  if (s < 60) return '${s.toStringAsFixed(1)} s';
  return '${(s / 60).toStringAsFixed(1)} min';
}

DateTime? parseTime(Object? v) => v is String ? DateTime.tryParse(v) : null;

/// Formats an ISO timestamp in local time or UTC depending on the user setting.
String fmtTime(Object? iso, {bool utc = false, bool withDate = false}) {
  final t = parseTime(iso);
  if (t == null) return '—';
  final d = utc ? t.toUtc() : t.toLocal();
  return DateFormat(withDate ? 'MMM dd HH:mm:ss' : 'HH:mm:ss').format(d);
}

String fmtRelativeDay(Object? iso, {bool utc = false}) {
  final t = parseTime(iso);
  if (t == null) return '—';
  final d = utc ? t.toUtc() : t.toLocal();
  final now = utc ? DateTime.now().toUtc() : DateTime.now();
  final days = DateTime(now.year, now.month, now.day).difference(DateTime(d.year, d.month, d.day)).inDays;
  final hm = DateFormat('HH:mm').format(d);
  if (days == 0) return 'Today $hm';
  if (days == 1) return 'Yesterday $hm';
  return DateFormat('MMM dd HH:mm').format(d);
}

String runLabel(int? seq) => seq == null ? 'RUN-—' : 'RUN-${seq.toString().padLeft(3, '0')}';

const methodNames = {
  'static': 'Static baseline',
  'periodic_retrain': 'Periodic retrain',
  'continual_replay': 'Continual replay',
  'guarded_selective': 'Selective adaptation',
  'uncertainty_al': 'Uncertainty sampling',
  'insomnia': 'INSOMNIA (label-free)',
  'netguard_ps': 'NetGuard prior selection',
  'cbrs_replay': 'Class-balanced replay',
  'nova': 'NOVA (proposed)',
};

String methodName(String? m) => methodNames[m] ?? (m ?? '—');

String titleCase(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1).replaceAll('_', ' ');
