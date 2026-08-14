#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이지스피크(EZspeak) OG 썸네일 생성기
====================================

지역 페이지(/region/{slug})마다 고유한 1200x1200 정방형 OG 카드를
og/{slug}.png 로 생성한다. 메인/허브용 카드(og/main.png, og/hub.png)도 함께 만든다.
파일명은 data/slugs.json 의 슬러그를 그대로 쓴다 (페이지가 심는 og:image 경로와 동일).

⚠️ 실행 순서
    1) python3 build_slugs.py            ← data/slugs.json (새 키워드가 생겼을 때)
    2) python3 generate_og_images.py     ← 이 스크립트
    3) 배포                               ← 페이지는 요청 시점에 og/{slug}.png 를 링크한다

    api/region.py(site_lib.py) 는 이미지 존재 여부를 검사하지 않고 URL만 심는다.
    따라서 이 스크립트를 돌리지 않으면 SNS 공유 미리보기가 404가 된다.
    site_lib.py 의 OG_WIDTH/OG_HEIGHT 도 이 파일의 W/H 와 같아야 한다(1200/1200).

레이아웃(정방형 세로 스택)
    상단 블루 바(오렌지 액센트) → 로고 → 이지스피크 / EZspeak → 액센트 룰
    → 상위 지역명 → 지역명(대형·잉크) + 영어회화(블루) → 값제안 밴드 → 도메인

사용법
    python3 generate_og_images.py                 # 없는 것만 생성(skip-if-exists)
    python3 generate_og_images.py --force         # 전체 재생성
    python3 generate_og_images.py --only 신림동,서울특별시   # 특정 키워드만(디자인 확인용)
    python3 generate_og_images.py --limit 50      # 앞에서 N개만(테스트)
    python3 generate_og_images.py --brand-only    # main.png / hub.png 만
    python3 generate_og_images.py --audit         # 전수 텍스트 영역 초과 감사(파일 미기록)

의존성: Pillow (11.x 확인), macOS 기본 한글 폰트 AppleSDGothicNeo.ttc
출력: 팔레트(P, 24색) PNG — 장당 20KB 이하
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# site_lib.py 의 대표 상위지역 선택 로직 / 키워드 로딩 / 슬러그 맵을 그대로 재사용한다.
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)
import site_lib as gp  # noqa: E402

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

OUT_DIRNAME = "og"
OUT_DIR = os.path.join(ROOT_DIR, OUT_DIRNAME)
LOGO_PATH = os.path.join(ROOT_DIR, "logo.png")
INPUT_PATH = gp.DEFAULT_INPUT

W, H = 1200, 1200            # 정방형
PALETTE_COLORS = 24          # 팔레트 색 수 (용량/품질 균형, 정방형은 픽셀이 1.9배)

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

# 지역 타입별 미세 변화 (강조색 / 상단바 오렌지 구간 길이). 타입 라벨 칩은 사용하지 않는다.
TYPE_STYLE = {
    "시":   {"accent": BLUE_DEEP, "bar": 300},
    "군":   {"accent": BLUE_DEEP, "bar": 270},
    "구":   {"accent": BLUE,      "bar": 240},
    "동":   {"accent": BLUE,      "bar": 210},
    "읍":   {"accent": BLUE,      "bar": 180},
    "면":   {"accent": BLUE,      "bar": 150},
    "축약": {"accent": BLUE_DEEP, "bar": 240},
}
DEFAULT_STYLE = {"accent": BLUE, "bar": 220}

VALUE_LINE = "집에서 하는 온라인 어학연수"
FOOTER_LINE = "ezspeak.vercel.app"
BRAND_NAME = "이지스피크"
BRAND_SUB = "EZspeak"

# 정방형 세로 스택 좌표
PAD = 80
CONTENT_W = W - PAD * 2       # 1040 — 모든 텍스트의 최대 폭
CX = W / 2

BAR_H = 12
LOGO_W = 236
LOGO_TOP = 92
HEAD_GAP = 24                 # 로고 → 브랜드명
RULE_W, RULE_H = 60, 6

BAND_H = 78                   # 값 제안 밴드 높이
FOOT_RULE_Y = 1074            # 하단 헤어라인
FOOT_TEXT_Y = 1100

MID_BOTTOM = 1030             # 본문 그룹이 넘으면 안 되는 하한

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


def centered(draw, text, f, y, fill):
    """가운데 정렬 텍스트 아이템."""
    return {"kind": "text", "text": text, "font": f,
            "x": CX - text_w(draw, text, f) / 2, "y": y, "fill": fill}


def draw_items(draw, items):
    for it in items:
        if it["kind"] == "text":
            draw.text((it["x"], it["y"]), it["text"], font=it["font"], fill=it["fill"])
        elif it["kind"] == "band":
            draw.rounded_rectangle(it["rect"], radius=it.get("radius", 18), fill=it["fill"])


def item_boxes(draw, items):
    """감사용: 각 텍스트 아이템의 실제 픽셀 bbox."""
    boxes = []
    for it in items:
        if it["kind"] == "text":
            boxes.append(draw.textbbox((it["x"], it["y"]), it["text"], font=it["font"]))
        elif it["kind"] == "band":
            x0, y0, x1, y1 = it["rect"]
            boxes.append((x0, y0, x1, y1))
    return boxes


def value_band(draw, y):
    """값 제안 밴드(가운데 정렬): 배경 + 문구."""
    fv, _ = fit_font(draw, VALUE_LINE, CONTENT_W - 60, [36, 34, 32, 30, 28], W_SEMI)
    tw = text_w(draw, VALUE_LINE, fv)
    bw = min(tw + 64, CONTENT_W)
    _, vt, _, vb = fv.getbbox(VALUE_LINE)
    return [
        {"kind": "band", "rect": [CX - bw / 2, y, CX + bw / 2, y + BAND_H],
         "radius": BAND_H // 4, "fill": TINT},
        {"kind": "text", "text": VALUE_LINE, "font": fv,
         "x": CX - tw / 2, "y": y + (BAND_H - (vb - vt)) / 2 - vt, "fill": BLUE_DEEP},
    ]


def draw_frame(draw, style):
    """상단 브랜드 바 + 오렌지 액센트 (모든 카드 공통)."""
    draw.rectangle([0, 0, W, BAR_H - 1], fill=BLUE)
    draw.rectangle([0, 0, style["bar"], BAR_H - 1], fill=ORANGE)


def draw_brand_head(draw, img, accent=BLUE, logo_w=LOGO_W, top=LOGO_TOP):
    """상단 브랜드 블록: 로고 + 이지스피크 + EZspeak + 액센트 룰. 블록 하단 y 반환."""
    lg = logo_image(logo_w)
    img.paste(lg, (int(CX - lg.width / 2), int(top)))
    y = top + lg.height + HEAD_GAP

    fb = font(42, W_BOLD)
    draw.text((CX - text_w(draw, BRAND_NAME, fb) / 2, y), BRAND_NAME, font=fb, fill=INK)
    y += line_h(fb) + 2

    fs = font(26, W_MED)
    draw.text((CX - text_w(draw, BRAND_SUB, fs) / 2, y), BRAND_SUB, font=fs, fill=INK3)
    y += line_h(fs) + 22

    draw.rounded_rectangle([CX - RULE_W / 2, y, CX + RULE_W / 2, y + RULE_H],
                           radius=RULE_H // 2, fill=accent)
    return y + RULE_H


def draw_footer(draw):
    draw.rectangle([PAD, FOOT_RULE_Y, W - PAD, FOOT_RULE_Y + 1], fill=LINE)
    ff = font(24, W_MED)
    draw.text((CX - text_w(draw, FOOTER_LINE, ff) / 2, FOOT_TEXT_Y),
              FOOTER_LINE, font=ff, fill=INK3)


def save_palette(img, path):
    """팔레트 PNG 로 저장해 용량을 최소화.

    FASTOCTREE + dither 없음이 같은 색 수에서 MEDIANCUT 대비 약 25% 작다
    (눈으로 구분되는 열화 없음). 미지원 환경에서는 ADAPTIVE 로 폴백.
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

def region_items(draw, keyword, parent, accent, mid_top):
    """본문(상위 지역명 · 제목 · 값 제안) 아이템을 mid_top~MID_BOTTOM 사이에 세로 중앙 정렬.

    긴 지명은 폰트 자동 축소 → 그래도 넘치면 '지역명 / 영어회화' 2줄로 분리한다.
    """
    # 제목: 한 줄로 크게 들어가면 한 줄, 아니면 두 줄
    one_line = "%s 영어회화" % keyword
    f1, s1 = fit_font(draw, one_line, CONTENT_W, [104, 98, 92], W_BOLD)
    two_lines = s1 < 92 or text_w(draw, one_line, f1) > CONTENT_W
    if two_lines:
        ft, _ = fit_font(draw, keyword, CONTENT_W,
                         [136, 124, 112, 100, 92, 84, 76, 68, 60], W_BOLD)
        fsub, _ = fit_font(draw, "영어회화", CONTENT_W, [76, 70, 64], W_BOLD)
        title_h = line_h(ft) + line_h(fsub) - 10
    else:
        ft, fsub = f1, None
        title_h = line_h(ft)

    fp = font(32, W_MED)

    blocks = []
    if parent:
        blocks += [line_h(fp), 24]
    blocks += [title_h, 44, BAND_H]
    total = sum(blocks)

    y = mid_top + max(0, (MID_BOTTOM - mid_top - total) / 2)
    items = []

    if parent:
        ptext = ellipsize(draw, parent, fp, CONTENT_W)
        items.append(centered(draw, ptext, fp, y, INK3))
        y += line_h(fp) + 24

    if two_lines:
        kw_text = ellipsize(draw, keyword, ft, CONTENT_W)
        items.append(centered(draw, kw_text, ft, y, INK))
        y += line_h(ft) - 10
        items.append(centered(draw, "영어회화", fsub, y, BLUE))
        y += line_h(fsub)
    else:
        tw = text_w(draw, one_line, ft)
        x = CX - tw / 2
        items.append({"kind": "text", "text": keyword, "font": ft,
                      "x": x, "y": y, "fill": INK})
        items.append({"kind": "text", "text": "영어회화", "font": ft,
                      "x": x + text_w(draw, keyword + " ", ft), "y": y, "fill": BLUE})
        y += line_h(ft)

    y += 44
    items += value_band(draw, y)
    return items


def render_region_card(keyword, kwtype, parent):
    style = TYPE_STYLE.get(kwtype, DEFAULT_STYLE)
    accent = style["accent"]

    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    draw_frame(draw, style)
    head_bottom = draw_brand_head(draw, img, accent)
    draw_footer(draw)

    draw_items(draw, region_items(draw, keyword, parent, accent, head_bottom + 40))
    return img


# ---------------------------------------------------------------------------
# 메인 / 허브 카드
# ---------------------------------------------------------------------------

def render_center_card(title_main, title_accent, subtitle, bar=300):
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    draw_frame(draw, {"bar": bar})
    head_bottom = draw_brand_head(draw, img, BLUE, logo_w=280, top=104)
    draw_footer(draw)

    full = (title_main + " " + title_accent).strip()
    ft, _ = fit_font(draw, full, CONTENT_W, [92, 84, 78, 72, 66, 60], W_BOLD)
    fs, _ = fit_font(draw, subtitle, CONTENT_W, [40, 36, 33, 30, 28], W_SEMI)

    total = line_h(ft) + 22 + line_h(fs) + 48 + BAND_H
    mid_top = head_bottom + 44
    y = mid_top + max(0, (MID_BOTTOM - mid_top - total) / 2)

    tw = text_w(draw, full, ft)
    x = CX - tw / 2
    if title_main:
        draw.text((x, y), title_main, font=ft, fill=INK)
        x += text_w(draw, title_main + " ", ft)
    draw.text((x, y), title_accent, font=ft, fill=BLUE)
    y += line_h(ft) + 22

    draw.text((CX - text_w(draw, subtitle, fs) / 2, y), subtitle, font=fs, fill=INK3)
    y += line_h(fs) + 48

    draw_items(draw, value_band(draw, y))
    return img


def render_main_card():
    return render_center_card("이지스피크", "영어회화",
                              "아쉬운 영어에서 아, 쉬운 영어로", bar=300)


def render_hub_card():
    return render_center_card("전국 지역별", "영어회화",
                              "우리 동네 영어회화를 시 · 군 · 구 · 읍 · 면 · 동으로", bar=240)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def png_name(keyword):
    """og 파일명 = 슬러그.png (URL 과 1:1). 슬러그 맵에 없으면 즉시 중단한다 —
    한글 파일명으로 조용히 되돌아가면 페이지의 og:image 와 어긋나 404 가 된다."""
    slug = gp.slugs().get(keyword)
    if not slug:
        raise SystemExit("[오류] data/slugs.json 에 없는 키워드: %r "
                         "(python3 build_slugs.py 를 먼저 실행하세요)" % keyword)
    return slug + ".png"


def collect_targets():
    """지역 페이지와 동일한 집합(원본 + 합성 시·도)을 만든다."""
    keywords, keyword_set = gp.load_keywords(INPUT_PATH)
    synth = gp.synthesize_sido(keywords, keyword_set)
    return keywords + synth


def audit(targets):
    """전수 감사: 모든 텍스트/밴드가 안전 영역(좌우 PAD, 상하 헤더·푸터 사이)에 있는지."""
    probe = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(probe)
    head_bottom = draw_brand_head(draw, probe.copy(), BLUE)   # 헤더 높이만 계산
    mid_top = head_bottom + 40

    bad = 0
    for i, kw in enumerate(targets, 1):
        keyword = kw["keyword"]
        parent = gp.representative_parent(kw)
        style = TYPE_STYLE.get(kw.get("type", ""), DEFAULT_STYLE)
        items = region_items(draw, keyword, parent, style["accent"], mid_top)
        for (x0, y0, x1, y1) in item_boxes(draw, items):
            if x0 < PAD - 1 or x1 > W - PAD + 1 or y0 < mid_top - 1 or y1 > FOOT_RULE_Y - 12:
                bad += 1
                print("  [초과] %s | box=(%.0f,%.0f,%.0f,%.0f)" % (keyword, x0, y0, x1, y1))
                break
        if i % 1000 == 0 or i == len(targets):
            print("  감사 %5d / %d  (초과 %d)" % (i, len(targets), bad), flush=True)
    print("=" * 60)
    print(" 텍스트 영역 초과: %d 건 / %d 개" % (bad, len(targets)))
    print("=" * 60)
    return bad


def main():
    ap = argparse.ArgumentParser(description="이지스피크 지역별 OG 썸네일 생성")
    ap.add_argument("--force", action="store_true", help="이미 있어도 다시 생성")
    ap.add_argument("--only", default="", help="쉼표로 구분된 키워드만 생성")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 생성")
    ap.add_argument("--brand-only", action="store_true", help="main/hub 카드만 생성")
    ap.add_argument("--audit", action="store_true", help="전수 텍스트 영역 감사만 수행")
    args = ap.parse_args()

    if not os.path.exists(LOGO_PATH):
        raise SystemExit("[오류] 로고가 없습니다: %s" % LOGO_PATH)

    if args.audit:
        raise SystemExit(1 if audit(collect_targets()) else 0)

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
    print(" 규격         : %dx%d (팔레트 %d색)" % (W, H, PALETTE_COLORS))
    print(" 생성         : %d 장" % made)
    print(" 건너뜀       : %d 장" % skipped)
    print(" 폴더 총 이미지: %d 장" % len(sizes))
    print(" 총 용량      : %.1f MB" % (tot / 1024 / 1024))
    if sizes:
        print(" 평균 용량    : %.1f KB (최소 %.1fKB / 최대 %.1fKB)"
              % (tot / len(sizes) / 1024, min(sizes) / 1024, max(sizes) / 1024))
    print("=" * 60)
    print(" 다음 단계: git push  (배포 후 /region/{slug} 가 og/{slug}.png 를 참조합니다)")


if __name__ == "__main__":
    main()
