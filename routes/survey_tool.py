"""
survey_tool.py - 测绘 EXIF 水印工具路由
======================================
为测绘外业照片批量写入 GPS 坐标、拍摄时间、设备型号等 EXIF 元数据水印，
保留原始 EXIF 信息，便于成果归档与溯源。处理结果可打包下载。

依赖:
- piexif: 读写 JPEG/TIFF EXIF
- Pillow: 图片处理（统一输出 JPG）
"""
import io
import logging
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
import piexif

from utils.file_check import validate_single_file

logger = logging.getLogger("FieldKit.SurveyTool")

# 像素炸弹防护：单张图片像素数超过上限直接报错，避免超大图拖垮内存
Image.MAX_IMAGE_PIXELS = 50_000_000  # 约 5000 万像素

router = APIRouter(prefix="/api/survey", tags=["测绘 EXIF 水印"])

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp_file"
OUTPUT_DIR = TEMP_DIR / "survey_output"   # 处理结果

# 支持处理的输入格式
ALLOWED_INPUT = ["jpg", "jpeg", "tiff", "tif", "png", "bmp", "webp"]

# UserComment 编码前缀（piexif 要求）
_USER_COMMENT_PREFIX = b"ASCII\x00\x00\x00"


# ============================================================
# 工具函数
# ============================================================

def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "error": detail})


def _ok(data: dict = None, message: str = "ok") -> dict:
    return {"ok": True, "message": message, "data": data or {}}


def _parse_coord(value: str, name: str, low: float, high: float) -> Optional[float]:
    """
    解析经纬度字符串（支持小数度，如 39.9042 或 39°54'15"）。
    返回十进制浮点数；为空返回 None；非法抛 ValueError。
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("°", " ").replace("'", " ").replace('"', " ")
    s = s.replace("’", " ").replace("“", " ").replace("”", " ")
    parts = [p for p in s.split() if p]
    if not parts:
        return None
    try:
        if len(parts) == 1:
            num = float(parts[0])
        elif len(parts) == 2:
            num = float(parts[0]) + float(parts[1]) / 60.0
        elif len(parts) == 3:
            num = float(parts[0]) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0
        else:
            raise ValueError
    except ValueError:
        raise ValueError(f"{name} 格式不正确（示例：39.9042）")

    if not (low <= num <= high):
        raise ValueError(f"{name} 超出范围（应为 {low} ~ {high}）")
    return round(num, 8)


def _to_dms(deg_float: float) -> Tuple[int, int, float]:
    """十进制度 -> (度, 分, 秒)"""
    sign = 1 if deg_float >= 0 else -1
    a = abs(deg_float)
    deg = int(a)
    m_f = (a - deg) * 60
    minute = int(m_f)
    sec = (m_f - minute) * 60
    return sign, deg, minute, round(sec, 3)


def _dms_to_piexif(deg: int, minute: int, sec: float) -> tuple:
    """度分秒 -> piexif 有理数格式 ((n1,d1),(n2,d2),(n3,d3))"""
    return ((deg, 1), (minute, 1), (int(round(sec * 1000)), 1000))


def _parse_datetime_str(value: str) -> Optional[datetime]:
    """解析表单时间（datetime-local），返回 datetime 或 None"""
    if value is None:
        return None
    s = str(value).strip().replace("T", " ")
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _apply_watermark(
    image_bytes: bytes,
    lat: Optional[float],
    lon: Optional[float],
    dt: Optional[datetime],
    device: Optional[str],
    note: Optional[str],
) -> Tuple[bytes, Dict[str, object]]:
    """
    将水印信息写入图片 EXIF，返回 (输出 JPG bytes, 水印信息摘要)。
    保留原始 EXIF，缺失字段自动补齐默认值（时间戳、设备）。
    """
    img = Image.open(io.BytesIO(image_bytes))
    img.load()

    # 统一转 RGB（RGBA 用白底合成，避免透明区变黑）
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # 读取原始 EXIF
    try:
        exif_bytes = img.info.get("exif", b"")
        exif_dict = piexif.load(exif_bytes)
    except Exception:
        exif_dict = {}

    # 确保各 IFD 字典存在
    exif_dict.setdefault("0th", {})
    exif_dict.setdefault("Exif", {})
    exif_dict.setdefault("GPS", {})
    exif_dict.setdefault("1st", {})
    exif_dict.setdefault("thumbnail", None)

    summary: Dict[str, object] = {}

    # ---- 1. GPS 坐标 ----
    if lat is not None and lon is not None:
        gps = exif_dict["GPS"]
        lat_sign, lat_d, lat_m, lat_s = _to_dms(lat)
        lon_sign, lon_d, lon_m, lon_s = _to_dms(lon)
        gps[piexif.GPSIFD.GPSLatitudeRef] = b"N" if lat_sign >= 0 else b"S"
        gps[piexif.GPSIFD.GPSLatitude] = _dms_to_piexif(lat_d, lat_m, lat_s)
        gps[piexif.GPSIFD.GPSLongitudeRef] = b"E" if lon_sign >= 0 else b"W"
        gps[piexif.GPSIFD.GPSLongitude] = _dms_to_piexif(lon_d, lon_m, lon_s)
        # 坐标来源：由工具写入
        gps[piexif.GPSIFD.GPSProcessingMethod] = _USER_COMMENT_PREFIX + b"FieldKit Watermark"
        if dt is not None:
            gps[piexif.GPSIFD.GPSDateStamp] = dt.strftime("%Y:%m:%d").encode()
            gps[piexif.GPSIFD.GPSTimeStamp] = (
                (dt.hour, 1),
                (dt.minute, 1),
                (dt.second, 1),
            )
        summary["lat"] = lat
        summary["lon"] = lon

    # ---- 2. 拍摄时间（DateTimeOriginal 等）----
    if dt is not None:
        time_str = dt.strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["0th"][piexif.ImageIFD.DateTime] = time_str.encode()
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = time_str.encode()
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = time_str.encode()
        summary["time"] = dt.strftime("%Y-%m-%d %H:%M:%S")

    # ---- 3. 设备型号（保留原值，缺省时写入）----
    model = exif_dict["0th"].get(piexif.ImageIFD.Model)
    if device:
        exif_dict["0th"][piexif.ImageIFD.Make] = device.encode("utf-8")[:255]
        exif_dict["0th"][piexif.ImageIFD.Model] = device.encode("utf-8")[:255]
        summary["device"] = device
    elif not model:
        # 原图无设备信息时补默认标记
        exif_dict["0th"][piexif.ImageIFD.Make] = b"FieldKit"
        exif_dict["0th"][piexif.ImageIFD.Model] = b"FieldKit"
        summary["device"] = "FieldKit"

    # ---- 4. 备注（UserComment）----
    if note:
        exif_dict["Exif"][piexif.ExifIFD.UserComment] = _USER_COMMENT_PREFIX + note.encode("utf-8")[:1500]
        summary["note"] = note

    # ---- 5. 写入图片描述（含时间戳溯源）----
    desc_parts = ["FieldKit EXIF 水印"]
    if "time" in summary:
        desc_parts.append(f"拍摄时间 {summary['time']}")
    if "lat" in summary and "lon" in summary:
        desc_parts.append(f"GPS {summary['lat']},{summary['lon']}")
    if note:
        desc_parts.append(f"备注 {note}")
    exif_dict["0th"][piexif.ImageIFD.ImageDescription] = " | ".join(desc_parts).encode("utf-8")[:500]

    # ---- 6. 输出 JPG ----
    out = io.BytesIO()
    try:
        exif_dump = piexif.dump(exif_dict)
    except Exception as e:
        logger.warning("piexif.dump 失败，退回仅输出图片: %s", e)
        exif_dump = b""
    img.save(out, format="JPEG", quality=92, exif=exif_dump or None, optimize=True)

    return out.getvalue(), summary


# ============================================================
# 接口：批量写入水印
# ============================================================

@router.post("/watermark", summary="批量写入 EXIF 水印（GPS/时间/设备/备注）")
def apply_watermark(
    files: List[UploadFile] = File(..., description="照片文件，可多张"),
    lat: str = Form(default="", description="纬度（十进制，如 39.9042），留空不写"),
    lon: str = Form(default="", description="经度（十进制，如 116.4074），留空不写"),
    datetime_str: str = Form(default="", description="拍摄时间（YYYY-MM-DDTHH:MM），留空用当前时间"),
    device: str = Form(default="", description="设备型号，留空保留原值"),
    note: str = Form(default="", description="备注说明"),
):
    """
    批量处理照片：
    - 支持 jpg/jpeg/tiff/tif/png/bmp/webp 输入，统一输出 JPG
    - 写入 GPS 坐标、拍摄时间、设备型号、备注到 EXIF
    - 保留原始 EXIF 信息
    - 全部处理完成后打包 zip 供下载
    """
    if not files:
        return _error(400, "请至少选择一张照片")

    # 解析表单参数（提前校验，避免处理到一半失败）
    try:
        lat_f = _parse_coord(lat, "纬度", -90, 90)
    except ValueError as e:
        return _error(400, str(e))
    try:
        lon_f = _parse_coord(lon, "经度", -180, 180)
    except ValueError as e:
        return _error(400, str(e))
    if (lat_f is None) != (lon_f is None):
        return _error(400, "经纬度需同时填写或同时留空")

    dt = _parse_datetime_str(datetime_str)
    device_s = str(device or "").strip() or None
    note_s = str(note or "").strip() or None

    # 逐张处理
    _ensure_dir(OUTPUT_DIR)
    batch_id = _ts() + uuid.uuid4().hex[:4]
    results = []
    processed_count = 0
    fail_count = 0

    for f in files:
        ok, msg = validate_single_file(
            filename=f.filename or "",
            file_size=f.size or 0,
            module="survey",
            allowed_extensions=ALLOWED_INPUT,
        )
        if not ok:
            fail_count += 1
            results.append({"name": f.filename or "未知文件", "status": "error", "message": msg})
            continue

        try:
            content = f.file.read()
            out_bytes, summary = _apply_watermark(content, lat_f, lon_f, dt, device_s, note_s)

            src_name = Path(f.filename).stem or "photo"
            out_name = f"{src_name}_watermarked_{batch_id}.jpg"
            (OUTPUT_DIR / out_name).write_bytes(out_bytes)

            processed_count += 1
            results.append({
                "name": f.filename,
                "status": "ok",
                "output": out_name,
                "url": f"/api/survey/download/{out_name}",
                **summary,
            })
        except Image.DecompressionBombError:
            logger.exception("图片像素过大: %s", f.filename)
            fail_count += 1
            results.append({"name": f.filename, "status": "error", "message": "图片像素过大（超出安全上限），请压缩后重新上传"})
        except Exception:
            logger.exception("处理照片失败: %s", f.filename)
            fail_count += 1
            results.append({"name": f.filename, "status": "error", "message": "处理失败，请检查文件是否损坏或格式是否支持"})

    if processed_count == 0:
        return _error(400, "所有照片处理失败，请检查文件是否损坏或格式是否支持")

    # 打包 zip（仅包含成功的文件）
    zip_name = f"测绘水印_{batch_id}.zip"
    zip_path = OUTPUT_DIR / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            if r.get("status") == "ok":
                zf.write(OUTPUT_DIR / r["output"], arcname=Path(r["output"]).name)

    return _ok({
        "results": results,
        "total": len(results),
        "processed": processed_count,
        "failed": fail_count,
        "zip_url": f"/api/survey/download/{zip_name}",
        "zip_name": zip_name,
        "zip_size_kb": round(zip_path.stat().st_size / 1024, 1),
    }, message=f"成功写入水印 {processed_count} 张" + (f"，失败 {fail_count} 张" if fail_count else ""))


# ============================================================
# 接口：下载处理结果
# ============================================================

@router.get("/download/{filename}", summary="下载处理后的照片或打包文件")
async def download_file(filename: str):
    """下载处理后的图片或 zip 压缩包"""
    target = (OUTPUT_DIR / filename).resolve()
    if not target.is_relative_to(OUTPUT_DIR.resolve()) or not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    if filename.lower().endswith(".zip"):
        media_type = "application/zip"
    else:
        media_type = "image/jpeg"
    return FileResponse(path=str(target), media_type=media_type, filename=filename)
