"""
clean_task.py - 临时文件自动清理任务
=====================================
由 APScheduler 定时触发，清理 temp_file/ 目录中超过指定时长的文件。
支持按文件修改时间判断、安全边界检查、详细日志记录。
"""

import os
import time
import logging
from pathlib import Path

logger = logging.getLogger("FieldKit.CleanTask")

# ============================================================
# 可配置常量
# ============================================================

# 项目根目录下的临时文件目录
TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp_file")

# 文件保留时长（秒），默认 24 小时
DEFAULT_RETENTION_SECONDS = 24 * 60 * 60


def clean_temp_files(
    temp_dir: str = TEMP_DIR,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    dry_run: bool = False,
) -> dict:
    """
    清理临时文件目录中超过保留时长的文件。

    清理策略：
    - 以文件的「最后修改时间」(st_mtime) 为判断依据
    - 只删除普通文件和符号链接，不操作子目录（确保安全）
    - 遇到无法删除的文件会记录日志并跳过，不影响整体流程

    参数:
        temp_dir:          临时文件目录路径
        retention_seconds: 文件保留时长（秒），超过则删除
        dry_run:           是否为试运行模式（True 时只统计不删除）

    返回:
        {
            "cleaned_count": int,   # 清理的文件数量
            "freed_bytes": int,     # 释放的磁盘空间（字节）
            "errors": [str, ...],   # 删除失败的文件及原因
            "dry_run": bool,        # 是否为试运行
        }
    """
    # ---- 安全检查：确保操作的是 temp_file 目录，防止误删 ----
    temp_path = Path(temp_dir).resolve()
    # 目录名必须包含 "temp" 字样，且不是系统关键路径
    if "temp" not in temp_path.name.lower():
        logger.warning(f"目录名不包含 'temp'，出于安全考虑跳过清理: {temp_path}")
        return {"cleaned_count": 0, "freed_bytes": 0, "errors": [], "dry_run": dry_run}

    # ---- 目录不存在则创建 ----
    if not temp_path.exists():
        logger.info(f"临时文件目录不存在，已自动创建: {temp_path}")
        temp_path.mkdir(parents=True, exist_ok=True)
        return {"cleaned_count": 0, "freed_bytes": 0, "errors": [], "dry_run": dry_run}

    now = time.time()
    cutoff_time = now - retention_seconds
    cleaned_count = 0
    freed_bytes = 0
    errors = []

    logger.info(
        f"开始清理临时文件 [目录={temp_path}, 保留时长={retention_seconds // 3600}h, "
        f"截止时间戳={cutoff_time:.0f}, dry_run={dry_run}]"
    )

    # ---- 遍历目录中的文件 ----
    for entry in temp_path.iterdir():
        # 只处理普通文件和符号链接，跳过子目录和特殊文件
        if not entry.is_file() and not entry.is_symlink():
            continue

        try:
            mtime = entry.stat().st_mtime
            if mtime < cutoff_time:
                file_size = entry.stat().st_size
                age_hours = (now - mtime) / 3600

                if dry_run:
                    logger.info(f"  [DRY_RUN] 将删除: {entry.name} (大小={file_size}B, 已存在{age_hours:.1f}h)")
                    cleaned_count += 1
                    freed_bytes += file_size
                else:
                    entry.unlink()
                    logger.info(f"  已删除: {entry.name} (大小={file_size}B, 已存在{age_hours:.1f}h)")
                    cleaned_count += 1
                    freed_bytes += file_size

        except PermissionError as e:
            err_msg = f"权限不足，无法删除 {entry.name}: {e}"
            logger.warning(err_msg)
            errors.append(err_msg)
        except OSError as e:
            err_msg = f"删除 {entry.name} 失败: {e}"
            logger.error(err_msg)
            errors.append(err_msg)

    # ---- 汇总日志 ----
    freed_mb = freed_bytes / (1024 * 1024)
    logger.info(
        f"临时文件清理完成: 共清理 {cleaned_count} 个文件, "
        f"释放 {freed_mb:.2f}MB, 错误数 {len(errors)}"
    )

    return {
        "cleaned_count": cleaned_count,
        "freed_bytes": freed_bytes,
        "errors": errors,
        "dry_run": dry_run,
    }


# ============================================================
# 快速测试
# ============================================================
if __name__ == "__main__":
    # 自测：试运行模式，查看会清理哪些文件
    print("=== 临时文件清理试运行 (dry_run=True) ===")
    result = clean_temp_files(dry_run=True)
    print(f"将清理: {result['cleaned_count']} 个文件, 释放 {result['freed_bytes']/1024/1024:.2f}MB")
    if result["errors"]:
        print(f"错误: {result['errors']}")
