import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:puzzle_flutter_ui/backend_bridge.dart';

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
  final BackendBridge backend = BackendBridge();
  final ValueNotifier<int> tuningRevision = ValueNotifier(0);
  PuzzleMode mode = PuzzleMode.cardPuzzle;
  bool solving = false;
  bool hasResult = false;
  bool connected = false;
  bool polling = false;
  bool initializedFromBackend = false;
  bool autoThreshold = true;
  int threshold = 128;
  int minPieceArea = 1500;
  String polarityMode = 'AUTO';
  int pieceCount = 0;
  double fps = 0;
  double score = 0;
  double solverMs = 0;
  String solverMessage = '';
  String lastCaptureName = '';
  Uint8List? cameraFrame;
  Uint8List? binaryFrame;
  Uint8List? resultFrame;
  Timer? pollTimer;
  Timer? settingsTimer;

  String get resultTitle {
    return switch (mode) {
      PuzzleMode.firstQuestion => '第一问结果',
      PuzzleMode.normalPuzzle => '普通拼图实图',
      PuzzleMode.cardPuzzle => '扑克牌拼接实图',
    };
  }

  String get resultHint {
    if (!connected) {
      return '视觉后端未连接';
    }
    return switch (solverMessage) {
      'NO STABLE' || 'CARD NO STABLE' => '请保持碎片静止后重试',
      'CARD NEED 2-4' => '需要识别到2至4块碎片',
      'NO RECT' || 'CARD NO RECT' => '未找到可用矩形',
      'NO SAFE' => '结果存在重叠，已拒绝',
      'SOLVE ERROR' || 'CARD ERROR' => '求解异常，请重试',
      _ => '等待生成拼接实图',
    };
  }

  @override
  void initState() {
    super.initState();
    _pollBackend();
    pollTimer = Timer.periodic(
      const Duration(milliseconds: 80),
      (_) => _pollBackend(),
    );
  }

  @override
  void dispose() {
    pollTimer?.cancel();
    settingsTimer?.cancel();
    tuningRevision.dispose();
    super.dispose();
  }

  String get backendMode {
    return switch (mode) {
      PuzzleMode.firstQuestion => 'first',
      PuzzleMode.normalPuzzle => 'normal',
      PuzzleMode.cardPuzzle => 'card',
    };
  }

  PuzzleMode _parseMode(String value) {
    return switch (value) {
      'first' => PuzzleMode.firstQuestion,
      'normal' => PuzzleMode.normalPuzzle,
      _ => PuzzleMode.cardPuzzle,
    };
  }

  Future<void> _pollBackend() async {
    if (polling) {
      return;
    }
    polling = true;
    final update = await backend.poll();
    polling = false;
    if (!mounted) {
      return;
    }
    if (update == null) {
      if (connected) {
        setState(() => connected = false);
      }
      return;
    }

    final snapshot = update.snapshot;
    final captureChanged =
        snapshot.lastCaptureName.isNotEmpty &&
        snapshot.lastCaptureName != lastCaptureName;
    setState(() {
      connected = snapshot.backendAlive && snapshot.cameraOk;
      solving = snapshot.solving;
      hasResult = snapshot.resultAvailable;
      pieceCount = snapshot.pieceCount;
      fps = snapshot.fps;
      score = snapshot.score;
      solverMs = snapshot.solverMs;
      solverMessage = snapshot.solverMessage;
      autoThreshold = snapshot.autoThreshold;
      threshold = snapshot.autoThreshold
          ? snapshot.currentThreshold
          : snapshot.manualThreshold;
      polarityMode = snapshot.polarityMode;
      minPieceArea = snapshot.minPieceArea;
      lastCaptureName = snapshot.lastCaptureName;
      if (!initializedFromBackend) {
        mode = _parseMode(snapshot.mode);
        initializedFromBackend = true;
      }
      if (update.frame != null) {
        cameraFrame = update.frame;
      }
      if (update.binary != null) {
        binaryFrame = update.binary;
      }
      if (update.result != null) {
        resultFrame = update.result;
      } else if (update.clearResult) {
        resultFrame = null;
      }
    });
    tuningRevision.value++;

    if (captureChanged) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('已保存：${snapshot.lastCaptureName}'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  Future<void> solve() async {
    if (solving || !connected) {
      return;
    }
    setState(() {
      solving = true;
      hasResult = false;
      resultFrame = null;
    });
    await backend.sendControl(mode: backendMode, action: 'solve');
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
      child: Row(
        children: [
          const Text(
            '拼图装置',
            style: TextStyle(
              color: Color(0xFF111827),
              fontSize: 20,
              fontWeight: FontWeight.w800,
            ),
          ),
          const Spacer(),
          Icon(
            Icons.circle,
            size: 9,
            color: connected
                ? const Color(0xFF10A37F)
                : const Color(0xFFEF4444),
          ),
          const SizedBox(width: 7),
          Text(
            connected ? '相机正常' : '后端未连接',
            style: const TextStyle(
              color: Color(0xFF334155),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(width: 12),
          Text(
            '${fps.toStringAsFixed(1)} FPS',
            style: const TextStyle(color: Color(0xFF64748B), fontSize: 12),
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
          child: ColoredBox(
            color: const Color(0xFF111827),
            child: cameraFrame == null
                ? const SizedBox.expand()
                : Image.memory(
                    cameraFrame!,
                    fit: BoxFit.contain,
                    gaplessPlayback: true,
                    filterQuality: FilterQuality.low,
                  ),
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
    if (value == mode || solving) {
      return;
    }
    setState(() {
      mode = value;
      hasResult = false;
      resultFrame = null;
    });
    unawaited(backend.sendControl(mode: backendMode));
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
                    : hasResult && resultFrame != null
                    ? _ResultView(frame: resultFrame!)
                    : _EmptyResultView(message: resultHint),
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
            _Metric(label: '碎片', value: pieceCount.toString()),
            const SizedBox(width: 15),
            _Metric(
              label: '置信度',
              value: '${(score * 100).toStringAsFixed(1)}%',
            ),
            const SizedBox(width: 15),
            _Metric(
              label: '用时',
              value: '${(solverMs / 1000).toStringAsFixed(2)}s',
            ),
            const Spacer(),
            _ActionButton(label: '拍照', onPressed: _capture),
            const SizedBox(width: 8),
            _ActionButton(label: '调参', onPressed: _showTuningSheet),
            const SizedBox(width: 9),
            SizedBox(
              height: 50,
              width: 166,
              child: FilledButton(
                onPressed: solving || !connected ? null : solve,
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

  Future<void> _capture() async {
    if (!connected) {
      return;
    }
    await backend.sendControl(mode: backendMode, action: 'capture');
  }

  void _changeThreshold(int amount, StateSetter setSheetState) {
    setState(() {
      threshold = (threshold + amount).clamp(0, 255);
      autoThreshold = false;
    });
    setSheetState(() {});
    _queueSettings();
  }

  void _changeArea(int amount, StateSetter setSheetState) {
    setState(() {
      minPieceArea = (minPieceArea + amount).clamp(100, 50000);
    });
    setSheetState(() {});
    _queueSettings();
  }

  void _queueSettings() {
    settingsTimer?.cancel();
    settingsTimer = Timer(
      const Duration(milliseconds: 60),
      () => unawaited(
        backend.sendControl(
          autoThreshold: autoThreshold,
          manualThreshold: threshold,
          polarityMode: polarityMode,
          minPieceArea: minPieceArea,
        ),
      ),
    );
  }

  Future<void> _showTuningSheet() async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (context) {
        return ValueListenableBuilder<int>(
          valueListenable: tuningRevision,
          builder: (context, revision, child) {
            void setSheetState(VoidCallback callback) {
              callback();
              tuningRevision.value++;
            }

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
                            child: ColoredBox(
                              color: const Color(0xFF111827),
                              child: binaryFrame == null
                                  ? const SizedBox.expand()
                                  : Image.memory(
                                      binaryFrame!,
                                      fit: BoxFit.contain,
                                      gaplessPlayback: true,
                                      filterQuality: FilterQuality.low,
                                    ),
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
                                _queueSettings();
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
                            _queueSettings();
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
                            _queueSettings();
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
  const _ResultView({required this.frame});

  final Uint8List frame;

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
          child: Image.memory(
            frame,
            fit: BoxFit.contain,
            gaplessPlayback: true,
            filterQuality: FilterQuality.medium,
          ),
        ),
      ),
    );
  }
}

class _EmptyResultView extends StatelessWidget {
  const _EmptyResultView({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey('empty'),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Center(
        child: Text(
          message,
          style: const TextStyle(
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
