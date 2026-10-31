"""Interchange tests decode the output independently from the writer."""
import hashlib
import struct
import xml.etree.ElementTree as ET
import zlib

import numpy as np
import pytest

from jc_colorlab.adobe import CRS, export_adobe_xmp, _base85_encode


class Identity:
    def predict(self, rgb):
        return rgb


class CrossChannel:
    def predict(self, rgb):
        return np.asarray(rgb)[:, [2, 0, 1]] * .75 + .1


def independent_decode(xmp, expected_encoding=(0, 1)):
    desc = ET.fromstring(xmp).find('.//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description')
    digest = desc.attrib[f'{{{CRS}}}RGBTable']
    encoded = desc.attrib[f'{{{CRS}}}Table_{digest}']
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#"
    buffer = bytearray()
    for i in range(0, len(encoded), 5):
        group = encoded[i:i + 5]
        value = sum(alphabet.index(c) * 85 ** j for j, c in enumerate(group))
        buffer.extend(value.to_bytes(4, 'little')[:len(group) - 1])
    size_bytes, = struct.unpack('<I', buffer[:4])
    raw = zlib.decompress(buffer[4:])
    assert len(raw) == size_bytes
    assert hashlib.md5(raw).hexdigest().upper() == digest
    table_type, version, dimensions, size = struct.unpack('<4I', raw[:16])
    assert (table_type, version, dimensions) == (1, 1, 3)
    n = size ** 3
    diffs = np.frombuffer(raw[16:16 + n * 6], dtype='<u2').reshape(size, size, size, 3).astype(np.int64)
    expected_bytes = 16 + n * 6 + 28
    assert len(raw) == expected_bytes
    assert struct.unpack('<3I2d', raw[16 + n * 6:]) == (*expected_encoding, 0, 0.0, 2.0)
    restored = np.empty_like(diffs)
    for r in range(size):
        for g in range(size):
            for b in range(size):
                identity = np.array([(i * 65535 + size // 2) // (size - 1) for i in (r, g, b)])
                restored[r, g, b] = (diffs[r, g, b] + identity) % 65536
    return restored / 65535, desc


def test_identity_lut_all_nodes_and_metadata():
    xmp, info = export_adobe_xmp(Identity(), '测试 <A&B>')
    restored, desc = independent_decode(xmp)
    axis = np.linspace(0, 1, 32)
    expected = np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), axis=-1)
    assert np.max(np.abs(restored - expected)) <= 0.5 / 65535 + 1e-12
    assert desc.attrib[f'{{{CRS}}}SupportsSceneReferred'] == 'False'
    assert desc.attrib[f'{{{CRS}}}SupportsOutputReferred'] == 'True'
    assert info['grid_size'] == 32 and info['quantization_bits'] == 16
    assert '测试 &lt;A&amp;B&gt;' in xmp


def test_cross_channel_table_order():
    xmp, _ = export_adobe_xmp(CrossChannel(), size=8)
    restored, _ = independent_decode(xmp)
    axis = np.linspace(0, 1, 8)
    coords = np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), axis=-1)
    expected = CrossChannel().predict(coords.reshape(-1, 3)).reshape(coords.shape)
    assert np.max(np.abs(restored - expected)) <= 0.5 / 65535 + 1e-12


@pytest.mark.parametrize('length', range(1, 20))
def test_base85_tail_round_trip(length):
    data = bytes(range(length))
    encoded = _base85_encode(data)
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#"
    result = bytearray()
    for i in range(0, len(encoded), 5):
        part = encoded[i:i + 5]
        n = sum(alphabet.index(c) * 85 ** j for j, c in enumerate(part))
        result += n.to_bytes(4, 'little')[:len(part) - 1]
    assert bytes(result) == data


def test_invalid_grid_size():
    with pytest.raises(ValueError):
        export_adobe_xmp(Identity(), size=33)


@pytest.mark.parametrize('space,header', [('srgb',(0,1)), ('adobe-rgb',(1,3)), ('display-p3',(3,1)), ('prophoto-rgb',(2,2))])
def test_native_wide_table_headers_and_transfer_adapters(space, header):
    from jc_colorlab.color_spaces import encode_rgb, decode_rgb
    model = CrossChannel()
    model.color_space = space
    xmp, info = export_adobe_xmp(model, size=16)
    restored, _ = independent_decode(xmp, header)
    coordinates = np.stack(np.meshgrid(*[np.linspace(0,1,16)]*3,indexing='ij'),axis=-1)
    flat = coordinates.reshape(-1,3)
    if space in ('adobe-rgb','prophoto-rgb'):
        gamma = 2.2 if space == 'adobe-rgb' else 1.8
        encoded = encode_rgb(flat ** gamma,space)
        expected = np.maximum(decode_rgb(model.predict(encoded),space),0) ** (1/gamma)
    else:
        expected = model.predict(flat)
    assert np.max(np.abs(restored.reshape(-1,3)-expected)) <= .5/65535+1e-12
    assert info['xmp_table_space']==space and info['model_space']==space


def test_aces_xmp_explicit_srgb_adapter():
    from jc_colorlab.color_spaces import convert_rgb
    model=CrossChannel();model.color_space='acescg'
    xmp,info=export_adobe_xmp(model,size=8)
    restored,_=independent_decode(xmp)
    coordinates=np.stack(np.meshgrid(*[np.linspace(0,1,8)]*3,indexing='ij'),axis=-1).reshape(-1,3)
    expected=np.clip(convert_rgb(model.predict(convert_rgb(coordinates,'srgb','acescg')),'acescg','srgb'),0,1)
    assert np.max(np.abs(restored.reshape(-1,3)-expected))<=.5/65535+1e-12
    assert info['xmp_table_space']=='srgb' and info['model_space']=='acescg'
    assert any('不是原生 ACES' in warning for warning in info['warnings'])
