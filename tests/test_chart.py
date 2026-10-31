import cv2
import numpy as np
import pytest
from jc_colorlab.chart import chart_manifest, render_chart, detect_chart, initial_points, sample_patches


@pytest.mark.parametrize('levels,count,grays',[(5,146,21),(7,376,33),(9,762,33),(17,4978,65)])
def test_exact_4k_chart_complete_lattice_black_gutters_and_spread(levels,count,grays):
    manifest=chart_manifest(levels)
    assert (manifest['width'],manifest['height'])==(3840,2160)
    assert len(manifest['patches'])==count
    assert manifest['gray_count']==grays
    assert manifest['gap_pixels']>=3
    assert manifest['layout']['min_neighbor_distance']>=26
    chart=render_chart(levels)
    assert chart.info['icc_profile']
    rgb=np.asarray(chart)
    lattice=[]
    for patch in manifest['patches']:
        x,y,w,h=patch['rect'];center=(y+h//2,x+w//2)
        np.testing.assert_array_equal(rgb[center],patch['rgb8'])
        np.testing.assert_allclose(np.array(patch['rgb'])*255,patch['rgb8'])
        assert np.all(rgb[y+h//2,x-1]==0)
        assert np.all(rgb[y+h//2,x+w]==0)
        if patch['kind']=='lattice':lattice.append(patch['rgb8'])
    assert len(np.unique(lattice,axis=0))==levels**3
    if levels==7:
        assert min(manifest['patches'][0]['rect'][2:])>=80
        assert manifest['gap_pixels']>=20


def test_identity_manual_outer_corner_mapping_and_samples():
    manifest=chart_manifest(5)
    points=initial_points([[0,0],[1,0],[1,1],[0,1]],5)
    np.testing.assert_allclose(points,[p['center'] for p in manifest['patches']],atol=1e-12)
    image=np.asarray(render_chart(5),dtype=float)/255
    samples=sample_patches(image,points,manifest['default_sample_radius'])
    assert all(samples['valid'])
    np.testing.assert_allclose(samples['colors'],[p['rgb'] for p in manifest['patches']],atol=1e-12)
    assert max(np.asarray(samples['std']).ravel())<1e-12
    with pytest.raises(ValueError):initial_points([[0,0],[1,1],[1,0],[0,1]],5)


def test_marker_detection_under_perspective_and_missing_markers():
    image=np.asarray(render_chart(9))
    height,width=image.shape[:2]
    destination=np.array([[100,50],[1780,95],[1700,1060],[150,1100]],np.float32)
    transform=cv2.getPerspectiveTransform(np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],np.float32),destination)
    photo=cv2.warpPerspective(image,transform,(1900,1200),borderValue=(40,40,40))
    result=detect_chart(photo,9)
    assert result['method']=='aruco-homography'
    assert result['marker_count']==4
    true_points=cv2.perspectiveTransform((np.asarray(initial_points(levels=9))*[width-1,height-1]).reshape(-1,1,2),transform).reshape(-1,2)/[1899,1199]
    assert np.max(np.linalg.norm(np.asarray(result['points'])-true_points,axis=1))<.002
    assert detect_chart(np.zeros((400,600,3)),9)['points'] is None
    assert detect_chart(image,5)['points'] is None
    assert detect_chart(image,17)['points'] is None
    # One corner may be obscured; two remaining markers are insufficient.
    partially=image.copy()
    for marker in chart_manifest(9)['markers'][:2]:
        x,y,w,h=marker['rect'];partially[y-24:y+h+24,x-24:x+w+24]=0
    assert detect_chart(partially,9)['points'] is None


def test_sampling_does_not_silently_accept_outside_points():
    samples=sample_patches(np.full((100,200,3),.5),[[.5,.5],[-.1,.5],[1,.5]],radius=.01)
    assert samples['valid']==[True,False,False]
    assert len(samples['warnings'])==2


@pytest.mark.parametrize('target_space',['srgb','display-p3','adobe-rgb'])
def test_target_space_manifest_icc_gray_transfer_and_marker_disambiguation(target_space):
    from jc_colorlab.color_spaces import decode_rgb
    from PIL import ImageCms
    import io
    manifest=chart_manifest(7,target_space)
    assert manifest['target_space']==target_space
    assert manifest['marker_dictionary']=='DICT_5X5_1000'
    assert manifest['layout']['layout_version']==5
    assert len(manifest['patches'])==376
    image=render_chart(7,target_space)
    profile=ImageCms.ImageCmsProfile(io.BytesIO(image.info['icc_profile']))
    assert ImageCms.getProfileDescription(profile)
    for patch in manifest['patches']:
        if patch['kind']=='gray':
            assert patch['linear_Y']==pytest.approx(decode_rgb(patch['rgb'],target_space)[0],abs=1e-12)
    detected=detect_chart(np.asarray(image),7,target_space)
    assert detected['marker_count']==4
    wrong='display-p3' if target_space=='srgb' else 'srgb'
    assert detect_chart(np.asarray(image),7,wrong)['points'] is None
    assert detect_chart(np.asarray(image),5,target_space)['points'] is None
