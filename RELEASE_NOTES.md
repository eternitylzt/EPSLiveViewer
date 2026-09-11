# EPS Live Viewer 1.2.0

## 简体中文

- 新增“文件 → 另存为 PDF”。
- 通过项目现有 Ghostscript `pdfwrite` 转换当前 EPS/PS，保留矢量质量和完整页数。
- 多页 EPS/PS 会导出为多页 PDF；导出不受当前预览页码、缩放和背景设置影响。
- PDF 转换在后台执行，并沿用 Ghostscript 自动检测、文件写入稳定等待和取消机制。
- 使用临时文件完成原子保存；转换失败不会破坏已有目标文件，并会显示明确错误信息。
- 中英文界面、帮助内容与 README 已同步更新。

本功能未引入新的 PDF 第三方依赖，不改变预览、自动刷新、PNG、MP4/GIF 及其他已有功能。Windows、Linux、macOS Apple Silicon 和 macOS Intel 继续使用现有跨平台发布流程。EPS/PS 与 PDF 转换仍需系统 Ghostscript；发布包不要求 Python。

## English

- Added **File → Save as PDF**.
- Converts the current EPS/PS through the existing Ghostscript `pdfwrite` path, preserving vector quality and the complete page set.
- Multi-page EPS/PS files produce multi-page PDFs. Export is independent of the displayed page, zoom, and preview background.
- PDF conversion runs in the background and reuses Ghostscript discovery, stable-file waiting, and cancellation handling.
- Atomic output prevents a failed conversion from damaging an existing destination and clear errors are shown on failure.
- Updated both interface languages, Help content, and the bilingual README.

No new PDF dependency was added, and preview, live refresh, PNG, MP4/GIF, and all existing features remain unchanged. The existing release workflow continues to build Windows, Linux, macOS Apple Silicon, and macOS Intel packages. EPS/PS and PDF conversion still require system Ghostscript; Python is not required.
