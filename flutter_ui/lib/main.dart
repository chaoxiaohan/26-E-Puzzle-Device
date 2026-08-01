import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:puzzle_flutter_ui/backend_bridge.dart';

void main() {
  runApp(const PuzzleStudioApp());
}

enum PuzzleMode { firstQuestion, normalPuzzle, cardPuzzle }

enum AppPage { puzzle, arm, settings }

enum SettingsPage { vision, serial, calibration, logs, system }

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
        scrollbarTheme: ScrollbarThemeData(
          thumbVisibility: WidgetStateProperty.all(true),
          trackVisibility: WidgetStateProperty.all(true),
          interactive: true,
          thickness: WidgetStateProperty.all(14),
          radius: const Radius.circular(7),
          thumbColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.dragged)) {
              return const Color(0xFF2563EB);
            }
            if (states.contains(WidgetState.hovered)) {
              return const Color(0xFF3B82F6);
            }
            return const Color(0xFF94A3B8);
          }),
          trackColor: WidgetStateProperty.all(const Color(0xFFE2E8F0)),
          trackBorderColor: WidgetStateProperty.all(const Color(0xFFCBD5E1)),
        ),
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
  final ScrollController _serialScrollController = ScrollController();
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
  bool competitionMode = false;
  bool competitionActive = false;
  int competitionRetryCount = 0;
  bool connected = false;
  int _offlineCount = 0;
  static const int _offlineRestartThreshold = 25; // ~2s at 80ms polling
  bool cameraOnline = false;
  bool serialConnected = false;
  bool polling = false;
  bool tuningOpen = false;
  bool settingsSyncPending = false;
  bool visionSettingsDirty = false;
  bool visionSettingsFlushRunning = false;
  bool initializedFromBackend = false;
  bool autoThreshold = true;
  int threshold = 128;
  bool _showBinaryPreview = true; // toggle: binary vs normal camera preview
  int minPieceArea = 1500;
  int assemblyGapPixels = 36;
  String polarityMode = 'AUTO';
  String backgroundMode = 'GREEN';
  String _greenMethod = 'border';
  bool _greenAuto = true;
  int _greenDetectedHueMin = 0;
  int _greenDetectedHueMax = 0;
  int _greenDetectedSatMin = 0;
  int _greenDetectedValMin = 0;
  int _greenHueMin = 30;
  int _greenHueMax = 95;
  int _greenSatMin = 20;
  int _greenValMin = 6;
  int _greenCloseKernel = 7;
  int _greenCloseIter = 2;
  int _paperCloseKernel = 5;
  int _paperCloseIter = 1;
  int cameraWidth = 720;
  int cameraHeight = 1280;
  int roiX = 10;
  int roiY = 100;
  int roiWidth = 700;
  int roiHeight = 900;
  int _assemblySplitY = 0;
  int pieceCount = 0;
  double fps = 0;
  double score = 0;
  List<Map<String, dynamic>> scoreItems = [];
  double solverMs = 0;
  String solverMessage = '';
  String lastCaptureName = '';
  String serialPort = '/dev/ttyUSB0';
  String serialActivePort = '';
  bool serialReconnecting = false;
  bool serialDevicePresent = false;
  int serialBaud = 115200;
  int serialPickZ = 0;
  int serialPlaceZ = 0;
  int motionPlanCount = 0;
  List<SolvedPieceShape> solvedDisplay = [];
  String serialLastReply = '';
  String serialError = '';
  List<Map<String, dynamic>> _serialRawLog = [];
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
  List<double>? calibrationVisualC;
  List<double>? calibrationVisualD;
  List<double>? calibrationVisualE;
  List<double>? calibrationVisualF;
  List<double>? calibrationPlatformA;
  List<double>? calibrationPlatformB;
  List<double>? calibrationPlatformC;
  List<double>? calibrationPlatformD;
  List<double>? calibrationPlatformE;
  List<double>? calibrationPlatformF;
  bool calibrationValid = false;
  double calibrationScaleX = 0;
  double calibrationScaleY = 0;
  double calibrationAffineDeterminant = 0;
  double calibrationRmsError = 0;
  double calibrationMaxError = 0;
  String calibrationTarget = 'a';
  Offset? _previewPointA;
  Offset? _previewPointB;
  Offset? _previewPointC;
  Offset? _previewPointD;
  Offset? _previewPointE;
  Offset? _previewPointF;
  String backendLog = '正在读取后端日志…';
  DateTime lastLogRead = DateTime.fromMillisecondsSinceEpoch(0);
  Uint8List? cameraFrame;
  Uint8List? resultFrame;
  List<Map<String, dynamic>> candidateItems = [];
  List<Uint8List> candidateFrames = [];
  Timer? pollTimer;

  String get resultTitle {
    return switch (mode) {
      PuzzleMode.firstQuestion => '第一问结果',
      PuzzleMode.normalPuzzle => '普通拼图实图',
      PuzzleMode.cardPuzzle => '扑克牌拼接实图',
    };
  }

  String get resultHint {
    if (!connected) {
      return backend.isRestarting ? '视觉后端重连中…' : '视觉后端未连接';
    }
    return switch (solverMessage) {
      'NO STABLE' || 'CARD NO STABLE' => '请保持碎片静止后重试',
      'CARD NEED 2-4' => '需要识别到2至4块碎片',
      'NO RECT' || 'CARD NO RECT' => '未找到可用矩形',
      'TEMPLATE FAIL' => '模板匹配失败，请重新学习',
      'TEMPLATE TOUCH' => '模板匹配存在轻微接触',
      'TEMPLATE MATCH' => '模板匹配中…',
      'LEARN OK' => '模板学习完成',
      'LEARN FAIL' => '模板学习失败',
      'LEARN NEED 2-4' => '学习需要2至4块碎片',
      'SOLVE GAP2' => '碎片已自动分离',
      'SOLVE TOUCH' => '碎片存在轻微接触',
      'NO SAFE' => '结果存在重叠，已拒绝',
      'SOLVE ERROR' || 'CARD ERROR' => '求解异常，请重试',
      'FALLBACK' => '已降级搬运方案',
      'STOPPED' => '已停止解算',
      'AUTO SEND WAIT' => '解算完成，等待平台连接后自动发送',
      'AUTO EXECUTING' => '已发送动作，平台开始执行',
      'AUTO BEST 80S' => '已到80秒，采用最高置信度方案',
      'AUTO BEST EXECUTING' => '已采用最高置信度方案并开始执行',
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
    // 通知后端关闭
    backend.sendControl(action: 'shutdown');
    binaryPreview.dispose();
    calibrationScrollController.dispose();
    _serialScrollController.dispose();
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
      _offlineCount++;
      if (_offlineCount == _offlineRestartThreshold && !backend.isRestarting) {
        // Backend has been unresponsive for ~2 seconds — try to restart it.
        await backend.restartBackend();
        _offlineCount = 0;
      }
      if (connected) {
        setState(() => connected = false);
      }
      return;
    }

    // Backend responded — reset the offline counter.
    _offlineCount = 0;

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
      scoreItems = snapshot.scoreItems;
      solverMs = snapshot.solverMs;
      solverMessage = snapshot.solverMessage;
      serialConnected = snapshot.serialConnected;
      serialPort = snapshot.serialPort;
      serialActivePort = snapshot.serialActivePort;
      serialReconnecting = snapshot.serialReconnecting;
      serialDevicePresent = snapshot.serialDevicePresent;
      serialBaud = snapshot.serialBaud;
      serialPickZ = snapshot.serialPickZ;
      serialPlaceZ = snapshot.serialPlaceZ;
      motionPlanCount = snapshot.motionPlanCount;
      solvedDisplay = snapshot.solvedDisplay;
      competitionMode = snapshot.competitionMode;
      competitionActive = snapshot.competitionActive;
      competitionRetryCount = snapshot.competitionRetryCount;
      serialLastReply = snapshot.serialLastReply;
      serialError = snapshot.serialError;
      _serialRawLog = snapshot.serialRawLog;
      serialEventRevision = snapshot.serialEventRevision;
      platformX = snapshot.platformX;
      platformY = snapshot.platformY;
      platformZ = snapshot.platformZ;
      platformRotation = snapshot.platformRotation;
      platformPositionValid = snapshot.platformPositionValid;
      calibrationVisualA = snapshot.calibrationVisualA;
      calibrationVisualB = snapshot.calibrationVisualB;
      calibrationVisualC = snapshot.calibrationVisualC;
      calibrationVisualD = snapshot.calibrationVisualD;
      calibrationVisualE = snapshot.calibrationVisualE;
      calibrationVisualF = snapshot.calibrationVisualF;
      calibrationPlatformA = snapshot.calibrationPlatformA;
      calibrationPlatformB = snapshot.calibrationPlatformB;
      calibrationPlatformC = snapshot.calibrationPlatformC;
      calibrationPlatformD = snapshot.calibrationPlatformD;
      calibrationPlatformE = snapshot.calibrationPlatformE;
      calibrationPlatformF = snapshot.calibrationPlatformF;
      calibrationValid = snapshot.calibrationValid;
      calibrationScaleX = snapshot.calibrationScaleX;
      calibrationScaleY = snapshot.calibrationScaleY;
      calibrationAffineDeterminant = snapshot.calibrationAffineDeterminant;
      calibrationRmsError = snapshot.calibrationRmsError;
      calibrationMaxError = snapshot.calibrationMaxError;
      _assemblySplitY = snapshot.assemblySplitY;
      _greenDetectedHueMin = snapshot.greenDetectedHueMin;
      _greenDetectedHueMax = snapshot.greenDetectedHueMax;
      _greenDetectedSatMin = snapshot.greenDetectedSatMin;
      _greenDetectedValMin = snapshot.greenDetectedValMin;
      if (!tuningOpen && !settingsSyncPending) {
        autoThreshold = snapshot.autoThreshold;
        threshold = snapshot.autoThreshold
            ? snapshot.currentThreshold
            : snapshot.manualThreshold;
        polarityMode = snapshot.polarityMode;
        backgroundMode = snapshot.backgroundMode;
        if (snapshot.greenMethod.isNotEmpty) {
          _greenMethod = snapshot.greenMethod;
        }
        _greenAuto = snapshot.greenAuto;
        _greenHueMin = snapshot.greenHueMin;
        _greenHueMax = snapshot.greenHueMax;
        _greenSatMin = snapshot.greenSatMin;
        _greenValMin = snapshot.greenValMin;
        _greenCloseKernel = snapshot.greenCloseKernel;
        _greenCloseIter = snapshot.greenCloseIter;
        _paperCloseKernel = snapshot.paperCloseKernel;
        _paperCloseIter = snapshot.paperCloseIter;
        minPieceArea = snapshot.minPieceArea;
        assemblyGapPixels = snapshot.assemblyGapPixels;
        cameraWidth = snapshot.cameraWidth;
        cameraHeight = snapshot.cameraHeight;
        roiX = snapshot.roiX;
        roiY = snapshot.roiY;
        roiWidth = snapshot.roiWidth;
        roiHeight = snapshot.roiHeight;
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
      candidateItems = snapshot.candidateItems;
      if (update.candidates != null) {
        candidateFrames = update.candidates!;
      } else if (update.clearCandidates) {
        candidateFrames = [];
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
      competitionActive = competitionMode;
      hasResult = false;
      resultFrame = null;
      solvedDisplay = [];
      candidateItems = [];
      candidateFrames = [];
    });
    await backend.sendControl(
      mode: backendMode,
      action: competitionMode ? 'competition_start' : 'solve',
    );
  }

  Future<void> _stopSolving() async {
    if (!connected) {
      return;
    }
    setState(() {
      solving = false;
      competitionActive = false;
    });
    await backend.sendControl(action: 'stop_solve');
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
          child: Column(
            children: [
              Expanded(child: _buildCameraPanel()),
              const SizedBox(height: 10),
              SizedBox(height: 124, child: _buildSolvedOutlinePanel()),
            ],
          ),
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
                ? backend.isRestarting
                      ? '后端重连中…'
                      : '后端离线'
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
        child: LayoutBuilder(
          builder: (context, constraints) {
            // 分割线在widget中的y坐标 = assemblySplitY / cameraHeight * widgetHeight
            final lineY = cameraHeight > 0
                ? (_assemblySplitY / cameraHeight) * constraints.maxHeight
                : constraints.maxHeight / 2;
            return ClipRRect(
              borderRadius: BorderRadius.circular(14),
              child: Stack(
                children: [
                  ColoredBox(
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
                  // 上/下半区分割线
                  if (cameraFrame != null &&
                      cameraOnline &&
                      _assemblySplitY > 0)
                    Positioned(
                      left: 0,
                      right: 0,
                      top: lineY,
                      child: CustomPaint(painter: _SplitLinePainter()),
                    ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _buildSolvedOutlinePanel() {
    return _Panel(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(
                  Icons.grid_view_rounded,
                  size: 16,
                  color: Color(0xFF2563EB),
                ),
                SizedBox(width: 7),
                Text(
                  '最终拼装框',
                  style: TextStyle(
                    color: Color(0xFF334155),
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 5),
            Expanded(
              child: solvedDisplay.isEmpty
                  ? const Center(
                      child: Text(
                        '等待解算',
                        style: TextStyle(
                          color: Color(0xFF94A3B8),
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    )
                  : CustomPaint(
                      painter: _SolvedOutlinePainter(solvedDisplay),
                      child: const SizedBox.expand(),
                    ),
            ),
          ],
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
                  onTap: () => unawaited(_changeMode(PuzzleMode.firstQuestion)),
                ),
                const SizedBox(width: 8),
                _ModeButton(
                  label: '普通拼图',
                  selected: mode == PuzzleMode.normalPuzzle,
                  onTap: () => unawaited(_changeMode(PuzzleMode.normalPuzzle)),
                ),
                const SizedBox(width: 8),
                _ModeButton(
                  label: '扑克牌',
                  selected: mode == PuzzleMode.cardPuzzle,
                  onTap: () => unawaited(_changeMode(PuzzleMode.cardPuzzle)),
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

  Future<void> _changeMode(PuzzleMode value) async {
    if (solving || competitionActive) {
      return;
    }
    if (value == mode && !competitionMode) {
      return;
    }
    setState(() {
      mode = value;
      competitionActive = competitionMode;
      hasResult = false;
      resultFrame = null;
      solvedDisplay = [];
      candidateItems = [];
      candidateFrames = [];
    });
    await backend.sendControl(
      mode: backendMode,
      action: competitionMode ? 'competition_start' : null,
    );
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
          if (scoreItems.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: _ScoreBreakdown(items: scoreItems),
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
            if (competitionActive) ...[
              const SizedBox(width: 15),
              _Metric(label: '重试', value: competitionRetryCount.toString()),
            ],
            const Spacer(),
            _ActionButton(label: '拍照', onPressed: _capture),
            if (mode == PuzzleMode.firstQuestion) ...[
              const SizedBox(width: 8),
              _ActionButton(
                label: solverMessage == 'LEARN OK' ? '已学习' : '学习',
                onPressed: _learnTemplate,
              ),
            ],
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
            if (mode == PuzzleMode.cardPuzzle &&
                candidateFrames.isNotEmpty) ...[
              const SizedBox(width: 8),
              _ActionButton(
                label: '候选池 ${candidateFrames.length}',
                onPressed: _showCandidatePool,
              ),
            ],
            const SizedBox(width: 9),
            SizedBox(
              height: 50,
              width: 166,
              child: FilledButton(
                onPressed: solving || competitionActive
                    ? _stopSolving
                    : !connected || !cameraOnline
                    ? null
                    : solve,
                style: FilledButton.styleFrom(
                  backgroundColor: solving || competitionActive
                      ? const Color(0xFFDC2626)
                      : const Color(0xFF2563EB),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(13),
                  ),
                ),
                child: Text(
                  solving || competitionActive ? '停止解算' : '开始求解',
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

  Future<void> _showCandidatePool() async {
    final count = candidateItems.length < candidateFrames.length
        ? candidateItems.length
        : candidateFrames.length;
    if (count == 0) {
      return;
    }
    await showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return Dialog(
          insetPadding: const EdgeInsets.all(24),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          child: SizedBox(
            width: 1080,
            height: 650,
            child: Padding(
              padding: const EdgeInsets.all(22),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(
                        Icons.grid_view_rounded,
                        color: Color(0xFF2563EB),
                      ),
                      const SizedBox(width: 10),
                      const Text(
                        '扑克牌候选池',
                        style: TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Text(
                        '共 $count 个 · 点击候选查看评分详情',
                        style: const TextStyle(color: Color(0xFF64748B)),
                      ),
                      const Spacer(),
                      IconButton(
                        onPressed: () => Navigator.of(dialogContext).pop(),
                        icon: const Icon(Icons.close_rounded),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Expanded(
                    child: GridView.builder(
                      itemCount: count,
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                            crossAxisCount: 4,
                            crossAxisSpacing: 14,
                            mainAxisSpacing: 14,
                            childAspectRatio: 1.15,
                          ),
                      itemBuilder: (context, index) {
                        final item = candidateItems[index];
                        final selected = item['selected'] == true;
                        final rank =
                            (item['rank'] as num?)?.toInt() ?? index + 1;
                        final score = (item['score'] as num?)?.toDouble() ?? 0;
                        return InkWell(
                          borderRadius: BorderRadius.circular(15),
                          onTap: () => _showCandidateDetail(index),
                          child: Container(
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: selected
                                  ? const Color(0xFFEFF6FF)
                                  : const Color(0xFFF8FAFC),
                              borderRadius: BorderRadius.circular(15),
                              border: Border.all(
                                color: selected
                                    ? const Color(0xFF2563EB)
                                    : const Color(0xFFE2E8F0),
                                width: selected ? 2 : 1,
                              ),
                            ),
                            child: Column(
                              children: [
                                Row(
                                  children: [
                                    Text(
                                      '候选 $rank',
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w800,
                                      ),
                                    ),
                                    const Spacer(),
                                    if (selected)
                                      const Text(
                                        '最终选择',
                                        style: TextStyle(
                                          color: Color(0xFF2563EB),
                                          fontWeight: FontWeight.w800,
                                        ),
                                      ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                Expanded(
                                  child: ClipRRect(
                                    borderRadius: BorderRadius.circular(9),
                                    child: Image.memory(
                                      candidateFrames[index],
                                      width: double.infinity,
                                      fit: BoxFit.contain,
                                      gaplessPlayback: true,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 7),
                                Row(
                                  children: [
                                    Text(
                                      '总分 ${(score * 100).toStringAsFixed(1)}%',
                                      style: const TextStyle(
                                        color: Color(0xFF334155),
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                    const Spacer(),
                                    Text(
                                      '几何 T${item['geometry_tier'] ?? 0}',
                                      style: const TextStyle(
                                        color: Color(0xFF64748B),
                                        fontSize: 12,
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ),
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
      },
    );
  }

  Future<void> _showCandidateDetail(int index) async {
    if (index >= candidateItems.length || index >= candidateFrames.length) {
      return;
    }
    final item = candidateItems[index];
    final scoreItems =
        (item['score_items'] as List<dynamic>?)
            ?.whereType<Map>()
            .map((value) => Map<String, dynamic>.from(value))
            .toList() ??
        [];
    final rank = (item['rank'] as num?)?.toInt() ?? index + 1;
    final score = (item['score'] as num?)?.toDouble() ?? 0;
    await showDialog<void>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: Text('候选 $rank · 总分 ${(score * 100).toStringAsFixed(1)}%'),
          content: SizedBox(
            width: 760,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  height: 360,
                  child: Image.memory(
                    candidateFrames[index],
                    fit: BoxFit.contain,
                    gaplessPlayback: true,
                  ),
                ),
                if (scoreItems.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  _ScoreBreakdown(items: scoreItems),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('关闭'),
            ),
          ],
        );
      },
    );
  }

  Future<void> _sendMotionPlan() async {
    if (!connected || motionPlanCount < 1) {
      return;
    }
    await backend.sendControl(action: 'arm_send_plan');
    await Future<void>.delayed(const Duration(milliseconds: 160));
    await _pollBackend();
  }

  Future<void> _learnTemplate() async {
    if (!connected || !cameraOnline) {
      return;
    }
    await backend.sendControl(action: 'learn_template');
    await Future<void>.delayed(const Duration(milliseconds: 300));
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
    // Save the tap position for visual dot overlay on the preview.
    final localPos = details.localPosition;
    setState(() {
      switch (calibrationTarget) {
        case 'a':
          _previewPointA = localPos;
        case 'b':
          _previewPointB = localPos;
        case 'c':
          _previewPointC = localPos;
        case 'd':
          _previewPointD = localPos;
        case 'e':
          _previewPointE = localPos;
        case 'f':
          _previewPointF = localPos;
      }
    });
    await backend.sendControl(
      action: 'calibration_visual_$calibrationTarget',
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
    await backend.sendControl(action: 'calibration_platform_$point');
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
                        disconnectedText: serialReconnecting
                            ? '自动重连中'
                            : serialDevicePresent
                            ? '串口待连接'
                            : '未发现USB串口',
                      ),
                      const SizedBox(height: 12),
                      Text(
                        '${serialActivePort.isEmpty ? serialPort : serialActivePort}'
                        '  ·  $serialBaud',
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
                                      items: const [
                                        10,
                                        50,
                                        100,
                                        200,
                                        500,
                                        6400,
                                      ],
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
                const SizedBox(width: 8),
                _SettingsTabButton(
                  label: '系统',
                  selected: settingsPage == SettingsPage.system,
                  onTap: () =>
                      setState(() => settingsPage = SettingsPage.system),
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
            SettingsPage.system => _buildSystemSettings(),
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
                  Row(
                    children: [
                      const Text(
                        '实时预览',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const Spacer(),
                      SegmentedButton<bool>(
                        segments: const [
                          ButtonSegment(value: true, label: Text('二值化')),
                          ButtonSegment(value: false, label: Text('原图')),
                        ],
                        selected: {_showBinaryPreview},
                        showSelectedIcon: false,
                        onSelectionChanged: (values) {
                          setState(() => _showBinaryPreview = values.first);
                        },
                        style: const ButtonStyle(
                          visualDensity: VisualDensity.compact,
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                      ),
                    ],
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
                            final imageBytes = _showBinaryPreview
                                ? bytes
                                : cameraFrame;
                            if (imageBytes == null || !cameraOnline) {
                              return const Center(
                                child: Text(
                                  '摄像头离线',
                                  style: TextStyle(color: Color(0xFFCBD5E1)),
                                ),
                              );
                            }
                            return Image.memory(
                              imageBytes,
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
              child: SingleChildScrollView(
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
                        _queueSettings();
                      },
                    ),
                    if (backgroundMode == 'GREEN') ...[
                      const SizedBox(height: 18),
                      const Text(
                        '绿膜提取方法',
                        style: TextStyle(fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 8),
                      SegmentedButton<String>(
                        segments: const [
                          ButtonSegment(value: 'border', label: Text('边框采样')),
                          ButtonSegment(value: 'largest', label: Text('最大连通域')),
                        ],
                        selected: {_greenMethod},
                        showSelectedIcon: false,
                        onSelectionChanged: (values) {
                          setState(() => _greenMethod = values.first);
                          _queueSettings();
                        },
                        style: const ButtonStyle(
                          visualDensity: VisualDensity.compact,
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                      ),
                      const SizedBox(height: 10),
                      FilterChip(
                        selected: _greenAuto,
                        label: const Text('自动取样绿色背景'),
                        onSelected: (selected) {
                          setState(() => _greenAuto = selected);
                          _queueSettings();
                        },
                      ),
                    ],
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
                          onSelected: (selected) {
                            setState(() => autoThreshold = selected);
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
                        _queueSettings();
                      },
                    ),
                    const Divider(height: 34),
                    // 绿膜参数（仅GREEN+最大连通域时显示）
                    if (backgroundMode == 'GREEN' &&
                        _greenMethod == 'largest') ...[
                      const Text(
                        '绿膜形态学参数',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          fontSize: 15,
                        ),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        '光照差时增大、光照好时减小，越小边角越锐利',
                        style: TextStyle(
                          color: Color(0xFF94A3B8),
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 10),
                      _buildGreenParamSlider(
                        '绿色闭运算核大小',
                        _greenCloseKernel,
                        1,
                        21,
                        (v) {
                          setState(() => _greenCloseKernel = v.round());
                          _queueSettings();
                        },
                      ),
                      _buildGreenParamSlider(
                        '绿色闭运算迭代次数',
                        _greenCloseIter,
                        0,
                        5,
                        (v) {
                          setState(() => _greenCloseIter = v.round());
                          _queueSettings();
                        },
                      ),
                      _buildGreenParamSlider(
                        'A4纸闭运算核大小',
                        _paperCloseKernel,
                        1,
                        15,
                        (v) {
                          setState(() => _paperCloseKernel = v.round());
                          _queueSettings();
                        },
                      ),
                      _buildGreenParamSlider(
                        'A4纸闭运算迭代次数',
                        _paperCloseIter,
                        0,
                        5,
                        (v) {
                          setState(() => _paperCloseIter = v.round());
                          _queueSettings();
                        },
                      ),
                      const SizedBox(height: 6),
                      if (_greenAuto)
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: const Color(0xFFEFF6FF),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Text(
                            _greenDetectedHueMax > 0
                                ? '当前自动范围  H $_greenDetectedHueMin–$_greenDetectedHueMax  '
                                      'S≥$_greenDetectedSatMin  V≥$_greenDetectedValMin'
                                : '正在从画面中取样绿色背景…',
                            style: const TextStyle(
                              color: Color(0xFF2563EB),
                              fontWeight: FontWeight.w700,
                              fontSize: 12,
                            ),
                          ),
                        )
                      else ...[
                        Row(
                          children: [
                            const Text(
                              'HSV色相',
                              style: TextStyle(
                                fontWeight: FontWeight.w700,
                                fontSize: 12,
                              ),
                            ),
                            const Spacer(),
                            Text(
                              '$_greenHueMin–$_greenHueMax',
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 12,
                                color: Color(0xFF2563EB),
                              ),
                            ),
                          ],
                        ),
                        RangeSlider(
                          values: RangeValues(
                            _greenHueMin.toDouble(),
                            _greenHueMax.toDouble(),
                          ),
                          min: 0,
                          max: 180,
                          divisions: 36,
                          onChanged: (values) {
                            setState(() {
                              _greenHueMin = values.start.round();
                              _greenHueMax = values.end.round();
                            });
                            _queueSettings();
                          },
                        ),
                        _buildGreenParamSlider('饱和度下限', _greenSatMin, 0, 255, (
                          v,
                        ) {
                          setState(() => _greenSatMin = v.round());
                          _queueSettings();
                        }),
                        _buildGreenParamSlider('亮度下限', _greenValMin, 0, 255, (
                          v,
                        ) {
                          setState(() => _greenValMin = v.round());
                          _queueSettings();
                        }),
                      ],
                      const Divider(height: 28),
                    ],
                    Row(
                      children: [
                        const Text(
                          '检测区域 ROI',
                          style: TextStyle(fontWeight: FontWeight.w800),
                        ),
                        const Spacer(),
                        Text(
                          '完整画面 $cameraWidth×$cameraHeight',
                          style: const TextStyle(
                            color: Color(0xFF64748B),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '当前 ROI：X $roiX，Y $roiY，宽 $roiWidth，高 $roiHeight',
                      style: const TextStyle(
                        color: Color(0xFF2563EB),
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 8),
                    _buildRoiSlider(
                      label: 'X',
                      value: roiX,
                      minimum: 0,
                      maximum: cameraWidth > 80 ? cameraWidth - 80 : 1,
                      onChanged: (value) {
                        setState(() {
                          roiX = value;
                          roiWidth = roiWidth
                              .clamp(80, cameraWidth - roiX)
                              .toInt();
                        });
                        _queueSettings();
                      },
                    ),
                    _buildRoiSlider(
                      label: 'Y',
                      value: roiY,
                      minimum: 0,
                      maximum: cameraHeight > 80 ? cameraHeight - 80 : 1,
                      onChanged: (value) {
                        setState(() {
                          roiY = value;
                          roiHeight = roiHeight
                              .clamp(80, cameraHeight - roiY)
                              .toInt();
                        });
                        _queueSettings();
                      },
                    ),
                    _buildRoiSlider(
                      label: '宽',
                      value: roiWidth,
                      minimum: 80,
                      maximum: cameraWidth - roiX,
                      onChanged: (value) {
                        setState(() => roiWidth = value);
                        _queueSettings();
                      },
                    ),
                    _buildRoiSlider(
                      label: '高',
                      value: roiHeight,
                      minimum: 80,
                      maximum: cameraHeight - roiY,
                      onChanged: (value) {
                        setState(() => roiHeight = value);
                        _queueSettings();
                      },
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        OutlinedButton(
                          onPressed: () {
                            setState(() {
                              roiX = 0;
                              roiY = 0;
                              roiWidth = cameraWidth;
                              roiHeight = cameraHeight;
                            });
                            _queueSettings();
                          },
                          child: const Text('ROI 铺满画面'),
                        ),
                        const SizedBox(width: 10),
                        OutlinedButton(
                          onPressed: () {
                            setState(() {
                              roiWidth = cameraWidth < 700 ? cameraWidth : 700;
                              roiHeight = cameraHeight < 900
                                  ? cameraHeight
                                  : 900;
                              roiX = (cameraWidth - roiWidth) ~/ 2;
                              roiY = cameraHeight >= 1000 ? 100 : 0;
                            });
                            _queueSettings();
                          },
                          child: const Text('恢复默认 ROI'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildGreenParamSlider(
    String label,
    int value,
    int min,
    int max,
    ValueChanged<double> onChanged,
  ) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(
        children: [
          SizedBox(
            width: 120,
            child: Text(
              label,
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12),
            ),
          ),
          Expanded(
            child: Slider(
              value: value.toDouble(),
              min: min.toDouble(),
              max: max.toDouble(),
              divisions: max - min,
              onChanged: onChanged,
              onChangeEnd: (_) => _queueSettings(),
            ),
          ),
          SizedBox(
            width: 30,
            child: Text(
              value.toString(),
              style: const TextStyle(
                fontWeight: FontWeight.w800,
                fontSize: 12,
                color: Color(0xFF2563EB),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRoiSlider({
    required String label,
    required int value,
    required int minimum,
    required int maximum,
    required ValueChanged<int> onChanged,
  }) {
    final safeMaximum = maximum > minimum ? maximum : minimum + 1;
    final safeValue = value.clamp(minimum, safeMaximum).toInt();
    return Row(
      children: [
        SizedBox(
          width: 28,
          child: Text(
            label,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
        Expanded(
          child: Slider(
            value: safeValue.toDouble(),
            min: minimum.toDouble(),
            max: safeMaximum.toDouble(),
            onChanged: (newValue) => onChanged(newValue.round()),
          ),
        ),
        SizedBox(
          width: 42,
          child: Text(
            value.toString(),
            textAlign: TextAlign.right,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
      ],
    );
  }

  Widget _buildSerialSettings() {
    return _Panel(
      child: Scrollbar(
        controller: _serialScrollController,
        thumbVisibility: true,
        interactive: true,
        child: SingleChildScrollView(
          controller: _serialScrollController,
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
                    disconnectedText: serialReconnecting
                        ? '自动重连中'
                        : serialDevicePresent
                        ? '待连接'
                        : '未发现USB串口',
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
                      unit: '自动兼容 /dev/ttyUSB0 与 ttyUSB1',
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
                  '实际设备：'
                  '${serialActivePort.isEmpty ? "等待设备上线" : serialActivePort}\n'
                  '${serialError.isEmpty ? (serialLastReply.isEmpty ? "等待串口操作" : serialLastReply) : "$serialLastReply\n$serialError"}',
                  style: TextStyle(
                    color: serialError.isEmpty
                        ? const Color(0xFF0F766E)
                        : const Color(0xFFDC2626),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(height: 24),
              // 原始收发日志
              Row(
                children: [
                  const Text(
                    '原始收发日志',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                  ),
                  const Spacer(),
                  Text(
                    '${_serialRawLog.length} 条',
                    style: const TextStyle(
                      color: Color(0xFF94A3B8),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                height: 220,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF0F172A),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: _serialRawLog.isEmpty
                    ? const Center(
                        child: Text(
                          '暂无收发数据',
                          style: TextStyle(color: Color(0xFF64748B)),
                        ),
                      )
                    : ListView.builder(
                        itemCount: _serialRawLog.length,
                        itemBuilder: (context, index) {
                          final entry = _serialRawLog[index];
                          final isTx = entry['d'] == 'TX';
                          final hex = entry['hex'] as String;
                          final parsed = _parseSerialFrame(hex, isTx);
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${entry['d']}  $hex',
                                  style: TextStyle(
                                    fontFamily: 'PuzzleLatin',
                                    fontSize: 11,
                                    color: isTx
                                        ? const Color(0xFF7DD3FC)
                                        : const Color(0xFF86EFAC),
                                    height: 1.4,
                                  ),
                                ),
                                if (parsed != null)
                                  Text(
                                    parsed,
                                    style: const TextStyle(
                                      fontFamily: 'PuzzleLatin',
                                      fontSize: 10,
                                      color: Color(0xFFFDE68A),
                                      height: 1.3,
                                    ),
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
                      switch (calibrationTarget) {
                        'a' => '当前：记录左上区域点 A',
                        'b' => '当前：记录右上区域点 B',
                        'c' => '当前：记录左中区域点 C',
                        'd' => '当前：记录右中区域点 D',
                        'e' => '当前：记录左下区域点 E',
                        _ => '当前：记录右下区域点 F',
                      },
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
                              final size = constraints.biggest;
                              return GestureDetector(
                                onTapDown: cameraOnline
                                    ? (details) => _recordVisualCalibration(
                                        details,
                                        size,
                                      )
                                    : null,
                                child: ClipRRect(
                                  borderRadius: BorderRadius.circular(14),
                                  child: Stack(
                                    children: [
                                      ColoredBox(
                                        color: const Color(0xFF111827),
                                        child:
                                            cameraFrame == null || !cameraOnline
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
                                                fit: BoxFit.contain,
                                                gaplessPlayback: true,
                                                filterQuality:
                                                    FilterQuality.low,
                                              ),
                                      ),
                                      // Calibration dot overlay.
                                      if (cameraFrame != null && cameraOnline)
                                        CustomPaint(
                                          size: Size.infinite,
                                          painter: _CalibrationDotPainter(
                                            pointA: _previewPointA,
                                            pointB: _previewPointB,
                                            pointC: _previewPointC,
                                            pointD: _previewPointD,
                                            pointE: _previewPointE,
                                            pointF: _previewPointF,
                                            selected: calibrationTarget,
                                          ),
                                        ),
                                    ],
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
                          '平台六点仿射标定',
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
                      '依次记录六组视觉坐标与平台坐标，点位可以任意选择，'
                      '但应分散覆盖整个抓取和放置区域。系统使用最小二乘拟合，'
                      '降低单个点测量误差造成的整体偏差。',
                      style: TextStyle(color: Color(0xFF64748B), height: 1.5),
                    ),
                    const SizedBox(height: 16),
                    SegmentedButton<String>(
                      segments: const [
                        ButtonSegment(value: 'a', label: Text('A')),
                        ButtonSegment(value: 'b', label: Text('B')),
                        ButtonSegment(value: 'c', label: Text('C')),
                        ButtonSegment(value: 'd', label: Text('D')),
                        ButtonSegment(value: 'e', label: Text('E')),
                        ButtonSegment(value: 'f', label: Text('F')),
                      ],
                      selected: {calibrationTarget},
                      showSelectedIcon: false,
                      onSelectionChanged: (values) {
                        setState(() => calibrationTarget = values.first);
                      },
                    ),
                    const SizedBox(height: 16),
                    LayoutBuilder(
                      builder: (context, constraints) {
                        final cardWidth = constraints.maxWidth >= 720
                            ? (constraints.maxWidth - 24) / 3
                            : constraints.maxWidth;
                        return Wrap(
                          spacing: 12,
                          runSpacing: 12,
                          children: [
                            SizedBox(
                              width: cardWidth,
                              child: _CalibrationPointCard(
                                title: 'A · 左上区域',
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
                            SizedBox(
                              width: cardWidth,
                              child: _CalibrationPointCard(
                                title: 'B · 右上区域',
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
                            SizedBox(
                              width: cardWidth,
                              child: _CalibrationPointCard(
                                title: 'C · 左中区域',
                                visualText: _formatCalibrationPoint(
                                  calibrationVisualC,
                                ),
                                platformText: _formatCalibrationPoint(
                                  calibrationPlatformC,
                                ),
                                selected: calibrationTarget == 'c',
                                onSelect: () =>
                                    setState(() => calibrationTarget = 'c'),
                                onRecordPlatform: serialConnected
                                    ? () => _recordPlatformCalibration('c')
                                    : null,
                              ),
                            ),
                            SizedBox(
                              width: cardWidth,
                              child: _CalibrationPointCard(
                                title: 'D · 右中区域',
                                visualText: _formatCalibrationPoint(
                                  calibrationVisualD,
                                ),
                                platformText: _formatCalibrationPoint(
                                  calibrationPlatformD,
                                ),
                                selected: calibrationTarget == 'd',
                                onSelect: () =>
                                    setState(() => calibrationTarget = 'd'),
                                onRecordPlatform: serialConnected
                                    ? () => _recordPlatformCalibration('d')
                                    : null,
                              ),
                            ),
                            SizedBox(
                              width: cardWidth,
                              child: _CalibrationPointCard(
                                title: 'E · 左下区域',
                                visualText: _formatCalibrationPoint(
                                  calibrationVisualE,
                                ),
                                platformText: _formatCalibrationPoint(
                                  calibrationPlatformE,
                                ),
                                selected: calibrationTarget == 'e',
                                onSelect: () =>
                                    setState(() => calibrationTarget = 'e'),
                                onRecordPlatform: serialConnected
                                    ? () => _recordPlatformCalibration('e')
                                    : null,
                              ),
                            ),
                            SizedBox(
                              width: cardWidth,
                              child: _CalibrationPointCard(
                                title: 'F · 右下区域',
                                visualText: _formatCalibrationPoint(
                                  calibrationVisualF,
                                ),
                                platformText: _formatCalibrationPoint(
                                  calibrationPlatformF,
                                ),
                                selected: calibrationTarget == 'f',
                                onSelect: () =>
                                    setState(() => calibrationTarget = 'f'),
                                onRecordPlatform: serialConnected
                                    ? () => _recordPlatformCalibration('f')
                                    : null,
                              ),
                            ),
                          ],
                        );
                      },
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
                                  ? '仿射标定有效：X轴单位比例 '
                                        '${calibrationScaleX.toStringAsFixed(5)}，'
                                        'Y轴单位比例 '
                                        '${calibrationScaleY.toStringAsFixed(5)}，'
                                        '均方根误差 '
                                        '${calibrationRmsError.toStringAsFixed(1)}，'
                                        '最大误差 '
                                        '${calibrationMaxError.toStringAsFixed(1)}'
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
                      '六点不需要固定在 A4 纸角上，但不要集中在同一区域。'
                      '建议按左上、右上、左中、右中、左下、右下分布，'
                      '并覆盖拼图最终放置位置。标定后误差越小越好；'
                      '若最大误差明显高于其他点，应重新记录对应点。'
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

  Widget _buildSystemSettings() {
    return _Panel(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '系统控制',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            const Text(
              '比赛运行方式与后端进程控制。',
              style: TextStyle(color: Color(0xFF64748B), height: 1.5),
            ),
            const SizedBox(height: 20),
            Container(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: const Color(0xFFE2E8F0)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(
                        Icons.space_bar_rounded,
                        color: Color(0xFF2563EB),
                      ),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '拼接物体间距',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            SizedBox(height: 3),
                            Text(
                              '控制相邻碎片边到边的目标距离，0 表示贴合。',
                              style: TextStyle(
                                color: Color(0xFF64748B),
                                height: 1.35,
                              ),
                            ),
                          ],
                        ),
                      ),
                      Text(
                        '$assemblyGapPixels px',
                        style: const TextStyle(
                          color: Color(0xFF2563EB),
                          fontSize: 16,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ],
                  ),
                  Row(
                    children: [
                      const Text('0'),
                      Expanded(
                        child: Slider(
                          value: assemblyGapPixels.toDouble(),
                          min: 0,
                          max: 80,
                          divisions: 80,
                          label: '$assemblyGapPixels px',
                          onChanged: (value) {
                            setState(() => assemblyGapPixels = value.round());
                            settingsSyncPending = true;
                          },
                          onChangeEnd: (_) => _queueSettings(),
                        ),
                      ),
                      const Text('80'),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.fromLTRB(16, 10, 10, 10),
              decoration: BoxDecoration(
                color: competitionMode
                    ? const Color(0xFFEFF6FF)
                    : const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(
                  color: competitionMode
                      ? const Color(0xFF93C5FD)
                      : const Color(0xFFE2E8F0),
                ),
              ),
              child: Row(
                children: [
                  Icon(
                    Icons.sports_score_rounded,
                    color: competitionMode
                        ? const Color(0xFF2563EB)
                        : const Color(0xFF64748B),
                  ),
                  const SizedBox(width: 14),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '比赛模式',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        SizedBox(height: 4),
                        Text(
                          '点击第一问、普通拼图或扑克牌后立即解算；结果不合格自动重试，合格后自动发送执行。',
                          style: TextStyle(
                            color: Color(0xFF64748B),
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Switch(
                    value: competitionMode,
                    onChanged: (value) async {
                      setState(() {
                        competitionMode = value;
                        if (!value) {
                          competitionActive = false;
                          solving = false;
                        }
                      });
                      await backend.sendControl(
                        competitionMode: value,
                        action: value ? null : 'stop_solve',
                      );
                    },
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              height: 50,
              child: OutlinedButton.icon(
                onPressed: () async {
                  await backend.restartBackend();
                },
                icon: const Icon(Icons.restart_alt, size: 18),
                label: const Text('重启后端'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: const Color(0xFFF59E0B),
                  side: const BorderSide(color: Color(0xFFF59E0B)),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(13),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              '关闭前端应用时后端也会自动退出。',
              style: TextStyle(color: Color(0xFF94A3B8), fontSize: 13),
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
    visionSettingsDirty = true;
    settingsSyncPending = true;
    if (!visionSettingsFlushRunning) {
      unawaited(_flushSettings());
    }
  }

  Future<void> _flushSettings() async {
    visionSettingsFlushRunning = true;
    try {
      while (mounted && visionSettingsDirty) {
        visionSettingsDirty = false;
        await backend.sendControl(
          autoThreshold: autoThreshold,
          manualThreshold: threshold,
          polarityMode: polarityMode,
          backgroundMode: backgroundMode,
          greenMethod: _greenMethod,
          greenAuto: _greenAuto,
          greenHueMin: _greenHueMin,
          greenHueMax: _greenHueMax,
          greenSatMin: _greenSatMin,
          greenValMin: _greenValMin,
          greenCloseKernel: _greenCloseKernel,
          greenCloseIter: _greenCloseIter,
          paperCloseKernel: _paperCloseKernel,
          paperCloseIter: _paperCloseIter,
          minPieceArea: minPieceArea,
          assemblyGapPixels: assemblyGapPixels,
          roiX: roiX,
          roiY: roiY,
          roiWidth: roiWidth,
          roiHeight: roiHeight,
        );
        await Future<void>.delayed(const Duration(milliseconds: 80));
      }
    } finally {
      visionSettingsFlushRunning = false;
      if (mounted && !visionSettingsDirty) {
        settingsSyncPending = false;
        await _pollBackend();
      } else if (mounted) {
        _queueSettings();
      }
    }
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
                          Row(
                            children: [
                              const Text(
                                '实时预览',
                                style: TextStyle(
                                  color: Color(0xFF111827),
                                  fontSize: 17,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                              const Spacer(),
                              SegmentedButton<bool>(
                                segments: const [
                                  ButtonSegment(
                                    value: true,
                                    label: Text('二值化'),
                                  ),
                                  ButtonSegment(
                                    value: false,
                                    label: Text('原图'),
                                  ),
                                ],
                                selected: {_showBinaryPreview},
                                showSelectedIcon: false,
                                onSelectionChanged: (values) {
                                  setSheetState(
                                    () => _showBinaryPreview = values.first,
                                  );
                                },
                                style: const ButtonStyle(
                                  visualDensity: VisualDensity.compact,
                                  tapTargetSize:
                                      MaterialTapTargetSize.shrinkWrap,
                                ),
                              ),
                            ],
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
                                    final imageBytes = _showBinaryPreview
                                        ? bytes
                                        : cameraFrame;
                                    if (imageBytes == null) {
                                      return const SizedBox.expand();
                                    }
                                    return Image.memory(
                                      imageBytes,
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
                          if (backgroundMode == 'GREEN') ...[
                            const SizedBox(height: 12),
                            const Text(
                              '绿膜提取方法',
                              style: TextStyle(
                                color: Color(0xFF334155),
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(height: 7),
                            SegmentedButton<String>(
                              segments: const [
                                ButtonSegment(
                                  value: 'border',
                                  label: Text('边框采样'),
                                ),
                                ButtonSegment(
                                  value: 'largest',
                                  label: Text('最大连通域'),
                                ),
                              ],
                              selected: {_greenMethod},
                              showSelectedIcon: false,
                              onSelectionChanged: (values) {
                                setSheetState(
                                  () => _greenMethod = values.first,
                                );
                                _queueSettings();
                              },
                              style: const ButtonStyle(
                                visualDensity: VisualDensity.compact,
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              ),
                            ),
                          ],
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
                                onSelected: (selected) {
                                  setSheetState(() => autoThreshold = selected);
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

  String? _parseSerialFrame(String hex, bool isTx) {
    try {
      final bytes = hex.split(' ').map((s) => int.parse(s, radix: 16)).toList();
      if (bytes.length < 6) return null;
      if (bytes[0] != 0xAA || bytes[1] != 0x55) return null;
      final cmd = bytes[2];
      final flags = bytes[3];
      final len = bytes[5];
      if (bytes.length < 6 + len) return null;

      String flagStr = '';
      if (flags & 0x01 != 0) flagStr += ' REL';
      if (flags & 0x10 != 0) flagStr += ' RETRY';
      if (flags & 0x20 != 0) flagStr += ' ACK';

      if (isTx) {
        switch (cmd) {
          case 0x10:
            if (len >= 28) {
              final payload = bytes.sublist(6, 6 + len);
              final taskId = payload[0];
              final idx = payload[1];
              final cnt = payload[2];
              final pieceId = payload[3];
              final pickX = _i32le(payload, 4);
              final pickY = _i32le(payload, 8);
              final pickZ = _i32le(payload, 12);
              final placeX = _i32le(payload, 16);
              final placeY = _i32le(payload, 20);
              final placeZ = _i32le(payload, 24);
              final rot = _i16le(payload, 28);
              return '→ 抓取动作 T$taskId #$idx/$cnt 碎片$pieceId'
                  ' 取($pickX,$pickY,$pickZ) 放($placeX,$placeY,$placeZ) ${rot / 100.0}°$flagStr';
            }
            break;
          case 0x11:
            if (len >= 1) {
              return '→ 执行任务 T${bytes[6]}$flagStr';
            }
            break;
          case 0x20:
            if (len >= 15) {
              final payload = bytes.sublist(6, 6 + len);
              final ctrlType = payload[0];
              final x = _i32le(payload, 1);
              final y = _i32le(payload, 5);
              final z = _i32le(payload, 9);
              final r = _i16le(payload, 13);
              final typeName = [
                '',
                '绝对移动',
                '相对移动',
                '归零',
                '查询位置',
              ][ctrlType.clamp(0, 4)];
              return '→ $typeName ($x,$y,$z) ${r / 100.0}°$flagStr';
            }
            break;
          default:
            return '→ CMD 0x${cmd.toRadixString(16).toUpperCase().padLeft(2, '0')} LEN=$len$flagStr';
        }
      } else {
        switch (cmd) {
          case 0x80:
            if (len >= 1) {
              return '← OK seq=${bytes[6]}$flagStr';
            }
            break;
          case 0x81:
            if (len >= 1) {
              return '← RETRY seq=${bytes[6]}$flagStr';
            }
            break;
          default:
            return '← CMD 0x${cmd.toRadixString(16).toUpperCase().padLeft(2, '0')} LEN=$len$flagStr';
        }
      }
    } catch (_) {
      return null;
    }
    return null;
  }

  static int _i32le(List<int> bytes, int offset) {
    return (bytes[offset] & 0xFF) |
        ((bytes[offset + 1] & 0xFF) << 8) |
        ((bytes[offset + 2] & 0xFF) << 16) |
        ((bytes[offset + 3] & 0xFF) << 24);
  }

  static int _i16le(List<int> bytes, int offset) {
    final v = (bytes[offset] & 0xFF) | ((bytes[offset + 1] & 0xFF) << 8);
    return v > 0x7FFF ? v - 0x10000 : v;
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

class _CalibrationDotPainter extends CustomPainter {
  _CalibrationDotPainter({
    this.pointA,
    this.pointB,
    this.pointC,
    this.pointD,
    this.pointE,
    this.pointF,
    this.selected = 'a',
  });

  final Offset? pointA;
  final Offset? pointB;
  final Offset? pointC;
  final Offset? pointD;
  final Offset? pointE;
  final Offset? pointF;
  final String selected;

  static const Color _colorA = Color(0xFFEF4444); // Red
  static const Color _colorB = Color(0xFF3B82F6); // Blue
  static const Color _colorC = Color(0xFF10B981); // Green
  static const Color _colorD = Color(0xFFF59E0B); // Amber
  static const Color _colorE = Color(0xFF8B5CF6); // Purple
  static const Color _colorF = Color(0xFF06B6D4); // Cyan

  @override
  void paint(Canvas canvas, Size size) {
    _drawPoint(canvas, size, pointA, 'A', _colorA, selected == 'a');
    _drawPoint(canvas, size, pointB, 'B', _colorB, selected == 'b');
    _drawPoint(canvas, size, pointC, 'C', _colorC, selected == 'c');
    _drawPoint(canvas, size, pointD, 'D', _colorD, selected == 'd');
    _drawPoint(canvas, size, pointE, 'E', _colorE, selected == 'e');
    _drawPoint(canvas, size, pointF, 'F', _colorF, selected == 'f');
  }

  void _drawPoint(
    Canvas canvas,
    Size bounds,
    Offset? point,
    String label,
    Color color,
    bool isSelected,
  ) {
    if (point == null) {
      return;
    }
    final r = isSelected ? 7.0 : 5.0;

    // White outer ring for contrast
    canvas.drawCircle(
      point,
      r + 2,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.fill,
    );

    // Colored dot
    canvas.drawCircle(
      point,
      r,
      Paint()
        ..color = color
        ..style = PaintingStyle.fill,
    );

    // Selected highlight ring
    if (isSelected) {
      canvas.drawCircle(
        point,
        r + 3,
        Paint()
          ..color = color.withAlpha(90)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
    }

    // Label text below the dot
    final textPainter = TextPainter(
      text: TextSpan(
        text: label,
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w900,
          shadows: const [
            Shadow(color: Colors.white, blurRadius: 3),
            Shadow(color: Colors.white, blurRadius: 3),
          ],
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();

    final textOffset = Offset(
      point.dx - textPainter.width / 2,
      point.dy + r + 3,
    );
    // Keep label within bounds
    final clampedDx = textOffset.dx
        .clamp(2.0, bounds.width - textPainter.width - 2)
        .toDouble();
    final clampedDy = textOffset.dy
        .clamp(2.0, bounds.height - textPainter.height - 2)
        .toDouble();
    textPainter.paint(canvas, Offset(clampedDx, clampedDy));
  }

  @override
  bool shouldRepaint(covariant _CalibrationDotPainter oldDelegate) {
    return pointA != oldDelegate.pointA ||
        pointB != oldDelegate.pointB ||
        pointC != oldDelegate.pointC ||
        pointD != oldDelegate.pointD ||
        pointE != oldDelegate.pointE ||
        pointF != oldDelegate.pointF ||
        selected != oldDelegate.selected;
  }
}

class _SplitLinePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color =
          const Color(0x80F59E0B) // 半透明琥珀色
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;

    final dashWidth = 10.0;
    final gapWidth = 6.0;
    var x = 0.0;
    final y = 0.0; // drawn at Positioned top
    while (x < size.width) {
      canvas.drawLine(
        Offset(x, y),
        Offset((x + dashWidth).clamp(0, size.width), y),
        paint,
      );
      x += dashWidth + gapWidth;
    }
  }

  @override
  bool shouldRepaint(covariant _SplitLinePainter oldDelegate) => false;
}

class _SolvedOutlinePainter extends CustomPainter {
  const _SolvedOutlinePainter(this.shapes);

  final List<SolvedPieceShape> shapes;

  @override
  void paint(Canvas canvas, Size size) {
    final validShapes = shapes.where((shape) => shape.points.length >= 3);
    final allPoints = [
      for (final shape in validShapes)
        for (final point in shape.points) point,
    ];
    if (allPoints.isEmpty) {
      return;
    }

    var minX = allPoints.first[0];
    var maxX = minX;
    var minY = allPoints.first[1];
    var maxY = minY;
    for (final point in allPoints.skip(1)) {
      if (point[0] < minX) minX = point[0];
      if (point[0] > maxX) maxX = point[0];
      if (point[1] < minY) minY = point[1];
      if (point[1] > maxY) maxY = point[1];
    }

    final sourceWidth = (maxX - minX).clamp(1.0, double.infinity).toDouble();
    final sourceHeight = (maxY - minY).clamp(1.0, double.infinity).toDouble();
    final scaleX = (size.width - 18) / sourceWidth;
    final scaleY = (size.height - 10) / sourceHeight;
    final scale = scaleX < scaleY ? scaleX : scaleY;
    final left = (size.width - sourceWidth * scale) * 0.5;
    final top = (size.height - sourceHeight * scale) * 0.5;
    Offset mapPoint(List<double> point) => Offset(
      left + (point[0] - minX) * scale,
      top + (point[1] - minY) * scale,
    );

    final colors = [
      const Color(0xFF2563EB),
      const Color(0xFF16A34A),
      const Color(0xFFEA580C),
      const Color(0xFF9333EA),
    ];
    for (final shape in validShapes) {
      final path = Path()
        ..moveTo(
          mapPoint(shape.points.first).dx,
          mapPoint(shape.points.first).dy,
        );
      for (final point in shape.points.skip(1)) {
        final mapped = mapPoint(point);
        path.lineTo(mapped.dx, mapped.dy);
      }
      path.close();
      final color = colors[shape.pieceId % colors.length];
      canvas.drawPath(
        path,
        Paint()
          ..color = color.withAlpha(30)
          ..style = PaintingStyle.fill,
      );
      canvas.drawPath(
        path,
        Paint()
          ..color = color
          ..strokeWidth = 2
          ..strokeJoin = StrokeJoin.round
          ..style = PaintingStyle.stroke,
      );

      final center =
          shape.points.fold(
            const Offset(0, 0),
            (sum, point) => sum + mapPoint(point),
          ) /
          shape.points.length.toDouble();
      final label = TextPainter(
        text: TextSpan(
          text: 'P${shape.pieceId + 1}',
          style: TextStyle(
            color: color,
            fontSize: 10,
            fontWeight: FontWeight.w900,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      label.paint(
        canvas,
        center - Offset(label.width * 0.5, label.height * 0.5),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _SolvedOutlinePainter oldDelegate) {
    return oldDelegate.shapes != shapes;
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

class _ScoreBreakdown extends StatelessWidget {
  const _ScoreBreakdown({required this.items});

  final List<Map<String, dynamic>> items;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Wrap(
        spacing: 14,
        runSpacing: 7,
        children: items.map((item) {
          final value = (item['value'] as num?)?.toDouble() ?? 0;
          final weight = (item['weight'] as num?)?.toDouble();
          final label = item['label']?.toString() ?? '评分项';
          final suffix = weight == null
              ? '${(value * 100).toStringAsFixed(1)}%'
              : '${(value * 100).toStringAsFixed(1)}% × ${(weight * 100).toStringAsFixed(0)}%';
          return Text(
            '$label $suffix',
            style: const TextStyle(
              color: Color(0xFF475569),
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          );
        }).toList(),
      ),
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
