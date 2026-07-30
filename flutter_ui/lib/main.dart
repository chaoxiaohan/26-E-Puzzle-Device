import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:puzzle_flutter_ui/backend_bridge.dart';

void main() {
  runApp(const PuzzleStudioApp());
}

enum PuzzleMode { firstQuestion, normalPuzzle, cardPuzzle }

enum AppPage { puzzle, arm, settings }

enum SettingsPage { vision, serial, calibration, logs }

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
  final ValueNotifier<Uint8List?> binaryPreview = ValueNotifier(null);
  final ScrollController calibrationScrollController = ScrollController();
  final TextEditingController serialPortController = TextEditingController(
    text: '/dev/ttyUSB0',
  );
  final TextEditingController serialBaudController = TextEditingController(
    text: '115200',
  );
  final TextEditingController serialPickZController = TextEditingController(
    text: '0',
  );
  final TextEditingController serialPlaceZController = TextEditingController(
    text: '0',
  );
  AppPage page = AppPage.puzzle;
  SettingsPage settingsPage = SettingsPage.vision;
  PuzzleMode mode = PuzzleMode.cardPuzzle;
  bool solving = false;
  bool hasResult = false;
  bool connected = false;
  bool cameraOnline = false;
  bool serialConnected = false;
  bool polling = false;
  bool tuningOpen = false;
  bool initializedFromBackend = false;
  bool autoThreshold = true;
  int threshold = 128;
  int minPieceArea = 1500;
  String polarityMode = 'AUTO';
  String backgroundMode = 'BLACK';
  int pieceCount = 0;
  double fps = 0;
  double score = 0;
  double solverMs = 0;
  String solverMessage = '';
  String lastCaptureName = '';
  String serialPort = '/dev/ttyUSB0';
  int serialBaud = 115200;
  int serialPickZ = 0;
  int serialPlaceZ = 0;
  int motionPlanCount = 0;
  String serialLastReply = '';
  String serialError = '';
  int serialEventRevision = 0;
  int platformX = 0;
  int platformY = 0;
  int platformZ = 0;
  int platformRotation = 0;
  bool platformPositionValid = false;
  int moveStep = 10;
  int rotationStep = 5;
  List<double>? calibrationVisualA;
  List<double>? calibrationVisualB;
  List<double>? calibrationPlatformA;
  List<double>? calibrationPlatformB;
  bool calibrationValid = false;
  double calibrationScaleX = 0;
  double calibrationScaleY = 0;
  String calibrationTarget = 'a';
  String backendLog = '正在读取后端日志…';
  DateTime lastLogRead = DateTime.fromMillisecondsSinceEpoch(0);
  Uint8List? cameraFrame;
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
    binaryPreview.dispose();
    calibrationScrollController.dispose();
    serialPortController.dispose();
    serialBaudController.dispose();
    serialPickZController.dispose();
    serialPlaceZController.dispose();
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
      connected = snapshot.backendAlive;
      cameraOnline = snapshot.cameraOk;
      solving = snapshot.solving;
      hasResult = snapshot.resultAvailable;
      pieceCount = snapshot.pieceCount;
      fps = snapshot.fps;
      score = snapshot.score;
      solverMs = snapshot.solverMs;
      solverMessage = snapshot.solverMessage;
      serialConnected = snapshot.serialConnected;
      serialPort = snapshot.serialPort;
      serialBaud = snapshot.serialBaud;
      serialPickZ = snapshot.serialPickZ;
      serialPlaceZ = snapshot.serialPlaceZ;
      motionPlanCount = snapshot.motionPlanCount;
      serialLastReply = snapshot.serialLastReply;
      serialError = snapshot.serialError;
      serialEventRevision = snapshot.serialEventRevision;
      platformX = snapshot.platformX;
      platformY = snapshot.platformY;
      platformZ = snapshot.platformZ;
      platformRotation = snapshot.platformRotation;
      platformPositionValid = snapshot.platformPositionValid;
      calibrationVisualA = snapshot.calibrationVisualA;
      calibrationVisualB = snapshot.calibrationVisualB;
      calibrationPlatformA = snapshot.calibrationPlatformA;
      calibrationPlatformB = snapshot.calibrationPlatformB;
      calibrationValid = snapshot.calibrationValid;
      calibrationScaleX = snapshot.calibrationScaleX;
      calibrationScaleY = snapshot.calibrationScaleY;
      if (!tuningOpen) {
        autoThreshold = snapshot.autoThreshold;
        threshold = snapshot.autoThreshold
            ? snapshot.currentThreshold
            : snapshot.manualThreshold;
        polarityMode = snapshot.polarityMode;
        backgroundMode = snapshot.backgroundMode;
        minPieceArea = snapshot.minPieceArea;
      }
      lastCaptureName = snapshot.lastCaptureName;
      if (!initializedFromBackend) {
        mode = _parseMode(snapshot.mode);
        serialPortController.text = snapshot.serialPort;
        serialBaudController.text = snapshot.serialBaud.toString();
        serialPickZController.text = snapshot.serialPickZ.toString();
        serialPlaceZController.text = snapshot.serialPlaceZ.toString();
        initializedFromBackend = true;
      }
      if (update.frame != null) {
        cameraFrame = update.frame;
      }
      if (update.result != null) {
        resultFrame = update.result;
      } else if (update.clearResult) {
        resultFrame = null;
      }
    });
    if (update.binary != null) {
      binaryPreview.value = update.binary;
    }
    final now = DateTime.now();
    if (page == AppPage.settings &&
        settingsPage == SettingsPage.logs &&
        now.difference(lastLogRead) > const Duration(milliseconds: 600)) {
      backendLog = await backend.readBackendLog();
      lastLogRead = now;
      if (mounted) {
        setState(() {});
      }
    }

    if (!mounted) {
      return;
    }
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
    if (solving || !connected || !cameraOnline) {
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
                    child: switch (page) {
                      AppPage.puzzle => _buildPuzzlePage(constraints),
                      AppPage.arm => _buildArmPage(),
                      AppPage.settings => _buildSettingsPage(),
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPuzzlePage(BoxConstraints constraints) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          width: (constraints.maxWidth * 0.31).clamp(285.0, 390.0),
          child: _buildCameraPanel(),
        ),
        const SizedBox(width: 12),
        Expanded(child: _buildControlPanel()),
      ],
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
          const SizedBox(width: 30),
          _HeaderNavButton(
            label: '拼图',
            icon: Icons.dashboard_outlined,
            selected: page == AppPage.puzzle,
            onTap: () => setState(() => page = AppPage.puzzle),
          ),
          const SizedBox(width: 6),
          _HeaderNavButton(
            label: '平台',
            icon: Icons.precision_manufacturing_outlined,
            selected: page == AppPage.arm,
            onTap: () {
              setState(() => page = AppPage.arm);
              if (serialConnected) {
                unawaited(_queryPlatformPosition());
              }
            },
          ),
          const SizedBox(width: 6),
          _HeaderNavButton(
            label: '设置',
            icon: Icons.tune,
            selected: page == AppPage.settings,
            onTap: () => setState(() => page = AppPage.settings),
          ),
          const Spacer(),
          if (serialEventRevision > 0) ...[
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 180),
              child: _SerialOperationBadge(
                key: ValueKey(serialEventRevision),
                success: serialError.isEmpty,
                message: serialError.isEmpty
                    ? serialLastReply
                    : '$serialLastReply：$serialError',
              ),
            ),
            const SizedBox(width: 12),
          ],
          Icon(
            Icons.circle,
            size: 9,
            color: !connected
                ? const Color(0xFFEF4444)
                : cameraOnline
                ? const Color(0xFF10A37F)
                : const Color(0xFFF59E0B),
          ),
          const SizedBox(width: 7),
          Text(
            !connected
                ? '后端离线'
                : cameraOnline
                ? '相机正常'
                : '相机离线',
            style: const TextStyle(
              color: Color(0xFF334155),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(width: 12),
          Text(
            cameraOnline ? '${fps.toStringAsFixed(1)} FPS' : '等待摄像头',
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
            child: cameraFrame == null || !cameraOnline
                ? const Center(
                    child: Text(
                      '摄像头离线\n串口与设置功能仍可使用',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: Color(0xFFCBD5E1),
                        height: 1.7,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  )
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
            _ActionButton(
              label: '设置',
              onPressed: () => setState(() {
                page = AppPage.settings;
                settingsPage = SettingsPage.vision;
              }),
            ),
            if (motionPlanCount > 0) ...[
              const SizedBox(width: 8),
              _ActionButton(label: '发送执行', onPressed: _sendMotionPlan),
            ],
            const SizedBox(width: 9),
            SizedBox(
              height: 50,
              width: 166,
              child: FilledButton(
                onPressed: solving || !connected || !cameraOnline
                    ? null
                    : solve,
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
    if (!connected || !cameraOnline) {
      return;
    }
    await backend.sendControl(mode: backendMode, action: 'capture');
  }

  Future<void> _sendMotionPlan() async {
    if (!connected || motionPlanCount < 1) {
      return;
    }
    await backend.sendControl(action: 'arm_send_plan');
    await Future<void>.delayed(const Duration(milliseconds: 160));
    await _pollBackend();
  }

  Future<void> _movePlatform({
    int x = 0,
    int y = 0,
    int z = 0,
    int rotationCdeg = 0,
  }) async {
    if (!connected) {
      return;
    }
    await backend.sendControl(
      action: 'arm_move_relative',
      armX: x,
      armY: y,
      armZ: z,
      armRotationCdeg: rotationCdeg,
    );
    await Future<void>.delayed(const Duration(milliseconds: 220));
    await _queryPlatformPosition();
  }

  Future<void> _queryPlatformPosition() async {
    if (!connected) {
      return;
    }
    await backend.sendControl(action: 'platform_query_position');
    await Future<void>.delayed(const Duration(milliseconds: 180));
    await _pollBackend();
  }

  Future<void> _homeArm() async {
    if (!connected) {
      return;
    }
    await backend.sendControl(action: 'arm_home');
    await Future<void>.delayed(const Duration(milliseconds: 260));
    await _queryPlatformPosition();
  }

  Future<void> _saveSerialSettings({bool connect = false}) async {
    await backend.sendControl(
      action: connect ? 'serial_connect' : null,
      serialPort: serialPortController.text.trim(),
      serialBaud: int.tryParse(serialBaudController.text.trim()) ?? 115200,
      serialPickZ: int.tryParse(serialPickZController.text.trim()) ?? 0,
      serialPlaceZ: int.tryParse(serialPlaceZController.text.trim()) ?? 0,
    );
    await Future<void>.delayed(const Duration(milliseconds: 180));
    await _pollBackend();
  }

  Future<void> _disconnectSerial() async {
    await backend.sendControl(action: 'serial_disconnect');
    await Future<void>.delayed(const Duration(milliseconds: 120));
    await _pollBackend();
  }

  Future<void> _recordVisualCalibration(
    TapDownDetails details,
    Size size,
  ) async {
    if (!connected || !cameraOnline || size.width <= 0 || size.height <= 0) {
      return;
    }
    final previewX = (details.localPosition.dx / size.width * 360)
        .round()
        .clamp(0, 359);
    final previewY = (details.localPosition.dy / size.height * 640)
        .round()
        .clamp(0, 639);
    await backend.sendControl(
      action: calibrationTarget == 'a'
          ? 'calibration_visual_a'
          : 'calibration_visual_b',
      calibrationPreviewX: previewX,
      calibrationPreviewY: previewY,
    );
    await Future<void>.delayed(const Duration(milliseconds: 120));
    await _pollBackend();
  }

  Future<void> _recordPlatformCalibration(String point) async {
    if (!connected || !serialConnected) {
      return;
    }
    await backend.sendControl(
      action: point == 'a'
          ? 'calibration_platform_a'
          : 'calibration_platform_b',
    );
    await Future<void>.delayed(const Duration(milliseconds: 240));
    await _pollBackend();
  }

  Future<void> _computeCalibration() async {
    if (!connected) {
      return;
    }
    await backend.sendControl(action: 'calibration_compute');
    await Future<void>.delayed(const Duration(milliseconds: 160));
    await _pollBackend();
  }

  String _formatCalibrationPoint(List<double>? point) {
    if (point == null || point.length < 2) {
      return '未记录';
    }
    return '(${point[0].toStringAsFixed(1)}, ${point[1].toStringAsFixed(1)})';
  }

  Widget _buildArmPage() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          width: 300,
          child: Column(
            children: [
              _Panel(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '串口通信',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 16),
                      _ConnectionRow(
                        connected: serialConnected,
                        connectedText: '串口已连接',
                        disconnectedText: '串口未连接',
                      ),
                      const SizedBox(height: 12),
                      Text(
                        '$serialPort  ·  $serialBaud',
                        style: const TextStyle(
                          color: Color(0xFF64748B),
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 18),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton(
                          onPressed: () => setState(() {
                            page = AppPage.settings;
                            settingsPage = SettingsPage.serial;
                          }),
                          child: const Text('打开串口设置'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Expanded(
                child: _Panel(
                  child: Padding(
                    padding: const EdgeInsets.all(18),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          '当前拼图动作',
                          style: TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          motionPlanCount > 0
                              ? '已生成 $motionPlanCount 个完整抓取动作'
                              : '尚未生成抓取动作',
                          style: const TextStyle(
                            color: Color(0xFF64748B),
                            height: 1.5,
                          ),
                        ),
                        const Spacer(),
                        SizedBox(
                          width: double.infinity,
                          height: 48,
                          child: FilledButton(
                            onPressed: motionPlanCount > 0 && connected
                                ? _sendMotionPlan
                                : null,
                            child: const Text('发送并开始执行'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _Panel(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '平台手动控制',
                            style: TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          SizedBox(height: 5),
                          Text(
                            '使用方向键点动平台，每次移动后自动读取当前位置。',
                            style: TextStyle(color: Color(0xFF64748B)),
                          ),
                        ],
                      ),
                      const Spacer(),
                      OutlinedButton.icon(
                        onPressed: serialConnected
                            ? _queryPlatformPosition
                            : null,
                        icon: const Icon(Icons.refresh),
                        label: const Text('读取位置'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  Row(
                    children: [
                      Expanded(
                        child: _PositionCard(
                          label: 'X',
                          value: platformPositionValid
                              ? platformX.toString()
                              : '--',
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: _PositionCard(
                          label: 'Y',
                          value: platformPositionValid
                              ? platformY.toString()
                              : '--',
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: _PositionCard(
                          label: 'Z',
                          value: platformPositionValid
                              ? platformZ.toString()
                              : '--',
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: _PositionCard(
                          label: '角度',
                          value: platformPositionValid
                              ? '${(platformRotation / 100).toStringAsFixed(1)}°'
                              : '--',
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  Expanded(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(
                          flex: 5,
                          child: Container(
                            padding: const EdgeInsets.all(18),
                            decoration: BoxDecoration(
                              color: const Color(0xFFF8FAFC),
                              borderRadius: BorderRadius.circular(15),
                              border: Border.all(
                                color: const Color(0xFFE2E8F0),
                              ),
                            ),
                            child: Column(
                              children: [
                                const Text(
                                  'XY 平面',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                const Spacer(),
                                _PlatformArrowButton(
                                  tooltip: 'Y 负方向',
                                  icon: Icons.keyboard_arrow_up,
                                  onPressed: serialConnected
                                      ? () => _movePlatform(y: -moveStep)
                                      : null,
                                ),
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    _PlatformArrowButton(
                                      tooltip: 'X 负方向',
                                      icon: Icons.keyboard_arrow_left,
                                      onPressed: serialConnected
                                          ? () => _movePlatform(x: -moveStep)
                                          : null,
                                    ),
                                    const SizedBox(width: 56),
                                    _PlatformArrowButton(
                                      tooltip: 'X 正方向',
                                      icon: Icons.keyboard_arrow_right,
                                      onPressed: serialConnected
                                          ? () => _movePlatform(x: moveStep)
                                          : null,
                                    ),
                                  ],
                                ),
                                _PlatformArrowButton(
                                  tooltip: 'Y 正方向',
                                  icon: Icons.keyboard_arrow_down,
                                  onPressed: serialConnected
                                      ? () => _movePlatform(y: moveStep)
                                      : null,
                                ),
                                const Spacer(),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          flex: 6,
                          child: Column(
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: _AxisControlCard(
                                      title: 'Z 轴',
                                      negativeLabel: 'Z −',
                                      positiveLabel: 'Z +',
                                      onNegative: serialConnected
                                          ? () => _movePlatform(z: -moveStep)
                                          : null,
                                      onPositive: serialConnected
                                          ? () => _movePlatform(z: moveStep)
                                          : null,
                                    ),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: _AxisControlCard(
                                      title: '平台旋转',
                                      negativeLabel: '↶',
                                      positiveLabel: '↷',
                                      onNegative: serialConnected
                                          ? () => _movePlatform(
                                              rotationCdeg: -rotationStep * 100,
                                            )
                                          : null,
                                      onPositive: serialConnected
                                          ? () => _movePlatform(
                                              rotationCdeg: rotationStep * 100,
                                            )
                                          : null,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 12),
                              Row(
                                children: [
                                  Expanded(
                                    child: _DropdownField<int>(
                                      label: 'XYZ 单次步长',
                                      value: moveStep,
                                      items: const [1, 5, 10, 20, 50],
                                      itemText: (value) => value.toString(),
                                      onChanged: (value) {
                                        if (value != null) {
                                          setState(() => moveStep = value);
                                        }
                                      },
                                    ),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: _DropdownField<int>(
                                      label: '旋转单次角度',
                                      value: rotationStep,
                                      items: const [1, 5, 10, 15, 30],
                                      itemText: (value) => '$value°',
                                      onChanged: (value) {
                                        if (value != null) {
                                          setState(() => rotationStep = value);
                                        }
                                      },
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 12),
                              SizedBox(
                                width: double.infinity,
                                height: 48,
                                child: OutlinedButton.icon(
                                  onPressed: serialConnected ? _homeArm : null,
                                  icon: const Icon(Icons.home_outlined),
                                  label: const Text('平台归零'),
                                ),
                              ),
                              const Spacer(),
                              Container(
                                width: double.infinity,
                                padding: const EdgeInsets.all(14),
                                decoration: BoxDecoration(
                                  color: const Color(0xFFF8FAFC),
                                  borderRadius: BorderRadius.circular(13),
                                  border: Border.all(
                                    color: const Color(0xFFE2E8F0),
                                  ),
                                ),
                                child: Text(
                                  serialError.isNotEmpty
                                      ? '$serialLastReply\n$serialError'
                                      : serialLastReply.isEmpty
                                      ? '等待平台命令'
                                      : serialLastReply,
                                  style: TextStyle(
                                    color: serialError.isEmpty
                                        ? const Color(0xFF0F766E)
                                        : const Color(0xFFDC2626),
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildSettingsPage() {
    return Column(
      children: [
        _Panel(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Row(
              children: [
                _SettingsTabButton(
                  label: '视觉调参',
                  selected: settingsPage == SettingsPage.vision,
                  onTap: () =>
                      setState(() => settingsPage = SettingsPage.vision),
                ),
                const SizedBox(width: 8),
                _SettingsTabButton(
                  label: '串口设置',
                  selected: settingsPage == SettingsPage.serial,
                  onTap: () =>
                      setState(() => settingsPage = SettingsPage.serial),
                ),
                const SizedBox(width: 8),
                _SettingsTabButton(
                  label: '平台标定',
                  selected: settingsPage == SettingsPage.calibration,
                  onTap: () =>
                      setState(() => settingsPage = SettingsPage.calibration),
                ),
                const SizedBox(width: 8),
                _SettingsTabButton(
                  label: '后端日志',
                  selected: settingsPage == SettingsPage.logs,
                  onTap: () async {
                    backendLog = await backend.readBackendLog();
                    if (mounted) {
                      setState(() => settingsPage = SettingsPage.logs);
                    }
                  },
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 10),
        Expanded(
          child: switch (settingsPage) {
            SettingsPage.vision => _buildVisionSettings(),
            SettingsPage.serial => _buildSerialSettings(),
            SettingsPage.calibration => _buildCalibrationSettings(),
            SettingsPage.logs => _buildLogSettings(),
          },
        ),
      ],
    );
  }

  Widget _buildVisionSettings() {
    return _Panel(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            Expanded(
              flex: 5,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '二值化实时预览',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 12),
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(14),
                      child: ColoredBox(
                        color: const Color(0xFF111827),
                        child: ValueListenableBuilder<Uint8List?>(
                          valueListenable: binaryPreview,
                          builder: (context, bytes, child) {
                            if (bytes == null || !cameraOnline) {
                              return const Center(
                                child: Text(
                                  '摄像头离线',
                                  style: TextStyle(color: Color(0xFFCBD5E1)),
                                ),
                              );
                            }
                            return Image.memory(
                              bytes,
                              fit: BoxFit.contain,
                              gaplessPlayback: true,
                            );
                          },
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 24),
            Expanded(
              flex: 6,
              child: StatefulBuilder(
                builder: (context, setSettingsState) {
                  return SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          '检测参数',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 18),
                        const Text(
                          '背景颜色',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 8),
                        SegmentedButton<String>(
                          segments: const [
                            ButtonSegment(value: 'BLACK', label: Text('黑色')),
                            ButtonSegment(value: 'GREEN', label: Text('绿色')),
                          ],
                          selected: {backgroundMode},
                          showSelectedIcon: false,
                          onSelectionChanged: (values) {
                            setState(() => backgroundMode = values.first);
                            setSettingsState(() {});
                            _queueSettings();
                          },
                        ),
                        const SizedBox(height: 18),
                        Row(
                          children: [
                            const Text(
                              '二值化阈值',
                              style: TextStyle(fontWeight: FontWeight.w700),
                            ),
                            const Spacer(),
                            FilterChip(
                              selected: autoThreshold,
                              label: const Text('自动 OTSU'),
                              onSelected: (_) {
                                setState(() => autoThreshold = true);
                                setSettingsState(() {});
                                _queueSettings();
                              },
                            ),
                          ],
                        ),
                        Slider(
                          value: threshold.toDouble(),
                          min: 0,
                          max: 255,
                          label: threshold.toString(),
                          onChanged: (value) {
                            setState(() {
                              threshold = value.round();
                              autoThreshold = false;
                            });
                            setSettingsState(() {});
                            _queueSettings();
                          },
                        ),
                        Center(
                          child: Text(
                            '当前阈值：$threshold',
                            style: const TextStyle(fontWeight: FontWeight.w800),
                          ),
                        ),
                        const SizedBox(height: 18),
                        const Text(
                          '目标极性',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 8),
                        SegmentedButton<String>(
                          segments: const [
                            ButtonSegment(value: 'AUTO', label: Text('自动')),
                            ButtonSegment(value: 'LIGHT', label: Text('亮色')),
                            ButtonSegment(value: 'DARK', label: Text('暗色')),
                          ],
                          selected: {polarityMode},
                          showSelectedIcon: false,
                          onSelectionChanged: (values) {
                            setState(() => polarityMode = values.first);
                            setSettingsState(() {});
                            _queueSettings();
                          },
                        ),
                        const SizedBox(height: 20),
                        Row(
                          children: [
                            const Text(
                              '最小碎片面积',
                              style: TextStyle(fontWeight: FontWeight.w700),
                            ),
                            const Spacer(),
                            Text(
                              minPieceArea.toString(),
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ],
                        ),
                        Slider(
                          value: minPieceArea.toDouble(),
                          min: 100,
                          max: 10000,
                          divisions: 99,
                          onChanged: (value) {
                            setState(() => minPieceArea = value.round());
                            setSettingsState(() {});
                            _queueSettings();
                          },
                        ),
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

  Widget _buildSerialSettings() {
    return _Panel(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Text(
                  '串口设置',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                ),
                const Spacer(),
                _ConnectionRow(
                  connected: serialConnected,
                  connectedText: '已连接',
                  disconnectedText: '未连接',
                ),
              ],
            ),
            const SizedBox(height: 22),
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: _CoordinateField(
                    label: '串口设备',
                    unit: 'CH340 通常为 /dev/ttyUSB0',
                    controller: serialPortController,
                    numeric: false,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: _DropdownField<int>(
                    label: '波特率',
                    value:
                        const [
                          9600,
                          19200,
                          38400,
                          57600,
                          115200,
                          230400,
                          460800,
                          921600,
                        ].contains(serialBaud)
                        ? serialBaud
                        : 115200,
                    items: const [
                      9600,
                      19200,
                      38400,
                      57600,
                      115200,
                      230400,
                      460800,
                      921600,
                    ],
                    itemText: (value) => '$value bit/s',
                    onChanged: (value) {
                      if (value != null) {
                        setState(() {
                          serialBaud = value;
                          serialBaudController.text = value.toString();
                        });
                      }
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _CoordinateField(
                    label: '自动抓取Z',
                    unit: '坐标单位',
                    controller: serialPickZController,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: _CoordinateField(
                    label: '自动放置Z',
                    unit: '坐标单位',
                    controller: serialPlaceZController,
                  ),
                ),
                const Spacer(flex: 2),
              ],
            ),
            const SizedBox(height: 22),
            Row(
              children: [
                SizedBox(
                  height: 48,
                  child: FilledButton(
                    onPressed: connected
                        ? () => _saveSerialSettings(connect: true)
                        : null,
                    child: Text(serialConnected ? '重新连接' : '保存并连接'),
                  ),
                ),
                const SizedBox(width: 10),
                SizedBox(
                  height: 48,
                  child: OutlinedButton(
                    onPressed: connected
                        ? () => _saveSerialSettings(connect: false)
                        : null,
                    child: const Text('仅保存'),
                  ),
                ),
                const SizedBox(width: 10),
                SizedBox(
                  height: 48,
                  child: OutlinedButton(
                    onPressed: serialConnected ? _disconnectSerial : null,
                    child: const Text('断开串口'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: const Color(0xFFE2E8F0)),
              ),
              child: Text(
                serialError.isEmpty
                    ? (serialLastReply.isEmpty ? '等待串口操作' : serialLastReply)
                    : '$serialLastReply\n$serialError',
                style: TextStyle(
                  color: serialError.isEmpty
                      ? const Color(0xFF0F766E)
                      : const Color(0xFFDC2626),
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCalibrationSettings() {
    return _Panel(
      child: Scrollbar(
        controller: calibrationScrollController,
        thumbVisibility: true,
        child: SingleChildScrollView(
          controller: calibrationScrollController,
          padding: const EdgeInsets.fromLTRB(20, 20, 28, 20),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 300,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '视觉点选择',
                      style: TextStyle(
                        fontSize: 19,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      calibrationTarget == 'a'
                          ? '当前：点击 A4 纸右上角'
                          : '当前：点击 A4 纸左下角',
                      style: const TextStyle(
                        color: Color(0xFF2563EB),
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      height: 520,
                      child: Center(
                        child: AspectRatio(
                          aspectRatio: 9 / 16,
                          child: LayoutBuilder(
                            builder: (context, constraints) {
                              return GestureDetector(
                                onTapDown: cameraOnline
                                    ? (details) => _recordVisualCalibration(
                                        details,
                                        constraints.biggest,
                                      )
                                    : null,
                                child: ClipRRect(
                                  borderRadius: BorderRadius.circular(14),
                                  child: ColoredBox(
                                    color: const Color(0xFF111827),
                                    child: cameraFrame == null || !cameraOnline
                                        ? const Center(
                                            child: Text(
                                              '摄像头离线\n上线后可选择视觉点',
                                              textAlign: TextAlign.center,
                                              style: TextStyle(
                                                color: Color(0xFFCBD5E1),
                                                height: 1.6,
                                              ),
                                            ),
                                          )
                                        : Image.memory(
                                            cameraFrame!,
                                            fit: BoxFit.fill,
                                            gaplessPlayback: true,
                                            filterQuality: FilterQuality.low,
                                          ),
                                  ),
                                ),
                              );
                            },
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 24),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Text(
                          '平台两点标定',
                          style: TextStyle(
                            fontSize: 22,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const Spacer(),
                        _ConnectionRow(
                          connected: serialConnected,
                          connectedText: '平台已连接',
                          disconnectedText: '平台未连接',
                        ),
                      ],
                    ),
                    const SizedBox(height: 7),
                    const Text(
                      '分别记录 A4 纸右上角与左下角的视觉坐标和平台坐标，再计算像素到平台的换算关系。',
                      style: TextStyle(color: Color(0xFF64748B), height: 1.5),
                    ),
                    const SizedBox(height: 16),
                    SegmentedButton<String>(
                      segments: const [
                        ButtonSegment(value: 'a', label: Text('A：右上角')),
                        ButtonSegment(value: 'b', label: Text('B：左下角')),
                      ],
                      selected: {calibrationTarget},
                      showSelectedIcon: false,
                      onSelectionChanged: (values) {
                        setState(() => calibrationTarget = values.first);
                      },
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: _CalibrationPointCard(
                            title: 'A · A4 纸右上角',
                            visualText: _formatCalibrationPoint(
                              calibrationVisualA,
                            ),
                            platformText: _formatCalibrationPoint(
                              calibrationPlatformA,
                            ),
                            selected: calibrationTarget == 'a',
                            onSelect: () =>
                                setState(() => calibrationTarget = 'a'),
                            onRecordPlatform: serialConnected
                                ? () => _recordPlatformCalibration('a')
                                : null,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: _CalibrationPointCard(
                            title: 'B · A4 纸左下角',
                            visualText: _formatCalibrationPoint(
                              calibrationVisualB,
                            ),
                            platformText: _formatCalibrationPoint(
                              calibrationPlatformB,
                            ),
                            selected: calibrationTarget == 'b',
                            onSelect: () =>
                                setState(() => calibrationTarget = 'b'),
                            onRecordPlatform: serialConnected
                                ? () => _recordPlatformCalibration('b')
                                : null,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(15),
                      decoration: BoxDecoration(
                        color: calibrationValid
                            ? const Color(0xFFECFDF5)
                            : const Color(0xFFFFFBEB),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: calibrationValid
                              ? const Color(0xFFA7F3D0)
                              : const Color(0xFFFDE68A),
                        ),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            calibrationValid
                                ? Icons.check_circle_outline
                                : Icons.info_outline,
                            color: calibrationValid
                                ? const Color(0xFF059669)
                                : const Color(0xFFD97706),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              calibrationValid
                                  ? '标定有效：X比例 ${calibrationScaleX.toStringAsFixed(5)}，'
                                        'Y比例 ${calibrationScaleY.toStringAsFixed(5)}'
                                  : '尚未完成标定，自动抓取动作不会发送。',
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          FilledButton(
                            onPressed: connected ? _computeCalibration : null,
                            child: const Text('计算并保存'),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      '两点法适合摄像头基本垂直、视觉轴与平台轴基本平行的情况。'
                      '如果画面有明显透视或旋转，仅用两个点不能完整校正，后续应改用 3 点仿射或 4 点单应性标定。'
                      'Z 轴高度仍使用串口设置中的抓取 Z 与放置 Z。',
                      style: TextStyle(color: Color(0xFF64748B), height: 1.55),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildLogSettings() {
    return _Panel(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Text(
                  '后端日志',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                ),
                const Spacer(),
                OutlinedButton.icon(
                  onPressed: () async {
                    backendLog = await backend.readBackendLog();
                    if (mounted) {
                      setState(() {});
                    }
                  },
                  icon: const Icon(Icons.refresh),
                  label: const Text('刷新'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Expanded(
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF111827),
                  borderRadius: BorderRadius.circular(13),
                ),
                child: SingleChildScrollView(
                  reverse: true,
                  child: SelectableText(
                    backendLog,
                    style: const TextStyle(
                      color: Color(0xFFD1FAE5),
                      fontFamily: 'PuzzleLatin',
                      fontSize: 12,
                      height: 1.45,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _changeThreshold(int amount, StateSetter setSheetState) {
    setSheetState(() {
      threshold = (threshold + amount).clamp(0, 255);
      autoThreshold = false;
    });
    _queueSettings();
  }

  void _changeArea(int amount, StateSetter setSheetState) {
    setSheetState(() {
      minPieceArea = (minPieceArea + amount).clamp(100, 50000);
    });
    _queueSettings();
  }

  void _queueSettings() {
    settingsTimer?.cancel();
    settingsTimer = Timer(
      const Duration(milliseconds: 110),
      () => unawaited(
        backend.sendControl(
          autoThreshold: autoThreshold,
          manualThreshold: threshold,
          polarityMode: polarityMode,
          backgroundMode: backgroundMode,
          minPieceArea: minPieceArea,
        ),
      ),
    );
  }

  // 保留旧弹窗作为触摸屏兼容入口，新界面统一使用设置页。
  // ignore: unused_element
  Future<void> _showTuningSheet() async {
    tuningOpen = true;
    try {
      await showModalBottomSheet<void>(
        context: context,
        backgroundColor: Colors.transparent,
        isScrollControlled: true,
        builder: (context) {
          return StatefulBuilder(
            builder: (context, setSheetState) {
              return Container(
                height: 500,
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
                                child: ValueListenableBuilder<Uint8List?>(
                                  valueListenable: binaryPreview,
                                  builder: (context, bytes, child) {
                                    if (bytes == null) {
                                      return const SizedBox.expand();
                                    }
                                    return Image.memory(
                                      bytes,
                                      fit: BoxFit.contain,
                                      gaplessPlayback: true,
                                      filterQuality: FilterQuality.low,
                                    );
                                  },
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
                          const Text(
                            '背景颜色',
                            style: TextStyle(
                              color: Color(0xFF334155),
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 7),
                          SegmentedButton<String>(
                            segments: const [
                              ButtonSegment(value: 'BLACK', label: Text('黑色')),
                              ButtonSegment(value: 'GREEN', label: Text('绿色')),
                            ],
                            selected: {backgroundMode},
                            showSelectedIcon: false,
                            onSelectionChanged: (values) {
                              setSheetState(() {
                                backgroundMode = values.first;
                              });
                              _queueSettings();
                            },
                          ),
                          const SizedBox(height: 12),
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
                                  setSheetState(() => autoThreshold = true);
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
                              setSheetState(() {
                                threshold = value.round();
                                autoThreshold = false;
                              });
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
                              setSheetState(() {
                                polarityMode = values.first;
                              });
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
                                onPressed: () =>
                                    _changeArea(-250, setSheetState),
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
                                onPressed: () =>
                                    _changeArea(250, setSheetState),
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
    } finally {
      tuningOpen = false;
      unawaited(_pollBackend());
    }
  }
}

class _HeaderNavButton extends StatelessWidget {
  const _HeaderNavButton({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        height: 38,
        padding: const EdgeInsets.symmetric(horizontal: 13),
        decoration: BoxDecoration(
          color: selected ? const Color(0xFFEFF6FF) : Colors.transparent,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: selected ? const Color(0xFFBFDBFE) : Colors.transparent,
          ),
        ),
        child: Row(
          children: [
            Icon(
              icon,
              size: 17,
              color: selected
                  ? const Color(0xFF2563EB)
                  : const Color(0xFF64748B),
            ),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                color: selected
                    ? const Color(0xFF1D4ED8)
                    : const Color(0xFF475569),
                fontWeight: FontWeight.w800,
                fontSize: 13,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SerialOperationBadge extends StatelessWidget {
  const _SerialOperationBadge({
    super.key,
    required this.success,
    required this.message,
  });

  final bool success;
  final String message;

  @override
  Widget build(BuildContext context) {
    final foreground = success
        ? const Color(0xFF047857)
        : const Color(0xFFB91C1C);
    return Container(
      constraints: const BoxConstraints(maxWidth: 230),
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
      decoration: BoxDecoration(
        color: success ? const Color(0xFFECFDF5) : const Color(0xFFFEF2F2),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: success ? const Color(0xFFA7F3D0) : const Color(0xFFFECACA),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            success ? Icons.check_circle_outline : Icons.error_outline,
            size: 17,
            color: foreground,
          ),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              '${success ? '发送成功' : '发送失败'} · $message',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: foreground,
                fontSize: 12,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SettingsTabButton extends StatelessWidget {
  const _SettingsTabButton({
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
      child: SizedBox(
        height: 46,
        child: selected
            ? FilledButton(onPressed: onTap, child: Text(label))
            : OutlinedButton(onPressed: onTap, child: Text(label)),
      ),
    );
  }
}

class _PositionCard extends StatelessWidget {
  const _PositionCard({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        children: [
          Text(
            label,
            style: const TextStyle(
              color: Color(0xFF64748B),
              fontWeight: FontWeight.w800,
            ),
          ),
          const Spacer(),
          Text(
            value,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
          ),
        ],
      ),
    );
  }
}

class _PlatformArrowButton extends StatelessWidget {
  const _PlatformArrowButton({
    required this.tooltip,
    required this.icon,
    required this.onPressed,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: SizedBox(
        width: 58,
        height: 54,
        child: FilledButton(
          onPressed: onPressed,
          style: FilledButton.styleFrom(
            padding: EdgeInsets.zero,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(13),
            ),
          ),
          child: Icon(icon, size: 32),
        ),
      ),
    );
  }
}

class _AxisControlCard extends StatelessWidget {
  const _AxisControlCard({
    required this.title,
    required this.negativeLabel,
    required this.positiveLabel,
    required this.onNegative,
    required this.onPositive,
  });

  final String title;
  final String negativeLabel;
  final String positiveLabel;
  final VoidCallback? onNegative;
  final VoidCallback? onPositive;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: onNegative,
                  child: Text(negativeLabel),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: FilledButton(
                  onPressed: onPositive,
                  child: Text(positiveLabel),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _DropdownField<T> extends StatelessWidget {
  const _DropdownField({
    required this.label,
    required this.value,
    required this.items,
    required this.itemText,
    required this.onChanged,
  });

  final String label;
  final T value;
  final List<T> items;
  final String Function(T value) itemText;
  final ValueChanged<T?> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: Color(0xFF334155),
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 8),
        DropdownButtonFormField<T>(
          initialValue: value,
          items: items
              .map(
                (item) => DropdownMenuItem<T>(
                  value: item,
                  child: Text(itemText(item)),
                ),
              )
              .toList(),
          onChanged: onChanged,
          decoration: InputDecoration(
            filled: true,
            fillColor: const Color(0xFFF8FAFC),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: Color(0xFFD6DEE8)),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: Color(0xFFD6DEE8)),
            ),
          ),
        ),
      ],
    );
  }
}

class _CalibrationPointCard extends StatelessWidget {
  const _CalibrationPointCard({
    required this.title,
    required this.visualText,
    required this.platformText,
    required this.selected,
    required this.onSelect,
    required this.onRecordPlatform,
  });

  final String title;
  final String visualText;
  final String platformText;
  final bool selected;
  final VoidCallback onSelect;
  final VoidCallback? onRecordPlatform;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onSelect,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        padding: const EdgeInsets.all(15),
        decoration: BoxDecoration(
          color: selected ? const Color(0xFFEFF6FF) : const Color(0xFFF8FAFC),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: selected ? const Color(0xFF60A5FA) : const Color(0xFFE2E8F0),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 11),
            Text('视觉坐标  $visualText'),
            const SizedBox(height: 6),
            Text('平台坐标  $platformText'),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: onRecordPlatform,
                icon: const Icon(Icons.add_location_alt_outlined),
                label: const Text('读取当前位置并记录'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CoordinateField extends StatelessWidget {
  const _CoordinateField({
    required this.label,
    required this.unit,
    required this.controller,
    this.numeric = true,
  });

  final String label;
  final String unit;
  final TextEditingController controller;
  final bool numeric;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: Color(0xFF334155),
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: controller,
          keyboardType: numeric
              ? const TextInputType.numberWithOptions(signed: true)
              : TextInputType.text,
          decoration: InputDecoration(
            filled: true,
            fillColor: const Color(0xFFF8FAFC),
            suffixText: unit,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: Color(0xFFD6DEE8)),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: Color(0xFFD6DEE8)),
            ),
          ),
        ),
      ],
    );
  }
}

class _ConnectionRow extends StatelessWidget {
  const _ConnectionRow({
    required this.connected,
    required this.connectedText,
    required this.disconnectedText,
  });

  final bool connected;
  final String connectedText;
  final String disconnectedText;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          Icons.circle,
          size: 10,
          color: connected ? const Color(0xFF10A37F) : const Color(0xFFEF4444),
        ),
        const SizedBox(width: 7),
        Text(
          connected ? connectedText : disconnectedText,
          style: const TextStyle(
            color: Color(0xFF334155),
            fontWeight: FontWeight.w800,
          ),
        ),
      ],
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
