# 第三方组件与来源

JC ColorLab 的原创代码和文档由 **J.C. Lu** 以 MIT 许可证发布。依赖库、Python 运行时以及各库所含的原生组件保留各自的许可证；项目的 MIT 许可不替代它们。

## 运行组件

| 组件 | 用途 | 上游许可/来源 |
|---|---|---|
| Python | 运行时 | [PSF License 与所附第三方条款](https://docs.python.org/3/license.html) |
| NumPy | 数值数组与线性代数 | [BSD-3-Clause](https://github.com/numpy/numpy/blob/main/LICENSE.txt)；wheel 可能包含 BLAS 等附属条款 |
| SciPy | 数值算法 | [BSD-3-Clause](https://github.com/scipy/scipy/blob/main/LICENSE.txt)；以所用 wheel 的完整许可为准 |
| Pillow / LittleCMS | 图像与 ICC 转换 | [Pillow MIT-CMU](https://github.com/python-pillow/Pillow/blob/main/LICENSE)，以及 wheel 随附的各图像编解码库许可 |
| 独立 LittleCMS 2.19.1 核心 DLL（Windows 便携包） | 浮点 ICC 转换 | [LittleCMS MIT](https://github.com/mm2/Little-CMS/blob/master/COPYING)，随 DLL 保留其许可证与构建来源说明 |
| OpenCV contrib headless | 定位标记与几何处理 | OpenCV 4.5+ 为 [Apache-2.0](https://opencv.org/license/)，另含包装器与原生依赖条款 |
| rawpy | RAW 解码包装器 | [MIT](https://github.com/letmaik/rawpy/blob/main/LICENSE) |
| LibRaw | RAW 解码与显影 | rawpy wheel 随附 [LibRaw 许可](https://github.com/letmaik/rawpy/blob/main/LICENSE.LibRaw)；LibRaw 上游提供 [LGPL-2.1 / CDDL-1.0](https://www.libraw.org/docs)许可选择 |
| tifffile | 高位深 TIFF 读写 | [BSD-3-Clause](https://github.com/cgohlke/tifffile/blob/master/LICENSE) |
| Flask / Werkzeug / Jinja / MarkupSafe / Click / ItsDangerous / Blinker | 本机界面服务及依赖 | [Pallets](https://palletsprojects.com/)各项目的 BSD 许可证及 Blinker 的 MIT 许可证，以安装包原文为准 |

## 构建与测试组件

pytest 采用 MIT 许可证。PyInstaller 采用 GPL 及允许分发所生成应用的例外；使用 PyInstaller 不会自动把本项目的原创代码改为 GPL。参见 [PyInstaller 许可说明](https://pyinstaller.org/en/stable/license.html)。构建环境还包含 setuptools、wheel、packaging 与平台相关组件。

`scripts/collect_licenses.py` 会从实际构建环境收集依赖版本、元数据与随包的 LICENSE / NOTICE 文件，生成 `licenses/DEPENDENCIES.json`。原生构建将这些材料放在应用内部和 `dist/licenses/`。二进制包的完整义务应根据**实际所含组件及其随附许可证**核对，不能只依赖上表摘要。

Windows 实验便携包单独记录 `BUILD-MANIFEST.json`：包含官方 Python 3.14.10 Windows x64 嵌入式运行时、14 个依赖 wheel 及 LittleCMS 2.19.1 核心 DLL。各 wheel 的原始 `.dist-info` 元数据和许可证随包保留；Python 许可证在 `runtime/LICENSE.txt`，独立 LittleCMS 的许可证与来源在 `app/jc_colorlab/native/`。这种组装不构成 Windows 运行验证，平台状态仍为未实机测试、作者暂不维护。

再次分发原生组件时，保留原始版权和许可证，并按相应许可证提供匹配版本的源码或其他要求的材料；不要把第三方代码重新标记为 J.C. Lu 的 MIT 作品。rawpy/LibRaw 对应源码可从其上游发布版本获取，构建版本记录用于确定具体版本。

## 色卡、参考软件与商标

- JC ColorLab 色卡由数学规则生成，是本项目原创数字采样布局，不使用用户附图中的商标、照片或其像素值作为测量标准。
- 用户提供的第三方 Windows 工具仅用于了解功能需求；本仓库不包含其二进制文件、反编译结果或资源。
- Datacolor、Spyder Checkr、Calibrite、ColorChecker、Adobe、Photoshop、Camera Raw 等名称属于各自权利人，仅用于说明互操作场景。本项目不隶属于这些厂商，也未获得其产品认证。
- 科学公式与规范的引用见 [COLOR_SCIENCE.md](docs/COLOR_SCIENCE.md)。


## Windows C++ 运行时

Python 嵌入式包附带 Microsoft VCRUNTIME 组件。Windows 便携包还将 NumPy wheel 中已附带的 `msvcp140-*.dll` 原样复制为 `runtime/MSVCP140.dll`，供 LibRaw 按标准文件名加载；来源与 SHA-256 记录于 `BUILD-MANIFEST.json`。这些 Microsoft 组件不适用本项目的 MIT 许可；原始依赖许可证和元数据随包保留。Microsoft 官方运行时说明：https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist
