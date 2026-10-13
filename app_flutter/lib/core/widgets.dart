import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api/api_client.dart';
import 'glass_menu.dart';
import 'theme.dart';
import 'toast.dart';

// ---------------------------------------------------------------- layout

class PageScaffold extends StatelessWidget {
  const PageScaffold({super.key, required this.title, required this.subtitle, required this.children});
  final String title;
  final String subtitle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(28, 4, 28, 28),
      children: [
        Text(title, style: TextStyles.pageTitle),
        const SizedBox(height: 6),
        Text(subtitle, style: TextStyles.pageSubtitle),
        const SizedBox(height: 18),
        for (final (i, c) in children.indexed) ...[if (i > 0) const SizedBox(height: 18), c],
      ],
    );
  }
}

/// Lays children out in a row with the given flex weights; stacks them on narrow windows.
class ResponsiveRow extends StatelessWidget {
  const ResponsiveRow({
    super.key,
    required this.children,
    this.flex,
    this.breakpoint = 1000,
    this.gap = 18,
    this.equalHeight = false,
  });
  final List<Widget> children;
  final List<int>? flex;
  final double breakpoint;
  final double gap;

  /// Stretch children to the tallest one. Only for children without LayoutBuilder (e.g. not charts).
  final bool equalHeight;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, c) {
        if (c.maxWidth < breakpoint) {
          return Column(
            children: [
              for (final (i, w) in children.indexed) ...[if (i > 0) SizedBox(height: gap), w],
            ],
          );
        }
        final row = Row(
          crossAxisAlignment: equalHeight ? CrossAxisAlignment.stretch : CrossAxisAlignment.start,
          children: [
            for (final (i, w) in children.indexed) ...[
              if (i > 0) SizedBox(width: gap),
              Expanded(flex: flex?[i] ?? 1, child: w),
            ],
          ],
        );
        return equalHeight ? IntrinsicHeight(child: row) : row;
      },
    );
  }
}

class Panel extends StatelessWidget {
  const Panel({super.key, this.title, this.subtitle, this.trailing, required this.child, this.padding});
  final String? title;
  final String? subtitle;
  final Widget? trailing;
  final Widget child;
  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) {
    return Glass(
      radius: AppColors.isGlass ? 16 : 12,
      padding: padding ?? const EdgeInsets.fromLTRB(20, 18, 20, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (title != null) ...[
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title!, style: TextStyles.panelTitle),
                      if (subtitle != null) ...[
                        const SizedBox(height: 4),
                        Text(subtitle!, style: TextStyles.secondary),
                      ],
                    ],
                  ),
                ),
                if (trailing != null)
                  Flexible(
                    child: Align(alignment: Alignment.centerRight, child: trailing),
                  ),
              ],
            ),
            const SizedBox(height: 16),
          ],
          child,
        ],
      ),
    );
  }
}

class StatCard extends StatelessWidget {
  const StatCard({super.key, required this.label, required this.value, this.caption, this._color});
  final String label;
  final String value;
  final String? caption;
  final Color? _color;
  Color get color => _color ?? AppColors.blue;

  @override
  Widget build(BuildContext context) {
    return Glass(
      radius: AppColors.isGlass ? 14 : 10,
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(), style: TextStyles.label, maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 10),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              value,
              style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800, color: color, height: 1),
            ),
          ),
          const SizedBox(height: 8),
          Text(caption ?? '', style: TextStyles.secondary, maxLines: 1, overflow: TextOverflow.ellipsis),
        ],
      ),
    );
  }
}

class StatRow extends StatelessWidget {
  const StatRow({super.key, required this.cards});
  final List<StatCard> cards;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, c) {
        const gap = 18.0, minCard = 210.0;
        final perRow = ((c.maxWidth + gap) ~/ (minCard + gap)).clamp(1, cards.length);
        if (perRow == cards.length) return ResponsiveRow(breakpoint: 0, equalHeight: true, children: cards);
        // Too narrow for one row: wrap into a grid of equal-width cards.
        final width = (c.maxWidth - gap * (perRow - 1)) / perRow;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [for (final card in cards) SizedBox(width: width, child: card)],
        );
      },
    );
  }
}

// ---------------------------------------------------------------- status & labels

/// Coloured text that always carries a word and an icon, so status is never conveyed by colour alone.
class StatusLabel extends StatelessWidget {
  const StatusLabel(this.text, {super.key, required this.color, this.icon});
  final String text;
  final Color color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (icon != null) ...[Icon(icon, size: 13, color: color), const SizedBox(width: 5)],
        Flexible(
          child: Text(
            text,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12.5),
          ),
        ),
      ],
    );
  }
}

class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, required this.color, this.icon, this.filled = false});
  final String text;
  final Color color;
  final IconData? icon;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: filled ? color : color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: filled ? 1 : 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 13, color: filled ? AppColors.background : color),
            const SizedBox(width: 5),
          ],
          Text(
            text,
            style: TextStyle(color: filled ? AppColors.background : color, fontSize: 11.5, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

/// Persistent DEMO marker required by the PRD for synthetic data.
class DemoBadge extends StatelessWidget {
  const DemoBadge({super.key, this.compact = false});
  final bool compact;

  @override
  Widget build(BuildContext context) => Tooltip(
    message: 'Synthetic DEMO data — results must not be reported as real-traffic results.',
    child: Pill(compact ? 'DEMO' : 'DEMO DATA', color: AppColors.orange, icon: Icons.science_outlined),
  );
}

class Meter extends StatelessWidget {
  const Meter({super.key, required this.label, required this.value, required this.color, this.valueText});
  final String label;
  final double? value; // 0..1
  final Color color;
  final String? valueText;

  @override
  Widget build(BuildContext context) {
    final v = (value ?? 0).clamp(0.0, 1.0);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(label, style: TextStyle(color: AppColors.textSecondary, fontSize: 13)),
            ),
            Text(
              valueText ?? (value == null ? '—' : '${(v * 100).round()}%'),
              style: TextStyle(color: AppColors.text, fontSize: 12.5),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(
            value: v,
            minHeight: 9,
            backgroundColor: AppColors.track,
            valueColor: AlwaysStoppedAnimation(color),
          ),
        ),
      ],
    );
  }
}

class KeyValueRow extends StatelessWidget {
  const KeyValueRow(this.label, this.value, {super.key, this.valueColor, this.trailing, this.labelWidth = 170});
  final String label;
  final String value;
  final Color? valueColor;
  final Widget? trailing;
  final double labelWidth;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 11),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Row(
        children: [
          SizedBox(
            width: labelWidth,
            child: Text(label, style: TextStyle(color: AppColors.textSecondary, fontSize: 13)),
          ),
          Expanded(
            child:
                trailing ??
                Text(
                  value,
                  style: TextStyle(color: valueColor ?? AppColors.text, fontWeight: FontWeight.w700, fontSize: 13.5),
                ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- table

class TableCol {
  const TableCol(this.label, {this.flex = 1, this.numeric = false, this.width});
  final String label;
  final int flex;
  final bool numeric;

  /// Fixed width in pixels (e.g. a checkbox column); overrides [flex].
  final double? width;
}

class SentinelTable extends StatelessWidget {
  const SentinelTable({
    super.key,
    required this.columns,
    required this.rows,
    this.onTap,
    this.selected,
    this.emptyText = 'No rows',
    this.rowHeight = 46,
  });

  final List<TableCol> columns;
  final List<List<Widget>> rows;
  final void Function(int index)? onTap;
  final int? selected;
  final String emptyText;
  final double rowHeight;

  Widget _cell(TableCol c, Widget w) {
    final child = Align(alignment: Alignment.centerLeft, child: w);
    return c.width != null ? SizedBox(width: c.width, child: child) : Expanded(flex: c.flex, child: child);
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          height: 38,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(color: AppColors.tableHeader, borderRadius: BorderRadius.circular(6)),
          child: Row(
            children: [
              for (final c in columns)
                _cell(c, Text(c.label.toUpperCase(), style: TextStyles.label.copyWith(fontSize: 10.5))),
            ],
          ),
        ),
        if (rows.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 28),
            child: Center(child: Text(emptyText, style: TextStyles.secondary)),
          ),
        for (final (i, r) in rows.indexed)
          Material(
            color: i == selected
                ? AppColors.navActive
                : i.isOdd
                ? AppColors.rowAlt
                : Colors.transparent,
            child: InkWell(
              onTap: onTap == null ? null : () => onTap!(i),
              child: Container(
                height: rowHeight,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                decoration: BoxDecoration(
                  border: Border(bottom: BorderSide(color: AppColors.border, width: 0.6)),
                ),
                child: Row(
                  children: [
                    for (final (j, c) in columns.indexed)
                      _cell(
                        c,
                        DefaultTextStyle.merge(style: TextStyles.mono, child: j < r.length ? r[j] : const SizedBox()),
                      ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class Pager extends StatelessWidget {
  const Pager({super.key, required this.page, required this.pages, required this.total, required this.onPage});
  final int page;
  final int pages;
  final int total;
  final ValueChanged<int> onPage;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Row(
        children: [
          Text('$total rows', style: TextStyles.secondary),
          const Spacer(),
          IconButton(
            tooltip: 'Previous page',
            onPressed: page > 1 ? () => onPage(page - 1) : null,
            icon: const Icon(Icons.chevron_left),
          ),
          Text('Page $page of $pages', style: TextStyles.secondary),
          IconButton(
            tooltip: 'Next page',
            onPressed: page < pages ? () => onPage(page + 1) : null,
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- inputs

/// Filter select used in panel headers; a [GlassSelect] (rounded frosted-glass menu).
class DropdownFilter<T> extends StatelessWidget {
  const DropdownFilter({
    super.key,
    required this.label,
    required this.value,
    required this.options,
    required this.onChanged,
    this.width = 170,
  });
  final String label;
  final T value;
  final Map<T, String> options;
  final ValueChanged<T> onChanged;
  final double width;

  @override
  Widget build(BuildContext context) =>
      GlassSelect<T>(label: label, value: value, options: options, onChanged: onChanged, width: width);
}

// ---------------------------------------------------------------- async states

class AsyncView<T> extends StatelessWidget {
  const AsyncView({super.key, required this.value, required this.builder, this.loadingHeight = 120});
  final AsyncValue<T> value;
  final Widget Function(T data) builder;
  final double loadingHeight;

  @override
  Widget build(BuildContext context) {
    if (value.hasValue) return builder(value.value as T);
    if (value.hasError) return ErrorNote(value.error!);
    return SizedBox(
      height: loadingHeight,
      child: const Center(child: CircularProgressIndicator(strokeWidth: 2)),
    );
  }
}

class ErrorNote extends StatelessWidget {
  const ErrorNote(this.error, {super.key});
  final Object error;

  @override
  Widget build(BuildContext context) {
    final offline = error is ApiException && (error as ApiException).isOffline;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Row(
        children: [
          Icon(offline ? Icons.cloud_off_rounded : Icons.error_outline, color: AppColors.red, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              offline ? '$error — start it with `python -m app.cli serve`.' : '$error',
              style: TextStyle(color: AppColors.red, fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState(this.message, {super.key, this.icon = Icons.inbox_outlined, this.action});
  final String message;
  final IconData icon;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 36),
      child: Column(
        children: [
          Icon(icon, color: AppColors.textMuted, size: 34),
          const SizedBox(height: 10),
          Text(message, textAlign: TextAlign.center, style: TextStyles.secondary),
          if (action != null) ...[const SizedBox(height: 14), action!],
        ],
      ),
    );
  }
}

/// Shown on run-scoped pages when no run exists yet.
class NoRunPlaceholder extends ConsumerWidget {
  const NoRunPlaceholder({super.key, required this.onCreate});
  final VoidCallback onCreate;

  @override
  Widget build(BuildContext context, WidgetRef ref) => Panel(
    child: EmptyState(
      'No experiment run yet. Create one on the Experiments page to see results here.',
      icon: Icons.science_outlined,
      action: FilledButton.icon(onPressed: onCreate, icon: const Icon(Icons.add), label: const Text('New experiment')),
    ),
  );
}

void showSnack(BuildContext context, String message, {bool error = false}) =>
    showToast(context, message, error: error);
