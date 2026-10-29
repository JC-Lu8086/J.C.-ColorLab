"""Original matrix/TRC ICC working profiles. Copyright 2026 J.C. Lu. MIT."""
from __future__ import annotations
import ctypes
import ctypes.util
import sys
from functools import lru_cache
from pathlib import Path
from PIL import ImageCms


class _xyY(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double), ('Y', ctypes.c_double)]


class _Primaries(ctypes.Structure):
    _fields_ = [('Red', _xyY), ('Green', _xyY), ('Blue', _xyY)]


@lru_cache(maxsize=1)
def _lcms():
    from PIL import _imagingcms
    candidates = [str(_imagingcms.__file__)]
    if sys.platform == 'win32':
        candidates.insert(0, str(Path(__file__).parent / 'native' / 'liblcms2-2.dll'))
    found = ctypes.util.find_library('lcms2')
    if found:
        candidates.append(found)
    pil_dir = Path(_imagingcms.__file__).parent
    for directory in [pil_dir, pil_dir.parent / 'pillow.libs', pil_dir.parent / 'Pillow.libs', pil_dir / '.dylibs']:
        if directory.is_dir():
            candidates += [str(p) for p in directory.glob('*lcms*')]
    for candidate in candidates:
        try:
            lib = ctypes.CDLL(candidate)
            ptr, u32, double = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_double
            specs = {
                'cmsOpenProfileFromMem': ([ptr, u32], ptr),
                'cmsCreate_sRGBProfile': ([], ptr),
                'cmsCreateTransform': ([ptr, u32, ptr, u32, u32, u32], ptr),
                'cmsDoTransform': ([ptr, ptr, ptr, u32], None),
                'cmsDeleteTransform': ([ptr], None),
                'cmsCloseProfile': ([ptr], ctypes.c_int),
                'cmsGetColorSpace': ([ptr], u32),
                'cmsCreateRGBProfile': ([ctypes.POINTER(_xyY), ctypes.POINTER(_Primaries), ctypes.POINTER(ptr)], ptr),
                'cmsBuildGamma': ([ptr, double], ptr),
                'cmsBuildParametricToneCurve': ([ptr, ctypes.c_int32, ctypes.POINTER(double)], ptr),
                'cmsFreeToneCurve': ([ptr], None),
                'cmsSaveProfileToMem': ([ptr, ptr, ctypes.POINTER(u32)], ctypes.c_int),
                'cmsMLUalloc': ([ptr, u32], ptr),
                'cmsMLUsetASCII': ([ptr, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int),
                'cmsMLUfree': ([ptr], None),
                'cmsWriteTag': ([ptr, u32, ptr], ctypes.c_int),
            }
            for name, (args, result) in specs.items():
                fn = getattr(lib, name)
                fn.argtypes, fn.restype = args, result
            return lib
        except (OSError, AttributeError):
            continue
    return None


# Chromaticities and transfer functions also appear in color_spaces.py.
# All profiles are generated here, not redistributed vendor ICC files.
_SPECS = {
    'srgb': ('sRGB IEC61966-2.1', ((.64, .33), (.30, .60), (.15, .06)), (.3127, .3290), 'srgb'),
    'adobe-rgb': ('Adobe RGB (1998)', ((.64, .33), (.21, .71), (.15, .06)), (.3127, .3290), 'adobe'),
    'display-p3': ('Display P3', ((.68, .32), (.265, .690), (.15, .06)), (.3127, .3290), 'srgb'),
    'prophoto-rgb': ('ProPhoto RGB D50', ((.7347, .2653), (.1596, .8404), (.0366, .0001)), (.3457, .3585), 'prophoto'),
    'acescg': ('ACEScg AP1 D60 linear normalized SDR', ((.713, .293), (.165, .830), (.128, .044)), (.32168, .33767), 'linear'),
}


@lru_cache(maxsize=5)
def profile_bytes(space: str = 'srgb') -> bytes:
    if space not in _SPECS:
        raise ValueError('不支持的 ICC 工作空间。')
    if space == 'srgb':
        return ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    lib = _lcms()
    if lib is None:
        raise ValueError('此运行环境未提供完整 LittleCMS，不能生成宽色域 ICC；请使用完整构建。')
    name, primaries, white, transfer = _SPECS[space]
    colorants = _Primaries(*[_xyY(x, y, 1.0) for x, y in primaries])
    wp = _xyY(*white, 1.0)
    curve = profile = None
    try:
        if transfer == 'srgb':
            params = (ctypes.c_double * 5)(2.4, 1 / 1.055, .055 / 1.055, 1 / 12.92, .04045)
            curve = lib.cmsBuildParametricToneCurve(None, 4, params)
        elif transfer == 'prophoto':
            params = (ctypes.c_double * 5)(1.8, 1, 0, 1 / 16, 16 / 512)
            curve = lib.cmsBuildParametricToneCurve(None, 4, params)
        else:
            curve = lib.cmsBuildGamma(None, 563 / 256 if transfer == 'adobe' else 1.0)
        if not curve:
            raise ValueError('无法建立工作空间传递函数。')
        curves = (ctypes.c_void_p * 3)(curve, curve, curve)
        profile = lib.cmsCreateRGBProfile(ctypes.byref(wp), ctypes.byref(colorants), curves)
        if not profile:
            raise ValueError('无法建立工作空间 ICC。')
        for signature, text in [(0x64657363, name + ' - JC ColorLab'), (0x63707274, 'Copyright 2026 J.C. Lu; MIT')]:
            mlu = lib.cmsMLUalloc(None, 1)
            try:
                if not mlu or not lib.cmsMLUsetASCII(mlu, b'en', b'US', text.encode('ascii')) or not lib.cmsWriteTag(profile, signature, mlu):
                    raise ValueError('无法写入 ICC 元数据。')
            finally:
                if mlu:
                    lib.cmsMLUfree(mlu)
        count = ctypes.c_uint32()
        if not lib.cmsSaveProfileToMem(profile, None, ctypes.byref(count)):
            raise ValueError('无法计算 ICC 数据尺寸。')
        buffer = ctypes.create_string_buffer(count.value)
        if not lib.cmsSaveProfileToMem(profile, buffer, ctypes.byref(count)):
            raise ValueError('无法写出 ICC 数据。')
        return buffer.raw[:count.value]
    finally:
        if profile:
            lib.cmsCloseProfile(profile)
        if curve:
            lib.cmsFreeToneCurve(curve)


working_icc = profile_bytes
