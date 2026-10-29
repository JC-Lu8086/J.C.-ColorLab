"""Original, numerically specified JC ColorLab sRGB target.

Copyright (c) 2026 J.C. Lu. MIT license.
Coordinates are normalized pixel-center coordinates: x/(width-1), y/(height-1).
This is not a ColorChecker / SpyderCHECKR reflectance target or a measurement
of a monitor's emitted spectrum. Reference values use the declared target RGB encoding.
"""
from __future__ import annotations

from functools import lru_cache
import copy
import itertools
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .color_spaces import SPACES, normalize_space, rgb_to_lab, decode_rgb, convert_rgb

CHART_ID = "jc-colorlab-v1"
TARGET_SPACES = ("srgb", "display-p3", "adobe-rgb")


def _target_space(space):
    space=normalize_space(space)
    if space not in TARGET_SPACES:
        raise ValueError("屏幕色卡只支持 sRGB、Display P3 和 Adobe RGB；ProPhoto/ACEScg 用于处理域。")
    return space


def _marker_ids(levels,target_space):
    base=100+TARGET_SPACES.index(target_space)*20+(5,7,9,17).index(levels)*4
    return tuple(range(base,base+4))


def _cv2():
    import cv2
    return cv2


def _dimensions(levels):
    if levels not in (5, 7, 9, 17):
        raise ValueError("色卡密度只支持 5、7、9 或 17 级 RGB 网格。")
    return 3840, 2160


def _spread_layout(colors, cols, target_space="srgb"):
    """Seeded arrangement with local swaps to separate similar neighbors.

    CIELAB Euclidean distance is used only as a layout objective, not as the
    reported calibration accuracy (which uses CIEDE2000).
    """
    lab=rgb_to_lab(np.asarray(colors,dtype=float)/255,target_space)
    n=len(colors)
    rng=np.random.default_rng(1467624978)
    order=rng.permutation(n)
    neighbors=[]
    for i in range(n):
        around=[]
        if i%cols: around.append(i-1)
        if i%cols<cols-1 and i+1<n: around.append(i+1)
        if i>=cols: around.append(i-cols)
        if i+cols<n: around.append(i+cols)
        neighbors.append(around)
    edges=np.array([(i,j) for i in range(n) for j in neighbors[i] if j>i],dtype=int)
    threshold=26.
    def edge_cost(edge_list, candidate_order):
        pairs=np.asarray(edge_list,dtype=int)
        d=np.linalg.norm(lab[candidate_order[pairs[:,0]]]-lab[candidate_order[pairs[:,1]]],axis=1)
        return float(np.sum(np.maximum(threshold-d,0)**2))
    for _ in range(8):
        distances=np.linalg.norm(lab[order[edges[:,0]]]-lab[order[edges[:,1]]],axis=1)
        bad=np.flatnonzero(distances<threshold)
        if not len(bad): break
        for edge_id in rng.permutation(bad):
            left,right=edges[edge_id]
            if np.linalg.norm(lab[order[left]]-lab[order[right]])>=threshold: continue
            pos=int(left if rng.integers(2)==0 else right)
            best_gain=0;best=None
            for candidate in rng.integers(n,size=28):
                candidate=int(candidate)
                if candidate==pos: continue
                affected=list({tuple(sorted((i,j))) for i in (pos,candidate) for j in neighbors[i]})
                before=edge_cost(affected,order)
                order[pos],order[candidate]=order[candidate],order[pos]
                after=edge_cost(affected,order)
                order[pos],order[candidate]=order[candidate],order[pos]
                if before-after>best_gain+1e-9:
                    best_gain=before-after;best=candidate
                    if after<1e-9: break
            if best is not None:
                order[pos],order[best]=order[best],order[pos]
    distances=np.linalg.norm(lab[order[edges[:,0]]]-lab[order[edges[:,1]]],axis=1)
    return order,{"metric":"CIELAB D65 Euclidean distance for adjacent layout only",
                  "min_neighbor_distance":float(distances.min()),"mean_neighbor_distance":float(distances.mean()),
                  "seed":1467624978,"layout_version":4}


@lru_cache(maxsize=12)
def _manifest(levels=7, target_space="srgb"):
    target_space=_target_space(target_space)
    width,height=_dimensions(levels)
    codes=np.rint(np.linspace(0,255,levels)).astype(int).tolist()
    colors=list(itertools.product(codes,repeat=3))
    n=len(colors)
    cols={5:15,7:24,9:36,17:91}[levels]
    rows=int(np.ceil(n/cols))
    start_x,start_y,available_w,available_h=292,244,3256,1538
    cell_w,cell_h=available_w/cols,available_h/rows
    gap=max(4,round(min(cell_w,cell_h)*(.20 if levels <= 9 else .14)))
    order,layout=_spread_layout(colors,cols,target_space)
    position=np.argsort(order)
    patches=[]
    for index,(r,g,b) in enumerate(colors):
        row,col=divmod(int(position[index]),cols)
        x,y=round(start_x+col*cell_w),round(start_y+row*cell_h)
        w,h=int(cell_w)-gap,int(cell_h)-gap
        patches.append({"id":f"C{index+1:04d}","label":f"RGB {r} {g} {b}",
                        "rgb":[r/255,g/255,b/255],"rgb8":[r,g,b],"kind":"lattice",
                        "grid_row":row,"grid_col":col,
                        "center":[(x+(w-1)/2)/(width-1),(y+(h-1)/2)/(height-1)],"rect":[x,y,w,h]})
    gray_count={5:21,7:33,9:33,17:65}[levels]
    gray_w=available_w/gray_count
    low=list(range((gray_count+1)//2));high=list(range((gray_count+1)//2,gray_count))
    gray_order=[]
    for i in range(len(low)):
        gray_order.append(low[i])
        if i<len(high):gray_order.append(high[i])
    gray_positions=np.argsort(gray_order)
    for index,code in enumerate(np.rint(np.linspace(0,255,gray_count)).astype(int)):
        code=int(code)
        x,y,w,h=round(start_x+int(gray_positions[index])*gray_w),1888,int(gray_w)-max(4,round(gray_w*.20)),116
        value=code/255
        linear_y=float(decode_rgb([value,value,value],target_space)[0])
        patches.append({"id":f"G{index:02d}","label":f"Gray {code}/255","rgb":[value]*3,"rgb8":[code]*3,"kind":"gray",
                        "linear_Y":linear_y,"EV_from_white":float(np.log2(linear_y)) if linear_y>0 else None,
                        "center":[(x+(w-1)/2)/(width-1),(y+(h-1)/2)/(height-1)],"rect":[x,y,w,h]})
    markers=[]
    for marker_id,(x,y) in zip(_marker_ids(levels,target_space),[(56,48),(3640,48),(3640,1968),(56,1968)]):
        size=147
        corners=[[x,y],[x+size-1,y],[x+size-1,y+size-1],[x,y+size-1]]
        markers.append({"id":marker_id,"rect":[x,y,size,size],"corners":[[a/(width-1),b/(height-1)] for a,b in corners]})
    sample_radius=min(min(p["rect"][2:]) for p in patches)*.18/min(width,height)
    return {"id":f"{CHART_ID}-{target_space}-L{levels}-layout4","width":width,"height":height,"levels":levels,
            "color_space":SPACES[target_space]["name"],"target_space":target_space,"white_point":"D65","transfer":SPACES[target_space]["transfer"],
            "reference_type":"digital RGB values, not measured emission","patches":patches,"patch_count":len(patches),
            "gray_count":gray_count,"gray_order":"interleaved dark/light; patch IDs retain numeric order",
            "grid_columns":cols,"grid_rows":rows,"gap_pixels":gap,"background_rgb8":[0,0,0],"layout":layout,
            "markers":markers,"marker_dictionary":"DICT_5X5_1000","default_sample_radius":sample_radius,"author":"J.C. Lu"}


def chart_manifest(levels=7, target_space="srgb"):
    """Return independent JSON-serializable target; levels is 5, 7, 9 or 17."""
    return copy.deepcopy(_manifest(levels,target_space))


def render_chart(levels=7, target_space="srgb"):
    """Return a 3840×2160 original RGB target with embedded target-space ICC profile."""
    cv2=_cv2();manifest=_manifest(levels,target_space)
    width,height=manifest["width"],manifest["height"]
    image=Image.new("RGB",(width,height),(0,0,0));draw=ImageDraw.Draw(image)
    font_large=ImageFont.load_default(size=58);font_small=ImageFont.load_default(size=30)
    draw.text((292,58),f"JC COLORLAB / {target_space.upper()} {manifest['patch_count']}",fill=(235,235,235),font=font_large)
    draw.text((296,147),f"{levels**3} RGB samples + {manifest['gray_count']} gray steps / D65 / 4K layout v4 / J.C. Lu",fill=(167,171,176),font=font_small)
    for patch in manifest["patches"]:
        x,y,w,h=patch["rect"];draw.rectangle((x,y,x+w-1,y+h-1),fill=tuple(patch["rgb8"]))
    draw.text((292,1830),"ENCODED GRAY / dark-light interleaved / values 0 - 255 / not equal exposure steps",fill=(190,193,196),font=font_small)
    draw.text((292,2066),"SCREEN-RELATIVE REFERENCE | Lock brightness, white balance and exposure. Avoid clipping.",fill=(167,171,176),font=font_small)
    dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_1000)
    for marker in manifest["markers"]:
        x,y,w,h=marker["rect"];quiet=24
        draw.rectangle((x-quiet,y-quiet,x+w+quiet-1,y+h+quiet-1),fill="white")
        image.paste(Image.fromarray(cv2.aruco.generateImageMarker(dictionary,marker["id"],w)).convert("RGB"),(x,y))
    from .icc import working_icc
    image.info["icc_profile"]=working_icc(target_space)
    return image


def initial_points(corners=None, levels=7, target_space="srgb"):
    """Map target points to manually selected chart outer corners (TL,TR,BR,BL).

    With no corners this gives the target layout, useful only as a manual initial
    guess. It never constitutes successful automatic detection.
    """
    points = np.asarray([p["center"] for p in _manifest(levels,target_space)["patches"]], dtype=np.float64)
    if corners is None:
        return points.tolist()
    corners = np.asarray(corners, dtype=np.float64)
    if corners.shape != (4,2) or not np.all(np.isfinite(corners)):
        raise ValueError("请提供四个有效的色卡外角坐标：左上、右上、右下、左下。")
    cv2 = _cv2()
    contour = corners.astype(np.float32)
    if not cv2.isContourConvex(contour) or abs(cv2.contourArea(contour)) < 0.0001:
        raise ValueError("四角必须按左上、右上、右下、左下顺序组成非退化凸四边形。")
    homography = cv2.getPerspectiveTransform(np.asarray([[0,0],[1,0],[1,1],[0,1]],np.float32), contour)
    return cv2.perspectiveTransform(points.reshape(-1,1,2), homography).reshape(-1,2).tolist()


def detect_chart(rgb, levels=7, target_space="srgb"):
    """Locate our target from uniquely identified marker geometry.

    All 4 markers are preferred; 3 allow a partially obscured target. No fallback
    rectangular grid is ever reported as successful detection.
    """
    cv2 = _cv2()
    manifest = _manifest(levels,target_space)
    WIDTH, HEIGHT = manifest["width"], manifest["height"]
    image = np.asarray(rgb)
    if image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 100:
        return {"points": None, "confidence": 0.0, "method": "none", "warnings": ["图像尺寸不足或不是 RGB 图像。"]}
    if not np.all(np.isfinite(image)):
        raise ValueError("图像包含无效数值。")
    image8 = np.uint8(np.rint(np.clip(image,0,1)*255)) if image.dtype != np.uint8 else image
    height,width = image8.shape[:2]
    scale = min(1.0, 2200/max(height,width))
    small = cv2.resize(image8, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image8
    gray = cv2.cvtColor(small,cv2.COLOR_RGB2GRAY)
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_1000)
    detector = cv2.aruco.ArucoDetector(dictionary,params)
    marker_corners, ids, _ = detector.detectMarkers(gray)
    expected_ids = set(_marker_ids(levels, target_space))
    accepted_count = len(set(ids.ravel().tolist()) & expected_ids) if ids is not None else 0
    if accepted_count < 4:
        # JPEG ringing and exact half-size resampling can merge candidate contours
        # in OpenCV's adaptive-threshold detector. The alternative AprilTag quad
        # detector keeps the same dictionary decoding and downstream geometry checks.
        # Prefer its result only if it recovers more of our expected identities.
        alternative = cv2.aruco.DetectorParameters()
        alternative.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_APRILTAG
        alt_corners, alt_ids, _ = cv2.aruco.ArucoDetector(dictionary, alternative).detectMarkers(gray)
        alt_count = len(set(alt_ids.ravel().tolist()) & expected_ids) if alt_ids is not None else 0
        if alt_count > accepted_count:
            marker_corners, ids = alt_corners, alt_ids
    empty = {"points": None, "confidence": 0.0, "method": "none", "warnings": []}
    if ids is None:
        empty["warnings"] = ["没有识别到本软件色卡的定位标记；可手动指定四角并拖动采样点。"]
        return empty
    found = {}
    duplicates = set()
    for marker_id, corners in zip(ids.ravel(), marker_corners):
        if int(marker_id) in _marker_ids(levels,target_space):
            if int(marker_id) in found:
                duplicates.add(int(marker_id))
            found[int(marker_id)] = corners.reshape(4,2)/scale
    if duplicates or len(found) < 3:
        empty["warnings"] = [f"找到 {len(found)} 个可用定位标记，需要至少 3 个且 ID 不重复；请手动定位。"]
        return empty
    source, destination = [], []
    for marker in _manifest(levels,target_space)["markers"]:
        if marker["id"] in found:
            source.extend(np.asarray(marker["corners"])*[WIDTH-1,HEIGHT-1])
            destination.extend(found[marker["id"]])
    source = np.asarray(source,dtype=np.float64)
    destination = np.asarray(destination,dtype=np.float64)
    homography,inliers = cv2.findHomography(source,destination,cv2.RANSAC,3.5/max(scale,0.1))
    if homography is None or inliers is None or np.mean(inliers) < 0.8:
        empty["warnings"] = ["标记几何关系不一致，未接受自动定位。"]
        return empty
    predicted_markers = cv2.perspectiveTransform(source.reshape(-1,1,2),homography).reshape(-1,2)
    error = np.linalg.norm(predicted_markers-destination,axis=1)
    rmse = float(np.sqrt(np.mean(error[inliers.ravel().astype(bool)]**2)))
    points = np.asarray(initial_points(levels=levels,target_space=target_space))*[WIDTH-1,HEIGHT-1]
    mapped = cv2.perspectiveTransform(points.reshape(-1,1,2),homography).reshape(-1,2)/[width-1,height-1]
    chart_corners = cv2.perspectiveTransform(np.array([[[0,0]],[[WIDTH-1,0]],[[WIDTH-1,HEIGHT-1]],[[0,HEIGHT-1]]],np.float64),homography).reshape(-1,2)/[width-1,height-1]
    if not np.all(np.isfinite(mapped)) or np.any((mapped < 0)|(mapped > 1)):
        empty["warnings"] = ["色卡部分采样区域在照片之外；请完整拍摄色卡。"]
        return empty
    warnings = []
    if len(found)==3:
        warnings.append("仅识别到 3 个标记；请检查所有采样点位置。")
    if rmse>2:
        warnings.append("透视拟合残差较大；请检查镜头畸变和采样点位置。")
    return {"points": mapped.tolist(), "corners": chart_corners.tolist(),
            "confidence": float(np.clip((len(found)/4)*np.exp(-rmse/8),0,1)),
            "method": "aruco-homography", "marker_count": len(found),
            "reprojection_rmse_px": rmse, "warnings": warnings}


def sample_patches(image, points, radius=0.006):
    """Median samples from circular neighborhoods; radius is fraction of min(H,W).

    Clipping is reported but does not itself invalidate a patch: the digital
    target intentionally includes gamut-edge values. Radius must be reviewed
    after extreme perspective or a very small target within a large photo.
    """
    image = np.asarray(image,dtype=np.float64)
    points = np.asarray(points,dtype=np.float64)
    if image.ndim!=3 or image.shape[2]!=3 or points.ndim!=2 or points.shape[1]!=2:
        raise ValueError("采样需要 RGB 图像和 N×2 归一化坐标。")
    if not np.isfinite(radius) or not 0.0001 <= radius <= 0.05:
        raise ValueError("采样半径必须在图像短边的 0.01% 到 5% 之间。")
    if not np.all(np.isfinite(points)):
        raise ValueError("采样点包含无效数值。")
    height,width = image.shape[:2]
    r = max(1.0,float(radius)*min(height,width))
    colors,std,clipped,valid,counts,warnings = [],[],[],[],[],[]
    for index,(nx,ny) in enumerate(points):
        x,y = nx*(width-1),ny*(height-1)
        x0,x1 = max(0,int(np.floor(x-r))),min(width,int(np.ceil(x+r))+1)
        y0,y1 = max(0,int(np.floor(y-r))),min(height,int(np.ceil(y+r))+1)
        in_bounds = 0<=nx<=1 and 0<=ny<=1 and x-r>=0 and x+r<width and y-r>=0 and y+r<height
        if not in_bounds or x0>=x1 or y0>=y1:
            colors.append([0.,0.,0.]);std.append([0.,0.,0.]);clipped.append(0.);valid.append(False);counts.append(0)
            warnings.append(f"采样点 {index+1} 的区域超出照片边缘。")
            continue
        yy,xx = np.ogrid[y0:y1,x0:x1]
        pixels = image[y0:y1,x0:x1][(xx-x)**2+(yy-y)**2<=r*r]
        finite = np.all(np.isfinite(pixels),axis=1)
        pixels = pixels[finite]
        ok = len(pixels)>=3
        if not ok:
            colors.append([0.,0.,0.]);std.append([0.,0.,0.]);clipped.append(0.);valid.append(False);counts.append(len(pixels))
            continue
        colors.append(np.median(pixels,axis=0).tolist())
        spread = np.std(pixels,axis=0)
        std.append(spread.tolist())
        clipped.append(float(np.mean(np.any((pixels<=1/65535)|(pixels>=1-1/65535),axis=1))))
        valid.append(True);counts.append(len(pixels))
        if np.max(spread)>0.04:
            warnings.append(f"采样点 {index+1} 不均匀，可能包含色块边缘、反光或摩尔纹。")
    return {"colors": colors, "std": std, "clipped": clipped, "valid": valid,
            "pixel_counts": counts, "radius": float(radius), "warnings": warnings,
            "clipping_note": "边界色块的 0/1 值可能是正常参考值；请结合 RAW 高光与实际拍摄检查截断。"}
