# RAW 厂商与格式支持

JC ColorLab 使用 rawpy / LibRaw 读取传感器数据，再按固定流程显影；不使用相机内嵌 JPEG 代替 RAW。当前 Mac 构建为 rawpy 0.27.1 / LibRaw 0.22.1。

文件选择器与后端共用同一格式清单，避免后端能读但界面无法选择。以下是可尝试导入的格式入口，**不是每种机型、固件、压缩方式均已测试的承诺**。

| 厂商 / 格式族 | 扩展名 |
|---|---|
| Canon 佳能 | CRW、CR2、CR3 |
| Nikon 尼康 | NEF、NRW |
| Sony 索尼 | ARW、SR2、SRF |
| Fujifilm 富士 | RAF |
| Panasonic 松下 | RW2、RAW |
| Olympus / OM System | ORF |
| Pentax 宾得 | PEF、DNG |
| Hasselblad 哈苏 | 3FR、FFF |
| Phase One / 部分中画幅背 | IIQ、CAP |
| Leica 徕卡 | RWL、DNG |
| Samsung 三星 | SRW |
| Minolta 美能达 | MRW |
| Epson 爱普生 | ERF |
| Kodak 柯达 | DCR、KDC |
| Leaf 等数字后背 | MOS |
| Mamiya 玛米亚 | MEF |
| Casio 卡西欧 | BAY |
| Sigma 适马 | X3F，依赖具体机型与解码构建；建议保留厂商 TIFF 备用流程 |
| 通用数字负片 | DNG，具体压缩及 DNG 子类型仍受解码器限制 |

上游的[相机支持清单](https://www.libraw.org/supported-cameras)说明其完整功能构建的支持范围，不能等同于当前 wheel 的所有编译选项。本软件在导入报告中记录 rawpy / LibRaw 版本、编译功能标志、CFA 排列及显影参数。即使后缀相同，新机型、特殊压缩、多帧/像素位移 RAW 仍可能需要上游更新；当前取第一幅主图，不进行多帧融合。

Bayer 请求 AHD（quality 3）；6×6 X-Trans 由 LibRaw 对应分支执行三遍 X-Trans 插值。全采样或其它传感器按 LibRaw 的传感器分支处理，报告不会把这些情况一概标成 AHD。依据：[rawpy 参数](https://letmaik.github.io/rawpy/api/rawpy.Params.html)、[LibRaw 0.22.1 分支实现](https://github.com/LibRaw/LibRaw/blob/0.22.1/src/postprocessing/dcraw_process.cpp)。这项功能没有沿用多帧融合程序的 Bayer-only 限制。

RAW 白平衡、自动增亮设置、宽色域中间空间和输出工作域固定并记录。LibRaw 的线性 ProPhoto D65 中间空间通过 XYZ 转到所选工作域；它不是标准 D50 ProPhoto，也不是 ACES IDT。当前输出限定 SDR 0–1，不支持负值与超白 HDR 数据。

无法读取的文件，请用厂商软件或 Adobe 在固定条件下导出**带正确 ICC 的 16 位 RGB TIFF**。X3F 可以用 Sigma Photo Pro；保持白平衡、曝光、色域、降噪和锐化一致。该 TIFF 和另一张匹配流程的照片可以参与校色或风格提取。无相机颜色信息或不明确的 DNG 矩阵不能靠随意补一个矩阵取得准确颜色。

用户提供的 Mac 移植参考目录也使用 rawpy / LibRaw，并有 Bayer 融合与全采样 TIFF/DNG 的不同限制。本项目仅用它核对需求和入口遗漏，没有复制其未开放许可的引擎、字节码、权重或适配代码。

## 已验证与未验证

- 一张真实 8000×5320 DNG 已完成 sRGB、ProPhoto RGB 固定显影和 16 位 TIFF 往返验证。
- CFA 分支的报告与固定参数有单元测试；这不替代每家厂商的真实样本测试。
- 尚未逐台验证 Canon / Nikon / Sony / Fujifilm 等所有相机，尚未在 Windows 运行该流程。
- 单图当前最多 60 百万像素，界面单次上传最多 128 MiB。更大的中画幅文件需先按一致流程输出较小 TIFF；本版不能声称原生覆盖所有高像素中画幅 RAW。
