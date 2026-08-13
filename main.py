"""
FieldKit - 一站式 Web 工具箱 项目入口
======================================
基于 FastAPI 构建，提供图片处理、文件工具箱、拼豆图纸转换、考勤点名、
测绘 EXIF 水印、村级资产清查表等 Web 服务。

启动方式：
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ---------- 导入工具模块 ----------
from utils.clean_task import clean_temp_files

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("FieldKit")

# ============================================================
# 全局调度器实例（在 lifespan 中启动/关闭）
# ============================================================
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


# ============================================================
# 应用生命周期管理
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 应用生命周期：
    - 启动时：挂载定时清理任务、创建必要目录
    - 关闭时：优雅停止调度器
    """
    # ---------- 启动阶段 ----------
    logger.info("=" * 50)
    logger.info("FieldKit 工具箱启动中...")

    # 确保临时文件目录存在
    os.makedirs("temp_file", exist_ok=True)
    logger.info("临时文件目录 temp_file/ 已就绪")

    # 添加定时任务：每 1 小时执行一次临时文件清理（清理超过 24 小时的文件）
    scheduler.add_job(
        func=clean_temp_files,
        trigger=IntervalTrigger(hours=1),
        id="clean_temp_files_job",
        name="自动清理临时文件（>24h）",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("APScheduler 定时任务已启动（每小时清理一次过期临时文件）")

    logger.info("FieldKit 工具箱启动完成！访问 http://localhost:8000")
    logger.info("=" * 50)

    yield  # 应用运行中...

    # ---------- 关闭阶段 ----------
    logger.info("FieldKit 工具箱正在关闭...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler 定时任务已停止")
    logger.info("FieldKit 工具箱已关闭")


# ============================================================
# FastAPI 应用实例
# ============================================================
app = FastAPI(
    title="FieldKit - 一站式 Web 工具箱",
    description="提供图片处理、文件工具箱、拼豆图纸转换、考勤点名、测绘 EXIF 水印、村级资产清查表等 Web 服务",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",       # Swagger UI 文档地址
    redoc_url="/redoc",     # ReDoc 文档地址
)

# ============================================================
# CORS 跨域配置
# 允许前端页面（可能部署在不同端口/域名）访问后端 API
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],                 # 生产环境建议限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],                 # 允许所有 HTTP 方法
    allow_headers=["*"],                 # 允许所有请求头
    expose_headers=["Content-Disposition"],  # 前端需要读取下载文件名
)

# ============================================================
# 静态文件挂载
# /static 路径映射到 static/ 目录，存放前端 HTML/CSS/JS
# ============================================================
app.mount("/static", StaticFiles(directory="static"), name="static")


# ============================================================
# 路由注册（后续分模块挂载）
# ============================================================
from routes.image_tool import router as image_router
app.include_router(image_router)
from routes.file_tool import router as file_router
app.include_router(file_router)
from routes.bead_tool import router as bead_router
app.include_router(bead_router)
from routes.attendance_tool import router as attendance_router
app.include_router(attendance_router)
from routes.survey_tool import router as survey_router
app.include_router(survey_router)
from routes.asset_tool import router as asset_router
app.include_router(asset_router)



# ============================================================
# 根路径 - 首页 HTML
# ============================================================
@app.get("/", tags=["系统"], include_in_schema=False)
async def root():
    """返回首页 HTML（导航页）"""
    return FileResponse("static/index.html", media_type="text/html")


@app.get("/api/info", tags=["系统"])
async def api_info():
    """工具箱基本信息（JSON，供 API 文档/调试）"""
    return {
        "name": "FieldKit - 一站式 Web 工具箱",
        "version": "1.0.0",
        "docs": "/docs",
        "modules": [
            {"name": "图片处理工具", "priority": "高"},
            {"name": "文件工具箱", "priority": "高"},
            {"name": "拼豆图纸转换工具", "priority": "中"},
            {"name": "考勤点名工具", "priority": "高"},
            {"name": "村级资产清查表工具", "priority": "中"},
            {"name": "测绘 EXIF 水印工具", "priority": "高"},
        ],
    }


# ============================================================
# 健康检查接口
# ============================================================
@app.get("/api/health", tags=["系统"])
async def health_check():
    """健康检查，用于监控服务状态"""
    return {
        "status": "ok",
        "scheduler_running": scheduler.running if scheduler else False,
    }


# ============================================================
# 主程序入口（直接运行 python main.py 时启动）
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
