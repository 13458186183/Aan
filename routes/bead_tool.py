
"""
拼豆图纸转换工具路由
上传图片自动转换为拼豆像素图纸，生成配色方案与拼豆数量清单
支持 221 色拼豆标准色库
"""
import os
import re
import io
import logging
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bead", tags=["拼豆图纸"])

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp_file"

# ============================================================
# 拼豆标准色库（221色，市面常见拼豆配色）
# ============================================================

BEAD_PALETTE = [
    # === 白色系 (W01-W12) ===
    ("纯白",     (255, 255, 255)),
    ("奶白",     (255, 250, 240)),
    ("象牙白",   (255, 255, 240)),
    ("米白",     (245, 245, 220)),
    ("雪白",     (255, 250, 250)),
    ("古董白",   (250, 235, 215)),
    ("亚麻白",   (250, 240, 230)),
    ("花白",     (253, 245, 230)),
    ("浅奶油",   (255, 253, 245)),
    ("香槟白",   (248, 243, 230)),
    ("珍珠白",   (252, 251, 247)),
    ("蛋壳白",   (240, 234, 214)),
    # === 灰色系 (G01-G20) ===
    ("极浅灰",   (245, 245, 245)),
    ("雾灰",     (235, 235, 235)),
    ("银灰",     (220, 220, 220)),
    ("浅灰",     (205, 205, 205)),
    ("中灰",     (180, 180, 180)),
    ("灰",       (160, 160, 160)),
    ("岩灰",     (145, 145, 145)),
    ("深灰",     (125, 125, 125)),
    ("暗灰",     (105, 105, 105)),
    ("铁灰",     (90, 90, 90)),
    ("炭灰",     (75, 75, 75)),
    ("鼠灰",     (185, 180, 175)),
    ("蓝灰",     (170, 175, 185)),
    ("紫灰",     (175, 170, 180)),
    ("暖灰",     (190, 180, 170)),
    ("冷灰",     (195, 195, 200)),
    ("水泥灰",   (165, 165, 165)),
    ("烟灰",     (140, 140, 145)),
    ("石板灰",   (115, 120, 125)),
    ("铅灰",     (95, 95, 100)),
    # === 黑色系 (B01-B08) ===
    ("墨灰",     (65, 65, 70)),
    ("暗夜灰",   (50, 50, 55)),
    ("深炭",     (42, 42, 45)),
    ("曜石黑",   (33, 33, 35)),
    ("纯黑",     (20, 20, 20)),
    ("墨黑",     (25, 22, 28)),
    ("棕黑",     (35, 28, 25)),
    ("蓝黑",     (22, 25, 35)),
    # === 粉色系 (P01-P22) ===
    ("婴儿粉",   (255, 235, 240)),
    ("芭蕾粉",   (255, 220, 230)),
    ("浅粉",     (255, 200, 215)),
    ("柔粉",     (255, 185, 200)),
    ("粉红",     (255, 160, 180)),
    ("桃粉",     (255, 140, 165)),
    ("樱花粉",   (255, 180, 195)),
    ("玫瑰粉",   (250, 140, 165)),
    ("玫红",     (240, 100, 140)),
    ("亮粉",     (255, 105, 145)),
    ("热粉",     (255, 70, 120)),
    ("深粉",     (235, 60, 110)),
    ("品红",     (225, 40, 100)),
    ("紫粉",     (210, 80, 150)),
    ("薰衣草粉", (235, 190, 210)),
    ("珊瑚粉",   (255, 160, 150)),
    ("蜜桃粉",   (255, 190, 180)),
    ("胭脂粉",   (240, 120, 140)),
    ("豆沙粉",   (220, 150, 160)),
    ("裸粉",     (235, 195, 190)),
    ("藕粉",     (210, 160, 175)),
    ("干枯玫瑰", (185, 110, 125)),
    # === 红色系 (R01-R20) ===
    ("浅红",     (255, 135, 125)),
    ("珊瑚红",   (255, 115, 105)),
    ("橘红",     (255, 85, 65)),
    ("朱红",     (240, 65, 50)),
    ("正红",     (230, 35, 35)),
    ("大红",     (215, 20, 30)),
    ("深红",     (185, 20, 25)),
    ("酒红",     (155, 20, 35)),
    ("勃艮第红", (130, 15, 30)),
    ("暗红",     (110, 18, 30)),
    ("铁锈红",   (175, 45, 40)),
    ("砖红",     (190, 70, 50)),
    ("辣椒红",   (215, 30, 25)),
    ("西瓜红",   (245, 90, 95)),
    ("草莓红",   (235, 55, 65)),
    ("樱桃红",   (200, 25, 35)),
    ("石榴红",   (195, 30, 40)),
    ("玫紫红",   (180, 30, 75)),
    ("棕红",     (160, 55, 45)),
    ("番茄红",   (225, 55, 40)),
    # === 橙色系 (O01-O16) ===
    ("浅杏",     (255, 220, 190)),
    ("杏色",     (255, 200, 160)),
    ("蜜橙",     (255, 185, 140)),
    ("浅橙",     (255, 170, 115)),
    ("橙色",     (255, 150, 50)),
    ("亮橙",     (255, 130, 30)),
    ("深橙",     (235, 110, 25)),
    ("南瓜橙",   (240, 130, 50)),
    ("橘色",     (245, 115, 40)),
    ("柿色",     (225, 95, 35)),
    ("浓橙",     (210, 80, 20)),
    ("琥珀",     (225, 145, 60)),
    ("赤橙",     (240, 95, 35)),
    ("奶油杏",   (255, 210, 175)),
    ("三文鱼",   (255, 175, 145)),
    ("橘棕",     (195, 110, 55)),
    # === 黄色系 (Y01-Y18) ===
    ("奶黄",     (255, 252, 220)),
    ("浅黄",     (255, 248, 180)),
    ("柔黄",     (255, 240, 160)),
    ("奶油黄",   (255, 250, 200)),
    ("淡黄",     (255, 245, 140)),
    ("黄色",     (255, 230, 60)),
    ("明黄",     (255, 220, 30)),
    ("亮黄",     (255, 210, 10)),
    ("深黄",     (245, 195, 20)),
    ("向日葵黄", (255, 215, 40)),
    ("金盏黄",   (250, 190, 30)),
    ("芥末黄",   (220, 180, 55)),
    ("金黄",     (245, 180, 15)),
    ("深金",     (220, 155, 20)),
    ("古铜金",   (200, 145, 35)),
    ("土黄",     (205, 160, 75)),
    ("沙色",     (225, 195, 140)),
    ("驼色",     (200, 170, 120)),
    # === 绿色系 (GR01-GR28) ===
    ("薄荷白",   (225, 248, 235)),
    ("浅薄荷",   (190, 235, 205)),
    ("薄荷绿",   (140, 220, 175)),
    ("浅绿",     (185, 230, 160)),
    ("嫩绿",     (160, 220, 120)),
    ("草绿",     (120, 210, 80)),
    ("青草绿",   (90, 200, 55)),
    ("亮绿",     (60, 195, 55)),
    ("翠绿",     (35, 180, 70)),
    ("绿色",     (30, 160, 55)),
    ("鲜绿",     (40, 175, 65)),
    ("深绿",     (15, 130, 40)),
    ("墨绿",     (12, 100, 35)),
    ("暗绿",     (10, 80, 30)),
    ("橄榄绿",   (120, 130, 55)),
    ("苔绿",     (90, 130, 50)),
    ("军绿",     (70, 100, 45)),
    ("卡其绿",   (145, 150, 105)),
    ("鼠尾草绿", (165, 185, 140)),
    ("湖水绿",   (85, 195, 165)),
    ("孔雀绿",   (30, 160, 140)),
    ("松石绿",   (60, 185, 160)),
    ("浅松石",   (145, 215, 200)),
    ("碧绿",     (25, 155, 100)),
    ("翡翠绿",   (20, 150, 115)),
    ("森林绿",   (20, 100, 55)),
    ("冬青绿",   (15, 90, 45)),
    ("韭葱绿",   (100, 160, 70)),
    # === 蓝色系 (BL01-BL30) ===
    ("婴儿蓝",   (220, 238, 255)),
    ("浅蓝",     (190, 225, 255)),
    ("淡蓝",     (170, 215, 250)),
    ("粉蓝",     (155, 200, 240)),
    ("天蓝",     (120, 190, 245)),
    ("天空蓝",   (100, 180, 240)),
    ("亮蓝",     (70, 155, 235)),
    ("蓝色",     (45, 110, 220)),
    ("宝蓝",     (30, 80, 210)),
    ("深蓝",     (20, 55, 170)),
    ("藏蓝",     (18, 35, 120)),
    ("午夜蓝",   (15, 25, 80)),
    ("海军蓝",   (25, 40, 100)),
    ("牛仔蓝",   (50, 90, 175)),
    ("矢车菊蓝", (100, 155, 225)),
    ("湖水蓝",   (80, 185, 220)),
    ("浅湖蓝",   (145, 215, 235)),
    ("蔚蓝",     (60, 175, 230)),
    ("钴蓝",     (35, 65, 195)),
    ("皇家蓝",   (25, 55, 190)),
    ("普鲁士蓝", (20, 45, 140)),
    ("灰蓝",     (100, 130, 175)),
    ("钢蓝",     (80, 110, 160)),
    ("石板蓝",   (65, 90, 140)),
    ("紫蓝",     (70, 60, 180)),
    ("鸢尾蓝",   (55, 50, 160)),
    ("冰蓝",     (200, 235, 255)),
    ("雾蓝",     (175, 205, 230)),
    ("深海蓝",   (10, 30, 90)),
    ("墨蓝",     (8, 20, 55)),
    # === 紫色系 (PU01-PU20) ===
    ("浅紫",     (225, 205, 240)),
    ("薰衣草",   (210, 185, 235)),
    ("淡紫",     (195, 165, 225)),
    ("丁香紫",   (180, 140, 215)),
    ("紫色",     (155, 90, 210)),
    ("深紫",     (120, 50, 185)),
    ("葡萄紫",   (100, 35, 160)),
    ("暗紫",     (75, 20, 125)),
    ("紫罗兰",   (165, 110, 215)),
    ("兰花紫",   (190, 130, 220)),
    ("紫红",     (195, 60, 170)),
    ("洋红",     (205, 35, 155)),
    ("品紫",     (170, 40, 165)),
    ("李紫",     (140, 30, 140)),
    ("茄子紫",   (90, 25, 110)),
    ("浅薰衣草", (230, 215, 245)),
    ("紫藤",     (175, 155, 215)),
    ("锦葵紫",   (200, 170, 220)),
    ("水晶紫",   (150, 130, 200)),
    ("帝王紫",   (80, 15, 115)),
    # === 棕色系 (BR01-BR20) ===
    ("奶油肤",   (255, 225, 200)),
    ("肤色",     (255, 210, 175)),
    ("浅肤",     (250, 195, 155)),
    ("肉色",     (245, 180, 140)),
    ("蜜肤",     (235, 165, 125)),
    ("奶茶色",   (215, 170, 135)),
    ("浅棕",     (205, 155, 115)),
    ("卡其色",   (195, 160, 120)),
    ("小麦色",   (210, 165, 125)),
    ("棕色",     (170, 115, 65)),
    ("可可棕",   (155, 100, 55)),
    ("咖啡色",   (140, 85, 45)),
    ("深棕",     (115, 65, 30)),
    ("巧克力色", (100, 50, 25)),
    ("栗色",     (130, 55, 30)),
    ("焦糖色",   (185, 120, 60)),
    ("摩卡色",   (150, 110, 75)),
    ("胡桃色",   (120, 80, 50)),
    ("檀木色",   (90, 55, 35)),
    ("黑巧色",   (75, 35, 20)),
    # === 荧光/特殊色 (N01-N09) ===
    ("荧光黄",   (225, 255, 50)),
    ("荧光绿",   (50, 255, 90)),
    ("荧光橙",   (255, 140, 40)),
    ("荧光粉",   (255, 80, 150)),
    ("荧光蓝",   (60, 200, 255)),
    ("闪金",     (255, 215, 0)),
    ("闪银",     (210, 210, 215)),
    ("幻彩紫",   (200, 180, 230)),
    ("夜光白",   (240, 255, 235)),
]


# ============================================================
# 工具函数
# ============================================================

def _ensure() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _err(code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"ok": False, "error": detail})


def _ok(data: dict = None, msg: str = "ok") -> dict:
    return {"ok": True, "message": msg, "data": data or {}}


def _sanitize(name: str) -> str:
    """安全文件名，防路径穿越"""
    name = os.path.basename(name)
    name = re.sub(r'[\\/:*?"<>|]', '_', name).strip(' .')
    return name if name else "untitled"


# 调色板分组信息（与 BEAD_PALETTE 顺序一致）
BEAD_GROUPS = (
    ["白色系"] * 12 + ["灰色系"] * 20 + ["黑色系"] * 8 +
    ["粉色系"] * 22 + ["红色系"] * 20 + ["橙色系"] * 16 +
    ["黄色系"] * 18 + ["绿色系"] * 28 + ["蓝色系"] * 30 +
    ["紫色系"] * 20 + ["棕色系"] * 20 + ["荧光/特殊色"] * 9
)

# 颜色编号前缀（与分组对应）
GROUP_PREFIX = {
    "白色系": "W", "灰色系": "G", "黑色系": "B",
    "粉色系": "P", "红色系": "R", "橙色系": "O",
    "黄色系": "Y", "绿色系": "GR", "蓝色系": "BL",
    "紫色系": "PU", "棕色系": "BR", "荧光/特殊色": "N",
}

def _bead_code(idx: int) -> str:
    """根据调色板索引生成颜色编号，如 W01, R05 等"""
    group = BEAD_GROUPS[idx] if idx < len(BEAD_GROUPS) else "其它"
    prefix = GROUP_PREFIX.get(group, "X")
    # 当前组内计数
    count = sum(1 for i in range(idx + 1) if i < len(BEAD_GROUPS) and BEAD_GROUPS[i] == group)
    return f"{prefix}{count:02d}"


def _closest_color(rgb: tuple, palette: list) -> tuple:
    """在调色板中找欧氏距离最近的颜色，返回 (名称, RGB)"""
    r, g, b = rgb
    best = palette[0]
    best_dist = float("inf")
    for item in palette:
        name, (pr, pg, pb) = item[0], item[1]
        dr, dg, db = r - pr, g - pg, b - pb
        dist = dr*dr*2 + dg*dg*4 + db*db
        if dist < best_dist:
            best_dist = dist
            best = (name, (pr, pg, pb))
    return best


def _rgb_to_hex(rgb: tuple) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# ============================================================
# 接口：图片转拼豆图纸
# ============================================================

@router.post("/convert", summary="图片转拼豆像素图纸")
async def bead_convert(
    file: UploadFile = File(..., description="待转换的图片文件"),
    size: int = Form(52, ge=8, le=300, description="画布尺寸（正方形，8~300）"),
    num_colors: int = Form(221, ge=2, le=221, description="量化颜色数（2~221）"),
    fit_mode: str = Form("fill", description="填充模式：fill=撑满画布, fit=保持比例居中留白"),
):
    """
    上传图片 → 像素化 → 颜色量化 → 匹配221色拼豆调色板 →
    返回像素网格数据 + 完整色库 + 配色清单 + 预览图。

    fit_mode:
      - "fill"（默认）：居中裁剪为正方形后拉伸填满画布
      - "fit"：保持原图比例缩放适配画布，周围留白
    """
    # === 校验 ===
    if not file.filename:
        return _err(400, "未选择文件")
    if not file.content_type or not file.content_type.startswith("image/"):
        return _err(400, "请上传图片文件（JPG / PNG / BMP / WebP 等）")

    try:
        raw = await file.read()
        if len(raw) == 0:
            return _err(400, "文件大小为 0")
        if len(raw) > 20 * 1024 * 1024:
            return _err(400, "图片大小超过 20MB 限制")
        img = Image.open(io.BytesIO(raw))
    except Exception:
        return _err(400, "无法打开该图片，文件可能已损坏或不支持此格式")

    try:
        # === 1. 调整图片尺寸 ===
        if fit_mode == "fit":
            # 自适应模式：保持比例，居中放置在白色画布上
            iw, ih = img.size
            ratio = min(size / iw, size / ih)
            new_w = int(iw * ratio)
            new_h = int(ih * ratio)
            img = img.resize((new_w, new_h), Image.NEAREST)
            canvas_img = Image.new("RGB", (size, size), (255, 255, 255))
            ox = (size - new_w) // 2
            oy = (size - new_h) // 2
            canvas_img.paste(img, (ox, oy))
            img = canvas_img
        else:
            # 填充模式：居中裁剪为正方形再缩放到画布
            iw, ih = img.size
            crop_sz = min(iw, ih)
            left = (iw - crop_sz) // 2
            top = (ih - crop_sz) // 2
            img = img.crop((left, top, left + crop_sz, top + crop_sz))
            img = img.resize((size, size), Image.NEAREST)
        img = img.convert("RGB")
        img = img.convert("RGB")

        # === 2. 颜色量化 ===
        max_c = min(num_colors, 221)
        try:
            quantized = img.quantize(colors=max_c)
        except Exception as qe:
            logger.exception("quantize 失败: %s", qe)
            # 兜底：直接用 convert("P") 或逐个像素匹配
            try:
                quantized = img.convert("P", palette=Image.ADAPTIVE, colors=max_c)
            except Exception:
                logger.exception("convert('P') 也失败")
                quantized = None

        # === 3. 建立 bead 索引映射 ===
        bead_idx_map = {}
        for idx, (name, _) in enumerate(BEAD_PALETTE):
            bead_idx_map[name] = idx

        from collections import Counter
        bead_counter = Counter()
        grid = [0] * (size * size)

        if quantized is not None:
            # 有量化图像，通过调色板映射
            raw_pal = quantized.getpalette()
            if raw_pal is not None and len(raw_pal) >= max_c * 3:
                q_palette = [tuple(raw_pal[i:i+3]) for i in range(0, max_c * 3, 3)]
                q_to_bead_idx = {}
                for q_idx, q_rgb in enumerate(q_palette):
                    bead_name, _ = _closest_color(q_rgb, BEAD_PALETTE)
                    q_to_bead_idx[q_idx] = bead_idx_map.get(bead_name, 0)

                pixels = list(quantized.getdata())
                for i, p in enumerate(pixels):
                    grid[i] = q_to_bead_idx.get(p, 0)
                    bead_counter[BEAD_PALETTE[grid[i]][0]] += 1
            else:
                # 调色板不可用，直接用像素匹配
                logger.warning("调色板不可用，逐个像素匹配")
                pixel_data = list(img.getdata())
                for i, px in enumerate(pixel_data):
                    bead_name, _ = _closest_color(px, BEAD_PALETTE)
                    grid[i] = bead_idx_map.get(bead_name, 0)
                    bead_counter[bead_name] += 1
        else:
            # 直接逐个像素匹配最近拼豆色
            pixel_data = list(img.getdata())
            for i, px in enumerate(pixel_data):
                bead_name, _ = _closest_color(px, BEAD_PALETTE)
                grid[i] = bead_idx_map.get(bead_name, 0)
                bead_counter[bead_name] += 1

        # === 5. 生成预览图 ===
        cell_size = max(4, min(24, 1200 // size))
        preview_w = size * cell_size
        preview_h = size * cell_size
        preview = Image.new("RGB", (preview_w, preview_h), (255, 255, 255))
        draw = ImageDraw.Draw(preview)

        for row in range(size):
            for col in range(size):
                idx = row * size + col
                _, bead_rgb = BEAD_PALETTE[grid[idx]]
                x1, y1 = col * cell_size, row * cell_size
                draw.rectangle([x1, y1, x1 + cell_size - 1, y1 + cell_size - 1], fill=bead_rgb)

        # === 6. 保存预览图 ===
        _ensure()
        safe_name = _sanitize(file.filename)
        output_name = f"bead_{safe_name.rsplit('.',1)[0]}_{size}x{size}.png"
        output_path = TEMP_DIR / output_name
        preview.save(output_path, "PNG", optimize=True)

        # === 7. 构造完整色库返回给前端 ===
        palette_full = []
        for i, (name, rgb) in enumerate(BEAD_PALETTE):
            if i >= 221:  # 严格221色
                break
            palette_full.append({
                "index": i,
                "name": name,
                "hex": _rgb_to_hex(rgb),
                "code": _bead_code(i),
                "group": BEAD_GROUPS[i] if i < len(BEAD_GROUPS) else "其它",
            })

        # === 8. 配色清单（按使用量降序） ===
        sorted_colors = bead_counter.most_common()
        color_list = []
        for name, count in sorted_colors:
            info = next((p for p in palette_full if p["name"] == name), None)
            color_list.append({
                "name": name,
                "hex": info["hex"] if info else "#000000",
                "code": info["code"] if info else "?",
                "count": count,
            })

        total = size * size

        return _ok({
            "size": size,
            "total_beads": total,
            "color_count_used": len(sorted_colors),
            "grid": grid,           # 1D 数组: grid[row*size+col] = palette index
            "palette": palette_full, # 221色完整色库
            "colors": color_list,   # 实际使用的颜色统计
            "preview_url": f"/api/bead/download/{output_name}",
            "filename": output_name,
        }, msg=f"转换成功，画布 {size}×{size}，使用 {len(sorted_colors)} 种颜色")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("bead_convert 异常: %s", e)
        return _err(500, f"转换过程出错: {e}")


# ============================================================
# 文件下载接口
# ============================================================

@router.get("/download/{filename}", summary="下载生成的拼豆图纸")
async def download_bead(filename: str):
    _ensure()
    target = (TEMP_DIR / filename).resolve()
    if not target.is_relative_to(TEMP_DIR.resolve()):
        raise HTTPException(status_code=403, detail="非法文件路径")
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    return FileResponse(path=str(target), media_type="image/png", filename=filename)
