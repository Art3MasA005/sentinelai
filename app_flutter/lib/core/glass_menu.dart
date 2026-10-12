import 'package:flutter/material.dart';

import 'theme.dart';

class GlassMenuItem<T> {
  const GlassMenuItem({
    required this.value,
    required this.label,
    this.icon,
    this.iconColor,
    this.trailing,
    this.enabled = true,
  });
  final T value;
  final Widget label;
  final IconData? icon;
  final Color? iconColor;
  final Widget? trailing;
  final bool enabled;
}

/// Rounded, frosted-glass dropdown menu used for every popup in the app (Material popups
/// cannot blur what is behind them). Width follows the content, so long rows never overflow.
class GlassMenu<T> extends StatelessWidget {
  const GlassMenu({
    super.key,
    required this.items,
    required this.builder,
    this.onSelected,
    this.selected,
    this.minWidth = 220,
    this.maxWidth = 560,
    this.maxHeight = 440,
    this.header,
    this.emptyText = 'Nothing here',
  });

  final List<GlassMenuItem<T>> items;
  final Widget Function(BuildContext context, MenuController controller) builder;
  final ValueChanged<T>? onSelected;
  final T? selected;
  final double minWidth;
  final double maxWidth;
  final double maxHeight;
  final String? header;
  final String emptyText;

  static const radius = 16.0;

  @override
  Widget build(BuildContext context) {
    return MenuAnchor(
      clipBehavior: Clip.none,
      alignmentOffset: const Offset(0, 8),
      style: MenuStyle(
        backgroundColor: const WidgetStatePropertyAll(Colors.transparent),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shadowColor: const WidgetStatePropertyAll(Colors.transparent),
        elevation: const WidgetStatePropertyAll(0),
        padding: const WidgetStatePropertyAll(EdgeInsets.zero),
        shape: const WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(radius))),
        ),
      ),
      menuChildren: [
        Builder(
          builder: (context) {
            final controller = MenuController.maybeOf(context);
            return ConstrainedBox(
              constraints: BoxConstraints(minWidth: minWidth, maxWidth: maxWidth, maxHeight: maxHeight),
              child: Glass(
                radius: radius,
                blur: 30,
                color: AppColors.isGlass ? const Color(0xB8FFFFFF) : AppColors.panelRaised,
                padding: const EdgeInsets.all(6),
                child: IntrinsicWidth(
                  child: SingleChildScrollView(
                    primary: false, // MenuAnchor's panel already owns the primary scroll controller
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (header != null)
                          Padding(
                            padding: const EdgeInsets.fromLTRB(12, 8, 12, 6),
                            child: Text(header!.toUpperCase(), style: TextStyles.label),
                          ),
                        if (items.isEmpty)
                          Padding(
                            padding: const EdgeInsets.all(14),
                            child: Text(emptyText, style: TextStyles.secondary),
                          ),
                        for (final item in items)
                          _Tile<T>(
                            item: item,
                            selected: item.value == selected,
                            onTap: item.enabled && onSelected != null
                                ? () {
                                    controller?.close();
                                    onSelected!(item.value);
                                  }
                                : null,
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ],
      builder: (context, controller, _) => builder(context, controller),
    );
  }
}

class _Tile<T> extends StatelessWidget {
  const _Tile({required this.item, required this.selected, required this.onTap});
  final GlassMenuItem<T> item;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final hover = AppColors.text.withValues(alpha: 0.06);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: Material(
        color: selected ? AppColors.navActive : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          hoverColor: hover,
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                if (item.icon != null) ...[
                  Icon(item.icon, size: 16, color: item.iconColor ?? AppColors.textSecondary),
                  const SizedBox(width: 12),
                ],
                Expanded(
                  child: DefaultTextStyle.merge(
                    style: TextStyle(color: AppColors.text, fontSize: 13),
                    maxLines: 1,
                    softWrap: false,
                    overflow: TextOverflow.ellipsis,
                    child: item.label,
                  ),
                ),
                if (item.trailing != null) ...[const SizedBox(width: 12), item.trailing!],
                if (selected) ...[
                  const SizedBox(width: 10),
                  Icon(Icons.check_rounded, size: 16, color: AppColors.blue),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Labelled select field ("Severity: All ▾") that opens a [GlassMenu].
class GlassSelect<T> extends StatelessWidget {
  const GlassSelect({
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
  Widget build(BuildContext context) {
    final current = options[value] ?? (options.isEmpty ? '—' : options.values.first);
    return GlassMenu<T>(
      selected: value,
      minWidth: width,
      onSelected: onChanged,
      items: [for (final e in options.entries) GlassMenuItem(value: e.key, label: Text(e.value))],
      builder: (context, controller) => SizedBox(
        width: width,
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: () => controller.isOpen ? controller.close() : controller.open(),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              decoration: BoxDecoration(
                color: AppColors.isGlass ? const Color(0x80FFFFFF) : AppColors.panelRaised,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.isGlass ? AppColors.glassEdge : AppColors.border),
              ),
              child: Row(
                children: [
                  if (label.isNotEmpty)
                    Text('$label: ', style: TextStyle(color: AppColors.textSecondary, fontSize: 12.5)),
                  Expanded(
                    child: Text(
                      current,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: AppColors.text, fontSize: 12.5, fontWeight: FontWeight.w600),
                    ),
                  ),
                  Icon(Icons.expand_more_rounded, size: 18, color: AppColors.textSecondary),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
