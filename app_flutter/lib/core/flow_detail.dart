import 'package:flutter/material.dart';

import 'api/models.dart';
import 'format.dart';
import 'status.dart';
import 'theme.dart';
import 'widgets.dart';

/// Model evidence for one flow: decision, uncertainty, top probabilities and raw features.
class FlowEvidence extends StatelessWidget {
  const FlowEvidence({super.key, required this.flow, this.utc = false});
  final NetFlow flow;
  final bool utc;

  @override
  Widget build(BuildContext context) {
    final probs = flow.probabilities.entries.toList()..sort((a, b) => (b.value as num).compareTo(a.value as num));
    final feats = flow.features?.entries.toList() ?? const [];
    return ResponsiveRow(
      breakpoint: 900,
      flex: const [2, 2, 3],
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('DECISION', style: TextStyles.label),
            const SizedBox(height: 6),
            KeyValueRow('Reported', '', trailing: decisionLabel(flow.decision), labelWidth: 120),
            KeyValueRow('Model top class', flow.predicted, labelWidth: 120),
            KeyValueRow('Confidence', fmtNum(flow.confidence, 4), labelWidth: 120),
            KeyValueRow('Attack score', fmtNum(flow.attackScore, 4), labelWidth: 120),
            KeyValueRow('Novelty score', fmtNum(flow.noveltyScore, 3), labelWidth: 120),
            if (flow.isUnknown)
              KeyValueRow(
                'Why unknown',
                (flow.unknownReason ?? '').replaceAll('_', ' '),
                valueColor: AppColors.orange,
                labelWidth: 120,
              ),
            KeyValueRow('Model version', 'v${flow.modelVersion}', labelWidth: 120),
            KeyValueRow(
              'Window · time',
              'W${flow.window} · ${fmtTime(flow.timestamp, utc: utc, withDate: true)}',
              labelWidth: 120,
            ),
            KeyValueRow(
              'Source → dest',
              '${flow.src ?? '—'} → ${flow.dst ?? '—'} (${flow.protocol ?? '—'})',
              labelWidth: 120,
            ),
            const SizedBox(height: 10),
            Tooltip(
              message: 'Ground truth is used only for evaluation; adaptation never reads it directly.',
              child: Row(
                children: [
                  Icon(Icons.fact_check_outlined, size: 14, color: AppColors.textSecondary),
                  const SizedBox(width: 6),
                  Text(
                    'Evaluation label: ${flow.trueLabel}${flow.isNovelClass ? '  (unseen by this model)' : ''}',
                    style: TextStyles.secondary,
                  ),
                ],
              ),
            ),
          ],
        ),
        Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('CLASS PROBABILITIES', style: TextStyles.label),
            const SizedBox(height: 10),
            for (final p in probs)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Meter(
                  label: p.key,
                  value: (p.value as num).toDouble(),
                  color: decisionColor(p.key),
                  valueText: fmtNum(p.value as num, 4),
                ),
              ),
            if (flow.isUnknown)
              Text(
                'UNKNOWN = unfamiliar or uncertain for the deployed model. It needs review; it is not a malicious verdict.',
                style: TextStyle(color: AppColors.orange, fontSize: 12),
              ),
          ],
        ),
        Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('FEATURES (${feats.length})', style: TextStyles.label),
            const SizedBox(height: 6),
            if (feats.isEmpty) Text('Features were not stored for this run.', style: TextStyles.secondary),
            Wrap(
              children: [
                for (final f in feats)
                  SizedBox(
                    width: 230,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(4, 5, 22, 5),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              f.key,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(color: AppColors.textSecondary, fontSize: 12),
                            ),
                          ),
                          Text(f.value is num ? _num(f.value as num) : '${f.value}', style: TextStyles.mono),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ],
    );
  }

  static String _num(num v) => v == v.roundToDouble() && v.abs() < 1e12 ? v.toInt().toString() : v.toStringAsFixed(3);
}
