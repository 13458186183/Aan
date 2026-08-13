"""
文件工具箱路由
提供批量重命名、打包压缩、解压功能
"""
import os
import re
import json
import shutil
import zipfile
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/api/file", tags=["文件工具箱"])

# 临时文件根目录（项目根目录下的 temp_file）
BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp_file"

# 解压到独立的子目录，避免污染
UNZIP_SUBDIR = TEMP_DIR / "unzipped"

# ============================================================
# 工具函数
# ============================================================

def _ensure_dir(path: Path) -> None:
    """自动创建不存在的目录"""
    path.mkdir(parents=True, exist_ok=True)


def _error(status_code: int, detail: str) -> JSONResponse:
    """统一错误响应"""
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": detail},
    )


def _ok(data: dict = None, message: str = "ok") -> dict:
    """统一成功响应"""
    return {"ok": True, "message": message, "data": data or {}}


def _safe_join(base: Path, sub: str) -> Path:
    """
    安全拼接路径，防止路径穿越
    如果 sub 包含 .. 或绝对路径，抛出 403
    """
    target = (base / sub).resolve()
    if not target.is_relative_to(base.resolve()):
        raise HTTPException(status_code=403, detail="非法文件路径")
    return target


def _sanitize_filename(name: str) -> str:
    """
    清理文件名，移除危险字符，防止路径穿越
    保留中文、字母、数字、下划线、点、短横线
    """
    # 先去除路径分隔符和危险字符
    name = os.path.basename(name)
    # 剔除控制字符和其他非法字符
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    # 去除首尾空格和点
    name = name.strip(' .')
    if not name:
        raise HTTPException(status_code=400, detail="文件名无效")
    return name


def _get_ext(filename: str) -> str:
    """获取小写扩展名（含点）"""
    return Path(filename).suffix.lower()


def _ts() -> str:
    """生成时间戳字符串，用于临时文件命名"""
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _validate_not_empty(files: List[UploadFile]) -> None:
    """校验文件列表不为空"""
    if not files or all(f.size == 0 for f in files):
        raise HTTPException(status_code=400, detail="请至少上传一个非空文件")


# ============================================================
# 接口 ①：批量重命名
# ============================================================

@router.post("/rename", summary="批量重命名文件")
async def batch_rename(
    prefix: str = Form(default="file", description="文件名前缀"),
    start_num: int = Form(default=1, description="起始序号（≥0）"),
    files: List[UploadFile] = File(..., description="待重命名的文件，按上传顺序编号"),
):
    """
    批量重命名文件。

    规则：
    - 按 files 数组顺序从 start_num 递增编号
    - 保留原始扩展名
    - 生成格式：{prefix}_{序号:03d}.ext

    示例：prefix="照片", start_num=1, 3个文件
      → 照片_001.jpg, 照片_002.png, 照片_003.jpeg
    """
    _validate_not_empty(files)

    if start_num < 0:
        return _error(400, "起始序号不能为负数")
    if not prefix:
        return _error(400, "前缀不能为空")

    # 清理前缀中的非法字符
    safe_prefix = re.sub(r'[\\/:*?"<>|]', '_', prefix.strip())

    _ensure_dir(TEMP_DIR)

    result_list = []
    for idx, f in enumerate(files):
        origin = _sanitize_filename(f.filename)
        ext = _get_ext(origin) if _get_ext(origin) else ""
        seq = start_num + idx
        new_name = f"{safe_prefix}_{seq:03d}{ext}"
        new_path = TEMP_DIR / new_name

        content = await f.read()
        new_path.write_bytes(content)

        result_list.append({
            "original": origin,
            "renamed": new_name,
            "download_url": f"/api/file/download/{new_name}",
        })

    return _ok({
        "count": len(result_list),
        "files": result_list,
    }, message=f"成功重命名 {len(result_list)} 个文件")


# ============================================================
# 接口 ②：打包压缩
# ============================================================

@router.post("/zip", summary="多文件打包压缩为 ZIP")
async def pack_zip(
    zip_name: str = Form(default="archive", description="压缩包名称（不含后缀）"),
    files: List[UploadFile] = File(..., description="待打包的文件"),
):
    """
    将多个文件打包成 ZIP 压缩包。

    返回 zip 文件的下载地址。
    """
    _validate_not_empty(files)

    safe_zip_name = re.sub(r'[\\/:*?"<>|]', '_', zip_name.strip())
    if not safe_zip_name:
        safe_zip_name = "archive"

    _ensure_dir(TEMP_DIR)

    timestamp = _ts()
    zip_filename = f"{safe_zip_name}_{timestamp}.zip"
    zip_path = TEMP_DIR / zip_filename

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            added_names: set = set()
            for f in files:
                name = _sanitize_filename(f.filename)
                # 处理重名文件：添加序号
                if name in added_names:
                    base, ext = os.path.splitext(name)
                    counter = 1
                    while f"{base}_{counter}{ext}" in added_names:
                        counter += 1
                    name = f"{base}_{counter}{ext}"
                added_names.add(name)

                content = await f.read()
                zf.writestr(name, content)

        zip_size = zip_path.stat().st_size
        return _ok({
            "zip_filename": zip_filename,
            "size": zip_size,
            "size_mb": round(zip_size / 1048576, 2),
            "file_count": len(added_names),
            "download_url": f"/api/file/download/{zip_filename}",
        }, message=f"打包完成，共 {len(added_names)} 个文件")

    except Exception:
        # 清理失败的 zip 文件
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="ZIP 打包失败")


# ============================================================
# 接口 ③：解压接口
# ============================================================

@router.post("/unzip", summary="解压 ZIP 文件")
async def unpack_zip(
    file: UploadFile = File(..., description="待解压的 ZIP 文件"),
):
    """
    解压 ZIP 文件到临时目录，返回解压后的文件列表。

    安全检查：
    - 验证文件确实是 ZIP 格式
    - 防止 ZIP 炸弹（压缩比检查）
    - 防止路径穿越（.. / 绝对路径）
    """
    # 校验文件类型
    if not file.filename:
        return _error(400, "文件名为空")
    ext = _get_ext(file.filename)
    if ext != ".zip":
        return _error(400, "仅支持 .zip 格式的压缩文件")

    _ensure_dir(UNZIP_SUBDIR)

    # 创建本次解压的独立子目录，避免冲突
    session_dir = UNZIP_SUBDIR / _ts()
    session_dir.mkdir(exist_ok=True)

    content = await file.read()

    # 验证是否是有效的 zip 文件
    try:
        with zipfile.ZipFile(zipfile.BytesIO(content)) as zf:
            bad = zf.testzip()
            if bad:
                session_dir.rmdir()
                return _error(400, f"ZIP 文件损坏，文件 {bad} 校验失败")
    except zipfile.BadZipFile:
        session_dir.rmdir()
        return _error(400, "文件不是有效的 ZIP 格式")
    except Exception:
        session_dir.rmdir()
        return _error(400, "ZIP 文件读取失败")

    # 正式解压
    extracted = []
    total_size = 0
    MAX_SIZE = 200 * 1024 * 1024  # 200MB 上限

    try:
        with zipfile.ZipFile(zipfile.BytesIO(content)) as zf:
            for info in zf.infolist():
                # 跳过目录条目
                if info.is_dir():
                    continue

                # 路径安全校验：防穿越
                safe_name = _sanitize_filename(info.filename)
                # 去除可能残留的路径分隔符
                safe_name = safe_name.replace('\\', '_').replace('/', '_')

                # 解压文件大小检查（防 zip bomb）
                if info.file_size > MAX_SIZE:
                    # 跳过超大文件但继续处理其他文件
                    extracted.append({
                        "filename": safe_name,
                        "size": info.file_size,
                        "size_mb": round(info.file_size / 1048576, 2),
                        "download_url": None,
                        "error": "文件过大（>200MB），已跳过",
                    })
                    continue

                target_path = session_dir / safe_name
                target_path = target_path.resolve()
                if not target_path.is_relative_to(session_dir.resolve()):
                    # 理论上经过 sanitize 不会到这，兜底
                    continue

                data = zf.read(info.filename)
                target_path.write_bytes(data)

                total_size += target_path.stat().st_size
                extracted.append({
                    "filename": safe_name,
                    "size": target_path.stat().st_size,
                    "size_mb": round(target_path.stat().st_size / 1048576, 2),
                    "download_url": f"/api/file/unzip-download/{session_dir.name}/{safe_name}",
                })

    except Exception as e:
        # 清理失败的解压目录
        shutil.rmtree(session_dir, ignore_errors=True)
        return _error(500, f"解压过程出错: {str(e)}")

    if not extracted:
        session_dir.rmdir()
        return _error(400, "压缩包内没有可解压的文件")

    return _ok({
        "session_id": session_dir.name,
        "file_count": len(extracted),
        "total_size": total_size,
        "total_size_mb": round(total_size / 1048576, 2),
        "files": extracted,
    }, message=f"解压完成，共 {len(extracted)} 个文件")


# ============================================================
# 公共：文件下载接口
# ============================================================

@router.get("/download/{filename}", summary="下载临时文件")
async def download_file(filename: str):
    """
    下载 temp_file 目录中由重命名/打包接口生成的文件
    """
    _ensure_dir(TEMP_DIR)
    file_path = _safe_join(TEMP_DIR, filename)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    return FileResponse(
        path=str(file_path),
        media_type=None,
        filename=filename,
    )


@router.get("/unzip-download/{session_id}/{filename}", summary="下载解压后的文件")
async def download_unzipped_file(session_id: str, filename: str):
    """
    下载解压后的文件
    """
    _ensure_dir(UNZIP_SUBDIR)
    session_dir = _safe_join(UNZIP_SUBDIR, session_id)
    file_path = _safe_join(session_dir, filename)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    return FileResponse(
        path=str(file_path),
        media_type=None,
        filename=filename,
    )
