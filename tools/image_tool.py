"""
image_tool.py
==============
AI画像生成を使わない、シンプルなアイキャッチ・挿絵の自動生成ツール。

Pillow（画像処理ライブラリ）だけで、以下を自動生成します:
  - generate_eyecatch(): 記事のアイキャッチ画像（1200x630、OGP標準サイズ）
  - generate_section_illustration(): 記事中に挟む挿絵（装飾用の小さい画像）

色はクライアント名から自動的に一意の色相を決めるので、クライアントごとに
毎回バラバラな配色にならず、ブランドとして一貫した雰囲気になります。
（config/clients.yaml で accent_color を指定すれば、その色を優先します）
"""

from __future__ import annotations

import hashlib
import math
import textwrap
from pathlib import Path

from crewai.tools import tool
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = PROJECT_ROOT / "fonts" / "NotoSansJP-Variable.ttf"

EYECATCH_SIZE = (1200, 630)
ILLUSTRATION_SIZE = (900, 500)


# ---------------------------------------------------------------------
# 色・フォントのユーティリティ
# ---------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    """h: 0-360, s/l: 0-1"""
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return (round((r + m) * 255), round((g + m) * 255), round((b + m) * 255))


def _base_color_for(seed_text: str, accent_color: str | None) -> tuple[int, int, int]:
    """クライアント名（や記事タイトル）から一貫した基準色を作る。accent_colorがあればそれを優先。"""
    if accent_color:
        return _hex_to_rgb(accent_color)
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    hue = int(digest[:4], 16) % 360
    return _hsl_to_rgb(hue, 0.55, 0.48)


def _lighten(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(min(255, round(c + (255 - c) * amount)) for c in rgb)  # type: ignore


def _darken(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(max(0, round(c * (1 - amount))) for c in rgb)  # type: ignore


_FONT_CACHE: dict[tuple[int, str], ImageFont.FreeTypeFont] = {}


def _load_font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    key = (size, weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    if not FONT_PATH.exists():
        # フォントが見つからない場合はPillow同梱のデフォルトにフォールバック
        # （日本語は文字化けするので、必ずfonts/にNotoSansJPを置くこと）
        font = ImageFont.load_default(size=size)
        _FONT_CACHE[key] = font
        return font
    font = ImageFont.truetype(str(FONT_PATH), size)
    try:
        font.set_variation_by_name(weight)
    except Exception:
        pass  # variation非対応フォントの場合はそのまま使う
    _FONT_CACHE[key] = font
    return font


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """日本語向けの簡易折り返し（1文字ずつ幅を測って詰める）。"""
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        width = draw.textlength(trial, font=font)
        if width > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------
# 背景生成
# ---------------------------------------------------------------------

def _gradient_background(size: tuple[int, int], color_top: tuple[int, int, int], color_bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", size, color_top)
    top = Image.new("RGB", (1, h), color_top)
    bottom = Image.new("RGB", (1, h), color_bottom)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = round(color_top[0] * (1 - t) + color_bottom[0] * t)
        g = round(color_top[1] * (1 - t) + color_bottom[1] * t)
        b = round(color_top[2] * (1 - t) + color_bottom[2] * t)
        base.paste((r, g, b), (0, y, w, y + 1))
    return base


def _add_decorative_circles(img: Image.Image, base_color: tuple[int, int, int], seed: str, count: int = 5) -> Image.Image:
    """半透明の円をいくつか散りばめて、単調な背景に奥行きを出す（決定論的に配置）。"""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    for i in range(count):
        chunk = digest[i * 4 : i * 4 + 8] or digest
        val = int(chunk, 16) if chunk else i * 12345
        cx = (val % w)
        cy = ((val // 7) % h)
        radius = 60 + (val % 220)
        alpha = 22 + (val % 30)
        color = _lighten(base_color, 0.25 + (i % 3) * 0.15) if i % 2 == 0 else _darken(base_color, 0.15)
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(*color, alpha),
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(2))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


# ---------------------------------------------------------------------
# 公開関数
# ---------------------------------------------------------------------

def generate_eyecatch(
    title: str,
    output_path: str,
    client_display_name: str = "",
    accent_color: str | None = None,
    category_label: str = "",
) -> str:
    """
    記事のアイキャッチ画像（1200x630）を生成して output_path に保存する。

    Args:
        title: 記事タイトル（画像内に表示される）
        output_path: 保存先ファイルパス（.png または .jpg）
        client_display_name: クライアント名（配色決定・フッター表示に使用）
        accent_color: "#RRGGBB" 形式で色を固定したい場合に指定
        category_label: カテゴリ名など、右上に小さく表示するラベル（任意）

    Returns:
        保存したファイルパス（output_pathと同じ）
    """
    base = _base_color_for(client_display_name or title, accent_color)
    top = _lighten(base, 0.10)
    bottom = _darken(base, 0.25)

    img = _gradient_background(EYECATCH_SIZE, top, bottom)
    img = _add_decorative_circles(img, base, seed=title, count=6)
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = EYECATCH_SIZE

    # 半透明の帯（テキストの可読性確保）
    band_top = h * 0.30
    band_bottom = h * 0.78
    draw.rectangle([0, band_top, w, band_bottom], fill=(0, 0, 0, 90))

    # タイトル
    font_size = 58
    font = _load_font(font_size, "Bold")
    max_text_width = w - 140
    lines = _wrap_text(draw, title, font, max_text_width)
    while len(lines) > 3 and font_size > 32:
        font_size -= 4
        font = _load_font(font_size, "Bold")
        lines = _wrap_text(draw, title, font, max_text_width)
    lines = lines[:3]

    line_height = font_size * 1.4
    total_text_height = line_height * len(lines)
    start_y = (band_top + band_bottom) / 2 - total_text_height / 2

    for i, line in enumerate(lines):
        text_width = draw.textlength(line, font=font)
        x = (w - text_width) / 2
        y = start_y + i * line_height
        # 影
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

    # カテゴリラベル（左上バッジ）
    if category_label:
        badge_font = _load_font(28, "Bold")
        pad_x, pad_y = 22, 12
        text_w = draw.textlength(category_label, font=badge_font)
        badge_w = text_w + pad_x * 2
        badge_h = 28 + pad_y * 2
        draw.rounded_rectangle(
            [50, 50, 50 + badge_w, 50 + badge_h], radius=badge_h / 2,
            fill=(255, 255, 255, 230),
        )
        draw.text((50 + pad_x, 50 + pad_y - 2), category_label, font=badge_font, fill=_darken(base, 0.1))

    # クライアント名（フッター）
    if client_display_name:
        footer_font = _load_font(26, "Regular")
        draw.text((50, h - 70), client_display_name, font=footer_font, fill=(255, 255, 255, 220))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, quality=92)
    return output_path


def generate_section_illustration(
    label: str,
    output_path: str,
    client_display_name: str = "",
    accent_color: str | None = None,
) -> str:
    """
    記事本文に挟む「挿絵」（装飾用の抽象イメージ）を生成する。
    AIによる画像生成は使わず、幾何学模様＋短いラベルのシンプルな構成。

    Args:
        label: 画像内に表示する短いキーワード・見出し（1〜10文字程度推奨）
        output_path: 保存先ファイルパス
        client_display_name: 配色を揃えるためのクライアント名
        accent_color: 色を固定したい場合の "#RRGGBB"

    Returns:
        保存したファイルパス
    """
    base = _base_color_for(client_display_name or label, accent_color)
    top = _lighten(base, 0.35)
    bottom = _lighten(base, 0.05)

    img = _gradient_background(ILLUSTRATION_SIZE, top, bottom)
    img = _add_decorative_circles(img, base, seed=label + "_ill", count=4)
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = ILLUSTRATION_SIZE

    # 中央に幾何学的なアクセント（同心円 + 直線）
    cx, cy = w // 2, h // 2
    for r, alpha in [(140, 60), (100, 90), (60, 130)]:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, alpha), width=4)

    if label:
        font = _load_font(40, "Bold")
        lines = _wrap_text(draw, label, font, w - 120)[:2]
        line_height = 50
        total_h = line_height * len(lines)
        start_y = cy - total_h / 2
        for i, line in enumerate(lines):
            text_width = draw.textlength(line, font=font)
            x = (w - text_width) / 2
            y = start_y + i * line_height
            draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 120))
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, quality=92)
    return output_path


# ---------------------------------------------------------------------
# CrewAI Agent 用ツール
# ---------------------------------------------------------------------

def build_image_tools(client_display_name: str, output_dir: str, accent_color: str | None = None) -> list:
    """編集者エージェントが記事タイトルからアイキャッチ・挿絵を自律生成できるようにするツール。"""

    @tool("generate_eyecatch_image")
    def generate_eyecatch_tool(title: str, category_label: str = "") -> str:
        """
        記事タイトルからアイキャッチ画像（1200x630）をAIを使わずに自動生成し、ローカルに保存する。
        引数:
          title: 記事タイトル
          category_label: 画像左上に表示するカテゴリ名（任意）
        戻り値: 生成した画像のローカルファイルパス
        """
        safe_name = "".join(c if c.isalnum() else "_" for c in title)[:40]
        path = str(Path(output_dir) / f"eyecatch_{safe_name}.png")
        return generate_eyecatch(
            title, path, client_display_name=client_display_name,
            accent_color=accent_color, category_label=category_label,
        )

    @tool("generate_illustration")
    def generate_illustration_tool(label: str) -> str:
        """
        記事本文の途中に挟む挿絵（装飾用の抽象画像）をAIを使わずに自動生成する。
        引数:
          label: 挿絵に表示する短いキーワード（1〜10文字程度）
        戻り値: 生成した画像のローカルファイルパス
        """
        safe_name = "".join(c if c.isalnum() else "_" for c in label)[:40]
        path = str(Path(output_dir) / f"illustration_{safe_name}.png")
        return generate_section_illustration(
            label, path, client_display_name=client_display_name, accent_color=accent_color
        )

    return [generate_eyecatch_tool, generate_illustration_tool]


if __name__ == "__main__":
    # 動作確認用
    out_dir = PROJECT_ROOT / "output" / "_test_images"
    p1 = generate_eyecatch(
        "乾燥肌さんのための正しいスキンケア順番ガイド【2026年最新版】",
        str(out_dir / "eyecatch_test.png"),
        client_display_name="株式会社サンプル",
        category_label="スキンケアコラム",
    )
    p2 = generate_section_illustration(
        "洗顔のポイント", str(out_dir / "illustration_test.png"), client_display_name="株式会社サンプル"
    )
    print("生成しました:", p1, p2)
