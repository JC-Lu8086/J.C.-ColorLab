import io
import numpy as np
import pytest
from PIL import Image
from jc_colorlab.chart import chart_manifest, render_chart, sample_patches
from jc_colorlab.color_spaces import decode_rgb
from jc_colorlab.image_io import _check_size, MAX_PIXELS, MAX_FILE_BYTES, load_image, write_tiff
from jc_colorlab.server import create_app
from jc_colorlab.core import fit_mapping

@pytest.mark.parametrize('space',['srgb','display-p3','adobe-rgb'])
def test_wb_bar_is_uniform_neutral_and_outside_sampling_grid(space):
    manifest=chart_manifest(7,space);bar=manifest['white_balance_reference']
    x,y,w,h=bar['rect'];pixels=np.asarray(render_chart(7,space))
    assert w>=1200 and h>=130
    np.testing.assert_array_equal(pixels[y:y+h,x:x+w],np.broadcast_to(bar['rgb8'],(h,w,3)))
    assert len(set(bar['rgb8']))==1
    assert abs(bar['linear_Y']-.18)<.003
    assert bar['linear_Y']==pytest.approx(decode_rgb(bar['rgb'],space)[0])
    assert manifest['patch_count']==376
    for p in manifest['patches']:
        a,b,c,d=p['rect']
        assert x+w<=a or a+c<=x or y+h<=b or b+d<=y


def test_240mp_boundary_and_pillow_guard():
    assert MAX_PIXELS==240_000_000 and Image.MAX_IMAGE_PIXELS==MAX_PIXELS
    assert MAX_FILE_BYTES>=240_000_000*6
    _check_size(12000,8500)  # 102 MP
    _check_size(20000,12000) # exactly 240 MP
    with pytest.raises(ValueError,match='240MP'):_check_size(20001,12000)
    with pytest.raises(ValueError,match='合计'):_check_size(12000,8500,pixel_limit=100_000_000)


def test_replacing_photo_budget_excludes_old_slot_and_rejects_before_decode(monkeypatch):
    import jc_colorlab.server as server
    from jc_colorlab.image_io import LoadedImage
    calls=[]
    def fake_load(data,name,working_space,pixel_limit):
        calls.append(pixel_limit)
        w,h=map(int,data.decode().split(','));_check_size(w,h,pixel_limit)
        # Broadcast view: exercise real session accounting without a 2.88GB CI allocation.
        return LoadedImage(np.broadcast_to(np.zeros(3,np.float32),(h,w,3)),{},[])
    monkeypatch.setattr(server,'load_image',fake_load)
    monkeypatch.setattr(server,'preview',lambda rgb,max_side=1600:rgb[:100,:100])
    monkeypatch.setattr(server,'detect_chart',lambda *args,**kwargs:{'points':None,'method':'none','warnings':[]})
    app=create_app('t');c=app.test_client();headers={'X-Lab-Token':'t'}
    def upload(role,w,h):return c.post('/api/upload',headers=headers,data={'role':role,'file':(io.BytesIO(f'{w},{h}'.encode()),'test.jpg')})
    assert upload('source',12000,10000).status_code==200
    assert upload('target',12000,10000).status_code==200
    assert calls==[240_000_000,120_000_000]
    response=upload('test',1,1)
    assert response.status_code==400 and '240MP' in response.json['error']
    assert upload('source',12000,10000).status_code==200
    assert calls[-1]==120_000_000
    assert c.get('/api/state',headers=headers).json['images']['target']['width']==12000


def test_streamed_tiff_matches_full_mapping_and_preserves_input(tmp_path):
    import tifffile
    rng=np.random.default_rng(97);pairs=rng.uniform(.02,.98,(60,3))
    model=fit_mapping(pairs,np.clip(pairs**1.08,0,1))
    rgb=rng.uniform(.02,.98,(137,91,3)).astype(np.float32);before=rgb.copy()
    path=tmp_path/'strip-output.tif'
    with path.open('w+b') as stream:write_tiff(stream,rgb,mapper=model)
    actual=tifffile.imread(path)
    expected=np.floor(model.predict(rgb)*65535+.5).astype(np.uint16)
    np.testing.assert_array_equal(actual,expected)
    np.testing.assert_array_equal(rgb,before)
    assert model.predict(rgb).dtype==np.float32


def test_sampling_does_not_convert_whole_large_image():
    # A broadcast array would need 5.76GB if promoted wholesale to float64.
    rgb=np.broadcast_to(np.array([.1,.2,.3],np.float32),(12000,20000,3))
    sampled=sample_patches(rgb,[[.5,.5]],radius=.0001)
    np.testing.assert_allclose(sampled['colors'][0],[.1,.2,.3],atol=1e-7)


def test_language_persists_across_sessions_without_changing_images(tmp_path):
    preferences=tmp_path/'preferences.json';headers={'X-Lab-Token':'t'}
    app=create_app('t',preferences_path=preferences);c=app.test_client()
    app.lab_state['revision']=7
    assert c.post('/api/preferences',json={'language':'fr'},headers=headers).status_code==200
    assert app.lab_state['revision']==7
    other=create_app('t',preferences_path=preferences).test_client()
    assert other.get('/api/preferences',headers=headers).json['language']=='fr'
    assert other.post('/api/preferences',json={'language':'unknown'},headers=headers).status_code==400
    assert other.get('/api/preferences',headers=headers).json['language']=='fr'
