import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:puzzle_flutter_ui/main.dart';

void main() {
  testWidgets('横屏控制台包含拼图、平台和设置页面', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 720));
    await tester.pumpWidget(const PuzzleStudioApp());

    expect(find.text('第一问'), findsOneWidget);
    expect(find.text('普通拼图'), findsOneWidget);
    expect(find.text('扑克牌'), findsAtLeast(1));
    expect(find.text('扑克牌拼接实图'), findsOneWidget);
    expect(find.text('开始求解'), findsOneWidget);

    await tester.tap(find.text('平台'));
    await tester.pump();

    expect(find.text('平台手动控制'), findsOneWidget);
    expect(find.text('读取位置'), findsOneWidget);
    expect(find.text('XY 平面'), findsOneWidget);
    expect(find.text('Z 轴'), findsOneWidget);
    expect(find.text('平台旋转'), findsOneWidget);
    expect(find.text('平台归零'), findsOneWidget);

    await tester.tap(find.text('设置').first);
    await tester.pump();

    expect(find.text('二值化实时预览'), findsOneWidget);
    expect(find.text('背景颜色'), findsOneWidget);
    expect(find.text('黑色'), findsOneWidget);
    expect(find.text('绿色'), findsOneWidget);
    expect(find.text('自动 OTSU'), findsOneWidget);
    expect(find.text('自动'), findsOneWidget);
    expect(find.text('亮色'), findsOneWidget);
    expect(find.text('暗色'), findsOneWidget);
    expect(find.text('最小碎片面积'), findsOneWidget);

    await tester.tap(find.text('串口设置'));
    await tester.pump();

    expect(find.text('串口设备'), findsOneWidget);
    expect(find.text('波特率'), findsOneWidget);
    expect(find.text('自动抓取Z'), findsOneWidget);
    expect(find.text('自动放置Z'), findsOneWidget);
    expect(find.text('保存并连接'), findsOneWidget);

    await tester.tap(find.text('平台标定'));
    await tester.pump();

    expect(find.text('平台两点标定'), findsOneWidget);
    expect(find.text('A：右上角'), findsOneWidget);
    expect(find.text('B：左下角'), findsOneWidget);
    expect(find.text('计算并保存'), findsOneWidget);

    await tester.binding.setSurfaceSize(null);
  });
}
