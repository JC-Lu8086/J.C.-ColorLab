"""Synthetic JPEG stress tests, not claims about physical camera accuracy."""
import io
import cv2
import numpy as np
import pytest
from PIL import Image
from jc_colorlab.chart import chart_manifest, render_chart, detect_chart, sample_patches
from jc_colorlab.core import delta_e_2000, srgb_to_lab


@pytest.mark.parametrize('quality', [60, 80, 95])
def test_exact_half_size_jpeg_recovers_all_marker_identities(quality):
    image = render_chart(7).resize((1920, 1080), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    image.save(stream, format='JPEG', quality=quality, subsampling=2)
    rgb = np.asarray(Image.open(io.BytesIO(stream.getvalue())), dtype=np.float32) / 255
    result = detect_chart(rgb, 7)
    assert result['marker_count'] == 4
    assert result['points'] is not None


@pytest.mark.parametrize('quality', [60, 80, 95])
def test_recommended_chart_survives_jpeg_420_and_half_resolution(quality):
    manifest = chart_manifest(7)
    target = np.asarray(render_chart(7))
    height, width = target.shape[:2]
    destination = np.array([[90, 50], [1950, 85], [1910, 1130], [120, 1150]], np.float32)
    transform = cv2.getPerspectiveTransform(np.array([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]], np.float32), destination)
    photo = cv2.warpPerspective(target, transform, (2050, 1200), borderValue=(28, 28, 28))
    photo = cv2.GaussianBlur(photo, (3, 3), .55)
    buffer = io.BytesIO()
    Image.fromarray(photo).save(buffer, format='JPEG', quality=quality, subsampling=2)
    decoded = np.asarray(Image.open(io.BytesIO(buffer.getvalue())), dtype=np.float32)/255
    found = detect_chart(decoded, 7)
    assert found['marker_count'] == 4
    samples = sample_patches(decoded, found['points'], radius=.006)
    assert all(samples['valid'])
    error = delta_e_2000(srgb_to_lab(samples['colors']), srgb_to_lab([p['rgb'] for p in manifest['patches']]))
    assert np.mean(error) < 1.5
    assert np.percentile(error, 95) < 3

