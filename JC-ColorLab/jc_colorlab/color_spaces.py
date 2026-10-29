"""Explicit RGB encodings, linear-light matrices and Bradford adaptation.

Copyright (c) 2026 J.C. Lu. MIT license.
Specifications: https://www.w3.org/TR/css-color-4/#color-conversion-code
https://www.adobe.com/digitalimag/pdfs/AdobeRGB1998.pdf
https://docs.acescentral.com/encodings/acescg/
Conversions preserve out-of-range floating values unless clip=True is requested.
They do not perform gamut mapping, tone mapping, an ACES view transform, or
convert a physical display into a colorimetric reference instrument.
"""
from __future__ import annotations
import numpy as np

WHITE_POINTS={"D65":(.3127,.3290),"D50":(.3457,.3585),"D60":(.32168,.33767)}
BRADFORD=np.array([[.8951,.2664,-.1614],[-.7502,1.7135,.0367],[.0389,-.0685,1.0296]],dtype=np.float64)


def xy_to_xyz(xy):
    xy=np.asarray(xy,dtype=np.float64)
    if xy.shape!=(2,) or not np.all(np.isfinite(xy)) or xy[1]<=0:
        raise ValueError("白点必须是有效的 CIE xy 坐标。")
    return np.array([xy[0]/xy[1],1.,(1-xy[0]-xy[1])/xy[1]])


def _matrix(primaries,white_xy):
    p=np.column_stack([xy_to_xyz(xy) for xy in primaries])
    scale=np.linalg.solve(p,xy_to_xyz(white_xy))
    return p*scale


SPACES={
    "srgb":{"name":"sRGB IEC61966-2.1","primaries":((.64,.33),(.30,.60),(.15,.06)),"white_xy":WHITE_POINTS["D65"],"white_name":"D65","transfer":"srgb","encoding":"encoded","screen_target":True},
    "adobe-rgb":{"name":"Adobe RGB (1998)","primaries":((.64,.33),(.21,.71),(.15,.06)),"white_xy":WHITE_POINTS["D65"],"white_name":"D65","transfer":"gamma563/256","encoding":"encoded","screen_target":True},
    "display-p3":{"name":"Display P3","primaries":((.68,.32),(.265,.69),(.15,.06)),"white_xy":WHITE_POINTS["D65"],"white_name":"D65","transfer":"srgb","encoding":"encoded","screen_target":True},
    "prophoto-rgb":{"name":"ProPhoto RGB","primaries":((.7347,.2653),(.1596,.8404),(.0366,.0001)),"white_xy":WHITE_POINTS["D50"],"white_name":"D50","transfer":"prophoto1.8","encoding":"encoded","screen_target":False},
    "acescg":{"name":"ACEScg / AP1 (SDR 0–1)","primaries":((.713,.293),(.165,.830),(.128,.044)),"white_xy":WHITE_POINTS["D60"],"white_name":"D60","transfer":"linear","encoding":"linear","screen_target":False},
}
for _space in SPACES.values():
    _m=_matrix(_space["primaries"],_space["white_xy"])
    _space["to_xyz"]=_m.tolist()
    _space["from_xyz"]=np.linalg.inv(_m).tolist()
    _space["lut_domain"]=[0.,1.]


def normalize_space(space):
    if space=="encoded sRGB IEC61966-2.1":return "srgb"
    if not isinstance(space,str) or space not in SPACES:
        raise ValueError("不支持的色彩空间；请选择 sRGB、Adobe RGB、Display P3、ProPhoto RGB 或 ACEScg。")
    return space


def _rgb(values):
    values=np.asarray(values,dtype=np.float64)
    if values.shape[-1:]!=(3,) or not np.all(np.isfinite(values)):
        raise ValueError("颜色必须是有限数值的 (..., 3) 数组。")
    return values


def decode_rgb(rgb,space="srgb"):
    """Decode to linear light. Signed extensions preserve negative values."""
    space=normalize_space(space);v=_rgb(rgb);a=np.abs(v);sign=np.sign(v)
    trc=SPACES[space]["transfer"]
    if trc=="linear":return v.copy()
    if trc=="srgb":return sign*np.where(a<=.04045,a/12.92,((a+.055)/1.055)**2.4)
    if trc=="gamma563/256":return sign*a**(563/256)
    return sign*np.where(a<=1/32,a/16,a**1.8)


def encode_rgb(linear,space="srgb"):
    """Encode linear light; preserve values beyond the nominal SDR range."""
    space=normalize_space(space);v=_rgb(linear);a=np.abs(v);sign=np.sign(v)
    trc=SPACES[space]["transfer"]
    if trc=="linear":return v.copy()
    if trc=="srgb":return sign*np.where(a<=.0031308,a*12.92,1.055*a**(1/2.4)-.055)
    if trc=="gamma563/256":return sign*a**(256/563)
    return sign*np.where(a<=1/512,a*16,a**(1/1.8))


def _white(white):
    return WHITE_POINTS[white] if isinstance(white,str) and white in WHITE_POINTS else white


def bradford_matrix(source_xy,target_xy):
    """Return XYZ-column-vector Bradford chromatic adaptation matrix."""
    source=xy_to_xyz(_white(source_xy));target=xy_to_xyz(_white(target_xy))
    if np.allclose(source,target,rtol=0,atol=1e-14):return np.eye(3)
    src_cone=BRADFORD@source;dst_cone=BRADFORD@target
    return np.linalg.inv(BRADFORD)@np.diag(dst_cone/src_cone)@BRADFORD


def rgb_to_xyz(rgb,space="srgb",white="native"):
    """Return relative XYZ, Ywhite=1, adapted to white if not 'native'."""
    space=normalize_space(space)
    xyz=decode_rgb(rgb,space)@np.asarray(SPACES[space]["to_xyz"]).T
    if isinstance(white,str) and white=="native":return xyz
    return xyz@bradford_matrix(SPACES[space]["white_xy"],_white(white)).T


def xyz_to_rgb(xyz,space="srgb",white="native"):
    """Encode XYZ from the declared source white; no clipping or tone mapping."""
    space=normalize_space(space);xyz=_rgb(xyz)
    if not (isinstance(white,str) and white=="native"):
        xyz=xyz@bradford_matrix(_white(white),SPACES[space]["white_xy"]).T
    return encode_rgb(xyz@np.asarray(SPACES[space]["from_xyz"]).T,space)


def convert_rgb(rgb,src,dst,clip=False):
    """Convert RGB encodings using Bradford between their native white points."""
    src=normalize_space(src);dst=normalize_space(dst);rgb=_rgb(rgb)
    if src==dst:result=rgb.copy()
    else:result=xyz_to_rgb(rgb_to_xyz(rgb,src),dst,white=SPACES[src]["white_xy"])
    return np.clip(result,0,1) if clip else result


def rgb_to_lab(rgb,space="srgb"):
    """CIELAB diagnostics under common D65 after Bradford adaptation."""
    xyz=rgb_to_xyz(rgb,space,white="D65")
    ratio=xyz/xy_to_xyz(WHITE_POINTS["D65"])
    delta=6/29
    f=np.where(ratio>delta**3,np.cbrt(ratio),ratio/(3*delta**2)+4/29)
    return np.stack((116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])),axis=-1)
