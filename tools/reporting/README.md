# 2026 年 10 月报告复现

这两个脚本生成当前固定日期的图集和 Word 报告，不修改视觉程序。使用包含 `summary.json`、原始照片、`results` 的完整板端证据目录作为 `--task`。作者环境为 Windows，字体为微软雅黑与宋体；需要 Python、Pillow、matplotlib、python-docx。

```powershell
python tools/reporting/build_gallery.py --task C:/path/to/pi5-design-20261018
python tools/reporting/build_design_report.py --task C:/path/to/pi5-design-20261018
```

板端数据先使用 `tools/summarize_image_benchmark.py` 汇总。报告中的章节文字与页码针对本次 43 张样本；更换数据后必须复核描述、目录页码，并重新渲染检查所有页面。PDF 为同一 DOCX 经 LibreOffice 渲染导出，最终版共 35 页。
