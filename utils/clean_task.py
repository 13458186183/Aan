"""
clean_task.py - 定时清理临时文件任务
=====================================
清理规则：
1. 仅清理项目根目录下的 temp_file/、temp_image/ 目录（防误删，目录名必须含 "temp"）
2. 超过 retention_seconds（默认 24 小时）未修改的文件将被删除
3. 删除失败（文件被占用等）自动跳过，不影响其他文件
4. 支持 dry_run 模式，仅统计不删除，便于测试
"""

import os
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# 项目根目录（utils/ 的上一级）
ROOT = Path(__file__).resolve().parent.parent

# 参与清理的临时目录
TEMP_DIRS = [
    ROOT / "temp_file",
    ROOT / "temp_image",
]

# 保留时长（秒），默认 24 小时
DEFAULT_RETENTION_SECONDS = 24 * 60 * 60


def clean_temp_files(
    temp_dirs: Optional[List[Path]] = None,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    dry_run: bool = False,
) -> dict:
    """
    清理所有临时目录中超过保留时长的文件。

    Args:
        temp_dirs: 待清理目录列表，默认使用 TEMP_DIRS
        retention_seconds: 文件保留时长（秒）
        dry_run: 为 True 时仅统计不删除（用于测试）

    Returns:
        {"removed": 删除数量, "skipped": 跳过数量, "total_size": 释放字节}
    """
    if temp_dirs is None:
        temp_dirs = TEMP_DIRS

    total_removed = 0
    total_skipped = 0
    total_size = 0

    for temp_dir in temp_dirs:
        _removed, _skipped, _freed = _clean_one_dir(
            temp_dir,
            retention_seconds=retention_seconds,
            dry_run=dry_run,
        )
        total_removed += _removed
        total_skipped += _skipped
        total_size += _freed

    logger.info(
        "临时文件清理完成: 目录 %d 个, 删除 %d 个, 跳过 %d 个, 释放 %.2f MB"
        % (len(temp_dirs), total_removed, total_skipped, total_size / 1024 / 1024)
    )
    return {"removed": total_removed, "skipped": total_skipped, "total_size": total_size}


def _clean_one_dir(
    temp_dir: Path,
    retention_seconds: int,
    dry_run: bool,
) -> tuple:
    """清理单个临时目录"""
    # 安全校验：目录名必须含 "temp"，防止误删其他目录
    if "temp" not in temp_dir.name:
        logger.warning("目录名不含 temp，跳过清理: %s", temp_dir)
        return 0, 0, 0

    # 目录不存在则创建（后续写入时无需再判断）
    temp_dir.mkdir(parents=True, exist_ok=True)

    removed = 0
    skipped = 0
    freed = 0

    for item in temp_dir.iterdir():
        if not item.is_file():
            continue
        try:
            mtime = item.stat().st_mtime
            age = _now_ts() - mtime
            if age > retention_seconds:
                if dry_run:
                    removed += 1
                    freed += item.stat().st_size
                    logger.debug("[dry-run] 将删除: %s", item.name)
                else:
                    size = item.stat().st_size
                    item.unlink()
                    removed += 1
                    freed += size
                    logger.debug("已删除过期临时文件: %s", item.name)
            else:
                skipped += 1
        except OSError as exc:
            # 文件被占用或权限不足等，跳过不中断
            skipped += 1
            logger.debug("删除临时文件失败，跳过: %s (%s)", item.name, exc)

    logger.info(
        "目录 %s: 删除 %d, 跳过 %d, 释放 %.2f KB"
        % (temp_dir.name, removed, skipped, freed / 1024)
    )
    return removed, skipped, freed


def _now_ts() -> float:
    """当前时间戳（秒）"""
    import time
    return time.time()


if __name__ == "__main__":
    # 手动执行：python -m utils.clean_task
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = clean_temp_files(dry_run=False)
    print(f"清理结果: 删除 {result['removed']} 个, 跳过 {result['skipped']} 个, 释放 {result['total_size']} 字节")
