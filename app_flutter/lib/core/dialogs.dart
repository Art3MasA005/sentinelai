import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import 'theme.dart';

/// Modal dialog with a frosted backdrop: the page behind is blurred and only faintly tinted (lighter in
/// the light theme, slightly darker in the dark one) instead of being covered by a dark scrim. The
/// dialog rises and scales in. Nothing is faded with an opacity layer, so frosted-glass panels inside
/// the dialog never flash dark while it opens or closes.
Future<T?> showFrostedDialog<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool barrierDismissible = true,
}) => showGeneralDialog<T>(
  context: context,
  barrierDismissible: barrierDismissible,
  barrierLabel: MaterialLocalizations.of(context).modalBarrierDismissLabel,
  barrierColor: Colors.transparent,
  transitionDuration: const Duration(milliseconds: 260),
  pageBuilder: (context, _, _) => builder(context),
  transitionBuilder: (context, animation, _, child) {
    final c = CurvedAnimation(parent: animation, curve: Curves.easeOutCubic, reverseCurve: Curves.easeInCubic);
    return Stack(
      fit: StackFit.expand,
      children: [
        // Taps fall through to the route's (transparent) barrier, which dismisses the dialog.
        IgnorePointer(
          child: AnimatedBuilder(
            animation: c,
            builder: (_, _) {
              final a = c.value;
              final tint = AppColors.isGlass ? const Color(0x29FFFFFF) : const Color(0x33000000);
              return BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 7 * a + 0.01, sigmaY: 7 * a + 0.01),
                child: ColoredBox(color: tint.withValues(alpha: tint.a * a)),
              );
            },
          ),
        ),
        SlideTransition(
          position: Tween(begin: const Offset(0, 0.035), end: Offset.zero).animate(c),
          child: ScaleTransition(scale: Tween(begin: 0.965, end: 1.0).animate(c), child: child),
        ),
      ],
    );
  },
);
