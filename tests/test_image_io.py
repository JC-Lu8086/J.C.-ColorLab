from io import BytesIO
from types import SimpleNamespace
import sys

import numpy as np
from PIL import Image, ImageCms
import pytest
import tifffile

from jc_colorlab.image_io import load_image, encode_png, encode_tiff, _lcms, _orient, _convert_high_depth_icc, srgb_profile_bytes


def test_png_icc_roundtrip():
    a = np.random.default_rng(4).random((20, 15, 3)).astype(np.float32)
    encoded = encode_png(a)
    assert Image.open(BytesIO(encoded)).info['icc_profile']
    loaded = load_image(encoded, 'test.png')
    assert loaded.metadata['source_bit_depth'] == 8
    assert np.max(np.abs(loaded.rgb - a)) < 0.51 / 255


def test_tiff_16bit_preserves_precision():
    a = np.linspace(.3, .31, 2700).reshape(30, 30, 3).astype(np.float32)
    encoded = encode_tiff(a)
    with tifffile.TiffFile(BytesIO(encoded)) as tif:
        assert tif.pages[0].dtype == np.dtype('uint16')
        assert 34675 in tif.pages[0].tags
    if _lcms() is None:
        pytest.skip('This Pillow build does not expose LittleCMS for float32 ICC conversions')
    loaded = load_image(encoded, 'test.tif')
    assert loaded.rgb.dtype == np.float32
    assert np.max(np.abs(loaded.rgb - a)) < 1.1 / 65535
    assert len(np.unique(loaded.rgb)) > 400  # Would be only four codes at 8-bit.


def test_untagged_tiff_retains_codes_and_warns():
    a = np.arange(120, dtype=np.uint16).reshape(5, 8, 3) + 28000
    buffer = BytesIO()
    tifffile.imwrite(buffer, a, photometric='rgb', metadata=None)
    loaded = load_image(buffer.getvalue(), 'x.tiff')
    assert np.array_equal(np.rint(loaded.rgb * 65535).astype(np.uint16), a)
    assert any('ICC' in w for w in loaded.warnings)


def test_16bit_png_retains_precision():
    import cv2
    a = np.arange(2700, dtype=np.uint16).reshape(30, 30, 3) + 10000
    success, encoded = cv2.imencode('.png', a[..., ::-1])
    assert success
    loaded = load_image(encoded.tobytes(), 'hi.png')
    assert loaded.metadata['source_bit_depth'] == 16
    assert np.array_equal(np.rint(loaded.rgb * 65535).astype(np.uint16), a)


def test_exif_orientation_matches_pillow():
    a = np.arange(12 * 3, dtype=np.uint8).reshape(3, 4, 3)
    for orientation in range(1, 9):
        im = Image.fromarray(a)
        exif = im.getexif()
        exif[274] = orientation
        stream = BytesIO()
        im.save(stream, format='PNG', exif=exif, icc_profile=srgb_profile_bytes())
        loaded = load_image(stream.getvalue(), 'oriented.png')
        assert np.array_equal(np.rint(loaded.rgb * 255).astype(np.uint8), _orient(a, orientation))


def test_invalid_icc_fails_instead_of_assuming_srgb():
    stream = BytesIO()
    Image.new('RGB', (5, 5)).save(stream, format='PNG', icc_profile=b'not a profile')
    with pytest.raises(ValueError, match='ICC'):
        load_image(stream.getvalue(), 'bad.png')


def test_high_depth_icc_missing_engine_fails(monkeypatch):
    import jc_colorlab.image_io as io
    monkeypatch.setattr(io, '_lcms', lambda: None)
    with pytest.raises(ValueError, match='高位深'):
        _convert_high_depth_icc(np.zeros((1, 1, 3), np.float32), srgb_profile_bytes())


def test_float_tiff_is_not_misinterpreted_as_srgb():
    stream = BytesIO()
    tifffile.imwrite(stream, np.ones((3, 4, 3), np.float32) * 1.5, photometric='rgb')
    with pytest.raises(ValueError, match='HDR'):
        load_image(stream.getvalue(), 'hdr.tif')


@pytest.mark.parametrize("pattern,layout", [(np.array([[0,1],[3,2]]), "Bayer 2x2"), (np.zeros((6,6),dtype=int), "X-Trans 6x6"), (None, "other / no repeated CFA")])
def test_raw_recipe_is_fixed_and_explicit(monkeypatch, pattern, layout):
    calls = {}
    class FakeRaw:
        sizes = SimpleNamespace(width=4, height=3)
        camera_whitebalance = [2.0, 1.0, 1.5, 1.0]
        raw_pattern = pattern
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def postprocess(self, **kwargs):
            calls.update(kwargs)
            return np.full((3, 4, 3), 32768, np.uint16)
    fake = SimpleNamespace(imread=lambda _: FakeRaw(), DemosaicAlgorithm=SimpleNamespace(AHD=3), ColorSpace=SimpleNamespace(sRGB=1, ProPhoto=4), HighlightMode=SimpleNamespace(Clip=0), __version__='test', libraw_version=(0, 0, 1))
    monkeypatch.setitem(sys.modules, 'rawpy', fake)
    loaded = load_image(b'fake raw', 'test.nef')
    assert loaded.metadata['raw_recipe']['sensor_layout'] == layout
    assert loaded.metadata['raw_recipe']['requested_quality'] == 3
    assert calls['no_auto_bright'] is True
    assert calls['use_auto_wb'] is False
    assert calls['use_camera_wb'] is True
    assert calls['gamma'] == (1.0, 1.0) and calls['output_bps'] == 16
    assert calls['adjust_maximum_thr'] == 0.0
    assert loaded.metadata['raw_recipe']['white_balance'] == 'as-shot'
    assert calls['output_color'] == 4
    assert loaded.metadata['raw_recipe']['intermediate_space'] == 'LibRaw ProPhoto D65 (not standard ProPhoto RGB)'
    assert np.max(np.abs(loaded.rgb - (1.055 * (32768 / 65535) ** (1 / 2.4) - .055))) < .0002
    assert any('显影' in w for w in loaded.warnings)


@pytest.mark.parametrize('space', ['srgb','adobe-rgb','display-p3','prophoto-rgb','acescg'])
def test_working_icc_tiff_native_roundtrip(space):
    from jc_colorlab.icc import profile_bytes
    a=np.random.default_rng(72).uniform(.03,.95,(12,13,3)).astype(np.float32)
    encoded=encode_tiff(a,working_space=space)
    loaded=load_image(encoded,'work.tif',working_space=space)
    assert loaded.metadata['working_space']==space
    assert np.max(np.abs(loaded.rgb-a)) < 3/65535
    assert ImageCms.ImageCmsProfile(BytesIO(profile_bytes(space))).profile.xcolor_space.strip()=='RGB'


@pytest.mark.parametrize('space', ['adobe-rgb','display-p3','prophoto-rgb','acescg'])
def test_direct_icc_conversion_matches_color_science(space):
    from jc_colorlab.color_spaces import convert_rgb
    a=np.random.default_rng(9).uniform(.1,.9,(8,9,3)).astype(np.float32)
    loaded=load_image(encode_tiff(a),'x.tif',working_space=space)
    expected=convert_rgb(a,'srgb',space)
    assert np.max(np.abs(loaded.rgb-expected))<.0005


def test_wide_icc_import_does_not_pass_through_srgb():
    # Saturated Display-P3 red would be irreversibly clipped through sRGB.
    a=np.array([[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]],np.float32)
    loaded=load_image(encode_tiff(a,'display-p3'),'p3.tif','display-p3')
    assert np.max(np.abs(loaded.rgb-a)) < 2/65535
