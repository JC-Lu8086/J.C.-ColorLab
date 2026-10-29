"""Precision-aware image interchange. Copyright (c) 2026 J.C. Lu, MIT.

Public pixel arrays use the selected SDR working space, H x W x 3, float32 [0, 1].
ACEScg arrays are linear; the other supported spaces use their transfer curves.
RAW processing is a documented development recipe, never sensor-native data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import ctypes
import ctypes.util
import functools
import struct
import warnings as pywarnings

import numpy as np
from PIL import Image, ImageCms, ImageOps
from .icc import profile_bytes, _lcms
from .color_spaces import SPACES, normalize_space, convert_rgb, encode_rgb, xyz_to_rgb

MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_PIXELS = 60_000_000
RAW_EXTENSIONS = {'.3fr', '.arw', '.bay', '.cap', '.cr2', '.cr3', '.crw', '.dcr', '.dng', '.erf', '.fff', '.iiq', '.kdc', '.mef', '.mos', '.mrw', '.nef', '.nrw', '.orf', '.pef', '.raf', '.raw', '.rw2', '.rwl', '.sr2', '.srf', '.srw', '.x3f'}


@dataclass
class LoadedImage:
    rgb: np.ndarray
    metadata: dict
    warnings: list[str] = field(default_factory=list)


def srgb_profile_bytes() -> bytes:
    return profile_bytes('srgb')


def _check_size(width: int, height: int) -> None:
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise ValueError(f'图片尺寸超过限制（最多 {MAX_PIXELS // 1_000_000} 百万像素）。请缩小后重试。')


def _array(rgb: np.ndarray) -> np.ndarray:
    a = np.asarray(rgb, dtype=np.float32)
    if a.ndim != 3 or a.shape[2] != 3 or not np.isfinite(a).all():
        raise ValueError('需要有限数值的 H×W×3 RGB 图片。')
    _check_size(a.shape[1], a.shape[0])
    return np.ascontiguousarray(np.clip(a, 0, 1))


def _srgb_encode(linear: np.ndarray) -> np.ndarray:
    a = np.clip(linear, 0, 1)
    return np.where(a <= 0.0031308, 12.92 * a, 1.055 * np.power(a, 1 / 2.4) - 0.055).astype(np.float32)


def _orient(a: np.ndarray, orientation: int) -> np.ndarray:
    # EXIF/TIFF orientation, with the same transforms as Pillow ImageOps.
    transforms = {
        2: lambda x: x[:, ::-1],
        3: lambda x: x[::-1, ::-1],
        4: lambda x: x[::-1],
        5: lambda x: np.swapaxes(x, 0, 1),
        6: lambda x: np.rot90(x, 3),
        7: lambda x: np.swapaxes(x, 0, 1)[::-1, ::-1],
        8: lambda x: np.rot90(x, 1),
    }
    return np.ascontiguousarray(transforms.get(orientation, lambda x: x)(a))


def _convert_high_depth_icc(rgb: np.ndarray, icc: bytes, working_space: str = 'srgb') -> np.ndarray:
    lib = _lcms()
    if lib is None:
        raise ValueError('此运行环境无法保持高位深进行 ICC 转换。请使用完整 LittleCMS 构建；或先转换为带 ICC 的 8 位图片（会损失精度）。')
    blob = ctypes.create_string_buffer(icc)
    source, destination, transform = None, None, None
    try:
        source = lib.cmsOpenProfileFromMem(blob, len(icc))
        if not source or lib.cmsGetColorSpace(source) != 0x52474220:  # RGB signature
            raise ValueError('图片的 ICC 不是有效的 RGB 配置文件。')
        destination_blob = ctypes.create_string_buffer(profile_bytes(working_space))
        destination = lib.cmsOpenProfileFromMem(destination_blob, len(destination_blob.raw) - 1)
        # lcms2.h TYPE_RGB_FLT: FLOAT_SH(1)|COLORSPACE_SH(PT_RGB)|CHANNELS_SH(3)|BYTES_SH(4).
        rgb_float = (1 << 22) | (4 << 16) | (3 << 3) | 4
        transform = lib.cmsCreateTransform(source, rgb_float, destination, rgb_float, 1, 0)
        if not transform:
            raise ValueError('无法创建高位深 ICC 转换。')
        src = np.ascontiguousarray(rgb, dtype=np.float32)
        out = np.empty_like(src)
        lib.cmsDoTransform(transform, src.ctypes.data, out.ctypes.data, src.size // 3)
        return out
    finally:
        if transform:
            lib.cmsDeleteTransform(transform)
        if source:
            lib.cmsCloseProfile(source)
        if destination:
            lib.cmsCloseProfile(destination)


def _finish(rgb, metadata, messages, working_space='srgb'):
    if not np.isfinite(rgb).all():
        raise ValueError('图片包含无效像素数值，无法用于色彩标定。')
    fraction = float(np.mean((rgb < 0) | (rgb > 1)))
    if fraction:
        messages.append(f'转换后 {fraction:.2%} 通道样本超出 {SPACES[working_space]["name"]} 的 0–1 范围，已裁切；这些颜色不能用于验证原色域。')
    rgb = _array(rgb)
    metadata.update(width=int(rgb.shape[1]), height=int(rgb.shape[0]), working_space=working_space, working_space_name=SPACES[working_space]['name'], encoding=SPACES[working_space]['transfer'], gamut_clipped_channel_fraction=fraction)
    return LoadedImage(rgb=rgb, metadata=metadata, warnings=messages)


def _load_raw(data: bytes, filename: str, working_space='srgb') -> LoadedImage:
    try:
        import rawpy
    except ImportError as exc:
        raise ValueError('此版本未安装 RAW 解码组件 rawpy；可先导出带 ICC 的 16 位 TIFF 再导入。') from exc
    messages = ['RAW 已按固定流程从 LibRaw 宽色域线性 ProPhoto D65 中间空间显影到所选工作空间；不同于相机直出及 Adobe 默认显影。请固定白平衡并沿用相同流程。', 'RAW 解码中间数据为 16 位整数 0–1；此流程不保留 HDR / 超范围 RAW 值，也不是 ACES IDT。']
    try:
        with rawpy.imread(BytesIO(data)) as raw:
            _check_size(raw.sizes.width, raw.sizes.height)
            wb = [float(v) for v in raw.camera_whitebalance]
            if len(wb) < 3 or not np.isfinite(wb).all() or min(wb[:3]) <= 0:
                raise ValueError('RAW 缺少有效的相机白平衡，不能静默换用另一种显影基准。请先用固定白平衡显影为带 ICC 的 16 位 TIFF。')
            pattern = getattr(raw, 'raw_pattern', None)
            pattern = None if pattern is None else np.asarray(pattern)
            layout = 'X-Trans 6x6' if pattern is not None and pattern.shape == (6, 6) else ('Bayer 2x2' if pattern is not None and pattern.shape == (2, 2) else 'other / no repeated CFA')
            demosaic = 'LibRaw X-Trans 3-pass' if layout == 'X-Trans 6x6' else ('AHD (LibRaw quality 3)' if layout == 'Bayer 2x2' else 'LibRaw sensor-specific; requested quality 3')
            linear = raw.postprocess(
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                use_camera_wb=True, use_auto_wb=False,
                no_auto_bright=True, no_auto_scale=False,
                adjust_maximum_thr=0.0, bright=1.0,
                gamma=(1.0, 1.0), output_color=rawpy.ColorSpace.ProPhoto,
                output_bps=16, highlight_mode=rawpy.HighlightMode.Clip,
            )
            # LibRaw ProPhoto is explicitly a D65 variant, not standard D50.
            # Recover D65 XYZ through its documented (linear-sRGB -> ProPhoto-D65)
            # matrix, without materializing or clipping an sRGB intermediate.
            raw_basis = np.array([[.529317, .330092, .140588], [.098368, .873465, .028169], [.016879, .117663, .865457]])
            xyz_from_srgb = np.array([[.4124564, .3575761, .1804375], [.2126729, .7151522, .0721750], [.0193339, .1191920, .9503041]])
            raw_to_xyz = xyz_from_srgb @ np.linalg.inv(raw_basis)
            rgb = np.empty(linear.shape, dtype=np.float32)
            for row in range(0, len(linear), 128):
                xyz = (linear[row:row + 128].astype(np.float64) / 65535) @ raw_to_xyz.T
                rgb[row:row + 128] = xyz_to_rgb(xyz, working_space, white='D65')
            metadata = {'filename': Path(filename).name, 'source_format': 'RAW', 'source_bit_depth': 'sensor dependent; developed at 16-bit', 'source_profile': 'LibRaw camera matrix -> linear ProPhoto D65 -> XYZ D65 -> selected working space', 'raw_recipe': {'demosaic': demosaic, 'sensor_layout': layout, 'cfa_pattern': None if pattern is None else pattern.tolist(), 'requested_quality': 3, 'decoder_features': dict(getattr(rawpy, 'flags', {})), 'white_balance': 'as-shot', 'camera_wb': wb, 'auto_white_balance': False, 'auto_brightness': False, 'auto_scale': True, 'adjust_maximum_thr': 0.0, 'brightness': 1.0, 'linear_output_bits': 16, 'intermediate_space': 'LibRaw ProPhoto D65 (not standard ProPhoto RGB)', 'output_space': working_space, 'highlight_mode': 'clip', 'rawpy_version': rawpy.__version__, 'libraw_version': '.'.join(str(x) for x in rawpy.libraw_version)}, 'orientation': 'LibRaw metadata applied'}
        return _finish(rgb, metadata, messages, working_space)
    except ValueError:
        raise
    except Exception as exc:
        fallback = '请用 Sigma Photo Pro 固定显影为带 ICC 的 16 位 TIFF。' if Path(filename).suffix.lower() == '.x3f' else '请用厂商软件或 Adobe 固定显影为带 ICC 的 16 位 TIFF；具体机型和压缩方式取决于随包 LibRaw。'
        raise ValueError(f'RAW 解码失败：{exc}。{fallback}') from exc


def _load_tiff(data: bytes, filename: str, working_space='srgb') -> LoadedImage:
    import tifffile
    messages = []
    with tifffile.TiffFile(BytesIO(data)) as tif:
        page = tif.pages[0]
        _check_size(page.imagewidth, page.imagelength)
        if len(tif.pages) > 1:
            messages.append('多页 TIFF 仅使用第一页。')
        if int(page.photometric) not in (1, 2):
            raise ValueError('只支持 RGB 或黑白灰度 TIFF，请先转换为 sRGB RGB TIFF。')
        if page.dtype not in (np.dtype('uint8'), np.dtype('uint16')):
            raise ValueError('只支持 8/16 位整数 SDR TIFF；浮点/HDR 文件请先按已知方式转换为 sRGB SDR。')
        a = page.asarray()
        if int(page.planarconfig or 1) == 2 and a.ndim == 3:
            a = np.moveaxis(a, 0, -1)
        if a.ndim == 2:
            a = np.repeat(a[..., None], 3, axis=-1)
        if a.ndim != 3 or a.shape[-1] != 3:
            raise ValueError('TIFF 需要恰好 3 个 RGB 通道（不支持附加通道）。')
        bits = int(a.dtype.itemsize * 8)
        rgb = a.astype(np.float32) / (65535 if bits == 16 else 255)
        orientation = int(page.tags['Orientation'].value) if 'Orientation' in page.tags else 1
        rgb = _orient(rgb, orientation)
        icc = page.tags[34675].value if 34675 in page.tags else None
    profile_name = 'untagged: assumed sRGB'
    if icc:
        if len(icc) > 8 * 1024 * 1024:
            raise ValueError('嵌入 ICC 超出 8 MB 限制。')
        try:
            profile_name = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(BytesIO(icc))).strip()
            rgb = _convert_high_depth_icc(rgb, icc, working_space)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f'无法读取 TIFF 色彩配置文件：{exc}') from exc
    else:
        messages.append('TIFF 没有嵌入 ICC，输入暂按 sRGB 解释并转换到工作空间。若实际为宽色域，请重新导出并嵌入正确配置文件。')
        rgb = convert_rgb(rgb, 'srgb', working_space)
    return _finish(rgb, {'filename': Path(filename).name, 'source_format': 'TIFF', 'source_bit_depth': bits, 'source_profile': profile_name, 'orientation': orientation, 'icc_conversion': 'relative colorimetric; float32; no black point compensation' if icc else 'assumed sRGB -> working'}, messages, working_space)


def load_image(data: bytes, filename: str = 'image', working_space: str = 'srgb') -> LoadedImage:
    working_space = normalize_space(working_space)
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError('图片为空或超过 512 MB 限制。')
    if Path(filename).suffix.lower() in RAW_EXTENSIONS:
        return _load_raw(data, filename, working_space)
    if data[:4] in (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+'):
        return _load_tiff(data, filename, working_space)
    messages = []
    with pywarnings.catch_warnings():
        pywarnings.simplefilter('error', Image.DecompressionBombWarning)
        im = Image.open(BytesIO(data))
        _check_size(*im.size)
        format_name = im.format
        if format_name not in ('JPEG', 'PNG', 'WEBP', 'BMP'):
            raise ValueError('支持 JPEG、PNG、TIFF、WebP、BMP 以及 LibRaw 可读取的 RAW。')
        icc = im.info.get('icc_profile')
        exif = im.getexif()
        if not icc and exif.get(40961) == 65535:
            messages.append('EXIF 未声明 sRGB 且没有 ICC，不能推断真实输入色彩空间；暂按 sRGB 解释。')
        profile_name = 'untagged: assumed sRGB'
        if icc and len(icc) > 8 * 1024 * 1024:
            raise ValueError('嵌入 ICC 超出 8 MB 限制。')
        if format_name == 'PNG' and len(data) > 24 and data[24] == 16:
            import cv2
            a = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
            if a is None or a.dtype != np.uint16:
                raise ValueError('无法保持 16 位精度解码此 PNG。')
            if a.ndim == 2:
                a = np.repeat(a[..., None], 3, axis=-1)
            elif a.shape[-1] == 3:
                a = a[..., ::-1]
            else:
                raise ValueError('16 位 PNG 暂不支持透明通道；请导出为 RGB TIFF。')
            rgb = _orient(a.astype(np.float32) / 65535, int(exif.get(274, 1)))
            if icc:
                profile_name = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(BytesIO(icc))).strip()
                rgb = _convert_high_depth_icc(rgb, icc, working_space)
            else:
                messages.append('16 位 PNG 未嵌入 ICC，输入暂按 sRGB 解释。')
                rgb = convert_rgb(rgb, 'srgb', working_space)
            return _finish(rgb, {'filename': Path(filename).name, 'source_format': format_name, 'source_bit_depth': 16, 'source_profile': profile_name}, messages, working_space)
        im = ImageOps.exif_transpose(im)
        if im.mode == 'CMYK' and not icc:
            raise ValueError('CMYK 图片没有嵌入 ICC，无法准确转换。请先转换为带 ICC 的 sRGB 图片。')
        alpha = im.getchannel('A') if 'A' in im.getbands() else None
        if im.mode == 'P':
            if 'transparency' in im.info:
                im = im.convert('RGBA')
                alpha = im.getchannel('A')
            im = im.convert('RGB')
        if icc:
            try:
                source = ImageCms.ImageCmsProfile(BytesIO(icc))
                profile_name = ImageCms.getProfileDescription(source).strip()
                if im.mode in ('RGB', 'RGBA') and _lcms() is not None:
                    rgb = _convert_high_depth_icc(np.asarray(im.convert('RGB'), dtype=np.float32) / 255, icc, working_space)
                    conversion = 'relative colorimetric, float32, direct source ICC -> working ICC'
                else:
                    if im.mode not in ('RGB', 'CMYK', 'LAB', 'L'):
                        im = im.convert('RGB')
                    im = ImageCms.profileToProfile(im, source, ImageCms.ImageCmsProfile(BytesIO(profile_bytes(working_space))), outputMode='RGB', renderingIntent=1)
                    rgb = np.asarray(im, dtype=np.float32) / 255
                    conversion = 'relative colorimetric, 8-bit, direct source ICC -> working ICC'
                    messages.append('此输入类型采用 8 位 ICC 转换。')
            except Exception as exc:
                raise ValueError(f'ICC 转换失败，未按无配置文件图片继续处理：{exc}') from exc
        else:
            messages.append('图片未嵌入 ICC，输入暂按 sRGB 解释并转换到所选工作空间。')
            rgb = convert_rgb(np.asarray(im.convert('RGB'), dtype=np.float32) / 255, 'srgb', working_space)
            conversion = 'assumed sRGB -> working'
        if alpha is not None and alpha.getextrema()[0] < 255:
            alpha_array = np.asarray(alpha, dtype=np.float32)[..., None] / 255
            rgb = rgb * alpha_array + (1 - alpha_array)
            messages.append('透明像素已在工作空间合成到白色背景。')
    return _finish(rgb, {'filename': Path(filename).name, 'source_format': format_name, 'source_bit_depth': 8, 'source_profile': profile_name, 'icc_conversion': conversion}, messages, working_space)


def encode_png(rgb: np.ndarray) -> bytes:
    """8-bit sRGB PNG for preview/download; never used as fitting input internally."""
    image = Image.fromarray(np.floor(_array(rgb) * 255 + 0.5).astype(np.uint8))
    stream = BytesIO()
    image.save(stream, format='PNG', icc_profile=srgb_profile_bytes(), optimize=False)
    return stream.getvalue()


def encode_tiff(rgb: np.ndarray, working_space: str = 'srgb') -> bytes:
    """16-bit integer SDR TIFF with the selected working ICC, no stale EXIF."""
    working_space = normalize_space(working_space)
    import tifffile
    a = np.floor(_array(rgb) * 65535 + 0.5).astype(np.uint16)
    stream = BytesIO()
    tifffile.imwrite(stream, a, photometric='rgb', compression=None, metadata=None, iccprofile=profile_bytes(working_space), software='JC ColorLab - J.C. Lu')
    return stream.getvalue()
