"""
file_check.py - 文件校验工具
=============================
提供文件大小校验、格式（扩展名/MIME）校验、批量文件检测等功能。
所有校验失败均返回明确的中文错误提示，便于前端直接展示给用户。
"""

import os
import mimetypes
from typing import Optional, List, Tuple, Dict

# ============================================================
# 可配置常量
# ============================================================

# 通用上传大小上限（默认 50MB，可根据模块覆盖）
DEFAULT_MAX_SIZE_MB = 50
DEFAULT_MAX_SIZE_BYTES = DEFAULT_MAX_SIZE_MB * 1024 * 1024

# 各功能模块支持的文件格式（扩展名小写，不含点）
ALLOWED_EXTENSIONS: Dict[str, List[str]] = {
    # 图片处理工具
    "image": ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif", "svg"],
    # 考勤点名工具
    "attendance": ["jpg", "jpeg", "png", "pdf"],
    # 测绘 EXIF 水印工具（原始照片格式）
    "survey": ["jpg", "jpeg", "tiff", "tif", "png"],
    # 村级资产清查表工具
    "asset": ["xlsx", "xls"],
    # 拼豆图纸转换工具
    "bead": ["jpg", "jpeg", "png", "gif", "webp", "bmp"],
}

# 各功能模块的文件大小限制（MB），未指定则使用默认值
MODULE_SIZE_LIMITS: Dict[str, int] = {
    "image": 20,        # 图片处理最大 20MB
    "attendance": 10,   # 考勤照片最大 10MB
    "survey": 30,       # 测绘原始照片最大 30MB
    "asset": 10,        # Excel 文件最大 10MB
    "bead": 15,         # 拼豆原图最大 15MB
}


# ============================================================
# 工具函数
# ============================================================

def _get_file_extension(filename: str) -> str:
    """提取文件扩展名（小写，不含点）"""
    return os.path.splitext(filename)[1].lstrip(".").lower()


def _format_size(size_bytes: int) -> str:
    """将字节数格式化为人类可读的大小字符串"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def validate_file_size(
    file_size: int,
    max_size_mb: Optional[int] = None,
    module: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    校验文件大小是否在允许范围内。

    参数:
        file_size:  文件大小（字节）
        max_size_mb: 自定义大小上限（MB），优先级最高
        module:     模块名称，从 MODULE_SIZE_LIMITS 获取对应限制

    返回:
        (是否通过, 错误提示) —— 通过时错误提示为空字符串
    """
    # 确定上限
    if max_size_mb is not None:
        limit_mb = max_size_mb
    elif module and module in MODULE_SIZE_LIMITS:
        limit_mb = MODULE_SIZE_LIMITS[module]
    else:
        limit_mb = DEFAULT_MAX_SIZE_MB

    limit_bytes = limit_mb * 1024 * 1024

    if file_size <= 0:
        return False, "文件大小为 0，请检查文件是否损坏"

    if file_size > limit_bytes:
        return False, (
            f"文件大小 {_format_size(file_size)} 超出上限 {limit_mb}MB，"
            f"请压缩后重新上传"
        )

    return True, ""


def validate_file_extension(
    filename: str,
    module: Optional[str] = None,
    allowed_extensions: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    校验文件扩展名是否在允许列表中。

    参数:
        filename:          文件名
        module:            模块名称，从 ALLOWED_EXTENSIONS 获取允许列表
        allowed_extensions: 自定义允许扩展名列表，优先级最高

    返回:
        (是否通过, 错误提示)
    """
    ext = _get_file_extension(filename)

    if not ext:
        return False, "无法识别文件类型，请确保文件名包含正确的后缀"

    # 确定允许列表
    if allowed_extensions is not None:
        allowed = [e.lower().lstrip(".") for e in allowed_extensions]
    elif module and module in ALLOWED_EXTENSIONS:
        allowed = ALLOWED_EXTENSIONS[module]
    else:
        return True, ""  # 未指定则放行

    if ext not in allowed:
        allowed_str = "、".join([f".{e}" for e in allowed])
        return False, f"不支持 .{ext} 格式，请上传以下格式的文件：{allowed_str}"

    return True, ""


def validate_file_mime(
    filename: str,
    expected_mime_types: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    校验文件 MIME 类型（基于扩展名推断）。
    注意：基于文件名的 MIME 推断不可完全信任，生产环境可结合 python-magic 做内容检测。

    参数:
        filename:          文件名
        expected_mime_types: 期望的 MIME 类型列表（如 ["image/jpeg", "image/png"]）

    返回:
        (是否通过, 错误提示)
    """
    if expected_mime_types is None:
        return True, ""

    mime_type, _ = mimetypes.guess_type(filename)
    if mime_type is None:
        return False, "无法识别文件的 MIME 类型"

    if mime_type not in expected_mime_types:
        expected_str = "、".join(expected_mime_types)
        return False, f"文件类型 {mime_type} 不符合要求，期望类型：{expected_str}"

    return True, ""


def validate_single_file(
    filename: str,
    file_size: int,
    module: Optional[str] = None,
    max_size_mb: Optional[int] = None,
    allowed_extensions: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    对单个文件执行完整校验（大小 + 扩展名），一站式检测。

    参数:
        filename:          文件名
        file_size:         文件大小（字节）
        module:            模块名称（自动匹配大小限制和格式白名单）
        max_size_mb:       自定义大小上限（MB）
        allowed_extensions: 自定义允许扩展名列表

    返回:
        (是否通过, 错误提示)
    """
    # 1. 校验扩展名
    ok, msg = validate_file_extension(
        filename=filename,
        module=module,
        allowed_extensions=allowed_extensions,
    )
    if not ok:
        return False, msg

    # 2. 校验文件大小
    ok, msg = validate_file_size(
        file_size=file_size,
        max_size_mb=max_size_mb,
        module=module,
    )
    if not ok:
        return False, msg

    return True, ""


def validate_batch_files(
    files: List[Tuple[str, int]],
    module: Optional[str] = None,
    max_size_mb: Optional[int] = None,
    allowed_extensions: Optional[List[str]] = None,
    max_file_count: int = 50,
) -> Tuple[bool, str, List[Dict[str, str]]]:
    """
    批量校验多个文件，返回每个文件的校验结果。

    参数:
        files:         [(文件名, 文件大小), ...]
        module:        模块名称
        max_size_mb:   自定义大小上限
        allowed_extensions: 自定义扩展名列表
        max_file_count: 单次上传文件数量上限

    返回:
        (整体是否全部通过, 汇总错误信息, [{"filename": ..., "passed": bool, "error": str}, ...])
    """
    if len(files) > max_file_count:
        return (
            False,
            f"单次上传文件数量不能超过 {max_file_count} 个",
            [],
        )

    results = []
    all_passed = True
    error_messages = []

    for filename, file_size in files:
        passed, error = validate_single_file(
            filename=filename,
            file_size=file_size,
            module=module,
            max_size_mb=max_size_mb,
            allowed_extensions=allowed_extensions,
        )
        results.append({
            "filename": filename,
            "passed": passed,
            "error": error,
        })
        if not passed:
            all_passed = False
            error_messages.append(f"{filename}: {error}")

    summary = "" if all_passed else "；".join(error_messages)
    return all_passed, summary, results


# ============================================================
# 快速使用示例
# ============================================================
if __name__ == "__main__":
    # 自测示例
    print("=== 单文件校验 ===")
    ok, msg = validate_single_file("photo.jpg", 5 * 1024 * 1024, module="image")
    print(f"photo.jpg (5MB): passed={ok}, msg='{msg}'")

    ok, msg = validate_single_file("data.xlsx", 50 * 1024 * 1024, module="image")
    print(f"data.xlsx (50MB, image模块): passed={ok}, msg='{msg}'")

    print("\n=== 批量校验 ===")
    test_files = [
        ("img1.png", 3 * 1024 * 1024),
        ("img2.txt", 1 * 1024 * 1024),       # 不支持格式
        ("img3.jpg", 25 * 1024 * 1024),       # 超出 image 模块 20MB 限制
    ]
    all_ok, summary, results = validate_batch_files(test_files, module="image")
    print(f"全部通过: {all_ok}")
    print(f"汇总: {summary}")
    for r in results:
        print(f"  {r['filename']}: {'✓' if r['passed'] else '✗'} {r['error']}")
