import json
import numpy as np
import pytest
from jc_colorlab.core import ColorMapping, srgb_to_linear, linear_to_srgb, srgb_to_lab, delta_e_2000, fit_mapping, cube_text


def test_srgb_transfer_roundtrip_and_white():
    v=np.concatenate(([0,.0031308,.04045,1],np.linspace(0,1,1000)))
    np.testing.assert_allclose(linear_to_srgb(srgb_to_linear(v)),v,atol=3e-8)
    np.testing.assert_allclose(srgb_to_lab([1,1,1]),[100,0,0],atol=2e-5)
    np.testing.assert_allclose(srgb_to_lab([0,0,0]),[0,0,0],atol=1e-12)


@pytest.mark.parametrize('first,second,expected',[
    ([50,2.6772,-79.7751],[50,0,-82.7485],2.0425),
    ([50,3.1571,-77.2803],[50,0,-82.7485],2.8615),
    ([50,2.8361,-74.0200],[50,0,-82.7485],3.4412),
    ([50,-1.3802,-84.2814],[50,0,-82.7485],1.0000),
    ([50,-1.1848,-84.8006],[50,0,-82.7485],1.0000),
    ([50,-.9009,-85.5211],[50,0,-82.7485],1.0000),
    ([50,0,0],[50,-1,2],2.3669),
    ([50,-1,2],[50,0,0],2.3669),
    ([50,2.49,-.001],[50,-2.49,.0009],7.1792),
    ([50,2.49,-.001],[50,-2.49,.0010],7.1792),
    ([50,2.49,-.001],[50,-2.49,.0011],7.2195),
    ([50,2.49,-.001],[50,-2.49,.0012],7.2195),
    ([50,-.001,2.49],[50,.0009,-2.49],4.8045),
    ([50,-.001,2.49],[50,.001,-2.49],4.8045),
    ([50,-.001,2.49],[50,.0011,-2.49],4.7461),
    ([50,2.5,0],[50,0,-2.5],4.3065),
    ([50,2.5,0],[73,25,-18],27.1492),
    ([50,2.5,0],[61,-5,29],22.8977),
    ([50,2.5,0],[56,-27,-3],31.9030),
    ([50,2.5,0],[58,24,15],19.4535),
    ([50,2.5,0],[50,3.1736,.5854],1.0000),
    ([50,2.5,0],[50,3.2972,0],1.0000),
    ([50,2.5,0],[50,1.8634,.5757],1.0000),
    ([50,2.5,0],[50,3.2592,.3350],1.0000),
    ([60.2574,-34.0099,36.2677],[60.4626,-34.1751,39.4387],1.2644),
    ([63.0109,-31.0961,-5.8663],[62.8187,-29.7946,-4.0864],1.2630),
    ([61.2901,3.7196,-5.3901],[61.4292,2.2480,-4.9620],1.8731),
    ([35.0831,-44.1164,3.7933],[35.0232,-40.0716,1.5901],1.8645),
    ([22.7233,20.0904,-46.6940],[23.0331,14.9730,-42.5619],2.0373),
    ([36.4612,47.8580,18.3852],[36.2715,50.5065,21.2231],1.4146),
    ([90.8027,-2.0831,1.4410],[91.1528,-1.6435,.0447],1.4441),
    ([90.9257,-.5406,-.9208],[88.6381,-.8985,-.7239],1.5381),
    ([6.7747,-.2908,-2.4247],[5.8714,-.0985,-2.2286],.6377),
    ([2.0776,.0795,-1.1350],[.9033,-.0636,-.5514],.9082),
])
def test_sharma_reference_ciede2000(first,second,expected):
    # Published 34-pair reference: https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/dataNprograms/ciede2000testdata.txt
    assert float(delta_e_2000(first,second))==pytest.approx(expected,abs=.00005)
    assert float(delta_e_2000(second,first))==pytest.approx(expected,abs=.00005)


def test_identity_and_cube_red_fastest():
    model=ColorMapping(np.array([[.5,.5,.5]]),np.zeros((1,3)))
    output=cube_text(model,size=17,title='test"\nTITLE "bad')
    assert output.count('TITLE')==2 # injected text remains inside the one sanitized title
    rows=[line for line in output.splitlines() if line and line[0].isdigit()]
    assert len(rows)==17**3
    grid=np.asarray([[float(x) for x in row.split()] for row in rows])
    np.testing.assert_allclose(grid[1],[1/16,0,0],atol=1e-8)
    np.testing.assert_allclose(grid[17],[0,1/16,0],atol=1e-8)
    np.testing.assert_allclose(grid[17**2],[0,0,1/16],atol=1e-8)
    np.testing.assert_allclose(grid[-1],[1,1,1],atol=1e-8)


def test_synthetic_correction_and_disjoint_grouped_validation():
    rng=np.random.default_rng(12)
    reference=rng.uniform(.06,.9,(400,3))
    reference=np.vstack([reference,reference[:20]])
    source=np.clip(reference*np.array([.91,1.02,.94])+[.025,.01,.035],0,1)
    model=fit_mapping(source,reference)
    validation=model.report['validation']
    assert validation['after']['mean']<validation['before']['mean']*.2
    train=set(validation['training_indices']);test=set(validation['heldout_indices'])
    assert train.isdisjoint(test) and train|test==set(range(len(source)))
    for index in range(20):
        assert (index in train)==(index+400 in train)
    restored=ColorMapping.from_dict(json.loads(json.dumps(model.to_dict())))
    np.testing.assert_allclose(restored.predict(source),model.predict(source),atol=1e-12)


def test_style_nonlinear_heldout_and_bounded_prediction():
    rng=np.random.default_rng(7)
    source=rng.uniform(0,1,(750,3))
    target=np.clip(source**np.array([.92,1.08,1.02])+np.sin(source[:,1:2]*np.pi)*[.025,-.015,.035],0,1)
    model=fit_mapping(source,target,'style')
    assert model.report['validation']['after']['mean']<model.report['validation']['before']['mean']*.5
    prediction=model.predict(rng.uniform(-.1,1.1,(50,50,3)))
    assert prediction.shape==(50,50,3)
    assert np.all(np.isfinite(prediction)) and prediction.min()>=0 and prediction.max()<=1


def test_invalid_data_and_untrusted_model_are_rejected():
    gray=np.linspace(0,1,20)[:,None]*np.ones((1,3))
    with pytest.raises(ValueError):fit_mapping(gray,gray)
    with pytest.raises(ValueError):fit_mapping(np.zeros((3,3)),np.zeros((3,3)))
    valid=ColorMapping(np.array([[.5,.5,.5]]),np.zeros((1,3))).to_dict()
    bad=dict(valid,coefficients=[[float('nan'),0,0]])
    with pytest.raises(ValueError):ColorMapping.from_dict(bad)
    with pytest.raises(ValueError):ColorMapping.from_dict(dict(valid,sigma=0))
    with pytest.raises(ValueError):ColorMapping.from_dict(dict(valid,color_space='ProPhoto'))
