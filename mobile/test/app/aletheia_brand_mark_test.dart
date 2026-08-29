import 'package:aletheia_mobile/app/branding/aletheia_brand_mark.dart';
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('brand mark renders the vector source directly', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: AletheiaBrandMark(size: 30)),
    );

    final svg = tester.widget<SvgPicture>(find.byType(SvgPicture));
    expect(svg.bytesLoader.toString(), contains('aletheia_icon_vector.svg'));
    expect(find.byType(Image), findsNothing);
  });
}
