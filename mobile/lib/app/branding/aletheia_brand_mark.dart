import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// The product mark used inside the app chrome.
///
/// Keep this separate from platform launcher configuration so the in-app
/// identity stays consistent on every route without reintroducing a generic
/// Material icon as a logo.
class AletheiaBrandMark extends StatelessWidget {
  const AletheiaBrandMark({required this.size, super.key});

  final double size;

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: ClipRRect(
        borderRadius: BorderRadius.circular(size * .28),
        child: SvgPicture.asset(
          'assets/branding/aletheia_icon_vector.svg',
          width: size,
          height: size,
          fit: BoxFit.cover,
        ),
      ),
    );
  }
}
