# 内置 Ghostscript / Bundled Ghostscript

## 结论 / Result

EPS Live Viewer 3.2.0 在发布包内提供独立 Ghostscript 子进程，不依赖用户已安装 Ghostscript，也不在首次运行时联网下载。设置界面不再提供外部引擎路径，升级时忽略旧路径；源码运行未准备内置引擎时仍可回退到系统安装。

Release packages contain a private interpreter. No separate Ghostscript installation or first-run download is required. The UI no longer exposes an external-engine path, and old saved paths are ignored. Source checkouts retain system discovery when no bundled runtime has been prepared.

## 分析依据 / Evidence

用户提供的 `C:\Program Files\gs\gs9.18` 是 2015 年安装目录，并非完整源代码。REA 用于检查实际 PE 依赖及 DLL 导出；功能需求来自应用源码，运行结果来自隔离转换测试。没有把静态导入表当作“已经验证所有运行路径”的证据。

The supplied directory is an installed 2015 release, not a complete source tree. REA inspected PE imports/exports; application source established required devices; isolated conversions tested runtime behavior. Static imports alone do not prove runtime completeness.

完整 REA 记录：[ghostscript-rea-evidence.json](ghostscript-rea-evidence.json)。关键记录：

| Evidence ID | Observed scope |
| --- | --- |
| `ev_bd10c1778daf80b8e5c85f0f36dcb592035dfe1e95f09a22ceedfc0391b4bfc7` | 9.18 console PE imports and SHA-256 |
| `ev_ea0f76193295487e49cff7fea0d069aac82a2236f495508de2efe9c396d64b85` | 9.18 interpreter DLL imports and SHA-256 |
| `ev_5cdfea1d7a4b1076bda07b24505c9ea1218c055e829848e8c98b82e93a2b63c9` | 9.18 DLL's 36 exports; no claim about live calls |
| `ev_359c69e4118045eb7f0382aa5feb7eeca0f2bc41fe12567103cef9b9b5132624` | 10.08.0 DLL's direct Windows/VC/UCRT dependencies |

9.18 的 `-h` 显示初始化资源已编译进程序；10.08.0 的隔离运行检查进一步直接打开 ROM 中的字体和 ICC，并实际使用以下设备：

| Device | Application use |
| --- | --- |
| `pdfwrite` | EPS/PS vector preview and PDF export |
| `pngalpha` | Transparent raster output |
| `nullpage` | Page-size checks before allocating large PNGs |
| `ps2write` | Regenerated multipage PS output |
| `eps2write` | Regenerated EPS output |

## 打包取舍 / Packaging decisions

- 使用校验过的官方 **10.08.0**，不分发旧 9.18。
- Windows 仅保留 `gswin64c.exe`、`gsdll64.dll`、四个本地 VC 运行库及许可文件。递归检查也发现了 `MSVCP140.dll` 的 `CONCRT140.dll` 依赖，不能只检查 GS 的直接导入。
- Linux/macOS 从匹配的未修改源码编译所需输出设备，使用 `COMPILE_INITS=1` 保留 ROM 字体、CMap、ICC 和完整 PostScript/PDF 解释器；保留输入编解码支持，不通过删除字体或页面特性缩小体积。
- 安装器、GUI 程序、示例、开发库、解包工具和重复的资源树不进入应用；完整源码作为独立发布附件。
- 继续使用可取消的独立进程；只为内置引擎清理 `GS_*` 环境变量，不影响用户系统环境或外部引擎。
- Pillow 不收集未使用的 NumPy。已有 FFmpeg 压缩保留，macOS 原生二进制保持可签名。

The interpreter adds necessary bytes: a self-contained release cannot be compared directly with an executable that relies on a separately installed engine. Python refactoring alone has limited size benefit; the previous Windows build's compressed FFmpeg payload accounted for about 41% of the EXE. The Windows private Ghostscript payload is approximately 25.3 MiB before executable compression, including notices and VC libraries.

本机 Windows 单文件测量：3.1.1 为 52.70 MiB（不含 GS），本次优化前为 77.58 MiB，明确排除无用 NumPy 后为 **66.36 MiB**（含完整所需 GS 运行时）。这是本机相同 Python/Qt 环境的构建结果，其他平台或不同依赖版本可能不同。

Same-machine Windows one-file measurements: 52.70 MiB for 3.1.1 without GS; 77.58 MiB for the initial integrated build; **66.36 MiB** after excluding unused NumPy. Other platforms and dependency versions may differ.

云端 Windows 构建使用较新的完整 FFmpeg（imageio-ffmpeg 0.8.1；本机为 0.6.0），EXE 为 **71.66 MiB**。清理构建时的库搜索路径后，不再意外收集构建机的另一套 OpenSSL/UCRT DLL，较清理前 75.13 MiB 减少约 3.47 MiB。直接检查成品确认无 NumPy，保留 Ghostscript 解释器及四个必要 VC 运行库；没有通过降低视频编码能力减小文件。

The CI Windows EXE is **71.66 MiB**, using the newer complete FFmpeg from imageio-ffmpeg 0.8.1 (the local build uses 0.6.0). Restricting build-time DLL discovery removed an unrelated runner OpenSSL/UCRT set, reducing the EXE from 75.13 MiB by about 3.47 MiB. Archive inspection confirms no NumPy and retains the interpreter plus its four required VC runtime DLLs. Video encoding capabilities were not reduced.

## 构建与验证 / Build and verification

```text
python -m pip install -r requirements.txt
python scripts/prepare_ghostscript.py
python scripts/verify_bundled_ghostscript.py
```

`build.bat` / `build_unix.sh` 自动完成准备步骤。Unix 构建需要本机编译器和 make；Windows 仅解包官方安装器，不执行安装或修改注册表。每个准备命令最多运行 30 分钟。

The preparation script pins archive checksums and writes a per-file manifest. The PyInstaller hook rejects missing, changed or wrong-platform files. Release workflows run both source and actual packaged `--verify-ghostscript` checks, with an empty PATH and conflicting GS environment variables. Missing bundled engines are failures, not skipped tests.

验证覆盖多页 EPS/PS、标准字体、页尺寸、透明 600 DPI PNG、矢量换色和旋转后 EPS/PS 回读、损坏输入保护及运行中取消。另运行应用的预览、视频、文字编辑及标签页回归检查。测试无法保证任意第三方 PostScript 都兼容；未嵌入的特殊字体仍受源文件及本机字体条件影响。

2026-11-10：[四平台构建](https://github.com/eternitylzt/EPSLiveViewer/actions/runs/42836621768)已全部通过，包含实际打包程序的内置引擎验证，以及 macOS 原生/打包后的菜单与鼠标操作检查。随后仅收紧 Windows 打包时的 DLL 搜索路径，[复核构建](https://github.com/eternitylzt/EPSLiveViewer/actions/runs/42838352980)的 Windows、Linux 和 Intel Mac 均通过；未变化的 Apple Silicon 任务仍在排队，结束重复构建，保留上一轮已通过的同一应用代码 DMG。以上为构建验证，未创建公开 Release。

All four platform builds passed on 2026-11-10, including packaged interpreter checks and native/frozen macOS controls. After the Windows-only DLL search-path refinement, Windows, Linux and Intel Mac passed again. The unchanged Apple Silicon job remained queued, so that redundant run was cancelled; its previously validated DMG uses the same application code. These were build-only runs, without publishing a Release.

## 许可 / License

用户已选择 AGPLv3 开源发行；应用为 AGPL-3.0-only，第三方保留各自许可。发布流水线将匹配的 Ghostscript 源码作为附件一并提供。见 [第三方说明](../THIRD_PARTY_NOTICES.md)。

官方依据 / Primary references:

- [Ghostscript 10.08.0 release](https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/tag/gs10080)
- [Official build documentation](https://ghostscript.readthedocs.io/en/gs10.08.0/Make.html)
- [Artifex licensing](https://artifex.com/licensing)
