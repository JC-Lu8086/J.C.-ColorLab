# JC ColorLab

**屏幕相对校色 · 相机风格重建**  
v0.2.0 alpha · Copyright © 2026 **J.C. Lu** · [MIT](LICENSE)

把屏幕上的已知数字色卡、相机拍到的色卡，以及相机风格化后的色卡连起来：建立可复现的相对校色映射，或从成对色卡中估计可复用的色彩风格。照片在本机处理。

> 这是第二个实验版本。它精确定义色卡的数字值和色彩空间，但不会测量屏幕实际发光，也不会自动把屏幕校准为物理色彩标准。CUBE 作用于**所选工作空间中的 RGB 数值**，不是相机 DCP、显示器 ICC 或对任意 RAW 都成立的校准。选择更宽的工作空间不会自动扩大屏幕实际覆盖的颜色。

## 可以做什么

- 界面可切换中文、English、Français、日本語、Deutsch、Русский，并记住语言选择。
- 色卡标题右侧提供宽中性灰条，便于白平衡截取；按当前色卡空间定义约 18% 线性亮度。
- 单图与当前会话总量均支持最多 **240MP**，单文件最多 **2GiB**；已实际验证两张各 120MP 的合成 JPG 同时载入。大图仍需要足够内存，RAW 支持取决于 LibRaw 与具体机型。

- 原创 4K 数字色卡：146、376、762、4978 个色块，包含 RGB 立方体采样、独立灰阶及用于定位的标记；黑色间隔分开各块，并在空间上错开相近颜色。
- 屏幕色卡可选 sRGB、Display P3 或 Adobe RGB (1998)，嵌入对应 ICC；导出参考图与数字参考信息。
- 识别本项目色卡上的定位标记；检查识别点，并逐点手动校正采样位置。
- 导入 RAW、JPEG、PNG 和支持的 TIFF，统一到所选工作域：sRGB、Adobe RGB (1998)、Display P3、ProPhoto RGB 或受限 ACEScg。
- **屏幕相对校色**：相机拍摄结果 → 已定义的数字色卡参考。
- **风格重建**：相同色卡的基准照片 → 相机直出风格照片，估计整体色彩映射。
- 导出 `.cube`、嵌入完整 3D LUT 的实验性 Adobe `.xmp`、可复查的模型/报告，以及处理后的图片。XMP 限定用于已显影 SDR 图片，详情见 [Adobe 格式与使用范围](docs/ADOBE_XMP_FORMAT.md)。
- 区分拟合误差与独立留出色块的误差；提示采样异常、剪切与不足的颜色覆盖。
- 自动排除工作域无法表示的校色参考块，并在报告中保存排除记录及拍摄备注。

本软件采用独立实现和原创色卡。用户提供的第三方 Windows 工具仅用于了解交互需求，没有复制其程序、资源或商用色卡图案。Datacolor Spyder Checkr 和 Calibrite ColorChecker 是不同厂商的实体产品，本项目没有附带其测量数据，也不宣称兼容其专有配置文件。

## 下载 / Downloads

[下载 v0.2.0 / Download v0.2.0](https://github.com/JC-Lu8086/J.C.-ColorLab/releases/tag/v0.2.0) — macOS Apple Silicon、Windows x64 实验包、源码与 SHA-256 校验文件。

本仓库保存源码；可运行应用包在 Releases。Windows 尚未实机测试，作者目前仅有 Mac，暂不维护 Windows。

## 启动

**macOS 应用包：** 解压后双击 `JC ColorLab.app`，默认浏览器会打开本机界面。程序没有 Apple 开发者签名或公证。关闭程序使用界面中的退出按钮；只关闭浏览器标签页不等于停止后台进程。

**Windows 实验便携包：** 完整解压后双击 `Start-JC-ColorLab.cmd`，不要只复制启动文件。包内包含官方 Python 3.14.10 Windows x64 嵌入式运行时、14 个依赖 wheel 的内容及 LittleCMS 2.19.1 核心 DLL，按离线运行设计。**该包尚未在 Windows 上运行验证。作者目前仅拥有 Mac，无法对 Windows 版本进行实机测试和日常维护；Windows 为实验性、社区协助支持。** 同时保留 Windows 源码和原生 PyInstaller 构建流程。

应用仅监听 `127.0.0.1` 的临时端口，并使用每次启动的访问令牌。它不需要云端账号；打包版正常处理照片时不需要联网。色卡的显示仍依赖当前浏览器、操作系统显示配置和屏幕状态。

### 从源码运行

建议 Python 3.12（支持范围见 `pyproject.toml`）。首次安装依赖需要联网。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m jc_colorlab
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe -m jc_colorlab
```

也可以使用仓库中的 `Launch.command` 或 `Launch-Windows.bat`，首次运行会在项目目录创建独立环境并安装依赖。

## 先做一次可靠的采样

1. 关闭 HDR、原彩显示、夜览/夜间模式及自动亮度，固定显示器亮度和系统显示配置。使用支持色彩管理的浏览器。
2. 推荐至少 **3840 × 2160（4K）** 显示分辨率，以 **15 英寸 4K 笔记本**为设计参考，默认使用 **376 色（优先适配相机 JPG）**。若照片有噪声、模糊或单块像素不足，改用 **146 色**；**4978 色属于实验模式，不推荐在 15 英寸 4K 屏幕上作为常规采样设置**。
3. 选择屏幕能够覆盖的色卡空间；不确定时先选 sRGB。P3/Adobe RGB 需要相应屏幕色域、有效显示 ICC 和浏览器色彩管理。全屏显示色卡，固定曝光和白平衡，避免反光、摩尔纹、刷新条纹和高光剪切。
4. 导入色卡照片，确认每个采样点在色块内部；需要时逐点拖动修正。
5. 校色时选择数字色卡为目标；重建风格时再导入相同色卡的风格照片，分别检查两张图的定位。
6. 查看留出误差、警告和图像预览，再导出映射。在另一张没有参与拟合的照片上检查效果。

这套校正以**当前显示器、当前拍摄条件、当前 JPG 直出或 RAW 显影链路**为条件。它不能自动推广到自然光、另一台相机、另一种 RAW 显影配置或另一种屏幕光谱。[完整流程与 Photoshop 使用说明](docs/WORKFLOW.md)

## 版本状态与边界

| 项目 | v0.2.0 状态 |
|---|---|
| macOS Apple Silicon | 本地开发与验证目标；已启动独立应用并验证五空间导出；见 [验证记录](docs/VALIDATION.md) |
| Windows x64 | 已组装实验便携包，另有源码与 CI；尚未运行验证，作者暂不维护 |
| Intel Mac | 未验证；较新的 rawpy 不再提供 Intel Mac wheel，需单独选择依赖或自行构建 |
| 绝对色准/显示器测量 | 未实现；需要测色仪与可追溯实测参考 |
| 实体 ColorChecker/Spyder Checkr | 当前不提供专有参考数据或自动识别工作流 |
| 屏幕色卡 | sRGB、Display P3、Adobe RGB (1998)；实际可显示色域由屏幕和显示链路决定 |
| 照片/模型工作域 | sRGB、Adobe RGB (1998)、Display P3、ProPhoto RGB、ACEScg；必须按所选域应用 LUT |
| ACEScg | 仅 AP1 / D60 / 线性 0–1 SDR LUT 域；不提供完整 ACES、HDR、IDT/ODT 或场景范围处理 |
| Adobe XMP | 32³、16 位 3D LUT，仅用于已显影 SDR 图片；常用四空间原生表，ACEScg 为 sRGB 适配；尚未完成 Adobe 宿主验证 |
| 风格重建 | 整体颜色/色调近似；不重建颗粒、锐化、纹理或局部/语义调色 |

截至本版文档核对，macOS 开发环境的 **167 项 Python 自动测试和 8 项 JavaScript 翻译检查通过**，覆盖颜色空间转换、色卡/定位、拟合、图像读写、导出格式与服务接口。这不等于 Windows 运行测试、Adobe 宿主渲染测试或真实显示器色准验证；独立应用包检查见 [验证记录](docs/VALIDATION.md)。

## 开发与打包

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
node --test tests/test_i18n.js
python scripts/build.py
```

构建结果在 `dist/`。在 Mac 上构建 Mac 应用，在 Windows 上构建 Windows 程序；PyInstaller 不提供直接的跨操作系统编译。[原理说明](https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems)

`.github/workflows/build.yml` 为 macOS Apple Silicon 与 Windows x64 配置自动测试及打包，只上传工作流附件，不自动公开发布。构建脚本收集实际依赖版本与随包许可证；重新发布时应保留这些文件。

第二版的语言、容量与灰条说明：[v0.2.0 使用说明](docs/SECOND_RELEASE.md)。

更多内容：[色彩科学约定](docs/COLOR_SCIENCE.md) · [操作流程](docs/WORKFLOW.md) · [迭代路线](docs/ROADMAP.md) · [版本记录](CHANGELOG.md) · [第三方组件](THIRD_PARTY_NOTICES.md)


RAW 厂商入口与限制：[RAW 支持说明](docs/RAW_SUPPORT.md)。参照用户提供的 Mac 移植源码核对了 LibRaw 路线，补齐了文件选择器中的中画幅及旧机型后缀；未复制参考项目的引擎与权重。
