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
      title: '拼图装置控制台',
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF48E6B0),
          secondary: Color(0xFF5BA8FF),
          surface: Color(0xFF151C25),
          error: Color(0xFFFF6B72),
        ),
        scaffoldBackgroundColor: const Color(0xFF090E14),
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
  double threshold = 109;

  String get modeTitle {
    return switch (mode) {
      PuzzleMode.firstQuestion => '第一问',
      PuzzleMode.normalPuzzle => '普通拼图',
      PuzzleMode.cardPuzzle => '扑克牌',
    };
  }

  String get resultTitle {
    return switch (mode) {
      PuzzleMode.firstQuestion => '目标定位结果',
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
        child: DecoratedBox(
          decoration: const BoxDecoration(
            gradient: RadialGradient(
              center: Alignment.topLeft,
              radius: 1.35,
              colors: [Color(0xFF142233), Color(0xFF090E14)],
            ),
          ),
          child: Column(
            children: [
              _buildHeader(),
              Expanded(
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    return Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          SizedBox(
                            width: (constraints.maxWidth * 0.34).clamp(
                              300.0,
                              430.0,
                            ),
                            child: _buildCameraPanel(),
                          ),
                          const SizedBox(width: 14),
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
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      height: 66,
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: const Color(0xCC111923),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xFF243244)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x66000000),
            blurRadius: 24,
            offset: Offset(0, 10),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFF48E6B0), Color(0xFF3E8FFF)],
              ),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Icon(
              Icons.extension_rounded,
              color: Color(0xFF071019),
              size: 23,
            ),
          ),
          const SizedBox(width: 12),
          const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'PUZZLE STUDIO',
                style: TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.4,
                ),
              ),
              Text(
                '智能拼图装置控制台',
                style: TextStyle(color: Color(0xFF8391A4), fontSize: 11),
              ),
            ],
          ),
          const Spacer(),
          const _StatusChip(
            icon: Icons.videocam_rounded,
            label: '相机正常',
            color: Color(0xFF48E6B0),
          ),
          const SizedBox(width: 8),
          const _StatusChip(
            icon: Icons.speed_rounded,
            label: '30 FPS',
            color: Color(0xFF5BA8FF),
          ),
          const SizedBox(width: 8),
          _StatusChip(
            icon: Icons.tonality_rounded,
            label: autoThreshold
                ? 'OTSU ${threshold.round()}'
                : '手动 ${threshold.round()}',
            color: const Color(0xFFFFC766),
          ),
          const SizedBox(width: 10),
          IconButton(
            tooltip: '设置',
            onPressed: _showTuningSheet,
            icon: const Icon(Icons.tune_rounded),
          ),
        ],
      ),
    );
  }

  Widget _buildCameraPanel() {
    return _Panel(
      child: Column(
        children: [
          const _PanelTitle(
            icon: Icons.center_focus_strong_rounded,
            title: '实时识别',
            trailing: '竖向画面',
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Center(
                child: AspectRatio(
                  aspectRatio: 9 / 16,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(16),
                    child: Stack(
                      fit: StackFit.expand,
                      children: [
                        const ColoredBox(color: Color(0xFF0A0F15)),
                        CustomPaint(painter: CameraScenePainter()),
                        Positioned(
                          left: 10,
                          top: 10,
                          child: _OverlayBadge(
                            label: modeTitle,
                            color: const Color(0xFF48E6B0),
                          ),
                        ),
                        const Positioned(
                          right: 10,
                          top: 10,
                          child: _OverlayBadge(
                            label: '4 PIECES',
                            color: Color(0xFF5BA8FF),
                          ),
                        ),
                        Positioned(
                          left: 10,
                          right: 10,
                          bottom: 10,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 11,
                              vertical: 8,
                            ),
                            decoration: BoxDecoration(
                              color: const Color(0xCC0B1119),
                              borderRadius: BorderRadius.circular(11),
                              border: Border.all(
                                color: const Color(0xFF263447),
                              ),
                            ),
                            child: const Row(
                              children: [
                                Icon(
                                  Icons.circle,
                                  size: 8,
                                  color: Color(0xFF48E6B0),
                                ),
                                SizedBox(width: 7),
                                Text('检测稳定', style: TextStyle(fontSize: 12)),
                                Spacer(),
                                Text(
                                  'ROI 520×700',
                                  style: TextStyle(
                                    color: Color(0xFF8B98AA),
                                    fontSize: 11,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildControlPanel() {
    return Column(
      children: [
        _Panel(
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Row(
              children: [
                _ModeButton(
                  icon: Icons.looks_one_rounded,
                  label: '第一问',
                  subtitle: '基础任务',
                  selected: mode == PuzzleMode.firstQuestion,
                  onTap: () => _changeMode(PuzzleMode.firstQuestion),
                ),
                const SizedBox(width: 9),
                _ModeButton(
                  icon: Icons.grid_view_rounded,
                  label: '普通拼图',
                  subtitle: '第二问 · 白色',
                  selected: mode == PuzzleMode.normalPuzzle,
                  onTap: () => _changeMode(PuzzleMode.normalPuzzle),
                ),
                const SizedBox(width: 9),
                _ModeButton(
                  icon: Icons.style_rounded,
                  label: '扑克牌',
                  subtitle: '第二问 · 花纹',
                  selected: mode == PuzzleMode.cardPuzzle,
                  onTap: () => _changeMode(PuzzleMode.cardPuzzle),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Expanded(child: _buildResultPanel()),
        const SizedBox(height: 12),
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
          _PanelTitle(
            icon: Icons.auto_awesome_mosaic_rounded,
            title: resultTitle,
            trailing: hasResult ? '真实纹理重建' : '等待求解',
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 280),
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
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            const _Metric(label: '碎片', value: '4'),
            const SizedBox(width: 14),
            const _Metric(label: '置信度', value: '92.8%'),
            const SizedBox(width: 14),
            const _Metric(label: '用时', value: '2.31s'),
            const Spacer(),
            _SmallAction(
              icon: Icons.camera_alt_rounded,
              label: '拍照',
              onPressed: _capture,
            ),
            const SizedBox(width: 8),
            _SmallAction(
              icon: Icons.tune_rounded,
              label: '调参',
              onPressed: _showTuningSheet,
            ),
            const SizedBox(width: 10),
            SizedBox(
              height: 54,
              width: 174,
              child: FilledButton.icon(
                onPressed: solving ? null : solve,
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF48E6B0),
                  foregroundColor: const Color(0xFF071019),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(15),
                  ),
                ),
                icon: solving
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Color(0xFF071019),
                        ),
                      )
                    : const Icon(Icons.play_arrow_rounded),
                label: Text(
                  solving ? '求解中' : '开始求解',
                  style: const TextStyle(
                    fontSize: 16,
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
        content: const Row(
          children: [
            Icon(Icons.check_circle_rounded, color: Color(0xFF48E6B0)),
            SizedBox(width: 10),
            Text('已保存当前原图、二值图和碎片数据'),
          ],
        ),
        backgroundColor: const Color(0xFF18232E),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    );
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
              margin: const EdgeInsets.all(14),
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: const Color(0xFF141C25),
                borderRadius: BorderRadius.circular(24),
                border: Border.all(color: const Color(0xFF2B394A)),
                boxShadow: const [
                  BoxShadow(color: Color(0x99000000), blurRadius: 32),
                ],
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Container(
                      height: 210,
                      decoration: BoxDecoration(
                        color: Colors.black,
                        borderRadius: BorderRadius.circular(18),
                        border: Border.all(color: const Color(0xFF303D4C)),
                      ),
                      child: const Center(
                        child: Text(
                          '二值化实时预览',
                          style: TextStyle(color: Color(0xFF7D8999)),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 22),
                  Expanded(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          '检测参数',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 12),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('自动阈值 OTSU'),
                          value: autoThreshold,
                          onChanged: (value) {
                            setState(() => autoThreshold = value);
                            setSheetState(() {});
                          },
                        ),
                        Text('阈值  ${threshold.round()}'),
                        Slider(
                          value: threshold,
                          min: 0,
                          max: 255,
                          onChanged: (value) {
                            setState(() {
                              threshold = value;
                              autoThreshold = false;
                            });
                            setSheetState(() {});
                          },
                        ),
                        const Row(
                          children: [
                            Expanded(
                              child: _OptionTile(title: '极性', value: 'AUTO'),
                            ),
                            SizedBox(width: 10),
                            Expanded(
                              child: _OptionTile(title: '最小面积', value: '1500'),
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
        color: const Color(0xD9111923),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFF243244)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x55000000),
            blurRadius: 20,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: child,
    );
  }
}

class _PanelTitle extends StatelessWidget {
  const _PanelTitle({
    required this.icon,
    required this.title,
    required this.trailing,
  });

  final IconData icon;
  final String title;
  final String trailing;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 50,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14),
        child: Row(
          children: [
            Icon(icon, size: 19, color: const Color(0xFF48E6B0)),
            const SizedBox(width: 8),
            Text(
              title,
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
            ),
            const Spacer(),
            Text(
              trailing,
              style: const TextStyle(color: Color(0xFF7F8DA0), fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({
    required this.icon,
    required this.label,
    required this.color,
  });

  final IconData icon;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 34,
      padding: const EdgeInsets.symmetric(horizontal: 11),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: color.withValues(alpha: 0.27)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 16),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.w700,
              fontSize: 11,
            ),
          ),
        ],
      ),
    );
  }
}

class _ModeButton extends StatelessWidget {
  const _ModeButton({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.selected,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final String subtitle;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(15),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            height: 61,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            decoration: BoxDecoration(
              gradient: selected
                  ? const LinearGradient(
                      colors: [Color(0xFF1D6958), Color(0xFF173A4D)],
                    )
                  : null,
              color: selected ? null : const Color(0xFF111922),
              borderRadius: BorderRadius.circular(15),
              border: Border.all(
                color: selected
                    ? const Color(0xFF48E6B0)
                    : const Color(0xFF273444),
                width: selected ? 1.4 : 1,
              ),
            ),
            child: Row(
              children: [
                Icon(
                  icon,
                  color: selected
                      ? const Color(0xFF48E6B0)
                      : const Color(0xFF77869A),
                  size: 22,
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        label,
                        style: const TextStyle(
                          fontWeight: FontWeight.w800,
                          fontSize: 14,
                        ),
                      ),
                      Text(
                        subtitle,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: Color(0xFF8290A2),
                          fontSize: 10,
                        ),
                      ),
                    ],
                  ),
                ),
                if (selected)
                  const Icon(
                    Icons.check_circle_rounded,
                    color: Color(0xFF48E6B0),
                    size: 17,
                  ),
              ],
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
        color: const Color(0xFF0A0F15),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFF273646)),
      ),
      child: Row(
        children: [
          Expanded(
            flex: 7,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: const Color(0xFF20252B),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Image.asset(
                    'assets/demo_result.png',
                    fit: BoxFit.contain,
                    filterQuality: FilterQuality.medium,
                  ),
                ),
              ),
            ),
          ),
          Container(
            width: 146,
            margin: const EdgeInsets.fromLTRB(0, 12, 12, 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFF121A23),
              borderRadius: BorderRadius.circular(13),
              border: Border.all(color: const Color(0xFF263545)),
            ),
            child: const Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _ResultState(
                  icon: Icons.check_circle_rounded,
                  label: '矩形闭合',
                  color: Color(0xFF48E6B0),
                ),
                SizedBox(height: 13),
                _ResultState(
                  icon: Icons.layers_clear_rounded,
                  label: '无重叠',
                  color: Color(0xFF48E6B0),
                ),
                SizedBox(height: 13),
                _ResultState(
                  icon: Icons.texture_rounded,
                  label: '纹理连续',
                  color: Color(0xFF5BA8FF),
                ),
                SizedBox(height: 15),
                Text(
                  '92.8%',
                  style: TextStyle(fontWeight: FontWeight.w900, fontSize: 27),
                ),
                Text(
                  '综合置信度',
                  style: TextStyle(color: Color(0xFF7F8C9D), fontSize: 10),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ResultState extends StatelessWidget {
  const _ResultState({
    required this.icon,
    required this.label,
    required this.color,
  });

  final IconData icon;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, color: color, size: 16),
        const SizedBox(width: 7),
        Text(label, style: const TextStyle(fontSize: 11)),
      ],
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
        color: const Color(0xFF0C1219),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFF273646)),
      ),
      child: const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.dashboard_customize_outlined,
              size: 45,
              color: Color(0xFF536173),
            ),
            SizedBox(height: 10),
            Text(
              '等待生成拼接实图',
              style: TextStyle(
                color: Color(0xFFA1ACBA),
                fontWeight: FontWeight.w700,
              ),
            ),
            SizedBox(height: 4),
            Text(
              '按下开始求解后显示真实碎片纹理',
              style: TextStyle(color: Color(0xFF667487), fontSize: 11),
            ),
          ],
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
        color: const Color(0xFF0C1219),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFF273646)),
      ),
      child: const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 34,
              height: 34,
              child: CircularProgressIndicator(
                strokeWidth: 3,
                color: Color(0xFF48E6B0),
              ),
            ),
            SizedBox(height: 13),
            Text('正在搜索最优拼接方案…', style: TextStyle(fontWeight: FontWeight.w700)),
          ],
        ),
      ),
    );
  }
}

class _OverlayBadge extends StatelessWidget {
  const _OverlayBadge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: const Color(0xDD0B1118),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.w800,
          fontSize: 10,
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
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          label,
          style: const TextStyle(color: Color(0xFF798798), fontSize: 10),
        ),
        Text(
          value,
          style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
        ),
      ],
    );
  }
}

class _SmallAction extends StatelessWidget {
  const _SmallAction({
    required this.icon,
    required this.label,
    required this.onPressed,
  });

  final IconData icon;
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 54,
      child: OutlinedButton.icon(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          foregroundColor: const Color(0xFFD7E0EA),
          side: const BorderSide(color: Color(0xFF304052)),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(15),
          ),
        ),
        icon: Icon(icon, size: 18),
        label: Text(label),
      ),
    );
  }
}

class _OptionTile extends StatelessWidget {
  const _OptionTile({required this.title, required this.value});

  final String title;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(11),
      decoration: BoxDecoration(
        color: const Color(0xFF0F161E),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF293747)),
      ),
      child: Row(
        children: [
          Text(
            title,
            style: const TextStyle(color: Color(0xFF8290A1), fontSize: 11),
          ),
          const Spacer(),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w800)),
        ],
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
        colors: [Color(0xFF202B36), Color(0xFF101820)],
      ).createShader(Offset.zero & size);
    canvas.drawRect(Offset.zero & size, background);

    final paper = RRect.fromRectAndRadius(
      Rect.fromLTWH(
        size.width * 0.10,
        size.height * 0.11,
        size.width * 0.80,
        size.height * 0.77,
      ),
      const Radius.circular(5),
    );
    canvas.drawRRect(paper, Paint()..color = const Color(0xFFE8EBE9));

    final roi = Paint()
      ..color = const Color(0xFFFFC766)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(
          size.width * 0.13,
          size.height * 0.15,
          size.width * 0.74,
          size.height * 0.66,
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
      canvas.drawPath(path, Paint()..color = const Color(0xFF343D43));
      canvas.drawPath(
        path,
        Paint()
          ..color = const Color(0xFF48E6B0)
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
            color: Color(0xFF48E6B0),
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
