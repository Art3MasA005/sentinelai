import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api/models.dart';
import 'state.dart';
import 'theme.dart';
import 'widgets.dart';

/// Renders [builder] for the current run, or a loading / offline / "no run yet" state.
class RunGuard extends ConsumerWidget {
  const RunGuard({super.key, required this.title, required this.subtitle, required this.builder});
  final String title;
  final String subtitle;
  final List<Widget> Function(Run run) builder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runs = ref.watch(runsProvider);
    final run = ref.watch(currentRunProvider);
    final List<Widget> body;
    if (!runs.hasValue && runs.hasError) {
      body = [Panel(child: ErrorNote(runs.error!))];
    } else if (!runs.hasValue) {
      body = [const SizedBox(height: 200, child: Center(child: CircularProgressIndicator(strokeWidth: 2)))];
    } else if (run == null) {
      body = [NoRunPlaceholder(onCreate: () => ref.read(navProvider.notifier).go(AppPage.experiments))];
    } else {
      body = [
        if (run.isDemo) const _DemoBanner(),
        if (run.status == 'failed') Panel(child: ErrorNote('Run failed: ${run.error ?? 'see logs'}')),
        ...builder(run),
      ];
    }
    return PageScaffold(title: title, subtitle: subtitle, children: body);
  }
}

class _DemoBanner extends StatelessWidget {
  const _DemoBanner();

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    decoration: BoxDecoration(
      color: AppColors.demoSurface,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: AppColors.orange.withValues(alpha: 0.4)),
    ),
    child: Row(
      children: [
        DemoBadge(compact: true),
        SizedBox(width: 12),
        Expanded(
          child: Text(
            'This run uses synthetic DEMO data. Values illustrate the pipeline only and are not research results.',
            style: TextStyle(color: AppColors.orange, fontSize: 12.5),
          ),
        ),
      ],
    ),
  );
}
