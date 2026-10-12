import 'package:flutter/material.dart';

import 'theme.dart';
import 'widgets.dart';

/// Maps backend values to the colour + icon + word used across screens.
/// UNKNOWN is always shown as "Review" (orange): unfamiliar/uncertain, never "malicious".
bool isBenignLabel(String label) => label.toUpperCase() == 'BENIGN' || label == 'Normal' || label == 'Benign';

Color decisionColor(String decision) {
  if (decision == 'UNKNOWN') return AppColors.orange;
  if (isBenignLabel(decision)) return AppColors.green;
  return AppColors.red;
}

String decisionText(String decision) => decision == 'UNKNOWN' ? 'Unknown' : decision;

Widget decisionLabel(String decision) => StatusLabel(
  decisionText(decision),
  color: decisionColor(decision),
  icon: decision == 'UNKNOWN'
      ? Icons.help_outline
      : isBenignLabel(decision)
      ? Icons.check_circle_outline
      : Icons.warning_amber_rounded,
);

/// The "review" column in flow tables: Review / Alert / Normal.
Widget reviewLabel(String decision) {
  if (decision == 'UNKNOWN') return StatusLabel('Review', color: AppColors.orange, icon: Icons.visibility_outlined);
  if (isBenignLabel(decision)) return StatusLabel('Normal', color: AppColors.green, icon: Icons.check);
  return StatusLabel('Alert', color: AppColors.red, icon: Icons.notification_important_outlined);
}

Map<String, Color> get severityColors => {
  'critical': AppColors.red,
  'high': AppColors.orange,
  'medium': AppColors.yellow,
  'low': AppColors.blue,
  'review': AppColors.orange,
};

Widget severityLabel(String s) => StatusLabel(
  s == 'review' ? 'Review' : s[0].toUpperCase() + s.substring(1),
  color: severityColors[s] ?? AppColors.textSecondary,
  icon: s == 'review' ? Icons.help_outline : Icons.priority_high_rounded,
);

Widget alertStateLabel(String s) => switch (s) {
  'open' => StatusLabel('Open', color: AppColors.orange, icon: Icons.radio_button_unchecked),
  'investigating' => StatusLabel('Investigating', color: AppColors.blue, icon: Icons.manage_search),
  'resolved' => StatusLabel('Resolved', color: AppColors.green, icon: Icons.check_circle_outline),
  _ => StatusLabel(s, color: AppColors.textSecondary),
};

Color runStatusColor(String s) => switch (s) {
  'completed' => AppColors.green,
  'running' => AppColors.orange,
  'paused' => AppColors.blue,
  'queued' => AppColors.cyan,
  'failed' => AppColors.red,
  'cancelled' => AppColors.textSecondary,
  _ => AppColors.purple,
};

Widget runStatusLabel(String s) => StatusLabel(
  s[0].toUpperCase() + s.substring(1),
  color: runStatusColor(s),
  icon: switch (s) {
    'completed' => Icons.check_circle_outline,
    'running' => Icons.play_circle_outline,
    'paused' => Icons.pause_circle_outline,
    'queued' => Icons.schedule,
    'failed' => Icons.error_outline,
    'cancelled' => Icons.cancel_outlined,
    _ => Icons.fiber_new_outlined,
  },
);

Widget adaptationDecisionLabel(String d) => switch (d) {
  'accepted' => StatusLabel('Accepted', color: AppColors.green, icon: Icons.check_circle_outline),
  'rejected' => StatusLabel('Rejected', color: AppColors.red, icon: Icons.block),
  'rollback' => StatusLabel('Rolled back', color: AppColors.purple, icon: Icons.undo),
  'proposed' => StatusLabel('Proposed', color: AppColors.orange, icon: Icons.pending_outlined),
  _ => StatusLabel(d, color: AppColors.textSecondary),
};
