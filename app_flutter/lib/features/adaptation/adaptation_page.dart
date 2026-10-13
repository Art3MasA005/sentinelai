import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/format.dart';
import '../../core/run_guard.dart';
import '../../core/state.dart';
import '../../core/status.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

const _modelNames = {
  'hist_gb': 'HistGB',
  'lightgbm': 'LGBM',
  'random_forest': 'RF',
  'xgboost': 'XGB',
  'logreg': 'LogReg',
};

/// One candidate model and how its update ended (the final decision wins over "proposed").
class _Update {
  _Update(this.event, this.proposed);
  final Json event;
  final Json? proposed;

  String get decision => event['decision'] as String;
  int get window => event['window'] as int;
  int? get fromVersion => asInt(event['from_version']);
  int? get toVersion => asInt(event['to_version']);
  Json get validation => asJson(event['validation']);
  Json get cost => asJson(event['cost']).isNotEmpty ? asJson(event['cost']) : asJson(proposed?['cost']);
  double? get gain => asDouble(validation['gain']);
  String get trigger => event['trigger'] as String? ?? '';
}

List<_Update> _updates(List<Json> events) {
  final proposed = <int?, Json>{};
  final out = <_Update>[];
  for (final e in events) {
    if (e['decision'] == 'proposed') {
      proposed[asInt(e['to_version'])] = e;
      continue;
    }
    out.add(_Update(e, proposed.remove(asInt(e['to_version']))));
  }
  // Candidates still waiting for a decision (only possible while a run is in progress).
  for (final p in proposed.values) {
    out.add(_Update(p, p));
  }
  out.sort((a, b) => (b.event['event_id'] as String).compareTo(a.event['event_id'] as String));
  return out;
}

String _triggerText(String t) {
  if (t.isEmpty) return '—';
  return t
      .split(',')
      .map((p) {
        if (p.startsWith('drift-')) {
          final parts = p.split('-'); // drift-00012-ks
          return 'Drift (${parts.length > 2 ? parts[2].toUpperCase() : '?'}) · window ${int.tryParse(parts[1]) ?? parts[1]}';
        }
        if (p.startsWith('novelty@')) return 'Novelty spike · ${p.substring(p.indexOf('(') + 1).replaceAll(')', '')}';
        if (p == 'schedule') return 'Scheduled retrain';
        if (p == 'new_labels') return 'New labels arrived';
        return p;
      })
      .join('  +  ');
}

class AdaptationPage extends ConsumerWidget {
  const AdaptationPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RunGuard(
      title: 'Adaptation Center',
      subtitle: 'Inspect risk-gated updates, validation outcomes, and model version history',
      builder: (run) {
        final events = ref.watch(adaptationEventsProvider).value?.items ?? const <Json>[];
        final models = ref.watch(modelVersionsProvider).value ?? const <Json>[];
        final count = {
          for (final d in ['proposed', 'accepted', 'rejected', 'rollback']) d: 0,
        };
        for (final e in events) {
          count[e['decision'] as String] = (count[e['decision']] ?? 0) + 1;
        }
        final candidates = math.max(0, models.length - 1);
        final updates = _updates(events);
        final modelName = _modelNames[asJson(run.config['model'])['kind']] ?? 'Model';
        final adaptCfg = asJson(run.config['adaptation']);
        return [
          if (run.method == 'static')
            const Panel(
              child: EmptyState(
                'The static baseline never adapts: it is trained once and uses no labels. '
                'Pick an adaptive run in the run selector to see updates here.',
                icon: Icons.lock_outline,
              ),
            ),
          StatRow(
            cards: [
              StatCard(
                label: 'Proposed updates',
                value: fmtInt(candidates),
                caption: 'Candidate models trained',
                color: AppColors.orange,
              ),
              StatCard(
                label: 'Accepted',
                value: fmtInt(count['accepted']),
                caption: const {'guarded_selective', 'nova'}.contains(run.method)
                    ? 'Passed validation'
                    : 'Deployed by schedule',
                color: AppColors.green,
              ),
              StatCard(
                label: 'Rejected',
                value: fmtInt(count['rejected']),
                caption: 'Risk gate blocked',
                color: AppColors.red,
              ),
              StatCard(
                label: 'Rolled back',
                value: fmtInt(count['rollback']),
                caption: 'Degradation detected',
                color: AppColors.purple,
              ),
            ],
          ),
          ResponsiveRow(
            flex: const [3, 2],
            children: [
              _CurrentCandidate(update: updates.firstOrNull, modelName: modelName),
              _RiskGate(
                update: updates.firstOrNull,
                maxForgetting: asDouble(adaptCfg['max_forgetting']) ?? 0.05,
                models: models,
              ),
            ],
          ),
          _History(updates: updates, modelName: modelName),
          _Versions(models: models, modelName: modelName),
        ];
      },
    );
  }
}

Widget _decisionPill(String decision) => switch (decision) {
  'accepted' => Pill('Accepted', color: AppColors.green, icon: Icons.check_circle_outline),
  'rejected' => Pill('Rejected', color: AppColors.red, icon: Icons.block),
  'rollback' => Pill('Rolled back', color: AppColors.purple, icon: Icons.undo),
  _ => Pill('Pending validation', color: AppColors.orange, icon: Icons.hourglass_top),
};

class _CurrentCandidate extends StatelessWidget {
  const _CurrentCandidate({required this.update, required this.modelName});
  final _Update? update;
  final String modelName;

  @override
  Widget build(BuildContext context) {
    final u = update;
    if (u == null) {
      return const Panel(title: 'Current candidate update', child: EmptyState('No updates proposed in this run.'));
    }
    final isRollback = u.decision == 'rollback';
    final v = u.validation;
    return Panel(
      title: 'Latest candidate update',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          KeyValueRow(
            isRollback ? 'Rolled back from' : 'Candidate model',
            '$modelName-${isRollback ? 'v${u.fromVersion}' : 'adapt-v${u.toVersion}'}',
          ),
          KeyValueRow(
            isRollback ? 'Restored version' : 'Source version',
            '$modelName-v${isRollback ? u.toVersion : u.fromVersion}',
          ),
          KeyValueRow(
            'Update trigger',
            '${_triggerText(u.trigger)}  ·  decided at window ${u.window}',
            valueColor: AppColors.orange,
          ),
          KeyValueRow(
            'Validation status',
            '',
            trailing: Align(alignment: Alignment.centerLeft, child: _decisionPill(u.decision)),
          ),
          KeyValueRow('Reason', u.event['reason'] as String? ?? '—'),
          if (v['recent_f1_candidate'] != null)
            KeyValueRow(
              'Hold-out macro-F1',
              '${fmtNum(v['recent_f1_current'] as num?)} → ${fmtNum(v['recent_f1_candidate'] as num?)}  '
                  '(${fmtSigned(u.gain)})',
            ),
          if (v['ref_f1_candidate'] != null)
            KeyValueRow(
              'Reference macro-F1',
              '${fmtNum(v['ref_f1_current'] as num?)} → ${fmtNum(v['ref_f1_candidate'] as num?)}',
            ),
          const SizedBox(height: 12),
          Text(
            'Offline replay: decisions were made by the adaptation policy during the run; this page only inspects them.',
            style: TextStyles.secondary,
          ),
        ],
      ),
    );
  }
}

class _RiskGate extends StatelessWidget {
  const _RiskGate({required this.update, required this.maxForgetting, required this.models});
  final _Update? update;
  final double maxForgetting;
  final List<Json> models;

  @override
  Widget build(BuildContext context) {
    final u = update;
    final v = u?.validation ?? const <String, dynamic>{};
    // Drift magnitude: strongest detector score relative to its threshold (100% = 2x threshold).
    final drift = asJson(v['drift_scores']).values
        .map(asJson)
        .map((d) {
          final s = asDouble(d['score']), t = asDouble(d['threshold']);
          return s == null || t == null || t == 0 ? 0.0 : s / t;
        })
        .fold<double>(0, math.max);
    final forgetting = asDouble(v['forgetting']);
    final trainS = asDouble(u?.cost['train_seconds']);
    final maxTrain = models.map((m) => asDouble(m['train_seconds']) ?? 0).fold<double>(0, math.max);
    final hold = asDouble(v['recent_f1_candidate']);
    return Panel(
      title: 'Risk gate signals',
      subtitle: u == null ? null : 'For the latest candidate (window ${u.window})',
      child: Column(
        children: [
          Meter(
            label: 'Drift magnitude',
            value: drift == 0 ? null : drift / 2,
            color: AppColors.purple,
            valueText: drift == 0
                ? (u == null ? '—' : 'Not drift-triggered')
                : '${drift.toStringAsFixed(2)}× threshold',
          ),
          const SizedBox(height: 18),
          Meter(
            label: 'Candidate hold-out macro-F1',
            value: hold,
            color: AppColors.blue,
            valueText: hold == null ? '—' : fmtNum(hold),
          ),
          const SizedBox(height: 18),
          Meter(
            label: 'Reference performance risk',
            value: forgetting == null ? null : (forgetting / maxForgetting).clamp(0, 1),
            color: (forgetting ?? 0) > maxForgetting ? AppColors.red : AppColors.green,
            valueText: forgetting == null
                ? '—'
                : '${fmtPp(forgetting)}${forgetting < 0 ? ' (improved)' : ''} / max ${fmtPp(maxForgetting)}',
          ),
          const SizedBox(height: 18),
          Meter(
            label: 'Update cost (training time)',
            value: trainS == null || maxTrain == 0 ? null : trainS / maxTrain,
            color: AppColors.orange,
            valueText: trainS == null ? '—' : '${fmtSeconds(trainS)} · ${fmtInt(asInt(u?.cost['train_rows']))} rows',
          ),
        ],
      ),
    );
  }
}

class _History extends StatelessWidget {
  const _History({required this.updates, required this.modelName});
  final List<_Update> updates;
  final String modelName;

  @override
  Widget build(BuildContext context) {
    return Panel(
      title: 'Update history',
      subtitle: 'Newest first. Validation delta = candidate minus current macro-F1 on the newest labelled window.',
      child: SentinelTable(
        columns: const [
          TableCol('Version'),
          TableCol('Window'),
          TableCol('Decision'),
          TableCol('Validation delta'),
          TableCol('Runtime'),
          TableCol('Labels used'),
          TableCol('Reason', flex: 3),
        ],
        emptyText: 'No adaptation events in this run',
        rows: [
          for (final u in updates)
            [
              Text(u.decision == 'rollback' ? 'v${u.fromVersion} → v${u.toVersion}' : 'v${u.toVersion ?? '—'}'),
              Text('W${u.window}'),
              adaptationDecisionLabel(u.decision),
              Text(
                u.gain == null
                    ? (u.decision == 'accepted' ? 'Not gated' : '—')
                    : '${u.gain! >= 0 ? '+' : ''}${fmtPp(u.gain)}',
                style: TextStyle(
                  color: u.gain == null
                      ? AppColors.textSecondary
                      : u.gain! >= 0
                      ? AppColors.green
                      : AppColors.red,
                ),
              ),
              Text(fmtSeconds(asDouble(u.cost['train_seconds']))),
              Text(fmtInt(asInt(u.cost['labels_used_total']))),
              Text(u.event['reason'] as String? ?? '', overflow: TextOverflow.ellipsis),
            ],
        ],
      ),
    );
  }
}

class _Versions extends StatelessWidget {
  const _Versions({required this.models, required this.modelName});
  final List<Json> models;
  final String modelName;

  Widget _status(String s) => switch (s) {
    'active' => StatusLabel('Active', color: AppColors.green, icon: Icons.play_circle_outline),
    'retired' => StatusLabel('Retired', color: AppColors.textSecondary, icon: Icons.history),
    'rejected' => StatusLabel('Rejected', color: AppColors.red, icon: Icons.block),
    'rolled_back' => StatusLabel('Rolled back', color: AppColors.purple, icon: Icons.undo),
    _ => StatusLabel('Candidate', color: AppColors.orange, icon: Icons.pending_outlined),
  };

  @override
  Widget build(BuildContext context) {
    return Panel(
      title: 'Model versions',
      subtitle: 'Every trained model, its parent and the classes it knows',
      child: SentinelTable(
        columns: const [
          TableCol('Model'),
          TableCol('Parent'),
          TableCol('Created'),
          TableCol('Status'),
          TableCol('Train rows'),
          TableCol('Size'),
          TableCol('Classes', flex: 3),
        ],
        rows: [
          for (final m in models.reversed)
            [
              Text('$modelName-v${m['version']}', style: const TextStyle(fontWeight: FontWeight.w700)),
              Text(m['parent_version'] == null ? '—' : 'v${m['parent_version']}'),
              Text((m['created_window'] as int) < 0 ? 'Training' : 'W${m['created_window']}'),
              _status(m['status'] as String),
              Text(fmtInt(asInt(m['train_rows']))),
              Text(fmtBytes(asInt(m['model_bytes']))),
              Text(((m['classes'] as List?) ?? const []).join(', '), overflow: TextOverflow.ellipsis),
            ],
        ],
      ),
    );
  }
}
