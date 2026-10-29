"""Local-only desktop workspace. Images stay in memory until the app exits."""
from __future__ import annotations

import argparse
import io
import json
import logging
import secrets
import threading
import webbrowser
from functools import lru_cache
from pathlib import Path

import numpy as np
from flask import Flask, Response, jsonify, request, send_file
from PIL import Image
from scipy.spatial import cKDTree
from werkzeug.serving import make_server

from . import __version__
from .adobe import export_adobe_xmp
from .chart import chart_manifest, detect_chart, initial_points, render_chart, sample_patches
from .core import ColorMapping, cube_text, fit_mapping
from .color_spaces import SPACES, convert_rgb
from .image_io import RAW_EXTENSIONS, LoadedImage, encode_png, encode_tiff, load_image

STATIC = Path(__file__).parent / "static"


def preview(rgb, max_side=1600):
    h, w = rgb.shape[:2]
    scale = min(1, max_side / max(h, w))
    if scale == 1:
        return rgb
    import cv2
    return cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def create_app(token=None):
    app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
    app.config.update(MAX_CONTENT_LENGTH=128 * 1024 * 1024, JSON_SORT_KEYS=False)
    token = token or secrets.token_urlsafe(32)
    state = {"levels": 7, "working_space": "srgb", "target_space": "srgb", "images": {}, "model": None, "report": None, "title": "JC ColorLab", "revision": 0}
    app.lab_state = state
    app.lab_token = token

    @app.before_request
    def local_only():
        host = request.host.split(":")[0]
        if host not in {"127.0.0.1", "localhost"}:
            return jsonify(error="只接受本机访问。"), 403
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            return jsonify(error="跨来源访问已拒绝。"), 403
        if request.path.startswith("/api/") and request.headers.get("X-Lab-Token") != token:
            return jsonify(error="会话已过期，请重新打开软件。"), 403

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.errorhandler(Exception)
    def error(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        logging.exception("Local processing failed")
        return jsonify(error=str(exc)[:600] or type(exc).__name__), 400

    def active_manifest():
        manifest = chart_manifest(state["levels"], target_space=state["target_space"])
        preview_values = convert_rgb([p["rgb"] for p in manifest["patches"]], state["target_space"], "srgb", clip=True)
        working_values = convert_rgb([p["rgb"] for p in manifest["patches"]], state["target_space"], state["working_space"])
        manifest["working_gamut_excluded_count"] = int(np.count_nonzero(np.any((working_values < -1e-4) | (working_values > 1.0001), axis=1)))
        for patch, value in zip(manifest["patches"], preview_values):
            patch["preview_rgb"] = value.tolist()
        return manifest

    def display_rgb(rgb):
        return convert_rgb(rgb, state["working_space"], "srgb", clip=True)

    def changed():
        state["model"] = None
        state["report"] = None
        state["revision"] += 1

    def image_entry(role):
        if role not in state["images"]:
            raise ValueError("请先导入对应的照片。")
        return state["images"][role]

    def points_array(value):
        points = np.asarray(value, dtype=float)
        n = len(active_manifest()["patches"])
        if points.shape != (n, 2) or not np.isfinite(points).all() or np.any((points < 0) | (points > 1)):
            raise ValueError("取样点数量或位置无效，请重新识别或定位四角。")
        return points

    def add_image(role, loaded, name):
        if role not in {"source", "target", "test"}:
            raise ValueError("未知照片位置。")
        total = loaded.rgb.shape[0] * loaded.rgb.shape[1]
        total += sum(x["image"].rgb.shape[0] * x["image"].rgb.shape[1] for k, x in state["images"].items() if k != role)
        if total > 90_000_000:
            raise ValueError("当前照片合计超过 9000 万像素，请缩小照片后重试。")
        detection = detect_chart(display_rgb(preview(loaded.rgb, 2200)), state["levels"], target_space=state["target_space"]) if role != "test" else {"points": None, "confidence": 0, "method": "preview", "warnings": []}
        p = detection.get("points")
        state["images"][role] = {"image": loaded, "name": Path(name).name, "points": np.asarray(p).tolist() if p is not None else None, "detection": detection}
        if role != "test":
            changed()
        state["revision"] += 1

    def describe(role):
        entry = image_entry(role)
        h, w = entry["image"].rgb.shape[:2]
        detection = dict(entry["detection"])
        detection.pop("points", None)
        return {"name": entry["name"], "width": w, "height": h, "points": entry["points"], "metadata": entry["image"].metadata, "warnings": entry["image"].warnings, "detection": detection}

    @app.get("/")
    def index():
        return Response((STATIC / "index.html").read_text().replace("__LAB_TOKEN__", token).replace("__VERSION__", __version__).replace("__IMAGE_EXTENSIONS__", ",".join(sorted(RAW_EXTENSIONS | {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}))), mimetype="text/html")

    @app.get("/chart")
    def chart_page():
        levels = int(request.args.get("levels", 7))
        target_space = request.args.get("target_space", "srgb")
        chart_manifest(levels, target_space=target_space)
        return Response((STATIC / "chart.html").read_text().replace("__LEVELS__", str(levels)).replace("__TARGET_SPACE__", target_space), mimetype="text/html")

    @lru_cache(maxsize=12)
    def chart_bytes(levels, target_space):
        image = render_chart(levels, target_space=target_space)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", icc_profile=image.info["icc_profile"])
        return buffer.getvalue()

    @app.get("/chart.png")
    def chart_png():
        levels = int(request.args.get("levels", 7))
        target_space = request.args.get("target_space", "srgb")
        return send_file(io.BytesIO(chart_bytes(levels, target_space)), mimetype="image/png", download_name=f"JC-ColorLab-{target_space}-{levels}.png")

    @app.get("/api/state")
    def get_state():
        return jsonify(version=__version__, levels=state["levels"], working_space=state["working_space"], target_space=state["target_space"], manifest=active_manifest(), images={k: describe(k) for k in state["images"]}, report=state["report"], has_model=state["model"] is not None, title=state["title"], revision=state["revision"])

    @app.post("/api/settings")
    def settings():
        levels = int(request.json.get("levels", 7))
        target_space = request.json.get("target_space", state["target_space"])
        working_space = request.json.get("working_space", state["working_space"])
        chart_manifest(levels, target_space=target_space)
        if working_space not in SPACES:
            raise ValueError("不支持的工作色彩空间。")
        state.update(levels=levels, target_space=target_space, working_space=working_space)
        state["images"].clear()
        changed()
        return jsonify(ok=True)

    @app.post("/api/upload")
    def upload():
        role = request.form.get("role", "source")
        file = request.files.get("file")
        if file is None:
            raise ValueError("请选择图像。")
        loaded = load_image(file.read(), file.filename or "image", working_space=state["working_space"])
        add_image(role, loaded, file.filename or "image")
        return jsonify(image=describe(role))

    @app.get("/api/image/<role>")
    def image_png(role):
        rgb = preview(image_entry(role)["image"].rgb)
        if request.args.get("after") == "1":
            if state["model"] is None:
                raise ValueError("请先生成映射。")
            rgb = state["model"].predict(rgb)
        return send_file(io.BytesIO(encode_png(display_rgb(rgb))), mimetype="image/png")

    @app.post("/api/points")
    def update_points():
        entry = image_entry(request.json["role"])
        entry["points"] = points_array(request.json["points"]).tolist()
        changed()
        return jsonify(ok=True)

    @app.post("/api/corners")
    def corners():
        p = np.asarray(request.json["corners"], dtype=float)
        if p.shape != (4, 2) or not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
            raise ValueError("需要四个有效角点。")
        # Strict convexity excludes self intersections and accidental repeated clicks.
        edges = np.roll(p, -1, axis=0) - p
        crosses = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
        if np.any(crosses < 0.0001):
            raise ValueError("请按左上、右上、右下、左下依次选择色卡外边缘，四角不能交叉。")
        entry = image_entry(request.json["role"])
        entry["points"] = points_array(initial_points(corners=p, levels=state["levels"], target_space=state["target_space"])).tolist()
        changed()
        return jsonify(points=entry["points"])

    @app.post("/api/detect")
    def detect():
        role = request.json["role"]
        entry = image_entry(role)
        found = detect_chart(display_rgb(preview(entry["image"].rgb, 2200)), state["levels"], target_space=state["target_space"])
        entry["detection"] = found
        entry["points"] = np.asarray(found["points"]).tolist() if found.get("points") is not None else None
        changed()
        return jsonify(image=describe(role))

    def samples(entry, fraction):
        p = points_array(entry["points"])
        rgb = entry["image"].rgb
        h, w = rgb.shape[:2]
        distances = cKDTree(p * [w, h]).query(p * [w, h], k=2)[0][:, 1]
        radius = max(1, np.percentile(distances, 10) * fraction) / min(w, h)
        sampled = sample_patches(rgb, p, radius=radius)
        sampled["radius_pixels"] = radius * min(w, h)
        if sampled["radius_pixels"] < 4:
            sampled["warnings"].append("中央取样区域半径不足 4 像素；对 JPG 压缩和噪声较敏感，建议降低色卡密度或增大拍摄占比。")
        gray_indices = [i for i, patch in enumerate(active_manifest()["patches"]) if patch["kind"] == "gray" and .06 < patch["rgb"][0] < .94]
        clipped_gray = [i for i in gray_indices if sampled["clipped"][i] > .25]
        if clipped_gray:
            sampled["warnings"].append(f"{len(clipped_gray)} 个非端点灰阶出现明显通道截断；请检查曝光或相机风格是否压死阴影/高光。")
        return sampled

    @app.post("/api/fit")
    def fit():
        data = request.json
        mode = data.get("mode", "calibrate")
        if mode not in {"calibrate", "style"}:
            raise ValueError("请选择校色或风格模式。")
        fraction = float(data.get("fraction", .18))
        if not .05 <= fraction <= .35:
            raise ValueError("取样范围无效。")
        source = samples(image_entry("source"), fraction)
        patches = active_manifest()["patches"]
        x = np.asarray(source["colors"])
        valid = np.asarray(source["valid"], dtype=bool)
        target = None
        gamut_excluded = np.zeros(len(patches), dtype=bool)
        if mode == "style":
            target = samples(image_entry("target"), fraction)
            y = np.asarray(target["colors"])
            valid &= np.asarray(target["valid"], dtype=bool)
        else:
            y = convert_rgb(np.asarray([p["rgb"] for p in patches]), state["target_space"], state["working_space"])
            gamut_excluded = np.any((y < -1e-4) | (y > 1.0001), axis=1)
            valid &= ~gamut_excluded
            y = np.clip(y, 0, 1)
        excluded = data.get("excluded", [])
        if not isinstance(excluded, list) or any(not isinstance(i, int) or not 0 <= i < len(patches) for i in excluded):
            raise ValueError("排除色块列表无效。")
        valid[excluded] = False
        model = fit_mapping(x[valid], y[valid], mode=mode, color_space=state["working_space"])
        state["model"] = model
        state["title"] = str(data.get("title", "JC ColorLab"))[:100]
        state["report"] = {"version": __version__, "author": "J.C. Lu", "mode": mode, "chart_id": active_manifest()["id"], "color_space": state["working_space"], "target_space": state["target_space"], "used_patches": int(valid.sum()), "total_patches": len(patches), "excluded": np.flatnonzero(~valid).tolist(), "model": model.report, "source_sampling": source, "target_sampling": target, "source": describe("source"), "target": describe("target") if mode == "style" else None, "limitation": "同一显影流程下的屏幕相对校正；留出误差不代表屏幕的实测准确度或真实场景保证。"}
        if state["working_space"] != state["target_space"]:
            model.report["warnings"].append("工作色域大于/不同于显示色卡的色域；未被色卡覆盖的颜色没有独立校准保证。")
        if state["working_space"] == "acescg":
            model.report["warnings"].append("ACEScg 仅使用 AP1 / D60 线性 0–1 范围，不含 ACES 显示变换，也不支持 HDR/负值的完整场景管线。")
        state["report"]["capture_notes"] = str(data.get("notes", ""))[:2000]
        state["report"]["used_patch_ids"] = [patches[i]["id"] for i in np.flatnonzero(valid)]
        state["report"]["gamut_excluded_patch_ids"] = [patches[i]["id"] for i in np.flatnonzero(gamut_excluded)]
        if np.any(gamut_excluded):
            model.report["warnings"].append(f"{int(gamut_excluded.sum())} 个参考色无法在所选工作色域 0–1 范围表示，已自动排除，未将裁切值当作准确参考。")
        return jsonify(report=state["report"])

    def attachment(data, filename, mimetype):
        if isinstance(data, str):
            data = data.encode("utf-8")
        return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=filename)

    @app.get("/api/export/<kind>")
    def export(kind):
        if kind == "manifest":
            return attachment(json.dumps(active_manifest(), ensure_ascii=False, indent=2), "JC-ColorLab-chart.json", "application/json")
        if kind == "baseline-tiff":
            rgb = image_entry(request.args.get("role", "source"))["image"].rgb
            return attachment(encode_tiff(rgb, working_space=state["working_space"]), f"JC-ColorLab-baseline-{state['working_space']}.tif", "image/tiff")
        model = state["model"]
        if model is None:
            raise ValueError("请先生成映射或导入已保存的映射。")
        if kind == "cube":
            size = int(request.args.get("size", 33))
            if size not in {17, 33, 65}:
                raise ValueError("LUT 网格必须为 17、33 或 65。")
            return attachment(cube_text(model, size=size, title=state["title"]), "JC-ColorLab.cube", "text/plain")
        if kind == "xmp":
            text, meta = export_adobe_xmp(model, title=state["title"])
            return attachment(text, "JC-ColorLab.xmp", "application/rdf+xml")
        if kind == "report":
            return attachment(json.dumps(state["report"], ensure_ascii=False, indent=2), "JC-ColorLab-report.json", "application/json")
        if kind == "model":
            return attachment(json.dumps({"format": "JC-ColorLab-project-v1", "version": __version__, "levels": state["levels"], "target_space": state["target_space"], "working_space": state["working_space"], "title": state["title"], "model": model.to_dict(), "report": state["report"]}, ensure_ascii=False), "JC-ColorLab-project.json", "application/json")
        if kind == "tiff":
            role = request.args.get("role", "source")
            rgb = image_entry(role)["image"].rgb
            return attachment(encode_tiff(model.predict(rgb), working_space=state["working_space"]), f"JC-ColorLab-rendered-{state['working_space']}.tif", "image/tiff")
        raise ValueError("未知导出格式。")

    @app.post("/api/import-model")
    def import_model():
        file = request.files.get("file")
        if file is None:
            raise ValueError("请选择项目 JSON。")
        raw = file.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("项目文件过大。")
        data = json.loads(raw)
        if data.get("format") != "JC-ColorLab-project-v1":
            raise ValueError("不是 JC ColorLab 项目。")
        model = ColorMapping.from_dict(data["model"])
        levels = int(data["levels"])
        target_space = data.get("target_space", "srgb")
        chart_manifest(levels, target_space=target_space)
        state.update(levels=levels, working_space=model.color_space, target_space=target_space, model=model, report=data.get("report"), title=str(data.get("title", "JC ColorLab"))[:100])
        state["images"].clear()
        return jsonify(ok=True)

    @app.post("/api/demo")
    def demo():
        # Clearly synthetic fixtures exercise the workflow; these are not measurements.
        ideal = np.asarray(render_chart(state["levels"], target_space=state["target_space"]), dtype=np.float32) / 255
        rgb = np.clip(ideal ** 1.07 * [.94, 1.02, .91] + [.018, .006, .012], 0, 1).astype(np.float32)
        style = np.clip(ideal ** .94 * [1.04, .98, .93] + [.008, .012, .028], 0, 1).astype(np.float32)
        rgb = convert_rgb(rgb, state["target_space"], state["working_space"], clip=True).astype(np.float32)
        style = convert_rgb(style, state["target_space"], state["working_space"], clip=True).astype(np.float32)
        state["images"].clear()
        add_image("source", LoadedImage(rgb=rgb, metadata={"pipeline": "synthetic demonstration", "synthetic": True}, warnings=["合成演示，不能作为真实相机或屏幕准确度的验证。"]), "合成偏色样本.png")
        add_image("target", LoadedImage(rgb=style, metadata={"pipeline": "synthetic demonstration", "synthetic": True}, warnings=["合成风格示例。"]), "合成暖调风格.png")
        return jsonify(ok=True)

    @app.post("/api/quit")
    def quit_app():
        shutdown = app.config.get("SHUTDOWN")
        if shutdown:
            threading.Timer(.2, shutdown).start()
        return jsonify(ok=True)

    return app


def main():
    parser = argparse.ArgumentParser(description="JC ColorLab · J.C. Lu")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    app = create_app()
    server = make_server("127.0.0.1", args.port, app, threaded=False)
    app.config["SHUTDOWN"] = server.shutdown
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"JC ColorLab {__version__} · J.C. Lu\n{url}", flush=True)
    if not args.no_browser:
        threading.Timer(.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
