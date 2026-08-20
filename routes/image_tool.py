"""
image_tool.py - 图片处理工具路由
=================================
提供图片压缩、尺寸缩放、文字水印三个核心接口，
处理后的图片统一输出到项目根目录 temp_image/ 文件夹。

依赖: Pillow (PIL), FastAPI
"""

import os
import uuid
import logging
from pathlib import Path
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

# 引入第一阶段工具
from utils.file_check import validate_single_file

logger = logging.getLogger("FieldKit.ImageTool")

# 像素炸弹防护：单张图片像素数超过上限直接报错，避免超大图拖垮内存
Image.MAX_IMAGE_PIXELS = 50_000_000  # 约 5000 万像素

# ============================================================
# 路由实例
# ============================================================
router = APIRouter(prefix="/api/image", tags=["图片处理"])

# ============================================================
# 临时图片输出目录（项目根目录下的 temp_image）
# ============================================================
TEMP_IMAGE_DIR = Path(__file__).resolve().parent.parent / "temp_image"

# ============================================================
# 水印位置映射
# ============================================================
WATERMARK_POSITIONS = {
    "top-left":      (0.05, 0.05),
    "top-center":    (0.50, 0.05),
    "top-right":     (0.95, 0.05),
    "center-left":   (0.05, 0.50),
    "center":        (0.50, 0.50),
    "center-right":  (0.95, 0.50),
    "bottom-left":   (0.05, 0.95),
    "bottom-center": (0.50, 0.95),
    "bottom-right":  (0.95, 0.95),
}


# ============================================================
# 工具函数
# ============================================================

def _ensure_temp_dir() -> Path:
    """确保 temp_image 目录存在，不存在则创建"""
    TEMP_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_IMAGE_DIR


def _generate_filename(original_name: str, suffix: str = "") -> str:
    """
    生成唯一的输出文件名（保留原始扩展名）
    示例: photo.jpg -> a1b2c3d4_photo.jpg
    """
    ext = Path(original_name).suffix.lower()
    # 若后缀异常，默认用 .jpg
    if not ext or len(ext) > 6:
        ext = ".jpg"
    short_id = uuid.uuid4().hex[:8]
    base = Path(original_name).stem
    if suffix:
        return f"{short_id}_{base}_{suffix}{ext}"
    return f"{short_id}_{base}{ext}"


def _find_font(font_size: int = 36) -> ImageFont.FreeTypeFont:
    """
    查找支持中文的系统字体，按优先级依次查找
    如果都找不到则使用 PIL 默认字体（不支持中文）
    """
    font_paths = [
        # Windows
        "C:/Windows/Fonts/msyh.ttc",    # 微软雅黑
        "C:/Windows/Fonts/simsun.ttc",  # 宋体
        "C:/Windows/Fonts/simhei.ttf",  # 黑体
        "C:/Windows/Fonts/msyhbd.ttc",  # 微软雅黑粗体
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, font_size)
            except Exception:
                continue
    # 兜底：PIL 默认字体
    logger.warning("未找到中文字体，水印中文可能显示异常")
    return ImageFont.load_default()


def _format_size(size_bytes: int) -> str:
    """字节转人类可读的大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _error_response(status_code: int, detail: str) -> JSONResponse:
    """构造统一错误响应"""
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": detail},
    )


def _success_response(data: dict, message: str = "处理成功") -> dict:
    """构造统一成功响应"""
    return {"ok": True, "message": message, "data": data}


# ============================================================
# 公共：处理后的图片文件访问
# ============================================================

@router.get("/file/{filename}", summary="获取处理后的图片文件")
async def get_processed_image(filename: str):
    """
    通过文件名从 temp_image 目录获取处理后的图片，
    用于前端下载或预览。
    """
    _ensure_temp_dir()
    file_path = TEMP_IMAGE_DIR / filename

    # 安全检查：防止路径穿越
    if not file_path.resolve().is_relative_to(TEMP_IMAGE_DIR.resolve()):
        raise HTTPException(status_code=403, detail="非法文件路径")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    return FileResponse(
        path=str(file_path),
        media_type=None,  # 自动识别 MIME 类型
        filename=filename,
    )


# ============================================================
# 接口①：图片压缩
# ============================================================

@router.post("/compress", summary="图片压缩")
def compress_image(
    file: UploadFile = File(..., description="待压缩的图片文件"),
    quality: int = Form(80, ge=1, le=100, description="压缩质量 1-100，默认 80"),
):
    """
    对上传的图片进行有损压缩，支持 JPG/PNG/WebP 等格式。

    请求示例（curl）:
        curl -X POST http://localhost:8000/api/image/compress \
             -F "file=@photo.jpg" \
             -F "quality=60"

    返回示例:
        {
            "ok": true,
            "message": "压缩成功",
            "data": {
                "original_name": "photo.jpg",
                "original_size": "2.3 MB",
                "compressed_name": "a1b2c3d4_photo.jpg",
                "compressed_size": "856.4 KB",
                "quality": 60,
                "download_url": "/api/image/file/a1b2c3d4_photo.jpg"
            }
        }
    """
    try:
        # ---- 参数校验 ----
        if not file.filename:
            return _error_response(400, "未选择文件")

        # ---- 格式校验 ----
        contents = file.file.read()
        original_size = len(contents)
        ok, err_msg = validate_single_file(
            filename=file.filename,
            file_size=original_size,
            module="image",
        )
        if not ok:
            return _error_response(400, err_msg)

        # ---- 打开图片 ----
        try:
            img = Image.open(BytesIO(contents))
        except Image.DecompressionBombError:
            return _error_response(400, "图片像素过大（超出安全上限），请压缩后重新上传")
        except UnidentifiedImageError:
            return _error_response(400, "无法识别该图片格式，文件可能已损坏")
        except Exception:
            return _error_response(400, "图片文件损坏，无法打开")

        # ---- 压缩处理 ----
        _ensure_temp_dir()
        output_name = _generate_filename(file.filename, suffix=f"q{quality}")
        output_path = TEMP_IMAGE_DIR / output_name

        # 将 RGBA/CMYK 等模式转换为 RGB（JPEG 不支持透明通道）
        if img.mode in ("RGBA", "P", "CMYK"):
            img = img.convert("RGB")

        # 根据原始扩展名选择保存格式
        ext = Path(file.filename).suffix.lower()
        save_format = None
        if ext in (".png",):
            # PNG 压缩: optimize=True 可减少体积
            img.save(output_path, format="PNG", optimize=True)
        elif ext in (".webp",):
            img.save(output_path, format="WEBP", quality=quality)
        else:
            # JPG / JPEG / 其他 -> 统一保存为 JPEG
            output_name = output_name.rsplit(".", 1)[0] + ".jpg"
            output_path = TEMP_IMAGE_DIR / output_name
            img.save(output_path, format="JPEG", quality=quality, optimize=True)

        compressed_size = output_path.stat().st_size

        logger.info(
            f"图片压缩完成: {file.filename} ({_format_size(original_size)}) "
            f"-> {output_name} ({_format_size(compressed_size)}), quality={quality}"
        )

        return _success_response({
            "original_name": file.filename,
            "original_size": _format_size(original_size),
            "compressed_name": output_name,
            "compressed_size": _format_size(compressed_size),
            "quality": quality,
            "download_url": f"/api/image/file/{output_name}",
        }, message="压缩成功")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"图片压缩异常: {file.filename}")
        return _error_response(500, "服务器内部错误，请稍后重试或联系管理员")


# ============================================================
# 接口②：图片尺寸缩放
# ============================================================

@router.post("/resize", summary="图片尺寸缩放")
def resize_image(
    file: UploadFile = File(..., description="待缩放的图片文件"),
    width: Optional[int] = Form(None, ge=1, le=8000, description="目标宽度(px)"),
    height: Optional[int] = Form(None, ge=1, le=8000, description="目标高度(px)"),
    keep_ratio: bool = Form(True, description="是否保持宽高比，默认 true"),
    mode: str = Form("inside", description="缩放模式: inside(限制在框内) | cover(填满) | exact(精确)"),
):
    """
    对图片进行缩放处理。

    - mode=inside:  图片等比缩放至完全在宽高范围内（不裁剪）
    - mode=cover:   图片等比缩放至完全覆盖宽高范围（居中裁剪）
    - mode=exact:   强制缩放到指定宽高（可能变形，建议搭配 keep_ratio=false）

    请求示例（curl）:
        curl -X POST http://localhost:8000/api/image/resize \
             -F "file=@photo.jpg" \
             -F "width=800" \
             -F "height=600" \
             -F "keep_ratio=true" \
             -F "mode=inside"

    返回示例:
        {
            "ok": true,
            "message": "缩放成功",
            "data": {
                "original_name": "photo.jpg",
                "original_size": "1920x1080",
                "resized_name": "a1b2c3d4_photo.jpg",
                "resized_size": "800x450",
                "download_url": "/api/image/file/a1b2c3d4_photo.jpg"
            }
        }
    """
    try:
        # ---- 参数校验 ----
        if not file.filename:
            return _error_response(400, "未选择文件")
        if width is None and height is None:
            return _error_response(400, "至少需要指定 width 或 height 其中一个参数")
        if mode not in ("inside", "cover", "exact"):
            return _error_response(400, "mode 参数无效，可选: inside / cover / exact")

        # ---- 格式校验 ----
        contents = file.file.read()
        ok, err_msg = validate_single_file(
            filename=file.filename,
            file_size=len(contents),
            module="image",
        )
        if not ok:
            return _error_response(400, err_msg)

        # ---- 打开图片 ----
        try:
            img = Image.open(BytesIO(contents))
        except Image.DecompressionBombError:
            return _error_response(400, "图片像素过大（超出安全上限），请压缩后重新上传")
        except UnidentifiedImageError:
            return _error_response(400, "无法识别该图片格式，文件可能已损坏")
        except Exception:
            return _error_response(400, "图片文件损坏，无法打开")

        orig_w, orig_h = img.size
        target_w = width if width else 99999  # 未指定宽度则设极大值
        target_h = height if height else 99999

        # ---- 缩放计算 ----
        if mode == "exact" and keep_ratio:
            return _error_response(400, "mode=exact 需搭配 keep_ratio=false，否则请使用 inside 模式")

        if mode == "exact":
            # 精确尺寸，强制拉伸
            new_w = target_w if width else orig_w
            new_h = target_h if height else orig_h
        elif mode == "cover" and keep_ratio:
            # 等比缩放至完全覆盖（Fill 模式，会裁切）
            ratio = max(target_w / orig_w, target_h / orig_h)
            new_w = int(orig_w * ratio)
            new_h = int(orig_h * ratio)
        else:
            # inside 模式：等比缩放，完全在框内（默认）
            if keep_ratio:
                ratio = min(target_w / orig_w, target_h / orig_h)
                new_w = int(orig_w * ratio)
                new_h = int(orig_h * ratio)
            else:
                new_w = target_w if width else orig_w
                new_h = target_h if height else orig_h

        # 确保不小于 1px
        new_w = max(1, new_w)
        new_h = max(1, new_h)

        # ---- 执行缩放 ----
        resample = Image.LANCZOS if orig_w * orig_h > new_w * new_h else Image.BICUBIC
        img_resized = img.resize((new_w, new_h), resample=resample)

        # cover 模式需要居中裁切
        if mode == "cover" and keep_ratio:
            # 裁切到目标尺寸
            if width and height:
                left = (new_w - width) // 2
                top = (new_h - height) // 2
                img_resized = img_resized.crop((left, top, left + width, top + height))
                new_w, new_h = width, height

        # ---- 保存 ----
        _ensure_temp_dir()
        suffix = f"{new_w}x{new_h}"
        output_name = _generate_filename(file.filename, suffix=suffix)
        output_path = TEMP_IMAGE_DIR / output_name

        # 转 RGB 确保兼容保存
        if img_resized.mode in ("RGBA", "P", "CMYK") and Path(output_name).suffix.lower() not in (".png", ".webp"):
            img_resized = img_resized.convert("RGB")

        img_resized.save(output_path, quality=92, optimize=True)

        logger.info(
            f"图片缩放完成: {file.filename} ({orig_w}x{orig_h}) -> {output_name} ({new_w}x{new_h}), mode={mode}"
        )

        return _success_response({
            "original_name": file.filename,
            "original_size": f"{orig_w}x{orig_h}",
            "resized_name": output_name,
            "resized_size": f"{new_w}x{new_h}",
            "mode": mode,
            "download_url": f"/api/image/file/{output_name}",
        }, message="缩放成功")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"图片缩放异常: {file.filename}")
        return _error_response(500, "服务器内部错误，请稍后重试或联系管理员")


# ============================================================
# 接口③：图片文字水印
# ============================================================

@router.post("/watermark", summary="添加文字水印")
def add_text_watermark(
    file: UploadFile = File(..., description="待添加水印的图片文件"),
    text: str = Form(..., min_length=1, max_length=200, description="水印文字内容"),
    position: str = Form("bottom-right", description="水印位置（单个水印模式，可选）"),
    opacity: float = Form(0.4, ge=0.0, le=1.0, description="水印透明度 0.0-1.0，默认 0.4"),
    font_size: int = Form(36, ge=8, le=200, description="字体大小 8-200，默认 36"),
    color: str = Form("255,255,255", description="水印颜色 R,G,B，默认白色"),
    rotation: int = Form(0, ge=0, le=360, description="旋转角度 0-360，默认 0"),
    tile: bool = Form(False, description="是否平铺全屏水印"),
    spacing_x: int = Form(0, ge=0, le=2000, description="平铺水平间距(px)，0=自动"),
    spacing_y: int = Form(0, ge=0, le=2000, description="平铺垂直间距(px)，0=自动"),
    x: float = Form(None, ge=0.0, le=1.0, description="自定义X位置(0-1百分比)，优先级高于position"),
    y: float = Form(None, ge=0.0, le=1.0, description="自定义Y位置(0~1百分比)，优先级高于position"),
):
    """
    给图片添加文字水印，支持自定义位置、透明度、字体大小、颜色、旋转角度。

    位置选项:
        top-left, top-center, top-right,
        center-left, center, center-right,
        bottom-left, bottom-center, bottom-right

    请求示例（curl）:
        curl -X POST http://localhost:8000/api/image/watermark \
             -F "file=@photo.jpg" \
             -F "text=© FieldKit" \
             -F "position=bottom-right" \
             -F "opacity=0.5" \
             -F "font_size=48" \
             -F "color=255,255,255"

    返回示例:
        {
            "ok": true,
            "message": "水印添加成功",
            "data": {
                "original_name": "photo.jpg",
                "watermarked_name": "a1b2c3d4_photo_wm.jpg",
                "watermark_text": "© FieldKit",
                "position": "bottom-right",
                "download_url": "/api/image/file/a1b2c3d4_photo_wm.jpg"
            }
        }
    """
    try:
        # ---- 参数校验 ----
        if not file.filename:
            return _error_response(400, "未选择文件")
        if not text.strip():
            return _error_response(400, "水印文字不能为空")
        # 单个水印模式：如果没有传 x,y 则校验 position 字符串
        if not tile and x is None and y is None and position not in WATERMARK_POSITIONS:
            valid_pos = ", ".join(WATERMARK_POSITIONS.keys())
            return _error_response(400, f"无效的水印位置，可选: {valid_pos}")

        # 解析颜色
        try:
            rgb = tuple(int(x.strip()) for x in color.split(","))
            if len(rgb) != 3 or any(c < 0 or c > 255 for c in rgb):
                raise ValueError
        except Exception:
            return _error_response(400, "颜色格式错误，请使用 R,G,B 格式，如 255,255,255")

        # ---- 格式校验 ----
        contents = file.file.read()
        ok, err_msg = validate_single_file(
            filename=file.filename,
            file_size=len(contents),
            module="image",
        )
        if not ok:
            return _error_response(400, err_msg)

        # ---- 打开图片 ----
        try:
            img = Image.open(BytesIO(contents))
        except Image.DecompressionBombError:
            return _error_response(400, "图片像素过大（超出安全上限），请压缩后重新上传")
        except UnidentifiedImageError:
            return _error_response(400, "无法识别该图片格式，文件可能已损坏")
        except Exception:
            return _error_response(400, "图片文件损坏，无法打开")

        # 确保图片支持透明度叠加（转换为 RGBA）
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # ---- 创建水印层 ----
        watermark_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)

        # 加载字体
        font = _find_font(font_size)

        # ---- 计算文字尺寸 ----
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
        except AttributeError:
            tw, th = draw.textsize(text, font=font)
            bbox = (0, 0, tw, th)

        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        img_w, img_h = img.size

        alpha = int(255 * opacity)
        text_color = (*rgb, alpha)

        # ---- 确定水印锚点比例 ----
        if x is not None and y is not None:
            ratio_x, ratio_y = x, y
        else:
            ratio_x, ratio_y = WATERMARK_POSITIONS[position]

        # ---- 绘制水印 ----
        if tile:
            # ===== 平铺全屏模式 =====
            spacing_x_val = spacing_x if spacing_x > 0 else text_w + 80
            spacing_y_val = spacing_y if spacing_y > 0 else text_h + 80

            y_offset = int(-spacing_y_val * 0.5)
            while y_offset < img_h + text_h + spacing_y_val:
                x_offset = int(-spacing_x_val * 0.5)
                while x_offset < img_w + text_w + spacing_x_val:
                    if rotation != 0:
                        text_layer = Image.new("RGBA", (text_w + 40, text_h + 40), (0, 0, 0, 0))
                        text_draw2 = ImageDraw.Draw(text_layer)
                        text_draw2.text((20, 20), text, font=font, fill=text_color)
                        text_layer = text_layer.rotate(-rotation, expand=True, resample=Image.BICUBIC)
                        watermark_layer.paste(text_layer, (x_offset - 20, y_offset - 20), text_layer)
                    else:
                        draw.text((x_offset, y_offset), text, font=font, fill=text_color)
                    x_offset += spacing_x_val
                y_offset += spacing_y_val
        else:
            # ===== 单个水印模式 =====
            margin_x = int(img_w * 0.02)
            margin_y = int(img_h * 0.02)

            pos_x = int(img_w * ratio_x - text_w * ratio_x)
            pos_y = int(img_h * ratio_y - text_h * ratio_y)

            pos_x = max(margin_x, min(pos_x, img_w - text_w - margin_x))
            pos_y = max(margin_y, min(pos_y, img_h - text_h - margin_y))

            if rotation != 0:
                text_layer = Image.new("RGBA", (text_w + 20, text_h + 20), (0, 0, 0, 0))
                text_draw2 = ImageDraw.Draw(text_layer)
                text_draw2.text((10, 10), text, font=font, fill=text_color)
                text_layer = text_layer.rotate(-rotation, expand=True, resample=Image.BICUBIC)
                watermark_layer.paste(text_layer, (pos_x - 10, pos_y - 10), text_layer)
            else:
                draw.text((pos_x, pos_y), text, font=font, fill=text_color)

        # ---- 合成水印到原图 ----
        result = Image.alpha_composite(img, watermark_layer)

        # ---- 保存 ----
        _ensure_temp_dir()
        output_name = _generate_filename(file.filename, suffix="wm")
        output_path = TEMP_IMAGE_DIR / output_name

        # JPEG 需要转 RGB
        ext = Path(output_name).suffix.lower()
        if ext in (".jpg", ".jpeg"):
            result = result.convert("RGB")
            result.save(output_path, format="JPEG", quality=92, optimize=True)
        elif ext == ".png":
            result.save(output_path, format="PNG", optimize=True)
        else:
            result.save(output_path, quality=92, optimize=True)

        if tile:
            pos_desc = "平铺全屏"
        elif x is not None and y is not None:
            pos_desc = f"自定义({x:.2f},{y:.2f})"
        else:
            pos_desc = position

        logger.info(
            f"水印添加完成: {file.filename} -> {output_name}, text='{text}', "
            f"tile={tile}, pos={pos_desc}, opacity={opacity}, rotation={rotation}"
        )

        return _success_response({
            "original_name": file.filename,
            "watermarked_name": output_name,
            "watermark_text": text,
            "position": pos_desc,
            "opacity": opacity,
            "tile": tile,
            "rotation": rotation,
            "download_url": f"/api/image/file/{output_name}",
        }, message="水印添加成功")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"水印添加异常: {file.filename}")
        return _error_response(500, "服务器内部错误，请稍后重试或联系管理员")
