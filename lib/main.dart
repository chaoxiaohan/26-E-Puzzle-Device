import 'dart:async';

import 'package:flutter/material.dart';

void main() {
  runApp(const PuzzleStudioApp());
}

enum PuzzleMode { firstQuestion, normalPuzzle, cardPuzzle }

class PuzzleStudioApp extends StatelessWidget {
  const PuzzleStudioApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: '拼图装置',
      theme: ThemeData(
        brightness: Brightness.light,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF2563EB),
          brightness: Brightness.light,
        ),
        fontFamily: 'PuzzleLatin',
        fontFamilyFallback: const ['PuzzleChinese'],
        scaffoldBackgroundColor: const Color(0xFFF5F7FA),
        useMaterial3: true,
      ),
      home: const PuzzleDashboard(),
    );
  }
}

class PuzzleDashboard extends StatefulWidget {
  const PuzzleDashboard({super.key});

  @override
  State<PuzzleDashboard> createState() => _PuzzleDashboardState();
}

class _PuzzleDashboardState extends State<PuzzleDashboard> {
  PuzzleMode mode = PuzzleMode.cardPuzzle;
  bool solving = false;
  bool hasResult = true;
  bool autoThreshold = true;
  int threshold = 109;
  int minPieceArea = 1500;
  String polarityMode = 'AUTO';

  String get resultTitle {
    return switch (mode) {
      PuzzleMode.firstQuestion => '第一问结果',
      PuzzleMode.normalPuzzle => '普通拼图实图',
      PuzzleMode.cardPuzzle => '扑克牌拼接实图',
    };
  }

  Future<void> solve() async {
    if (solving) {
      return;
    }
    setState(() {
      solving = true;
      hasResult = false;
    });
    await Future<void>.delayed(const Duration(milliseconds: 1300));
    if (!mounted) {
      return;
    }
    setState(() {
      solving = false;
      hasResult = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildHeader(),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  return Padding(
                    padding: const EdgeInsets.fromLTRB(14, 6, 14, 14),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        SizedBox(
                          width: (constraints.maxWidth * 0.31).clamp(
                            285.0,
                            390.0,
                          ),
                          child: _buildCameraPanel(),
                        ),
                        const SizedBox(width: 12),
                        Expanded(child: _buildControlPanel()),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      height: 58,
      margin: const EdgeInsets.fromLTRB(14, 10, 14, 4),
      padding: const EdgeInsets.symmetric(horizontal: 18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE4E9EF)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0D0F172A),
            blurRadius: 16,
            offset: Offset(0, 6),
          ),
        ],
      ),
      child: const Row(
        children: [
          Text(
            '拼图装置',
            style: TextStyle(
              color: Color(0xFF111827),
              fontSize: 20,
              fontWeight: FontWeight.w800,
            ),
          ),
          Spacer(),
          Icon(Icons.circle, size: 9, color: Color(0xFF10A37F)),
          SizedBox(width: 7),
          Text(
            '相机正常',
            style: TextStyle(
              color: Color(0xFF334155),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
          SizedBox(width: 12),
          Text(
            '30 FPS',
            style: TextStyle(color: Color(0xFF64748B), fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _buildCameraPanel() {
    return Center(
      child: AspectRatio(
        aspectRatio: 9 / 16,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(14),
          child: Stack(
            fit: StackFit.expand,
            children: [
              const ColoredBox(color: Color(0xFF111827)),
              CustomPaint(painter: CameraScenePainter()),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildControlPanel() {
    return Column(
      children: [
        _Panel(
          child: Padding(
            padding: const EdgeInsets.all(9),
            child: Row(
              children: [
                _ModeButton(
                  label: '第一问',
                  selected: mode == PuzzleMode.firstQuestion,
                  onTap: () => _changeMode(PuzzleMode.firstQuestion),
                ),
                const SizedBox(width: 8),
                _ModeButton(
                  label: '普通拼图',
                  selected: mode == PuzzleMode.normalPuzzle,
                  onTap: () => _changeMode(PuzzleMode.normalPuzzle),
                ),
                const SizedBox(width: 8),
                _ModeButton(
                  label: '扑克牌',
                  selected: mode == PuzzleMode.cardPuzzle,
                  onTap: () => _changeMode(PuzzleMode.cardPuzzle),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 10),
        Expanded(child: _buildResultPanel()),
        const SizedBox(height: 10),
        _buildActionBar(),
      ],
    );
  }

  void _changeMode(PuzzleMode value) {
    setState(() {
      mode = value;
      hasResult = value == PuzzleMode.cardPuzzle;
    });
  }

  Widget _buildResultPanel() {
    return _Panel(
      child: Column(
        children: [
          _PanelHeader(title: resultTitle, trailing: ''),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 250),
                child: solving
                    ? const _SolvingView()
                    : hasResult
                    ? const _ResultView()
                    : const _EmptyResultView(),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildActionBar() {
    return _Panel(
      child: Padding(
        padding: const EdgeInsets.all(11),
        child: Row(
          children: [
            const _Metric(label: '碎片', value: '4'),
            const SizedBox(width: 15),
            const _Metric(label: '置信度', value: '92.8%'),
            const SizedBox(width: 15),
            const _Metric(label: '用时', value: '2.31s'),
            const Spacer(),
            _ActionButton(label: '拍照', onPressed: _capture),
            const SizedBox(width: 8),
            _ActionButton(label: '调参', onPressed: _showTuningSheet),
            const SizedBox(width: 9),
            SizedBox(
              height: 50,
              width: 166,
              child: FilledButton(
                onPressed: solving ? null : solve,
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF2563EB),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(13),
                  ),
                ),
                child: Text(
                  solving ? '求解中' : '开始求解',
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _capture() {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('已保存原图、二值图和碎片数据'),
        backgroundColor: const Color(0xFF1E293B),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    );
  }

  void _changeThreshold(int amount, StateSetter setSheetState) {
    setState(() {
      threshold = (threshold + amount).clamp(0, 255);
      autoThreshold = false;
    });
    setSheetState(() {});
  }

  void _changeArea(int amount, StateSetter setSheetState) {
    setState(() {
      minPieceArea = (minPieceArea + amount).clamp(100, 50000);
    });
    setSheetState(() {});
  }

  Future<void> _showTuningSheet() async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setSheetState) {
            return Container(
              height: 430,
              margin: const EdgeInsets.all(12),
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: const Color(0xFFE2E8F0)),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x260F172A),
                    blurRadius: 30,
                    offset: Offset(0, -4),
                  ),
                ],
              ),
              child: Row(
                children: [
                  Expanded(
                    flex: 5,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          '二值化实时预览',
                          style: TextStyle(
                            color: Color(0xFF111827),
                            fontSize: 17,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Expanded(
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(14),
                            child: CustomPaint(
                              painter: BinaryPreviewPainter(),
                              child: const SizedBox.expand(),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 22),
                  Expanded(
                    flex: 6,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Text(
                              '检测参数',
                              style: TextStyle(
                                color: Color(0xFF111827),
                                fontSize: 19,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            const Spacer(),
                            TextButton(
                              onPressed: () => Navigator.pop(context),
                              child: const Text('完成'),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Row(
                          children: [
                            const Text(
                              '二值化阈值',
                              style: TextStyle(
                                color: Color(0xFF334155),
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const Spacer(),
                            FilterChip(
                              selected: autoThreshold,
                              label: const Text('自动 OTSU'),
                              onSelected: (_) {
                                setState(() => autoThreshold = true);
                                setSheetState(() {});
                              },
                            ),
                          ],
                        ),
                        const SizedBox(height: 7),
                        Row(
                          children: [
                            _AdjustButton(
                              label: '-5',
                              onPressed: () =>
                                  _changeThreshold(-5, setSheetState),
                            ),
                            const SizedBox(width: 9),
                            Expanded(
                              child: _ValueBox(
                                value: threshold.toString(),
                                active: !autoThreshold,
                              ),
                            ),
                            const SizedBox(width: 9),
                            _AdjustButton(
                              label: '+5',
                              onPressed: () =>
                                  _changeThreshold(5, setSheetState),
                            ),
                          ],
                        ),
                        Slider(
                          value: threshold.toDouble(),
                          min: 0,
                          max: 255,
                          onChanged: (value) {
                            setState(() {
                              threshold = value.round();
                              autoThreshold = false;
                            });
                            setSheetState(() {});
                          },
                        ),
                        const Text(
                          '目标极性',
                          style: TextStyle(
                            color: Color(0xFF334155),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 7),
                        SegmentedButton<String>(
                          segments: const [
                            ButtonSegment(value: 'AUTO', label: Text('自动')),
                            ButtonSegment(value: 'LIGHT', label: Text('亮色')),
                            ButtonSegment(value: 'DARK', label: Text('暗色')),
                          ],
                          selected: {polarityMode},
                          showSelectedIcon: false,
                          onSelectionChanged: (values) {
                            setState(() {
                              polarityMode = values.first;
                            });
                            setSheetState(() {});
                          },
                        ),
                        const SizedBox(height: 15),
                        const Text(
                          '最小碎片面积',
                          style: TextStyle(
                            color: Color(0xFF334155),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 7),
                        Row(
                          children: [
                            _AdjustButton(
                              label: '-250',
                              onPressed: () => _changeArea(-250, setSheetState),
                            ),
                            const SizedBox(width: 9),
                            Expanded(
                              child: _ValueBox(
                                value: minPieceArea.toString(),
                                active: true,
                              ),
                            ),
                            const SizedBox(width: 9),
                            _AdjustButton(
                              label: '+250',
                              onPressed: () => _changeArea(250, setSheetState),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(17),
        border: Border.all(color: const Color(0xFFE4E9EF)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0A0F172A),
            blurRadius: 14,
            offset: Offset(0, 5),
          ),
        ],
      ),
      child: child,
    );
  }
}

class _PanelHeader extends StatelessWidget {
  const _PanelHeader({required this.title, required this.trailing});

  final String title;
  final String trailing;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 45,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14),
        child: Row(
          children: [
            Text(
              title,
              style: const TextStyle(
                color: Color(0xFF111827),
                fontSize: 15,
                fontWeight: FontWeight.w800,
              ),
            ),
            const Spacer(),
            Text(
              trailing,
              style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }
}

class _ModeButton extends StatelessWidget {
  const _ModeButton({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            height: 52,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: selected
                  ? const Color(0xFF2563EB)
                  : const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: selected
                    ? const Color(0xFF2563EB)
                    : const Color(0xFFE2E8F0),
              ),
            ),
            child: Text(
              label,
              style: TextStyle(
                color: selected ? Colors.white : const Color(0xFF334155),
                fontWeight: FontWeight.w800,
                fontSize: 14,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ResultView extends StatelessWidget {
  const _ResultView();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey('result'),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Image.asset(
            'assets/demo_result.png',
            fit: BoxFit.contain,
            filterQuality: FilterQuality.medium,
          ),
        ),
      ),
    );
  }
}

class _EmptyResultView extends StatelessWidget {
  const _EmptyResultView();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey('empty'),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: const Center(
        child: Text(
          '等待生成拼接实图',
          style: TextStyle(
            color: Color(0xFF64748B),
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

class _SolvingView extends StatelessWidget {
  const _SolvingView();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey('solving'),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 30,
              height: 30,
              child: CircularProgressIndicator(strokeWidth: 3),
            ),
            SizedBox(height: 11),
            Text(
              '正在求解…',
              style: TextStyle(
                color: Color(0xFF334155),
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 10),
        ),
        Text(
          value,
          style: const TextStyle(
            color: Color(0xFF1E293B),
            fontSize: 15,
            fontWeight: FontWeight.w800,
          ),
        ),
      ],
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 50,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          foregroundColor: const Color(0xFF334155),
          side: const BorderSide(color: Color(0xFFD6DEE8)),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(13),
          ),
        ),
        child: Text(label),
      ),
    );
  }
}

class _AdjustButton extends StatelessWidget {
  const _AdjustButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 72,
      height: 42,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          padding: EdgeInsets.zero,
          foregroundColor: const Color(0xFF2563EB),
          side: const BorderSide(color: Color(0xFFBFDBFE)),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
        child: Text(label, style: const TextStyle(fontWeight: FontWeight.w800)),
      ),
    );
  }
}

class _ValueBox extends StatelessWidget {
  const _ValueBox({required this.value, required this.active});

  final String value;
  final bool active;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 42,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: active ? const Color(0xFFEFF6FF) : const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: active ? const Color(0xFF93C5FD) : const Color(0xFFE2E8F0),
        ),
      ),
      child: Text(
        value,
        style: const TextStyle(
          color: Color(0xFF1E293B),
          fontSize: 15,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class CameraScenePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final background = Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [Color(0xFF2A3541), Color(0xFF121922)],
      ).createShader(Offset.zero & size);
    canvas.drawRect(Offset.zero & size, background);

    final paper = RRect.fromRectAndRadius(
      Rect.fromLTWH(
        size.width * 0.04,
        size.height * 0.06,
        size.width * 0.92,
        size.height * 0.88,
      ),
      const Radius.circular(5),
    );
    canvas.drawRRect(paper, Paint()..color = const Color(0xFFE8EBE9));

    final roi = Paint()
      ..color = const Color(0xFFFFC857)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(
          size.width * 0.08,
          size.height * 0.11,
          size.width * 0.84,
          size.height * 0.74,
        ),
        const Radius.circular(4),
      ),
      roi,
    );

    final fragments = [
      [
        Offset(size.width * 0.24, size.height * 0.27),
        Offset(size.width * 0.48, size.height * 0.25),
        Offset(size.width * 0.44, size.height * 0.37),
        Offset(size.width * 0.21, size.height * 0.39),
      ],
      [
        Offset(size.width * 0.55, size.height * 0.26),
        Offset(size.width * 0.75, size.height * 0.31),
        Offset(size.width * 0.69, size.height * 0.43),
        Offset(size.width * 0.51, size.height * 0.39),
      ],
      [
        Offset(size.width * 0.20, size.height * 0.49),
        Offset(size.width * 0.41, size.height * 0.46),
        Offset(size.width * 0.46, size.height * 0.59),
        Offset(size.width * 0.25, size.height * 0.63),
      ],
      [
        Offset(size.width * 0.52, size.height * 0.50),
        Offset(size.width * 0.74, size.height * 0.48),
        Offset(size.width * 0.78, size.height * 0.62),
        Offset(size.width * 0.57, size.height * 0.66),
      ],
    ];

    for (var index = 0; index < fragments.length; index++) {
      final path = Path()..addPolygon(fragments[index], true);
      canvas.drawPath(path, Paint()..color = const Color(0xFF374151));
      canvas.drawPath(
        path,
        Paint()
          ..color = const Color(0xFF5EE6BA)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2,
      );
      final center =
          fragments[index].reduce((a, b) => a + b) /
          fragments[index].length.toDouble();
      final text = TextPainter(
        text: TextSpan(
          text: 'P${index + 1}',
          style: const TextStyle(
            color: Color(0xFF5EE6BA),
            fontSize: 11,
            fontWeight: FontWeight.w800,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      text.paint(canvas, center - Offset(text.width / 2, text.height / 2));
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class BinaryPreviewPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xFF111111),
    );

    final paper = RRect.fromRectAndRadius(
      Rect.fromLTWH(
        size.width * 0.12,
        size.height * 0.09,
        size.width * 0.76,
        size.height * 0.82,
      ),
      const Radius.circular(5),
    );
    canvas.drawRRect(paper, Paint()..color = Colors.white);

    final fragments = [
      Rect.fromLTWH(
        size.width * 0.23,
        size.height * 0.24,
        size.width * 0.22,
        size.height * 0.17,
      ),
      Rect.fromLTWH(
        size.width * 0.52,
        size.height * 0.25,
        size.width * 0.20,
        size.height * 0.19,
      ),
      Rect.fromLTWH(
        size.width * 0.25,
        size.height * 0.54,
        size.width * 0.22,
        size.height * 0.18,
      ),
      Rect.fromLTWH(
        size.width * 0.53,
        size.height * 0.54,
        size.width * 0.21,
        size.height * 0.18,
      ),
    ];
    for (final fragment in fragments) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(fragment, const Radius.circular(3)),
        Paint()..color = Colors.black,
      );
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
