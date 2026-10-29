# Adobe XMP 与颜色导出

JC ColorLab 的 `.xmp` 是包含三维 RGB 查找表的 **Adobe enhanced profile（创意配置文件）**，不是仅包含曲线的近似预设。它不是相机 DCP，也不是显示器 ICC。

## 使用范围

输入与输出定义为**已显影 SDR 图片的颜色映射**。sRGB、Adobe RGB (1998)、Display P3 和 ProPhoto RGB 模型使用对应的 Adobe RGBTable 原色枚举；ACEScg 模型通过 sRGB 适配表输出。导出的 XMP 限定用于已显影图片（`SupportsOutputReferred=True`、`SupportsSceneReferred=False`），不会作为适用配置文件出现在未显影 RAW 图片上。这是为了避免把 LibRaw/相机的显影结果与 Adobe 的 RAW 显影结果误当作同一输入。

推荐流程：在 JC ColorLab 使用固定流程显影 RAW，并导出**未应用映射的基准 16 位 TIFF**，保留所选工作域的正确 ICC；在 Photoshop 的 Camera Raw 滤镜或 Camera Raw 中对该已显影图片使用配置文件。也可以在 Adobe 中先显影并导出带正确 ICC 的 TIFF，以这些 TIFF 建立映射，再对相同基准的图片应用。应保持白平衡、曝光处理、基础配置文件及工作域一致。已经导出的“校正后 TIFF”不能再重复套用同一映射。

导出的 CUBE 要求输入为模型记录的工作域数值。在 Photoshop 中先把图片**转换到 LUT 对应的空间**，再用「颜色查找 / Color Lookup」调整图层载入 CUBE。仅“指定”空间不会转换原有像素数值，不能代替色彩空间转换。ACEScg CUBE 只支持 AP1 / D60 / 线性 0–1 SDR 域，不是完整 ACES/HDR 管线。

## RGBTable 与工作域的对应

| 模型工作域 | Adobe RGBTable 原色 / gamma 枚举 | 处理 |
|---|---|---|
| sRGB | 0 / 1 | 原生 sRGB 表 |
| Adobe RGB (1998) | 1 / 3 | 原生 Adobe RGB 原色；表的纯 gamma 2.2 与模型的精确 563/256 曲线之间做数值适配 |
| ProPhoto RGB | 2 / 2 | 原生 ProPhoto 原色；表的纯 gamma 1.8 与模型含暗部线性段的曲线之间做数值适配 |
| Display P3 | 3 / 1 | 原生 P3 原色、sRGB 传递函数 |
| ACEScg | 0 / 1 | sRGB 格点 → ACEScg 模型 → sRGB；结果可能裁切 |

曲线适配发生在表格生成时，不能把相近的 gamma 数值或 ProPhoto 暗部线性段直接忽略。ACEScg 的 XMP 只覆盖 sRGB 适配域，无法完整表达原生 ACEScg 色域；文件描述明确标注该限制，需要原工作域时保留并使用 CUBE。

当前 XMP 使用 32×32×32 个格点，每个输出通道量化至 16 位。CUBE 可以选用不同格点数，软件和 Adobe 的插值方式也可能不同，因此二者在格点之间可能有微小差异。图像的局部蒙版、锐化、颗粒、光晕、降噪和场景自适应效果均不属于三维 LUT 的表达能力。

## 载入

在 Adobe Camera Raw 的配置文件浏览器中使用「导入配置文件和预设」。不同版本对单独 XMP 与 ZIP 的接受方式不同；如果当前版本只接受 ZIP，可把导出的 XMP 压缩后导入。也可按照 Adobe 文档把 XMP 放入本机 CameraRaw/Settings 配置文件目录，然后重新打开 Adobe 应用。导入成功后在 **JC ColorLab** 分组中查找。首次请用已显影的 SDR 彩色 TIFF/JPEG 测试。

本项目没有写入或修改你的 Adobe 配置目录。应用内的导出操作只生成文件。

## 文件格式与独立实现

本项目根据 Adobe 官方 DNG SDK 中公开的 RGBTable 数据格式独立实现序列化，没有分发 Adobe SDK 源代码、示例图片或 Adobe LUT。

- 格点遍历顺序为 R 外层、G 中层、B 内层；这与 CUBE 的 R 最快顺序不同。
- 每个格点储存相对于整数单位映射的 16 位模差值。
- 数据声明所选表格的原色、传递函数和超出色域裁切；对应关系见上表。强度范围为 0–2，默认值为 1。
- 表格数据按小端格式序列化，用 MD5 形成 Adobe 格式要求的内容键。MD5 此处只用于格式标识，不承担安全认证。
- 数据经 zlib 压缩，并使用 Adobe XMP 大表的 base85 传输编码，嵌入 `crs:Table_<内容键>`；`crs:RGBTable` 引用该键。
- 采用 32³ 格点是为了兼容官方 2018 Profiles SDK 与较早应用版本的范围。

## 已验证与待验证

自动测试用独立解码器验证完整数据长度、压缩、内容键、base85 尾部、格点数值、RGB 通道顺序、空间枚举和配置文件适用属性，并检查 Adobe RGB / ProPhoto 曲线适配。还对本机安装的一个 Adobe 原有配置文件做了只读格式交叉检查：其大表传输字节可完整重编码，原有内容键与计算结果一致。这个只读检查没有把 Adobe 的文件或色彩值复制进项目。

这些检查证明格式和格点序列化的一致性，**尚未在 Adobe 宿主中实际完成本项目生成文件的导入与渲染验证**。发布前应在目标版本中导入配置文件，对受控测试图检查渲染；本版本仍标记为实验性互操作功能。

## 官方参考

- [Adobe Digital Negative：Profiles SDK 与 DNG SDK 下载](https://www.adobe.com/support/downloads/dng/dng_sdk.html)
- [Adobe Profiles SDK（Enhanced Profiles.pdf，2018）](https://download.adobe.com/pub/adobe/lightroom/profile-sdk/ACR_and_Lightroom_Profile_SDK.zip)
- [Adobe Camera Raw：配置文件与导入](https://helpx.adobe.com/camera-raw/desktop/edit-and-enhance-images/tone-and-color/adjust-color-rendering-camera-camera.html)
- [rawpy Params：RAW 显影参数](https://letmaik.github.io/rawpy/api/rawpy.Params.html)
- [LittleCMS 公共接口](https://github.com/mm2/Little-CMS/blob/master/include/lcms2.h)

Copyright © 2026 J.C. Lu. MIT.
