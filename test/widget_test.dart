import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:puzzle_flutter_ui/main.dart';

void main() {
  testWidgets('横屏控制台包含三个模式和真实结果区', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1024, 600));
    await tester.pumpWidget(const PuzzleStudioApp());

    expect(find.text('第一问'), findsOneWidget);
    expect(find.text('普通拼图'), findsOneWidget);
    expect(find.text('扑克牌'), findsAtLeast(1));
    expect(find.text('扑克牌拼接实图'), findsOneWidget);
    expect(find.text('开始求解'), findsOneWidget);

    await tester.tap(find.text('调参'));
    await tester.pumpAndSettle();

    expect(find.text('二值化实时预览'), findsOneWidget);
    expect(find.text('自动 OTSU'), findsOneWidget);
    expect(find.text('-5'), findsOneWidget);
    expect(find.text('+5'), findsOneWidget);
    expect(find.text('自动'), findsOneWidget);
    expect(find.text('亮色'), findsOneWidget);
    expect(find.text('暗色'), findsOneWidget);
    expect(find.text('最小碎片面积'), findsOneWidget);
    expect(find.text('-250'), findsOneWidget);
    expect(find.text('+250'), findsOneWidget);
    expect(find.text('完成'), findsOneWidget);

    await tester.binding.setSurfaceSize(null);
  });
}
