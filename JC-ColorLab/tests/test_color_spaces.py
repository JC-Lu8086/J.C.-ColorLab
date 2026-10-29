import numpy as np
import pytest
from jc_colorlab.color_spaces import (SPACES,WHITE_POINTS,xy_to_xyz,bradford_matrix,
    encode_rgb,decode_rgb,rgb_to_xyz,xyz_to_rgb,convert_rgb,rgb_to_lab)
from jc_colorlab.core import ColorMapping,fit_mapping,cube_text


@pytest.mark.parametrize('space',list(SPACES))
def test_white_primaries_and_transfer_roundtrip(space):
    info=SPACES[space]
    np.testing.assert_allclose(rgb_to_xyz([1,1,1],space),xy_to_xyz(info['white_xy']),atol=1e-12)
    xyz=rgb_to_xyz(np.eye(3),space)
    xy=xyz[:,:2]/np.sum(xyz,axis=1)[:,None]
    np.testing.assert_allclose(xy,info['primaries'],atol=1e-12)
    values=np.array([[-.2,.001,2],[.5,.04045,1/32],[.0031308,1/512,1]])
    np.testing.assert_allclose(encode_rgb(decode_rgb(values,space),space),values,atol=3e-8)
    np.testing.assert_allclose(rgb_to_lab([1,1,1],space),[100,0,0],atol=1e-11)


def test_published_matrix_and_trc_references():
    # W3C CSS Color 4 normalized matrices; ACEScg official AP1/D60 matrix.
    np.testing.assert_allclose(SPACES['srgb']['to_xyz'],
        [[.4123907993,.3575843394,.1804807884],[.2126390059,.7151686788,.0721923154],[.0193308187,.1191947798,.9505321522]],atol=1e-10)
    np.testing.assert_allclose(SPACES['acescg']['to_xyz'],
        [[.6624541811,.1340042065,.1561876870],[.2722287168,.6740817658,.0536895174],[-.0055746495,.0040607335,1.0103391003]],atol=1e-10)
    assert decode_rgb([.5,.5,.5],'adobe-rgb')[0]==pytest.approx(.5**(563/256),abs=1e-14)
    assert decode_rgb([1/32]*3,'prophoto-rgb')[0]==pytest.approx(1/512,abs=1e-15)
    assert encode_rgb([1/512]*3,'prophoto-rgb')[0]==pytest.approx(1/32,abs=1e-15)
    assert decode_rgb([.5]*3,'acescg')[0]==.5


def test_bradford_d65_d50_reference_and_inverse():
    matrix=bradford_matrix('D65','D50')
    np.testing.assert_allclose(matrix,[[1.0479297925,.0229468706,-.0501922663],[.0296278088,.9904344268,-.0170737991],[-.0092430582,.0150551449,.75187428996]],atol=1e-7)
    np.testing.assert_allclose(matrix@xy_to_xyz(WHITE_POINTS['D65']),xy_to_xyz(WHITE_POINTS['D50']),atol=1e-14)
    np.testing.assert_allclose(bradford_matrix('D50','D65')@matrix,np.eye(3),atol=1e-14)


@pytest.mark.parametrize('source',list(SPACES))
@pytest.mark.parametrize('destination',list(SPACES))
def test_roundtrip_across_all_spaces_preserves_extended_values(source,destination):
    values=np.random.default_rng(45).uniform(-.1,1.25,(100,3))
    converted=convert_rgb(values,source,destination)
    np.testing.assert_allclose(convert_rgb(converted,destination,source),values,atol=1e-6)
    np.testing.assert_allclose(convert_rgb([1,1,1],source,destination),[1,1,1],atol=1e-12)


def test_no_hidden_gamut_clipping_and_explicit_xyz_white():
    p3red=convert_rgb([1,0,0],'display-p3','srgb')
    assert p3red[0]>1 and p3red[1]<0
    np.testing.assert_allclose(convert_rgb([1,0,0],'display-p3','srgb',clip=True),[1,0,0],atol=1e-12)
    np.testing.assert_allclose(xyz_to_rgb(xy_to_xyz(WHITE_POINTS['D65']),'prophoto-rgb',white='D65'),[1,1,1],atol=1e-12)


@pytest.mark.parametrize('space',list(SPACES))
def test_working_space_persists_and_diagnostics_use_actual_encoding(space):
    reference=np.random.default_rng(6).uniform(.1,.85,(80,3))
    source=reference*np.array([.97,.96,1.01])
    model=fit_mapping(source,reference,color_space=space)
    assert model.color_space==space
    assert ColorMapping.from_dict(model.to_dict()).color_space==space
    assert SPACES[space]['name'] in cube_text(model,17)
    assert model.report['validation']['after']['mean']<model.report['validation']['before']['mean']
    if space=='acescg':assert any('HDR' in item for item in model.report['warnings'])


def test_legacy_model_loads_as_srgb_and_wrong_space_rejected():
    data=ColorMapping(np.array([[.5]*3]),np.zeros((1,3))).to_dict()
    data.update(version=1,color_space='encoded sRGB IEC61966-2.1')
    assert ColorMapping.from_dict(data).color_space=='srgb'
    with pytest.raises(ValueError):convert_rgb([0,0,0],'ARGB','srgb')


@pytest.mark.parametrize('space',list(SPACES))
def test_common_d65_lab_is_encoding_invariant(space):
    rgb=np.random.default_rng(40).uniform(.05,.95,(100,3))
    converted=convert_rgb(rgb,'srgb',space)
    np.testing.assert_allclose(rgb_to_lab(converted,space),rgb_to_lab(rgb,'srgb'),atol=1e-10)
