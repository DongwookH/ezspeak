#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이지스피크(EZspeak) OG 썸네일 생성기
====================================

지역 SEO 페이지(지역/{keyword}-영어회화.html)마다 고유한 1200x630 OG 카드를
og/{keyword}-영어회화.png 로 생성한다. 메인/허브용 카드(og/main.png, og/hub.png)도 함께 만든다.

⚠️ 실행 순서
    1) python3 generate_og_images.py     ← 반드시 먼저 (이 스크립트)
    2) python3 generate_pages.py         ← 페이지가 og/*.png 를 절대경로로 참조한다

    generate_pages.py 는 이미지 존재 여부를 검사하지 않고 URL만 심는다.
    따라서 이 스크립트를 돌리지 않으면 SNS 공유 미리보기가 404가 된다.

사용법
    python3 generate_og_images.py                 # 없는 것만 생성(skip-if-exists)
    python3 generate_og_images.py --force         # 전체 재생성
    python3 generate_og_images.py --only 신림동,서울특별시   # 특정 키워드만(디자인 확인용)
    python3 generate_og_images.py --limit 50      # 앞에서 N개만(테스트)
    python3 generate_og_images.py --brand-only    # main.png / hub.png 만

의존성: Pillow (11.x 확인), macOS 기본 한글 폰트 AppleSDGothicNeo.ttc
출력: 팔레트(P, 32색) PNG — 장당 10KB 내외
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# generate_pages.py 의 대표 상위지역 선택 로직 / 키워드 로딩을 그대로 재사용한다.
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)
import generate_pages as gp  # noqa: E402

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

OUT_DIRNAME = "og"
OUT_DIR = os.path.join(ROOT_DIR, OUT_DIRNAME)
LOGO_PATH = os.path.join(ROOT_DIR, "logo.png")
INPUT_PATH = gp.DEFAULT_INPUT

W, H = 1200, 630
PALETTE_COLORS = 32          # 팔레트 색 수 (용량/품질 균형)

FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
FONT_FALLBACKS = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/AppleGothic.ttf",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
]
# AppleSDGothicNeo.ttc 인덱스: 0=Regular 2=Medium 4=SemiBold 6=Bold
W_REG, W_MED, W_SEMI, W_BOLD = 0, 2, 4, 6

# 브랜드 색
BLUE = (29, 111, 194)         # --blue   #1D6FC2
BLUE_DEEP = (20, 79, 140)     # --blue-deep #144F8C
TINT = (234, 243, 251)        # --blue-tint #EAF3FB
INK = (23, 33, 43)            # --ink    #17212B
INK3 = (124, 138, 153)        # --ink-3  #7C8A99
ORANGE = (240, 129, 30)       # --orange #F0811E
LINE = (226, 235, 244)
WHITE = (255, 255, 255)

# 지역 타입별 미세 변화 (칩 접미사 / 강조색 / 상단바 오렌지 구간 길이)
TYPE_STYLE = {
    "시":   {"chip": " · 시",  "accent": BLUE_DEEP, "bar": 260},
    "군":   {"chip": " · 군",  "accent": BLUE_DEEP, "bar": 230},
    "구":   {"chip": " · 구",  "accent": BLUE,      "bar": 200},
    "동":   {"chip": " · 동",  "accent": BLUE,      "bar": 170},
    "읍":   {"chip": " · 읍",  "accent": BLUE,      "bar": 140},
    "면":   {"chip": " · 면",  "accent": BLUE,      "bar": 115},
    "축약": {"chip": "",       "accent": BLUE_DEEP, "bar": 200},
}
DEFAULT_STYLE = {"chip": "", "accent": BLUE, "bar": 180}

CHIP_BASE = "온라인 영어회화"
VALUE_LINE = "온라인 1:1 원어민 수업 · 무료 레벨테스트"
FOOTER_LINE = "ezspeak.vercel.app"
BRAND_NAME = "이지스피크"
BRAND_SUB = "EZspeak"

# 좌측 텍스트 컬럼
PAD_L = 76
COL_W = 700              # 좌측 컬럼 최대 폭 (우측 브랜드 영역 침범 금지)
DIVIDER_X = 852          # 좌/우 구분선
RIGHT_CX = 1012          # 우측 브랜드 영역 중심 x

# ---------------------------------------------------------------------------
# 폰트 / 로고
# ---------------------------------------------------------------------------

_font_cache = {}
_font_file = None


def _resolve_font():
    global _font_file
    if _font_file:
        return _font_file
    for p in [FONT_PATH] + FONT_FALLBACKS:
        if os.path.exists(p):
            _font_file = p
            return p
    raise SystemExit("[오류] 한글 폰트를 찾을 수 없습니다: %s" % FONT_PATH)


def font(size, weight=W_BOLD):
    key = (size, weight)
    f = _font_cache.get(key)
    if f is None:
        path = _resolve_font()
        try:
            f = ImageFont.truetype(path, size, index=weight)
        except Exception:
            f = ImageFont.truetype(path, size)
        _font_cache[key] = f
    return f


_logo_cache = {}


def logo_image(target_w):
    """logo.png 를 흰 여백/그림자 제거 후 target_w 폭으로 리사이즈해 캐시."""
    im = _logo_cache.get(target_w)
    if im is not None:
        return im
    src = Image.open(LOGO_PATH).convert("RGB")
    # 흰 배경 대비 임계값으로 내용 영역만 잘라낸다.
    # 임계값 210: 로고 하단의 옅은 회색 그림자 타원(≈235)을 제외하고 마크+워드마크만 남긴다.
    gray = src.convert("L")
    mask = gray.point(lambda p: 255 if p < 210 else 0)
    bbox = mask.getbbox() or (0, 0, src.width, src.height)
    src = src.crop(bbox)
    h = max(1, round(src.height * target_w / src.width))
    im = src.resize((target_w, h), Image.LANCZOS)
    _logo_cache[target_w] = im
    return im


# ---------------------------------------------------------------------------
# 그리기 헬퍼
# ---------------------------------------------------------------------------

def text_w(draw, text, f):
    return draw.textlength(text, font=f)


def fit_font(draw, text, max_w, sizes, weight=W_BOLD):
    """max_w 안에 들어가는 가장 큰 폰트를 고른다(클리핑 방지)."""
    for s in sizes:
        f = font(s, weight)
        if text_w(draw, text, f) <= max_w:
            return f, s
    return font(sizes[-1], weight), sizes[-1]


def ellipsize(draw, text, f, max_w):
    """최소 크기로도 넘칠 때의 최후 안전장치."""
    if text_w(draw, text, f) <= max_w:
        return text
    s = text
    while s and text_w(draw, s + "…", f) > max_w:
        s = s[:-1]
    return (s + "…") if s else ""


def line_h(f):
    a, d = f.getmetrics()
    return a + d


def draw_chip(draw, x, y, text, fg, bg=TINT, fsize=25, pad_x=22, h=48):
    f = font(fsize, W_SEMI)
    w = text_w(draw, text, f) + pad_x * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg)
    _, top, _, bottom = f.getbbox(text)
    draw.text((x + pad_x, y + (h - (bottom - top)) / 2 - top), text, font=f, fill=fg)
    return w, h


def draw_frame(draw, style):
    """상단 브랜드 바 + 좌/우 구분선 (모든 카드 공통)."""
    draw.rectangle([0, 0, W, 11], fill=BLUE)
    draw.rectangle([0, 0, style["bar"], 11], fill=ORANGE)


def draw_brand_column(draw, img, logo_w=230, cx=RIGHT_CX, top=176):
    """우측 브랜드 배지: 로고 + 이지스피크 + EZspeak."""
    lg = logo_image(logo_w)
    img.paste(lg, (int(cx - lg.width / 2), int(top)))
    y = top + lg.height + 26
    fb = font(36, W_BOLD)
    draw.text((cx - text_w(draw, BRAND_NAME, fb) / 2, y), BRAND_NAME, font=fb, fill=INK)
    y += 50
    fs = font(24, W_MED)
    draw.text((cx - text_w(draw, BRAND_SUB, fs) / 2, y), BRAND_SUB, font=fs, fill=INK3)
    y += 42
    draw.rounded_rectangle([cx - 26, y, cx + 26, y + 5], radius=3, fill=BLUE)


def draw_footer(draw, right_text=None):
    draw.rectangle([PAD_L, 543, W - PAD_L, 544], fill=LINE)
    ff = font(23, W_MED)
    draw.text((PAD_L, 566), FOOTER_LINE, font=ff, fill=INK3)
    if right_text:
        draw.text((W - PAD_L - text_w(draw, right_text, ff), 566), right_text,
                  font=ff, fill=INK3)


def save_palette(img, path):
    """팔레트 PNG 로 저장해 용량을 최소화.

    FASTOCTREE + dither 없음이 같은 32색에서 MEDIANCUT 대비 약 25% 작다
    (18.5KB -> 13.6KB, 눈으로 구분되는 열화 없음). 미지원 환경에서는 ADAPTIVE 로 폴백.
    """
    try:
        q = img.quantize(colors=PALETTE_COLORS, method=Image.Quantize.FASTOCTREE,
                         dither=Image.Dither.NONE)
    except Exception:
        q = img.convert("P", palette=Image.ADAPTIVE, colors=PALETTE_COLORS)
    q.save(path, optimize=True)


# ---------------------------------------------------------------------------
# 지역 카드
# ---------------------------------------------------------------------------

def render_region_card(keyword, kwtype, parent):
    style = TYPE_STYLE.get(kwtype, DEFAULT_STYLE)
    accent = style["accent"]

    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    draw_frame(draw, style)
    draw.rectangle([DIVIDER_X, 150, DIVIDER_X + 1, 470], fill=LINE)
    draw_brand_column(draw, img)
    draw_footer(draw, "무료 레벨테스트")

    # ---- 제목: 한 줄로 크게 들어가면 한 줄, 아니면 두 줄 ----
    one_line = "%s 영어회화" % keyword
    f1, s1 = fit_font(draw, one_line, COL_W, [96, 92, 88], W_BOLD)
    two_lines = s1 < 88 or text_w(draw, one_line, f1) > COL_W
    if two_lines:
        ft, _ = fit_font(draw, keyword, COL_W, [116, 108, 100, 92, 84, 76, 68, 60], W_BOLD)
        fsub, _ = fit_font(draw, "영어회화", COL_W, [64, 58, 52], W_BOLD)
        title_h = line_h(ft) + line_h(fsub) - 6
    else:
        ft, fsub = f1, None
        title_h = line_h(ft)

    # ---- 블록 높이 계산 후 세로 중앙 정렬(클리핑 방지) ----
    chip_text = CHIP_BASE + style["chip"]
    fp = font(30, W_MED)
    fv, _ = fit_font(draw, VALUE_LINE, COL_W - 44, [32, 30, 28, 26, 24], W_SEMI)

    blocks = [48, 30, title_h]                    # 칩, 간격, 제목
    if parent:
        blocks += [22, line_h(fp)]                # 간격, 상위 지역
    blocks += [26, 64]                            # 간격, 값 제안 밴드
    total = sum(blocks)

    top_bound, bottom_bound = 92, 516
    y = top_bound + max(0, (bottom_bound - top_bound - total) / 2)

    draw_chip(draw, PAD_L, y, chip_text, accent)
    y += 48 + 30

    if two_lines:
        draw.text((PAD_L, y), keyword, font=ft, fill=INK)
        y += line_h(ft) - 6
        draw.text((PAD_L, y), "영어회화", font=fsub, fill=BLUE)
        y += line_h(fsub)
    else:
        draw.text((PAD_L, y), keyword, font=ft, fill=INK)
        off = text_w(draw, keyword + " ", ft)
        draw.text((PAD_L + off, y), "영어회화", font=ft, fill=BLUE)
        y += line_h(ft)

    if parent:
        y += 22
        draw.rounded_rectangle([PAD_L, y + 8, PAD_L + 6, y + 34], radius=3, fill=accent)
        ptext = ellipsize(draw, parent, fp, COL_W - 22)
        draw.text((PAD_L + 22, y), ptext, font=fp, fill=INK3)
        y += line_h(fp)

    y += 26
    vw = text_w(draw, VALUE_LINE, fv) + 44
    draw.rounded_rectangle([PAD_L, y, PAD_L + min(vw, COL_W), y + 64], radius=14, fill=TINT)
    _, vt, _, vb = fv.getbbox(VALUE_LINE)
    draw.text((PAD_L + 22, y + (64 - (vb - vt)) / 2 - vt), VALUE_LINE, font=fv, fill=BLUE_DEEP)

    return img


# ---------------------------------------------------------------------------
# 메인 / 허브 카드 (가운데 정렬 변형)
# ---------------------------------------------------------------------------

def render_center_card(title_main, title_accent, subtitle, chip_text, bar=260):
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    draw_frame(draw, {"bar": bar})
    draw_footer(draw, "무료 레벨테스트")

    cx = W / 2
    lg = logo_image(300)
    img.paste(lg, (int(cx - lg.width / 2), 74))
    y = 74 + lg.height + 26

    # 칩
    fc = font(25, W_SEMI)
    cw = text_w(draw, chip_text, fc) + 44
    draw.rounded_rectangle([cx - cw / 2, y, cx + cw / 2, y + 48], radius=24, fill=TINT)
    _, ct, _, cb = fc.getbbox(chip_text)
    draw.text((cx - text_w(draw, chip_text, fc) / 2, y + (48 - (cb - ct)) / 2 - ct),
              chip_text, font=fc, fill=BLUE_DEEP)
    y += 48 + 26

    # 제목 (앞부분 잉크 + 강조 파랑)
    full = (title_main + " " + title_accent).strip()
    ft, _ = fit_font(draw, full, W - 160, [78, 72, 66, 60, 54], W_BOLD)
    tw = text_w(draw, full, ft)
    x = cx - tw / 2
    if title_main:
        draw.text((x, y), title_main, font=ft, fill=INK)
        x += text_w(draw, title_main + " ", ft)
    draw.text((x, y), title_accent, font=ft, fill=BLUE)
    y += line_h(ft) + 6

    # 슬로건
    fs, _ = fit_font(draw, subtitle, W - 200, [38, 34, 30, 28], W_SEMI)
    draw.text((cx - text_w(draw, subtitle, fs) / 2, y), subtitle, font=fs, fill=BLUE_DEEP)

    return img


def render_main_card():
    return render_center_card("이지스피크", "영어회화",
                              "아쉬운 영어에서 아, 쉬운 영어로",
                              "온라인 1:1 원어민 수업 · 무료 레벨테스트", bar=260)


def render_hub_card():
    return render_center_card("전국 지역별", "영어회화",
                              "우리 동네 영어회화를 시 · 군 · 구 · 읍 · 면 · 동으로",
                              "온라인 1:1 원어민 수업 · 무료 레벨테스트", bar=200)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def png_name(keyword):
    return keyword + "-영어회화.png"


def collect_targets():
    """generate_pages.py 와 동일한 페이지 집합(원본 + 합성 시·도)을 만든다."""
    keywords, keyword_set = gp.load_keywords(INPUT_PATH)
    synth = gp.synthesize_sido(keywords, keyword_set)
    return keywords + synth


def main():
    ap = argparse.ArgumentParser(description="이지스피크 지역별 OG 썸네일 생성")
    ap.add_argument("--force", action="store_true", help="이미 있어도 다시 생성")
    ap.add_argument("--only", default="", help="쉼표로 구분된 키워드만 생성")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 생성")
    ap.add_argument("--brand-only", action="store_true", help="main/hub 카드만 생성")
    args = ap.parse_args()

    if not os.path.exists(LOGO_PATH):
        raise SystemExit("[오류] 로고가 없습니다: %s" % LOGO_PATH)
    os.makedirs(OUT_DIR, exist_ok=True)

    made = skipped = 0

    # 메인 / 허브
    for name, renderer in (("main.png", render_main_card), ("hub.png", render_hub_card)):
        path = os.path.join(OUT_DIR, name)
        if args.force or not os.path.exists(path):
            save_palette(renderer(), path)
            made += 1
        else:
            skipped += 1

    if not args.brand_only:
        targets = collect_targets()
        if args.only:
            want = {s.strip() for s in args.only.split(",") if s.strip()}
            targets = [k for k in targets if k["keyword"] in want]
            missing = want - {k["keyword"] for k in targets}
            if missing:
                print("[경고] regions.json 에 없는 키워드: %s" % ", ".join(sorted(missing)))
        if args.limit:
            targets = targets[:args.limit]

        total = len(targets)
        for i, kw in enumerate(targets, 1):
            keyword = kw["keyword"]
            path = os.path.join(OUT_DIR, png_name(keyword))
            if os.path.exists(path) and not args.force:
                skipped += 1
            else:
                parent = gp.representative_parent(kw)
                save_palette(render_region_card(keyword, kw.get("type", ""), parent), path)
                made += 1
            if i % 250 == 0 or i == total:
                print("  진행 %5d / %d  (생성 %d · 건너뜀 %d)" % (i, total, made, skipped),
                      flush=True)

    # 요약
    sizes = [os.path.getsize(os.path.join(OUT_DIR, f))
             for f in os.listdir(OUT_DIR) if f.endswith(".png")]
    tot = sum(sizes)
    print("=" * 60)
    print(" 출력 폴더    : %s" % OUT_DIR)
    print(" 생성         : %d 장" % made)
    print(" 건너뜀       : %d 장" % skipped)
    print(" 폴더 총 이미지: %d 장" % len(sizes))
    print(" 총 용량      : %.1f MB" % (tot / 1024 / 1024))
    if sizes:
        print(" 평균 용량    : %.1f KB (최소 %.1fKB / 최대 %.1fKB)"
              % (tot / len(sizes) / 1024, min(sizes) / 1024, max(sizes) / 1024))
    print("=" * 60)
    print(" 다음 단계: python3 generate_pages.py  (페이지에 og/*.png 링크가 심어집니다)")


if __name__ == "__main__":
    main()
