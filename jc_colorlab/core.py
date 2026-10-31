"""Colorimetric diagnostics and smooth, regularized encoded-sRGB mappings.

Copyright (c) 2026 J.C. Lu. MIT license.
The mapping is a rendered-RGB look/correction, not a camera spectral model,
DCP profile, or proof of absolute screen accuracy. XYZ/Lab use D65 throughout.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import itertools
import numpy as np
from .color_spaces import SPACES, normalize_space, rgb_to_lab


SRGB_TO_XYZ = np.array([[.4124564,.3575761,.1804375],
                        [.2126729,.7151522,.0721750],
                        [.0193339,.1191920,.9503041]], dtype=np.float64)
D65 = np.array([.95047,1.,1.08883])
MODEL_KIND = "jc-colorlab-gaussian-rbf-v1"


def srgb_to_linear(rgb):
    rgb = np.asarray(rgb,dtype=np.float64)
    return np.where(rgb<=.04045,rgb/12.92,((np.maximum(rgb,0)+.055)/1.055)**2.4)


def linear_to_srgb(rgb):
    rgb=np.asarray(rgb,dtype=np.float64)
    return np.where(rgb<=.0031308,12.92*rgb,1.055*np.maximum(rgb,0)**(1/2.4)-.055)


def srgb_to_lab(rgb):
    """Encoded sRGB to CIELAB with D65 reference, no chromatic adaptation."""
    xyz = srgb_to_linear(rgb) @ SRGB_TO_XYZ.T
    ratio = xyz/D65
    delta=6/29
    f=np.where(ratio>delta**3,np.cbrt(ratio),ratio/(3*delta**2)+4/29)
    return np.stack((116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])),axis=-1)


def delta_e_2000(lab1, lab2):
    """CIEDE2000, kL=kC=kH=1; vectorized Sharma/Wu/Dalal formulation."""
    a=np.asarray(lab1,dtype=np.float64);b=np.asarray(lab2,dtype=np.float64)
    L1,a1,b1=np.moveaxis(a,-1,0);L2,a2,b2=np.moveaxis(b,-1,0)
    C1=np.hypot(a1,b1);C2=np.hypot(a2,b2)
    Cbar=(C1+C2)/2
    G=.5*(1-np.sqrt(Cbar**7/(Cbar**7+25**7)))
    ap1=(1+G)*a1;ap2=(1+G)*a2
    cp1=np.hypot(ap1,b1);cp2=np.hypot(ap2,b2)
    hp1=np.mod(np.degrees(np.arctan2(b1,ap1)),360)
    hp2=np.mod(np.degrees(np.arctan2(b2,ap2)),360)
    hp1=np.where(cp1==0,0,hp1);hp2=np.where(cp2==0,0,hp2)
    dL=L2-L1;dC=cp2-cp1
    dh=hp2-hp1
    dh=np.where(cp1*cp2==0,0,np.where(dh>180,dh-360,np.where(dh < -180,dh+360,dh)))
    dH=2*np.sqrt(cp1*cp2)*np.sin(np.radians(dh/2))
    Lbar=(L1+L2)/2;cpbar=(cp1+cp2)/2
    hsum=hp1+hp2
    hpbar=np.where(cp1*cp2==0,hsum,
                   np.where(np.abs(hp1-hp2)<=180,hsum/2,
                            np.where(hsum<360,(hsum+360)/2,(hsum-360)/2)))
    T=1-.17*np.cos(np.radians(hpbar-30))+.24*np.cos(np.radians(2*hpbar))+.32*np.cos(np.radians(3*hpbar+6))-.20*np.cos(np.radians(4*hpbar-63))
    delta_theta=30*np.exp(-((hpbar-275)/25)**2)
    RC=2*np.sqrt(cpbar**7/(cpbar**7+25**7))
    SL=1+.015*(Lbar-50)**2/np.sqrt(20+(Lbar-50)**2)
    SC=1+.045*cpbar;SH=1+.015*cpbar*T
    RT=-np.sin(np.radians(2*delta_theta))*RC
    result=(dL/SL)**2+(dC/SC)**2+(dH/SH)**2+RT*(dC/SC)*(dH/SH)
    return np.sqrt(np.maximum(result,0))


def _kernel(points,centers,sigma):
    distances=np.maximum(np.sum(points*points,axis=1)[:,None]+np.sum(centers*centers,axis=1)[None,:]-2*(points@centers.T),0)
    return np.exp(-distances/(2*sigma*sigma))


def _stats(values):
    values=np.asarray(values,dtype=float)
    return {"mean":float(np.mean(values)),"median":float(np.median(values)),
            "p95":float(np.percentile(values,95)),"max":float(np.max(values))}


@dataclass
class ColorMapping:
    centers: np.ndarray
    coefficients: np.ndarray
    sigma: float=.30
    report: dict=field(default_factory=dict)
    color_space: str="srgb"

    def __post_init__(self):
        self.color_space=normalize_space(self.color_space)

    def predict(self, rgb):
        """Apply to arbitrary (...,3) finite RGB, with bounded working memory."""
        values=np.asarray(rgb)
        if values.shape[-1:]!=(3,):
            raise ValueError("映射输入必须是有效的 RGB 数值。")
        shape=values.shape
        values=values.reshape(-1,3)
        output=np.empty(values.shape,dtype=np.float32 if values.dtype==np.float32 else np.float64)
        for start in range(0,len(values),8192):
            batch=np.asarray(values[start:start+8192],dtype=np.float64)
            if not np.isfinite(batch).all():
                raise ValueError("映射输入必须是有效的 RGB 数值。")
            batch=np.clip(batch,0,1)
            output[start:start+8192]=np.clip(batch+_kernel(batch,self.centers,self.sigma)@self.coefficients,0,1)
        return output.reshape(shape)

    def to_dict(self):
        return {"kind":MODEL_KIND,"version":2,"color_space":self.color_space,
                "sigma":float(self.sigma),"centers":self.centers.tolist(),
                "coefficients":self.coefficients.tolist(),"report":self.report}

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or data.get("kind")!=MODEL_KIND or data.get("version") not in (1,2):
            raise ValueError("不是受支持的 JC ColorLab 映射文件。")
        color_space=normalize_space(data.get("color_space","srgb"))
        centers=np.asarray(data.get("centers"),dtype=np.float64)
        coefficients=np.asarray(data.get("coefficients"),dtype=np.float64)
        sigma=float(data.get("sigma",0))
        if centers.ndim!=2 or centers.shape[1]!=3 or not 1<=centers.shape[0]<=216 or coefficients.shape!=centers.shape:
            raise ValueError("映射参数维度不正确或超出限制。")
        if not np.all(np.isfinite(centers)) or not np.all(np.isfinite(coefficients)) or not np.isfinite(sigma):
            raise ValueError("映射参数包含无效数值。")
        if np.any((centers<0)|(centers>1)) or np.max(np.abs(coefficients))>100 or not .05<=sigma<=1:
            raise ValueError("映射参数超出有效范围。")
        report=data.get("report",{})
        if not isinstance(report,dict):
            raise ValueError("映射报告必须为对象。")
        return cls(centers,coefficients,sigma,report,color_space)


def _fit(source,target,color_space="srgb"):
    # A fixed 5^3 basis is independent of the observations and validation split.
    # This caps cost for 4,978-patch charts and regularizes toward identity.
    centers=np.asarray(list(itertools.product(np.linspace(0,1,5),repeat=3)))
    sigma=.30
    kernel=_kernel(source,centers,sigma)
    residual=target-source
    weights=np.ones(len(source))
    coefficients=np.zeros((len(centers),3))
    ridge=.035 * max(len(source)/146, .5)
    for _ in range(4):
        weighted=kernel*weights[:,None]
        coefficients=np.linalg.solve(kernel.T@weighted+ridge*np.eye(len(centers)),weighted.T@residual)
        error=np.linalg.norm(kernel@coefficients-residual,axis=1)
        robust_scale=max(float(np.median(error))/.6745,.008)
        weights=np.clip(1.5*robust_scale/np.maximum(error,1e-12),.1,1)
    return ColorMapping(centers,coefficients,sigma,color_space=color_space)


def fit_mapping(source,target,mode="calibrate",color_space="srgb"):
    """Fit a smooth rendered-sRGB transform and calculate independent validation.

    At least 12 patches and three-dimensional color coverage are required.
    Exact/near duplicate calibration targets (or style inputs) stay in one
    validation group. The final exported model is then fitted to all patches.
    Validation is therefore an estimate for this method, not a held-out score
    of the final refitted model or any guarantee on unrelated photographs.
    """
    color_space=normalize_space(color_space)
    source=np.asarray(source,dtype=np.float64);target=np.asarray(target,dtype=np.float64)
    if mode not in ("calibrate","style"):
        raise ValueError("映射模式必须是 calibrate 或 style。")
    if source.ndim!=2 or source.shape[1]!=3 or target.shape!=source.shape:
        raise ValueError("输入与目标必须是相同尺寸的 N×3 色彩数组。")
    if not 12<=len(source)<=10000:
        raise ValueError("需要 12 至 10000 对有效色块。")
    if not np.all(np.isfinite(source)) or not np.all(np.isfinite(target)):
        raise ValueError("色块数据包含无效数值；请先排除无效采样点。")
    if np.any((source < -1e-7)|(source > 1+1e-7)|(target < -1e-7)|(target > 1+1e-7)):
        raise ValueError("色块必须为当前工作空间内的 SDR 0–1 数值；此 LUT 不支持超出该范围的 HDR 数据。")
    source=np.clip(source,0,1);target=np.clip(target,0,1)
    singular=np.linalg.svd(source-source.mean(axis=0),compute_uv=False)
    if singular[-1]<max(singular[0]*.005,1e-5):
        raise ValueError("采样颜色不足以覆盖三维色彩空间；只有灰阶或严重截断的数据无法拟合 3D 映射。")
    groups_data=target if mode=="calibrate" else source
    _,groups=np.unique(np.rint(groups_data*255).astype(np.int16),axis=0,return_inverse=True)
    unique_groups=np.unique(groups)
    if len(unique_groups)<10:
        raise ValueError("独立色彩样本过少，无法建立可靠映射。")
    rng=np.random.default_rng(20261028)
    shuffled=rng.permutation(unique_groups)
    heldout_groups=shuffled[:max(2,int(round(len(unique_groups)*.2))) ]
    heldout=np.flatnonzero(np.isin(groups,heldout_groups))
    training=np.flatnonzero(~np.isin(groups,heldout_groups))
    if len(training)<8:
        raise ValueError("去除重复样本后，训练色块不足。")
    validation_model=_fit(source[training],target[training],color_space)
    validation_before=delta_e_2000(rgb_to_lab(source[heldout],color_space),rgb_to_lab(target[heldout],color_space))
    validation_after=delta_e_2000(rgb_to_lab(validation_model.predict(source[heldout]),color_space),rgb_to_lab(target[heldout],color_space))
    final_model=_fit(source,target,color_space)
    before=delta_e_2000(rgb_to_lab(source,color_space),rgb_to_lab(target,color_space))
    after=delta_e_2000(rgb_to_lab(final_model.predict(source),color_space),rgb_to_lab(target,color_space))
    warnings=[]
    if color_space!="srgb":
        warnings.append("宽色域工作空间不代表色卡或显示器覆盖了整个色域；未实测颜色只由平滑模型推测。")
    if color_space=="acescg":
        warnings.append("ACEScg 仅使用线性 AP1 的 SDR 0–1 LUT 域；不包含 HDR、相机 IDT 或 ACES 输出显示变换。")
    ranges=np.ptp(source,axis=0)
    if np.any(ranges<.65):
        warnings.append("输入覆盖较窄；未采样颜色的映射主要依赖平滑假设，外推不可靠。")
    if len(source)<60:
        warnings.append("有效色块较少；复杂风格的非线性颜色变化可能无法重建。")
    if np.mean(validation_after)>np.mean(validation_before)+.2:
        warnings.append("独立留出验证未改善平均色差，请检查定位、色彩空间、白平衡和曝光。")
    if np.mean(validation_after)>5:
        warnings.append("独立留出验证误差较高；当前结果只宜作为近似，应检查样本质量。")
    unique_source=len(np.unique(np.rint(source*255).astype(np.int16),axis=0))
    if unique_source<len(unique_groups)*.75:
        warnings.append("输入中很多颜色相同或近似，可能发生截断；丢失的颜色信息无法恢复。")
    if mode=="style":
        warnings.append("只拟合全局颜色与明暗映射；颗粒、锐化、局部对比、语义调整和动态处理无法由 3D LUT 复现。")
    report={"mode":mode,"sample_count":len(source),"unique_source_count":unique_source,
            "model":"125-center regularized Gaussian residual over identity",
            "working_space":SPACES[color_space]["name"],"color_space":color_space,"lut_domain":[0,1],"delta_e_space":"CIELAB D65 / CIEDE2000",
            "training_before":_stats(before),"training_after":_stats(after),
            "validation":{"count":len(heldout),"training_count":len(training),
                          "before":_stats(validation_before),"after":_stats(validation_after),
                          "heldout_indices":heldout.tolist(),"training_indices":training.tolist(),
                          "method":"deterministic 20% grouped holdout; final model refit on all samples",
                          "seed":20261028},
            "input_range":{"min":source.min(axis=0).tolist(),"max":source.max(axis=0).tolist()},
            "per_patch_before":before.tolist(),"per_patch_after":after.tolist(),
            "warnings":warnings,
            "scope":"屏幕相对参考 / 固定显影流程；非绝对色度校准，也非相机 DCP/ICC 配置。"}
    final_model.report=report
    return final_model


def cube_text(model,size=33,title="JC ColorLab"):
    """Serialize an sRGB-domain 3D .cube, red index changes fastest."""
    if size not in (17,33,65):
        raise ValueError("LUT 边长只支持 17、33 或 65。")
    title=str(title).replace('"',"'").replace("\n"," ").replace("\r"," ")[:200]
    values=np.linspace(0,1,size)
    # cube order is B outer, G middle, R inner.
    grid=np.array([(r,g,b) for b in values for g in values for r in values])
    mapped=model.predict(grid)
    lines=[f'TITLE "{title}"',f"# JC ColorLab | J.C. Lu | {SPACES[model.color_space]['name']} input and output",
           f"# Working encoding: {SPACES[model.color_space]['transfer']} | SDR domain 0..1",
           "# Apply only to the same rendering pipeline used to fit the chart.",
           f"LUT_3D_SIZE {size}","DOMAIN_MIN 0.0 0.0 0.0","DOMAIN_MAX 1.0 1.0 1.0"]
    lines.extend(f"{r:.8f} {g:.8f} {b:.8f}" for r,g,b in mapped)
    return "\n".join(lines)+"\n"
