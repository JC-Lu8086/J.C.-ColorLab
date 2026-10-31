"""Adobe enhanced-profile interoperability. Copyright (c) 2026 J.C. Lu, MIT.

Independent serializer of the documented DNG SDK RGBTable wire representation.
No Adobe SDK code or Adobe-authored LUT samples are included in this package.
The table operates on encoded sRGB output values, not camera sensor data.
"""
from __future__ import annotations

import hashlib
import struct
import uuid
import xml.etree.ElementTree as ET
import zlib

import numpy as np
from .color_spaces import normalize_space, convert_rgb, encode_rgb, decode_rgb, SPACES

CRS = 'http://ns.adobe.com/camera-raw-settings/1.0/'
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
XMP = 'adobe:ns:meta/'
XML = 'http://www.w3.org/XML/1998/namespace'
# Alphabet of Adobe's little-endian base-85 XMP big-table transport.
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#"


def _base85_encode(data: bytes) -> str:
    parts = []
    for offset in range(0, len(data), 4):
        block = data[offset:offset + 4]
        n = int.from_bytes(block, 'little')
        digits = []
        for _ in range(len(block) + 1):
            n, digit = divmod(n, 85)
            digits.append(_ALPHABET[digit])
        parts.append(''.join(digits))
    return ''.join(parts)


def _serialize_rgb_table(model, size: int = 32) -> tuple[bytes, dict]:
    if not 2 <= size <= 32:
        raise ValueError('XMP RGBTable 尺寸必须在 2 至 32 之间，以兼容较早版本的 Camera Raw。')
    model_space = normalize_space(getattr(model, 'color_space', 'srgb'))
    table_space = 'srgb' if model_space == 'acescg' else model_space
    primaries, gamma = {'srgb': (0, 1), 'adobe-rgb': (1, 3), 'prophoto-rgb': (2, 2), 'display-p3': (3, 1)}[table_space]
    axis = np.linspace(0, 1, size, dtype=np.float64)
    # Adobe serializes blue fastest (CUBE serializes red fastest).
    coordinates = np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), axis=-1).reshape(-1, 3)
    samples = []
    clipped = 0
    for start in range(0, len(coordinates), 4096):
        nodes = coordinates[start:start + 4096]
        if model_space == 'acescg':
            inputs = convert_rgb(nodes, 'srgb', 'acescg')
        elif table_space in ('adobe-rgb', 'prophoto-rgb'):
            # Adobe's table gamma enums are pure 2.2/1.8. Adapt to exact
            # Adobe RGB gamma563/256 / standard ProPhoto toe before fitting.
            table_exponent = 2.2 if table_space == 'adobe-rgb' else 1.8
            inputs = encode_rgb(nodes ** table_exponent, model_space)
        else:
            inputs = nodes
        predicted = np.asarray(model.predict(inputs), dtype=np.float64)
        if model_space == 'acescg':
            predicted = convert_rgb(predicted, 'acescg', 'srgb')
        elif table_space in ('adobe-rgb', 'prophoto-rgb'):
            linear = decode_rgb(predicted, model_space)
            predicted = np.sign(linear) * np.abs(linear) ** (1 / table_exponent)
        if predicted.shape != coordinates[start:start + 4096].shape or not np.isfinite(predicted).all():
            raise ValueError('色彩映射输出无效，无法导出 XMP。')
        clipped += int(np.count_nonzero((predicted < 0) | (predicted > 1)))
        samples.append(np.floor(np.clip(predicted, 0, 1) * 65535 + 0.5).astype(np.int64))
    values = np.concatenate(samples)
    identity_axis = (np.arange(size, dtype=np.int64) * 65535 + (size >> 1)) // (size - 1)
    identity = np.stack(np.meshgrid(identity_axis, identity_axis, identity_axis, indexing='ij'), axis=-1).reshape(-1, 3)
    differences = ((values - identity) & 0xFFFF).astype('<u2')
    # Type=RGBTable, format version=1, dimensions=3; samples; sRGB primaries,
    # sRGB transfer curve, clip out-of-gamut input; amount range 0..2.
    raw = struct.pack('<4I', 1, 1, 3, size) + differences.tobytes() + struct.pack('<3I2d', primaries, gamma, 0, 0.0, 2.0)
    return raw, {'grid_size': size, 'quantization_bits': 16, 'model_space': model_space, 'xmp_table_space': table_space, 'table_primaries_enum': primaries, 'table_gamma_enum': gamma, 'clipped_channel_fraction': clipped / (len(coordinates) * 3)}


def export_adobe_xmp(model, title: str = 'JC ColorLab', size: int = 32) -> tuple[str, dict]:
    """Return a real embedded RGBTable profile and its explicit applicability.

    The profile intentionally does not appear on RAW/HDR source images: its
    domain is the developed SDR working-space baseline used to fit the model. Applying
    it to a different RAW rendering pipeline is not scientifically equivalent.
    Adobe import/render validation remains a separate application-level check.
    """
    raw, info = _serialize_rgb_table(model, size)
    fingerprint = hashlib.md5(raw).hexdigest().upper()  # Adobe format key, not security.
    transport = struct.pack('<I', len(raw)) + zlib.compress(raw)
    encoded = _base85_encode(transport)
    title = str(title).strip()[:160] or 'JC ColorLab'
    for prefix, uri in [('x', XMP), ('rdf', RDF), ('crs', CRS)]:
        ET.register_namespace(prefix, uri)
    document = ET.Element(f'{{{XMP}}}xmpmeta', {f'{{{XMP}}}xmptk': 'JC ColorLab 0.1.0'})
    rdf = ET.SubElement(document, f'{{{RDF}}}RDF')
    attributes = {
        'PresetType': 'Look', 'Cluster': 'J.C. Lu',
        'UUID': uuid.uuid5(uuid.NAMESPACE_URL, 'jc-colorlab:' + title + ':' + fingerprint).hex.upper(),
        'SupportsAmount': 'True', 'SupportsColor': 'True', 'SupportsMonochrome': 'False',
        'SupportsHighDynamicRange': 'False', 'SupportsNormalDynamicRange': 'True',
        'SupportsSceneReferred': 'False', 'SupportsOutputReferred': 'True',
        'CameraModelRestriction': '', 'Copyright': 'Copyright 2026 J.C. Lu',
        'ContactInfo': '', 'Version': '10.3', 'ProcessVersion': '10.0',
        'ConvertToGrayscale': 'False', 'RGBTable': fingerprint,
        'Table_' + fingerprint: encoded, 'RGBTableAmount': '1.000000', 'HasSettings': 'True',
    }
    description = ET.SubElement(rdf, f'{{{RDF}}}Description', {f'{{{RDF}}}about': '', **{f'{{{CRS}}}{k}': v for k, v in attributes.items()}})
    text_fields = {
        'Name': title, 'ShortName': '', 'SortName': title, 'Group': 'JC ColorLab',
        'Description': f"SDR output-referred {info['xmp_table_space']} 3D LUT from {info['model_space']} model. Use the same developed baseline. Not a camera DCP or display ICC. {size}-cube, 16-bit nodes." + (' ACEScg conversion is limited to sRGB gamut; not a native ACES profile.' if info['model_space'] == 'acescg' else ''),
    }
    for field, text in text_fields.items():
        alt = ET.SubElement(ET.SubElement(description, f'{{{CRS}}}{field}'), f'{{{RDF}}}Alt')
        ET.SubElement(alt, f'{{{RDF}}}li', {f'{{{XML}}}lang': 'x-default'}).text = text
    ET.indent(document, space=' ')
    text = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(document, encoding='unicode') + '\n'
    info.update({
        'format': 'Adobe enhanced XMP profile with embedded RGBTable',
        'fingerprint': fingerprint, 'input_space': info['xmp_table_space'] + ' SDR', 'output_space': info['xmp_table_space'] + ' SDR',
        'supports_raw': False, 'supports_hdr': False, 'supports_output_referred': True,
        'compatibility': 'RGBTable serializer validated against Adobe DNG SDK wire format; Adobe import and render behavior not yet certified.',
        'warnings': ['仅适用于与拟合时相同显影基准的 SDR 图片。RAW 需先显影成带正确 ICC 的 TIFF；未应用映射的基准 TIFF 才能再应用此 XMP。', 'XMP 是真正的三维 LUT 配置文件；CUBE 的格点与传递函数可能不同，插值结果可略有差异。'] + (['ACEScg 在此 XMP 中通过 sRGB 转换适配，无法表达 sRGB 之外的颜色；不是原生 ACES 配置文件。'] if info['model_space'] == 'acescg' else []),
        'sources': ['https://www.adobe.com/support/downloads/dng/dng_sdk.html', 'https://download.adobe.com/pub/adobe/lightroom/profile-sdk/ACR_and_Lightroom_Profile_SDK.zip'],
    })
    return text, info
