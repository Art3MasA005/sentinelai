import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/flow_detail.dart';
import '../../core/format.dart';
import '../../core/run_guard.dart';
import '../../core/state.dart';
import '../../core/status.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

class AlertQuery {
  const AlertQuery({this.severity, this.state = 'open', this.decision, this.page = 1});
  final String? severity;
  final String? state;
  final String? decision;
  final int page;

  AlertQuery copy({Object? severity = _keep, Object? state = _keep, Object? decision = _keep, int? page}) => AlertQuery(
    severity: severity == _keep ? this.severity : severity as String?,
    state: state == _keep ? this.state : state as String?,
    decision: decision == _keep ? this.decision : decision as String?,
    page: page ?? 1,
  );

  static const _keep = Object();
}

class AlertQueryNotifier extends Notifier<AlertQuery> {
  @override
  AlertQuery build() {
    ref.watch(currentRunIdProvider); // reset filters when the run changes
    return const AlertQuery();
  }

  void set(AlertQuery q) => state = q;
}

final alertQueryProvider = NotifierProvider<AlertQueryNotifier, AlertQuery>(AlertQueryNotifier.new);

final alertsPageProvider = FutureProvider<PageOf<Alert>?>((ref) {
  ref.watch(refreshTickProvider);
  final id = ref.watch(currentRunIdProvider);
  final q = ref.watch(alertQueryProvider);
  if (id == null) return Future.value(null);
  return ref.watch(apiProvider).alerts(id, {
    'severity': q.severity,
    'state': q.state,
    'decision': q.decision,
    'page': q.page,
    'page_size': 12,
  });
});

class SelectedAlert extends Notifier<int?> {
  @override
  int? build() {
    ref.watch(currentRunIdProvider);
    return int.tryParse(Uri.base.queryParameters['alert'] ?? ''); // `?alert=<flow id>` deep link
  }

  void select(int? id) => state = id;
}

final selectedAlertProvider = NotifierProvider<SelectedAlert, int?>(SelectedAlert.new);

final alertDetailProvider = FutureProvider<Json?>((ref) {
  final id = ref.watch(currentRunIdProvider);
  final flowId = ref.watch(selectedAlertProvider);
  if (id == null || flowId == null) return Future.value(null);
  return ref.watch(apiProvider).alertDetail(id, flowId);
});

class AlertsPage extends ConsumerWidget {
  const AlertsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RunGuard(
      title: 'Alerts',
      subtitle: 'Review detections, prioritize risk, and inspect model evidence',
      builder: (run) {
        final s = ref.watch(alertSummaryProvider).value ?? const {};
        return [
          StatRow(
            cards: [
              StatCard(
                label: 'Open alerts',
                value: fmtInt(s['open'] as num?),
                caption: 'Needs triage',
                color: AppColors.red,
              ),
              StatCard(
                label: 'Critical',
                value: fmtInt(s['critical'] as num?),
                caption: 'Attack score ≥ 0.90, unresolved',
                color: AppColors.red,
              ),
              StatCard(
                label: 'Under review',
                value: fmtInt(s['under_review'] as num?),
                caption: 'Uncertain / unknown',
                color: AppColors.orange,
              ),
              StatCard(
                label: 'Resolved today',
                value: fmtInt(s['resolved_today'] as num?),
                caption: 'Closed by triage',
                color: AppColors.green,
              ),
            ],
          ),
          const _AlertQueue(),
          const _SelectedAlert(),
        ];
      },
    );
  }
}

class _AlertQueue extends ConsumerWidget {
  const _AlertQueue();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final q = ref.watch(alertQueryProvider);
    final setQ = ref.read(alertQueryProvider.notifier).set;
    final page = ref.watch(alertsPageProvider);
    final selected = ref.watch(selectedAlertProvider);
    final utc = ref.watch(settingsProvider).utc;
    final classes = asJson(
      ref.watch(classDistributionProvider).value?['decision'],
    ).keys.where((k) => !isBenignLabel(k)).toList()..sort();
    return Panel(
      title: 'Alert queue',
      trailing: Wrap(
        spacing: 12,
        children: [
          DropdownFilter<String?>(
            label: 'Severity',
            value: q.severity,
            options: const {
              null: 'All',
              'critical': 'Critical',
              'high': 'High',
              'medium': 'Medium',
              'low': 'Low',
              'review': 'Review (unknown)',
            },
            onChanged: (v) => setQ(q.copy(severity: v)),
          ),
          DropdownFilter<String?>(
            label: 'Status',
            value: q.state,
            options: const {null: 'All', 'open': 'Open', 'investigating': 'Investigating', 'resolved': 'Resolved'},
            onChanged: (v) => setQ(q.copy(state: v)),
          ),
          DropdownFilter<String?>(
            label: 'Predicted class',
            value: q.decision,
            options: {null: 'All', for (final c in classes) c: decisionText(c)},
            onChanged: (v) => setQ(q.copy(decision: v)),
          ),
        ],
      ),
      child: AsyncView(
        value: page,
        builder: (p) {
          final items = p?.items ?? const <Alert>[];
          return Column(
            children: [
              SentinelTable(
                columns: const [
                  TableCol('Alert ID'),
                  TableCol('Time'),
                  TableCol('Predicted class', flex: 2),
                  TableCol('Source flow'),
                  TableCol('Severity'),
                  TableCol('Confidence'),
                  TableCol('State'),
                ],
                emptyText: 'No alerts match these filters',
                selected: items.indexWhere((a) => a.flowId == selected),
                onTap: (i) => ref.read(selectedAlertProvider.notifier).select(items[i].flowId),
                rows: [
                  for (final a in items)
                    [
                      Text(a.alertId),
                      Text(fmtTime(a.timestamp, utc: utc)),
                      decisionLabel(a.decision),
                      Text('Flow #${a.flowId}'),
                      severityLabel(a.severity),
                      // 4 decimals: boosted models are near 1.0 even when a flow is flagged UNKNOWN.
                      Text(fmtNum(a.confidence, 4)),
                      alertStateLabel(a.state),
                    ],
                ],
              ),
              if (p != null)
                Pager(
                  page: p.page,
                  pages: p.pages,
                  total: p.total,
                  onPage: (n) => setQ(q.copy(page: n)),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _SelectedAlert extends ConsumerStatefulWidget {
  const _SelectedAlert();

  @override
  ConsumerState<_SelectedAlert> createState() => _SelectedAlertState();
}

class _SelectedAlertState extends ConsumerState<_SelectedAlert> {
  final _note = TextEditingController();
  bool _saving = false;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _setState(String runId, int flowId, String state) async {
    setState(() => _saving = true);
    try {
      await ref
          .read(apiProvider)
          .updateAlert(runId, flowId, state, _note.text.trim().isEmpty ? null : _note.text.trim());
      _note.clear();
      ref.invalidate(alertDetailProvider);
      ref.invalidate(alertsPageProvider);
      ref.invalidate(alertSummaryProvider);
      ref.invalidate(recentAlertsProvider);
      if (mounted) showSnack(context, 'Alert marked ${titleCase(state)}');
    } catch (e) {
      if (mounted) showSnack(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final detail = ref.watch(alertDetailProvider);
    final runId = ref.watch(currentRunIdProvider);
    final utc = ref.watch(settingsProvider).utc;
    if (ref.watch(selectedAlertProvider) == null) {
      return const Panel(
        title: 'Selected alert',
        subtitle: 'Choose a row to inspect flow features, model score, and review history.',
        child: SizedBox(),
      );
    }
    return Panel(
      title: 'Selected alert',
      child: AsyncView(
        value: detail,
        builder: (d) {
          if (d == null) return const SizedBox();
          final alert = Alert(d['alert']);
          final flow = NetFlow(d['flow']);
          final history = asJsonList(d['history']);
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Text(alert.alertId, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
                  const SizedBox(width: 14),
                  severityLabel(alert.severity),
                  const SizedBox(width: 14),
                  alertStateLabel(alert.state),
                  const Spacer(),
                  SizedBox(
                    width: 280,
                    child: TextField(
                      controller: _note,
                      style: const TextStyle(fontSize: 13),
                      decoration: const InputDecoration(hintText: 'Triage note (optional)'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  for (final (state, label, icon) in [
                    ('investigating', 'Investigate', Icons.manage_search),
                    ('resolved', 'Resolve', Icons.check),
                    ('open', 'Reopen', Icons.replay),
                  ])
                    if (alert.state != state)
                      Padding(
                        padding: const EdgeInsets.only(left: 8),
                        child: OutlinedButton.icon(
                          onPressed: _saving ? null : () => _setState(runId!, alert.flowId, state),
                          icon: Icon(icon, size: 16),
                          label: Text(label),
                        ),
                      ),
                ],
              ),
              const SizedBox(height: 16),
              FlowEvidence(flow: flow, utc: utc),
              const SizedBox(height: 16),
              Text('REVIEW HISTORY', style: TextStyles.label),
              const SizedBox(height: 6),
              if (history.isEmpty) Text('No triage actions yet.', style: TextStyles.secondary),
              for (final h in history)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Text(
                    '${fmtTime(h['at'], utc: utc, withDate: true)} · ${h['updated_by']}: '
                    '${titleCase('${h['from_state']}')} → ${titleCase('${h['to_state']}')}'
                    '${h['note'] == null ? '' : ' — "${h['note']}"'}',
                    style: TextStyles.secondary,
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}
