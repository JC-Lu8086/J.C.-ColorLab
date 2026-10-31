import io
import json
import numpy as np
import pytest
from PIL import Image
from jc_colorlab.server import create_app
from jc_colorlab.chart import render_chart


def test_session_origin_and_host_protection():
    app = create_app('test-token')
    client = app.test_client()
    assert client.get('/').status_code == 200
    assert client.get('/api/state').status_code == 403
    assert client.get('/api/state', headers={'X-Lab-Token':'test-token'}).status_code == 200
    assert client.get('/', base_url='http://evil.example').status_code == 403
    assert client.post('/api/demo', headers={'X-Lab-Token':'test-token','Origin':'https://evil.example'}).status_code == 403


def test_jpeg_upload_fit_export_manual_edit_invalidates_and_reload():
    app = create_app('test-token')
    client = app.test_client()
    headers = {'X-Lab-Token':'test-token'}
    chart = render_chart(7).resize((1920,1080), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    chart.save(buffer, format='JPEG', quality=90, subsampling=2, icc_profile=chart.info['icc_profile'])
    response = client.post('/api/upload', data={'role':'source','file':(io.BytesIO(buffer.getvalue()),'test.jpg')}, headers=headers)
    assert response.status_code == 200, response.json
    points = response.json['image']['points']
    assert len(points) == 376
    assert client.get('/api/export/baseline-tiff',headers=headers).status_code == 200
    response = client.post('/api/fit', json={'mode':'calibrate','fraction':.18,'title':'JPEG test','excluded':[]},headers=headers)
    assert response.status_code == 200, response.json
    assert response.json['report']['used_patches'] == 376
    assert response.json['report']['model']['validation']['after']['mean'] < 3
    for kind, marker in [('cube',b'LUT_3D_SIZE 17'),('xmp',b'crs:RGBTable='),('report',b'used_patches')]:
        r=client.get('/api/export/'+kind+'?size=17', headers=headers)
        assert r.status_code == 200, r.json
        assert marker in r.data
    saved=client.get('/api/export/model',headers=headers).data
    points[0][0] += .001
    assert client.post('/api/points',json={'role':'source','points':points},headers=headers).status_code==200
    assert not client.get('/api/state',headers=headers).json['has_model']
    assert client.post('/api/import-model',data={'file':(io.BytesIO(saved),'project.json')},headers=headers).status_code==200
    assert client.get('/api/state',headers=headers).json['has_model']
    assert client.get('/api/state',headers=headers).json['images']=={}


def test_invalid_manual_corners_and_density_clears_state():
    app=create_app('test-token');client=app.test_client();headers={'X-Lab-Token':'test-token'}
    r=client.post('/api/corners',json={'role':'source','corners':[[0,0],[1,1],[0,1],[1,0]]},headers=headers)
    assert r.status_code==400
    r=client.post('/api/settings',json={'levels':7},headers=headers)
    assert r.status_code==200
    assert client.get('/api/state',headers=headers).json['manifest']['patch_count']==376


@pytest.mark.parametrize('space', ['srgb','adobe-rgb','display-p3','prophoto-rgb','acescg'])
def test_working_space_settings_and_embedded_tiff(space):
    from jc_colorlab.image_io import load_image
    from jc_colorlab.color_spaces import convert_rgb
    app=create_app('test-token');client=app.test_client();headers={'X-Lab-Token':'test-token'}
    assert client.post('/api/settings',json={'levels':7,'working_space':space,'target_space':'srgb'},headers=headers).status_code==200
    assert client.get('/api/state',headers=headers).json['working_space']==space
    pixels=np.full((100,120,3),[180,120,60],dtype=np.uint8)
    buffer=io.BytesIO();Image.fromarray(pixels).save(buffer,format='PNG')
    result=client.post('/api/upload',data={'role':'test','file':(io.BytesIO(buffer.getvalue()),'test.png')},headers=headers)
    assert result.status_code==200,result.json
    response=client.get('/api/export/baseline-tiff?role=test',headers=headers)
    assert response.status_code==200,response.json
    loaded=load_image(response.data,'export.tif',working_space=space)
    expected=convert_rgb(pixels[0,0]/255,'srgb',space,clip=True)
    np.testing.assert_allclose(loaded.rgb[0,0],expected,atol=8e-4)


def test_target_gamut_mismatch_is_exposed_before_fitting():
    app=create_app('test-token');client=app.test_client();headers={'X-Lab-Token':'test-token'}
    assert client.post('/api/settings',json={'target_space':'display-p3','working_space':'srgb'},headers=headers).status_code==200
    assert client.get('/api/state',headers=headers).json['manifest']['working_gamut_excluded_count']>0
    assert client.post('/api/settings',json={'target_space':'display-p3','working_space':'prophoto-rgb'},headers=headers).status_code==200
    assert client.get('/api/state',headers=headers).json['target_space']=='display-p3'



def test_file_picker_includes_every_raw_extension():
    import re
    from jc_colorlab.image_io import RAW_EXTENSIONS
    page=create_app('test-token').test_client().get('/').get_data(as_text=True)
    accepted=set(re.search(r'id="file-input"[^>]*accept="([^"]+)"',page).group(1).split(','))
    assert RAW_EXTENSIONS <= accepted
    assert '__IMAGE_EXTENSIONS__' not in page


@pytest.mark.parametrize("route", ["/", "/chart"])
def test_pages_ignore_windows_default_text_encoding(monkeypatch, route):
    from pathlib import Path
    from jc_colorlab.server import STATIC
    original = Path.read_text
    def windows_read_text(path, encoding=None, errors=None):
        if path.parent == STATIC and path.suffix == ".html":
            return path.read_bytes().decode(encoding or "cp1252", errors or "strict")
        return original(path, encoding=encoding, errors=errors)
    monkeypatch.setattr(Path, "read_text", windows_read_text)
    response = create_app("test-token").test_client().get(route)
    assert response.status_code == 200
    assert "JC ColorLab" in response.get_data(as_text=True)
