#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
/textbooks  교재 전체 목록 페이지 (Vercel Python 서버리스 함수)
=====================================================================

vercel.json 리라이트
  /textbooks, /textbooks/  -> /api/textbooks
  (/textbooks/lib/... 같은 실제 이미지 파일은 정적 서빙 — 리라이트 대상 아님)

데이터는 api/_data/textbooks.json. 파일이 없거나 비었거나 깨져도 예외 없이
"교재 정보를 준비 중입니다" 페이지를 200 으로 낸다.
api/guide.py 와 동일한 핸들러/캐시 구조, 헤더·푸터·공통 CSS·JSON-LD 는 site_lib 재사용.

표기 규칙 (사용자 결정 사항)
  type=self        -> "이지스피크 자체 제작" 라벨
  type=partner     -> "출판: {publisher}" 필수, 자체 제작 라벨 금지
  type=unverified  -> 라벨 없음 (그 외 알 수 없는 type 도 같은 취급)
  exclude=true     -> 렌더하지 않음
"""

import os
import sys
import json
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_lib as S  # noqa: E402

CACHE_OK = "public, max-age=0, s-maxage=86400, stale-while-revalidate=604800"
CACHE_404 = "public, max-age=0, s-maxage=300"

TB_PREFIX = "/textbooks"
TB_CANONICAL = S.BASE_URL + TB_PREFIX
TB_LABEL = "교재"
DATA_PATH = os.path.join(S.DATA_DIR, "textbooks.json")

# 상담 CTA 유입 슬러그 — /?from=textbooks#contact
SRC = "textbooks"

TYPE_ORDER = {"self": 0, "partner": 1}  # 나머지(unverified 등)는 2

# 필터 값과 표시 순서 (textbooks.json 의 levels / purposes 가 이 목록 안에서만 쓰인다)
LEVELS = ["입문", "초급", "중급", "고급"]
PURPOSES = ["일상회화", "비즈니스", "여행", "유학·어학연수", "시사·토론", "문법·어휘", "쓰기", "말하기 시험", "키즈·주니어", "중등 내신"]
TYPES = [("self", "이지스피크 자체 제작"), ("partner", "수업에 함께 쓰는 교재")]


def _vals(b, key, allowed):
    """책의 levels / purposes 중 허용 값만, 표시 순서대로."""
    got = b.get(key) or []
    return [v for v in allowed if v in got]


def load_data():
    """(updated, [(group_id, group_name, [book, ...]), ...]) — 책이 있는 그룹만, 그룹 순서 유지.
    파일 없음·빈 파일·형식 오류 모두 ("", []) 로 흡수한다."""
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return "", []
    if not isinstance(data, dict):
        return "", []

    order = []
    names = {}
    for g in data.get("groups") or []:
        if isinstance(g, dict) and g.get("id") and g["id"] not in names:
            order.append(g["id"])
            names[g["id"]] = g.get("name") or g["id"]

    buckets = {}
    for b in data.get("books") or []:
        if not isinstance(b, dict) or b.get("exclude") or not b.get("name"):
            continue
        # 대표 과정(group) + 추가 과정(also_groups) 모두에 카드를 둔다 — 레귤러·이머전처럼
        # 여러 과정에서 쓰는 책이 한쪽 섹션에만 보이지 않도록
        gids = []
        for gid in [b.get("group")] + list(b.get("also_groups") or []):
            if gid not in names:
                gid = "etc"
                if gid not in names:
                    order.append(gid)
                    names[gid] = "기타"
            if gid not in gids:
                gids.append(gid)
        for gid in gids:
            buckets.setdefault(gid, []).append(b)

    groups = []
    for gid in order:
        books = buckets.get(gid)
        if books:
            books.sort(key=lambda b: TYPE_ORDER.get(b.get("type"), 2))  # 안정 정렬: 데이터 순서 유지
            groups.append((gid, names[gid], books))
    return str(data.get("updated") or ""), groups


def book_label(b):
    """카드 라벨 HTML. partner 는 publisher 가 비어도 '출판:' 을 붙이지 않는다(지어내지 않기)."""
    t = b.get("type")
    if t == "self":
        return '<span class="tb-tag tb-tag--self">이지스피크 자체 제작</span>'
    if t == "partner" and b.get("publisher"):
        return '<p class="tb-pub">출판: %s</p>' % S.esc(b["publisher"])
    return ""


def _abs(src):
    return S.BASE_URL + src if src.startswith("/") else src


ARROW = ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
         'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="%s"></polyline></svg>')


def _shot(src, w, h, alt, lazy):
    """스테이지 한 장. 링크라서 JS 가 없어도 원본이 열리고, JS 가 있으면 확대 보기로 가로챈다."""
    size = ' width="%d" height="%d"' % (int(w), int(h)) if w and h else ""
    return ('<li class="stage-item"><a class="tb-shot" href="%s"><img class="tb-img" src="%s"%s%s decoding="async" alt="%s"></a></li>'
            % (S.esc(src), S.esc(src), size, ' loading="lazy"' if lazy else "", S.esc(alt)))


def book_stage(b, group_name, eager=False):
    """교재 이미지 스테이지(메인 index.html 과 같은 마크업·클래스): 한 번에 1장 크게, 좌우로 넘김.
    eager=True 면 첫 화면 카드라 표지만 즉시 로드, 나머지는 전부 lazy."""
    name = b["name"]
    shots = []  # (src, w, h, alt, 탭 이름)
    cover = b.get("cover") or {}
    if cover.get("src"):
        shots.append((cover["src"], cover.get("w"), cover.get("h"), "%s %s 표지" % (group_name, name), "표지"))
    pages = [p for p in (b.get("pages") or []) if isinstance(p, dict) and p.get("src")]
    for i, p in enumerate(pages, start=1):
        shots.append((p["src"], p.get("w"), p.get("h"), "%s %s 속지 %d" % (group_name, name, i), "속지 %d" % i))
    if not shots:
        return ""
    items = "".join(_shot(src, w, h, alt, not (eager and k == 0)) for k, (src, w, h, alt, _) in enumerate(shots))
    tabs = "".join('<button type="button" aria-current="%s">%s</button>' % ("true" if k == 0 else "false", cap)
                   for k, (_, _, _, _, cap) in enumerate(shots))
    return f"""<div class="stage" tabindex="0" aria-roledescription="carousel" aria-label="{S.esc(name)} 표지·속지 보기">
                            <div class="stage-view">
                                <ul class="stage-track">{items}</ul>
                                <button type="button" class="stage-arrow stage-prev" aria-label="이전 이미지">{ARROW % "15 18 9 12 15 6"}</button>
                                <button type="button" class="stage-arrow stage-next" aria-label="다음 이미지">{ARROW % "9 18 15 12 9 6"}</button>
                            </div>
                            <div class="stage-bar"><div class="stage-tabs">{tabs}</div><span class="stage-count" aria-live="polite">1 / {len(shots)}</span></div>
                        </div>"""


# 여러 과정에 걸친 책은 섹션마다 카드가 있지만 id 는 첫 카드에만 (HTML id 중복 방지)
_ID_SEEN = set()


def book_card(b, group_name, eager=False):
    name = b["name"]
    gallery = book_stage(b, group_name, eager)

    en = ' <span class="en">%s</span>' % S.esc(b["name_en"]) if b.get("name_en") else ""
    meta = []
    if b.get("audience"):
        meta.append("<div><dt>대상</dt><dd>%s</dd></div>" % S.esc(b["audience"]))
    if b.get("series"):
        meta.append("<div><dt>구성</dt><dd>%s</dd></div>" % S.esc(b["series"]))
    levels, purposes = _vals(b, "levels", LEVELS), _vals(b, "purposes", PURPOSES)
    if levels:
        meta.append("<div><dt>레벨</dt><dd>%s</dd></div>" % S.esc(" · ".join(levels)))
    if purposes:
        meta.append("<div><dt>목적</dt><dd>%s</dd></div>" % S.esc(" · ".join(purposes)))
    meta_html = '<dl class="tb-meta">%s</dl>' % "".join(meta) if meta else ""
    desc = '<p class="tb-desc">%s</p>' % S.esc(b["description"]) if b.get("description") else ""

    slug = S.esc(b.get("slug") or "")
    first = bool(slug) and slug not in _ID_SEEN
    if first:
        _ID_SEEN.add(slug)
    # 필터용 데이터(쉼표 구분 — "말하기 시험" 처럼 값에 공백이 있다)
    data = ' data-slug="%s" data-type="%s" data-levels="%s" data-purposes="%s"' % (
        slug, S.esc(b.get("type") or ""), S.esc(",".join(levels)), S.esc(",".join(purposes)))
    return f"""                    <li class="tb-card"{' id="book-%s"' % slug if first else ''}{data}>
                        <div class="tb-body">
                            {book_label(b)}
                            <h3 class="tb-name">{S.esc(name)}{en}</h3>
                            {meta_html}
                            {desc}
                        </div>
                        {gallery}
                    </li>"""


def book_ld(b):
    node = {"@type": "Book", "name": b["name"]}
    if b.get("name_en"):
        node["alternateName"] = b["name_en"]
    if (b.get("cover") or {}).get("src"):
        node["image"] = _abs(b["cover"]["src"])
    if b.get("description"):
        node["description"] = b["description"]
    if b.get("slug"):
        node["url"] = TB_CANONICAL + "#book-" + b["slug"]
    t = b.get("type")
    if t == "self":
        # build_jsonld 의 WebPage 와 같은 규약: 자체 저작물은 author/publisher 모두 사업자 @id
        node["author"] = {"@id": S.BASE_URL + "/#business"}
        node["publisher"] = {"@id": S.BASE_URL + "/#business"}
    elif t == "partner" and b.get("publisher"):
        node["publisher"] = {"@type": "Organization", "name": b["publisher"]}
    levels, purposes = _vals(b, "levels", LEVELS), _vals(b, "purposes", PURPOSES)
    if levels:
        node["educationalLevel"] = ", ".join(levels)
    if purposes:
        node["keywords"] = ", ".join(purposes)
    return node


# 교재 페이지 전용 스타일 — 공용 토큰만 사용. guide.py 와 같은 이유로 인라인
# (style.css 는 1년 immutable 캐시라 자산 버전 무효화 없이 쓰려고).
TB_INLINE_CSS = """    <style>
        .tb-nav { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 24px; }
        .tb-nav a.pill { text-decoration: none; transition: border-color .16s, color .16s, background-color .16s; }
        .tb-nav a.pill:hover { border-color: var(--blue); color: var(--blue); background: var(--blue-tint); }
        .tb-group { scroll-margin-top: calc(var(--header-h) + 16px); }
        .tb-group:not([hidden]) ~ .tb-group { padding-top: 0; }  /* 앞에 보이는 과정이 있을 때만 붙여 쌓기 */
        .tb-group h2 { font-weight: 800; font-size: clamp(21px, 3.2vw, 28px); letter-spacing: -.02em;
            color: var(--ink); word-break: keep-all; }
        .tb-grid { list-style: none; padding: 0; margin: 20px 0 0; display: grid; gap: 18px; }
        /* 카드 = [설명 | 큰 이미지 스테이지]. 한 줄 1권 */
        .tb-card { display: grid; grid-template-columns: 280px minmax(0, 1fr); background: #fff;
            border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden;
            scroll-margin-top: calc(var(--header-h) + 16px); }
        .tb-body { padding: 20px 20px 22px; display: flex; flex-direction: column; gap: 8px; }
        .tb-card > .stage { padding: 16px; border-left: 1px solid var(--line); border-radius: 0; }
        .tb-shot { display: block; width: 100%; height: 100%; cursor: zoom-in; border-radius: var(--r-sm); }
        .tb-shot:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
        .tb-img { display: block; width: 100%; height: 100%; object-fit: contain; }
        /* 교재 이미지 스테이지 — 메인 style.css 의 .stage 와 같은 규칙(이 페이지는 자산 캐시 때문에 인라인) */
        .stage { min-width: 0; }
        .stage:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
        .stage-view { position: relative; overflow: hidden; overflow: clip; background: #F3F6FA; border: 1px solid var(--line-2);
            border-radius: var(--r-md); touch-action: pan-y; }
        .stage-track { list-style: none; margin: 0; padding: 0; display: flex; transition: transform .35s ease; }
        .stage-item { flex: 0 0 100%; min-width: 0; height: 520px; padding: 16px 64px;
            display: flex; align-items: center; justify-content: center; }  /* 좌우 64px = 화살표 자리 */
        .stage-item > a { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; }
        /* max-width/max-height 로 가두어야 세로형 표지도 잘리지 않는다 */
        .stage-item .tb-img { width: auto; height: auto; max-width: 100%; max-height: 100%; }
        .stage-arrow { position: absolute; top: 50%; transform: translateY(-50%); width: 44px; height: 44px;
            border: 0; border-radius: 50%; background: rgba(15, 23, 42, .45); color: #fff;
            display: grid; place-items: center; cursor: pointer; transition: background-color .16s; }
        .stage-arrow:hover { background: rgba(15, 23, 42, .7); }
        .stage-arrow:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
        .stage-prev { left: 10px; }
        .stage-next { right: 10px; }
        .stage-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; }
        .stage-tabs { display: flex; flex-wrap: wrap; gap: 6px; }
        .stage-tabs button { font: 600 13px var(--font-body); color: var(--ink-2); background: #fff; cursor: pointer;
            border: 1px solid var(--line); border-radius: var(--r-pill); padding: 5px 12px; }
        .stage-tabs button:hover { border-color: var(--blue); color: var(--blue); }
        .stage-tabs button[aria-current="true"] { background: var(--blue); border-color: var(--blue); color: #fff; }
        .stage-count { font-size: 13px; font-weight: 600; color: var(--ink-3); font-variant-numeric: tabular-nums; }
        @media (prefers-reduced-motion: reduce) { .stage-track { transition: none; } }
        .tb-tag { align-self: flex-start; font-size: 12.5px; font-weight: 700; color: var(--blue);
            background: var(--blue-tint); border-radius: var(--r-pill); padding: 3px 10px; }
        .tb-pub { margin: 0; font-size: 13.5px; font-weight: 600; color: var(--blue-deep); word-break: keep-all; }
        .tb-name { margin: 0; font-weight: 800; font-size: 18px; color: var(--ink); letter-spacing: -.02em; word-break: keep-all; }
        .tb-name .en { display: block; font-weight: 600; font-size: 13px; color: var(--ink-3); margin-top: 2px; letter-spacing: 0; }
        .tb-meta { margin: 0; display: grid; gap: 2px; font-size: 13.5px; line-height: 1.6; }
        .tb-meta div { display: flex; gap: 8px; }
        .tb-meta dt { flex: 0 0 auto; color: var(--ink-3); font-weight: 700; }
        .tb-meta dd { margin: 0; color: var(--ink-2); word-break: keep-all; }
        .tb-desc { margin: 0; font-size: 14px; color: var(--ink-2); line-height: 1.65; word-break: keep-all; }
        @media (max-width: 860px) {
            .tb-card { grid-template-columns: 1fr; }
            .tb-card > .stage { border-left: 0; border-top: 1px solid var(--line); }
            .stage-item { height: 440px; }
        }
        @media (max-width: 560px) {
            .tb-card > .stage { padding: 12px; }
            .stage-item { height: 440px; padding: 8px; }
            .stage-arrow { width: 36px; height: 36px; }
            .stage-prev { left: 6px; }
            .stage-next { right: 6px; }
        }
        html:has(.tb-lb[open]) { overflow: hidden; }
        .tb-lb { width: 100%; height: 100%; max-width: none; max-height: none; margin: 0; padding: 56px 64px 20px;
            border: 0; background: transparent; color: #fff; }
        .tb-lb::backdrop { background: rgba(10, 22, 38, .88); }
        .tb-lb[open] { display: flex; align-items: center; justify-content: center; }
        .tb-lb figure { margin: 0; display: flex; flex-direction: column; align-items: center; gap: 12px; max-height: 100%; }
        .tb-lb img { display: block; width: auto; height: auto; max-width: min(100%, 1000px);
            max-height: calc(100vh - 120px); max-height: calc(100dvh - 120px); background: #fff; border-radius: var(--r-sm); }
        .tb-lb figcaption { font-size: 14px; font-weight: 600; text-align: center; word-break: keep-all; }
        .tb-lb button { position: absolute; display: grid; place-items: center; width: 44px; height: 44px;
            border: 0; border-radius: var(--r-pill); background: rgba(255, 255, 255, .14); color: #fff;
            font: inherit; font-size: 26px; line-height: 1; cursor: pointer; }
        .tb-lb button:hover { background: rgba(255, 255, 255, .26); }
        .tb-lb button:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
        .tb-lb-close { top: 10px; right: 12px; }
        .tb-lb-prev { left: 10px; top: 50%; transform: translateY(-50%); }
        .tb-lb-next { right: 10px; top: 50%; transform: translateY(-50%); }
        .tb-lb button[hidden] { display: none; }
        @media (max-width: 560px) {
            .tb-lb { padding: 56px 8px 72px; }
            .tb-lb-prev, .tb-lb-next { top: auto; bottom: 14px; transform: none; }
            .tb-lb-prev { left: calc(50% - 54px); }
            .tb-lb-next { right: calc(50% - 54px); }
        }
        .tb-empty { color: var(--ink-2); font-size: 16px; }
        /* 필터 바 — JS 가 hidden 을 풀 때만 보인다(JS 없으면 전체 카드 그대로) */
        .tb-filter { margin-top: 24px; display: grid; gap: 8px; }
        .tb-frow { display: flex; align-items: flex-start; gap: 10px; }
        .tb-flabel { flex: 0 0 34px; padding-top: 6px; font-size: 13px; font-weight: 700; color: var(--ink-3); }
        .tb-fopts { display: flex; flex-wrap: wrap; gap: 6px; min-width: 0; }
        .tb-fopts button, .tb-none button { font: 600 13px var(--font-body); color: var(--ink-2); background: #fff; cursor: pointer;
            border: 1px solid var(--line); border-radius: var(--r-pill); padding: 5px 12px;
            transition: border-color .16s, color .16s, background-color .16s; }
        .tb-fopts button:hover { border-color: var(--blue); color: var(--blue); }
        .tb-fopts button[aria-pressed="true"] { background: var(--blue); border-color: var(--blue); color: #fff; }
        .tb-fopts button:focus-visible, .tb-none button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
        .tb-count { margin: 4px 0 0; font-size: 14px; font-weight: 700; color: var(--ink); }
        .tb-filter[hidden], .tb-card[hidden], .tb-group[hidden], .tb-nav a[hidden], .tb-none[hidden] { display: none; }
        .tb-none { margin-bottom: clamp(32px, 5vw, 56px); display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 48px 20px;
            border: 1px dashed var(--line); border-radius: var(--r-lg); background: #fff; text-align: center; }
        .tb-none p { margin: 0; font-size: 15px; color: var(--ink-2); }
        .tb-none button { color: var(--blue); border-color: var(--blue); padding: 7px 14px; }
        .tb-none button:hover { background: var(--blue); color: #fff; }
    </style>"""


# 표지·속지 확대 보기 — 네이티브 <dialog> + 최소 JS. ESC·닫기 버튼·배경 클릭으로 닫힘, 좌우 화살표로 넘김.
# smooth 스크롤 금지(임베디드 미리보기에서 끝나지 않는 버그 이력) — 스크롤 코드는 아예 없다.
TB_LIGHTBOX = """    <dialog class="tb-lb" id="tb-lb" aria-label="교재 이미지 크게 보기">
        <button type="button" class="tb-lb-close" aria-label="닫기">&times;</button>
        <button type="button" class="tb-lb-prev" aria-label="이전 이미지">&lsaquo;</button>
        <figure><img id="tb-lb-img" alt=""><figcaption id="tb-lb-cap"></figcaption></figure>
        <button type="button" class="tb-lb-next" aria-label="다음 이미지">&rsaquo;</button>
    </dialog>
    <script>
        /* 교재 이미지 스테이지 — 메인 script.js 의 initStage 와 같은 동작(transform 방식, smooth 스크롤 없음) */
        (function () {
            Array.prototype.forEach.call(document.querySelectorAll('.stage-view'), function (v) {
                v.addEventListener('scroll', function () { if (v.scrollLeft) v.scrollLeft = 0; }, { passive: true });
            });
            Array.prototype.forEach.call(document.querySelectorAll('.stage'), function (root) {
                var track = root.querySelector('.stage-track');
                var items = Array.prototype.slice.call(root.querySelectorAll('.stage-item'));
                var tabs = Array.prototype.slice.call(root.querySelectorAll('.stage-tabs button'));
                var count = root.querySelector('.stage-count');
                var n = items.length, i = 0;
                if (!track || !n) return;
                function eager(k) { var img = items[k] && items[k].querySelector('img'); if (img) img.loading = 'eager'; }
                function go(k, user) {
                    i = (k + n) % n;
                    track.style.transform = 'translateX(-' + (i * 100) + '%)';
                    items.forEach(function (it, j) { it.inert = j !== i; });
                    tabs.forEach(function (t, j) { t.setAttribute('aria-current', String(j === i)); });
                    if (count) count.textContent = (i + 1) + ' / ' + n;
                    if (user) { eager(i); eager((i + 1) % n); }
                }
                root.querySelector('.stage-prev').addEventListener('click', function () { go(i - 1, true); });
                root.querySelector('.stage-next').addEventListener('click', function () { go(i + 1, true); });
                tabs.forEach(function (t, j) { t.addEventListener('click', function () { go(j, true); }); });
                root.addEventListener('keydown', function (e) {
                    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
                    e.preventDefault();
                    go(i + (e.key === 'ArrowRight' ? 1 : -1), true);
                });
                var view = root.querySelector('.stage-view'), x0 = null, y0 = 0;
                view.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
                view.addEventListener('touchend', function (e) {
                    if (x0 === null) return;
                    var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
                    x0 = null;
                    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) go(i + (dx < 0 ? 1 : -1), true);
                }, { passive: true });
                go(0, false);
            });
        })();
        (function () {
            var d = document.getElementById('tb-lb');
            if (!d || typeof d.showModal !== 'function') return;  // 미지원 브라우저는 링크로 원본 열기
            var img = document.getElementById('tb-lb-img'), cap = document.getElementById('tb-lb-cap');
            var prev = d.querySelector('.tb-lb-prev'), next = d.querySelector('.tb-lb-next');
            var list = [], idx = 0, opener = null;
            function show(k) {
                idx = (k + list.length) % list.length;
                var a = list[idx], t = a.querySelector('img');
                img.src = a.getAttribute('href');
                img.alt = t.alt;
                if (t.getAttribute('width')) { img.width = +t.getAttribute('width'); img.height = +t.getAttribute('height'); }
                cap.textContent = t.alt + (list.length > 1 ? ' (' + (idx + 1) + '/' + list.length + ')' : '');
            }
            document.addEventListener('click', function (e) {
                var a = e.target.closest && e.target.closest('a.tb-shot');
                if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                e.preventDefault();
                list = Array.prototype.slice.call(a.closest('.tb-card').querySelectorAll('a.tb-shot'));
                opener = a;
                prev.hidden = next.hidden = list.length < 2;
                show(list.indexOf(a));
                d.showModal();
            });
            prev.addEventListener('click', function () { show(idx - 1); });
            next.addEventListener('click', function () { show(idx + 1); });
            d.querySelector('.tb-lb-close').addEventListener('click', function () { d.close(); });
            d.addEventListener('click', function (e) { if (e.target === d) d.close(); });  // 배경 클릭
            d.addEventListener('keydown', function (e) {
                // ESC 는 네이티브 close 도 되지만, 합성 키 이벤트·일부 임베디드 렌더러에서 빠지는 경우가 있어 직접 닫는다
                if (e.key === 'Escape') { e.preventDefault(); d.close(); return; }
                if (list.length < 2) return;
                if (e.key === 'ArrowLeft') { e.preventDefault(); show(idx - 1); }
                else if (e.key === 'ArrowRight') { e.preventDefault(); show(idx + 1); }
            });
            d.addEventListener('close', function () {
                img.removeAttribute('src');
                if (opener) opener.focus({ preventScroll: true });
            });
        })();
        /* 구분·레벨·목적 필터 — 점진적 향상. 상태는 ?type=&level=&purpose= 로 남겨 공유 가능(canonical 은 /textbooks) */
        (function () {
            var bar = document.getElementById('tb-filter');
            if (!bar) return;
            var KEYS = { type: 'type', level: 'levels', purpose: 'purposes' };
            var cards = Array.prototype.slice.call(document.querySelectorAll('.tb-card'));
            var groups = Array.prototype.slice.call(document.querySelectorAll('.tb-group'));
            var none = document.getElementById('tb-none'), count = document.getElementById('tb-count');
            var btns = Array.prototype.slice.call(bar.querySelectorAll('button[data-f]'));
            var picked = { type: '', level: '', purpose: '' };
            var q = new URLSearchParams(location.search);
            Object.keys(picked).forEach(function (k) {
                var v = q.get(k) || '';
                if (btns.some(function (b) { return b.dataset.f === k && b.dataset.v === v; })) picked[k] = v;
            });
            function has(card, k) {
                var v = picked[k];
                if (!v) return true;
                if (k === 'type') return card.dataset.type === v;
                return (card.dataset[KEYS[k]] || '').split(',').indexOf(v) >= 0;
            }
            function apply(push) {
                btns.forEach(function (b) { b.setAttribute('aria-pressed', String(picked[b.dataset.f] === b.dataset.v)); });
                var seen = {};
                cards.forEach(function (c) {
                    var ok = has(c, 'type') && has(c, 'level') && has(c, 'purpose');
                    c.hidden = !ok;
                    if (ok) seen[c.dataset.slug] = 1;
                });
                groups.forEach(function (g) {
                    g.hidden = !g.querySelector('.tb-card:not([hidden])');
                    var a = document.querySelector('.tb-nav a[href="#' + g.id + '"]');
                    if (a) a.hidden = g.hidden;
                });
                var n = Object.keys(seen).length;  // 여러 과정에 걸친 책은 한 권으로
                count.textContent = '교재 ' + n + '권';
                none.hidden = n > 0;
                if (push) {
                    var p = new URLSearchParams();
                    Object.keys(picked).forEach(function (k) { if (picked[k]) p.set(k, picked[k]); });
                    var s = p.toString();
                    history.replaceState(null, '', location.pathname + (s ? '?' + s : '') + location.hash);
                }
            }
            btns.forEach(function (b) {
                b.addEventListener('click', function () { picked[b.dataset.f] = b.dataset.v; apply(true); });
            });
            none.querySelector('button').addEventListener('click', function () {
                picked = { type: '', level: '', purpose: '' };
                apply(true);
            });
            bar.hidden = false;
            apply(false);
        })();
    </script>"""


def _crumb_html():
    return f"""        <nav class="rg-crumb" aria-label="브레드크럼">
            <div class="container">
                <ol>
                    <li><a href="/">홈</a></li>
                    <li aria-current="page">{TB_LABEL}</li>
                </ol>
            </div>
        </nav>"""


def render_page():
    _ID_SEEN.clear()
    updated, groups = load_data()
    # 여러 과정에 걸친 책은 섹션마다 카드가 있지만 ItemList 에는 한 번만
    seen, books = set(), []
    for _, _, bs in groups:
        for b in bs:
            key = b.get("slug") or b.get("name")
            if key not in seen:
                seen.add(key)
                books.append(b)
    contact = S.esc(S.contact_href(SRC))

    title = "이지스피크 영어회화 교재 - 과정별 교재 안내"
    desc = ("레벨테스트 결과와 목표에 맞춰 과정별 교재를 골라 1:1 원어민 화상 수업에서 사용합니다. "
            "일상회화·비즈니스·여행·시사·문법·시험 대비 교재를 과정별로 정리했습니다.")
    lead = "레벨테스트 결과와 목표에 맞춰 과정별 교재를 골라 1:1 원어민 화상 수업에서 사용합니다."

    # ---- JSON-LD : build_jsonld 재사용 → CollectionPage + ItemList(Book) ----
    crumb = [("홈", S.BASE_URL + "/"), (TB_LABEL, TB_CANONICAL)]
    doc = json.loads(S.build_jsonld({"keyword": TB_LABEL}, TB_CANONICAL, title, desc, crumb, None))
    for node in doc["@graph"]:
        if node.get("@type") == "WebPage":
            node["@type"] = "CollectionPage"
            if updated:
                node["dateModified"] = updated
            if books:
                node["mainEntity"] = {
                    "@type": "ItemList",
                    "numberOfItems": len(books),
                    "itemListElement": [
                        {"@type": "ListItem", "position": i, "item": book_ld(b)}
                        for i, b in enumerate(books, start=1)
                    ],
                }
    jsonld = json.dumps(doc, ensure_ascii=False, indent=2)

    if groups:
        present = lambda key, allowed: [v for v in allowed if any(v in (b.get(key) or []) for b in books)]
        rows = [("type", "구분", [(t, lab) for t, lab in TYPES if any(b.get("type") == t for b in books)]),
                ("level", "레벨", [(v, v) for v in present("levels", LEVELS)]),
                ("purpose", "목적", [(v, v) for v in present("purposes", PURPOSES)])]
        filter_rows = "\n".join(
            '                    <div class="tb-frow"><span class="tb-flabel">%s</span><div class="tb-fopts">%s</div></div>' % (
                label, "".join('<button type="button" data-f="%s" data-v="%s" aria-pressed="%s">%s</button>'
                               % (key, S.esc(v), "true" if not v else "false", S.esc(lab))
                               for v, lab in [("", "전체")] + opts))
            for key, label, opts in rows)
        filter_html = f"""
                <div class="tb-filter" id="tb-filter" role="group" aria-label="교재 골라 보기" hidden>
{filter_rows}
                    <p class="tb-count" id="tb-count" aria-live="polite">교재 {len(books)}권</p>
                </div>"""
        nav = "\n".join(
            f'                    <a class="pill" href="#group-{S.esc(gid)}">{S.esc(gname)}</a>'
            for gid, gname, _ in groups)
        nav_html = f"""
                <nav class="tb-nav" aria-label="과정별 교재 바로가기">
{nav}
                </nav>"""
        sections = """        <div class="container"><div class="tb-none" id="tb-none" hidden><p>조건에 맞는 교재가 없습니다.</p><button type="button">필터 초기화</button></div></div>
""" + "\n".join(f"""        <section class="section tb-group" id="group-{S.esc(gid)}" aria-labelledby="group-{S.esc(gid)}-title">
            <div class="container">
                <h2 id="group-{S.esc(gid)}-title">{S.esc(gname)} 교재</h2>
                <ul class="tb-grid">
{chr(10).join(book_card(b, gname, (gi, k) < (0, 2)) for k, b in enumerate(bs))}
                </ul>
            </div>
        </section>""" for gi, (gid, gname, bs) in enumerate(groups))
    else:
        nav_html = filter_html = ""
        sections = """        <section class="section">
            <div class="container">
                <p class="tb-empty">교재 정보를 준비 중입니다. 수업에 쓰는 교재는 무료 레벨테스트 상담에서 안내해 드립니다.</p>
            </div>
        </section>"""

    updated_html = ('\n        <div class="container"><p class="rg-updated">최종 업데이트: %s</p></div>'
                    % S.esc(updated.replace("-", "."))) if updated else ""

    body = f"""{_crumb_html()}

        <section class="rg-hero">
            <div class="container">
                <span class="eyebrow">{TB_LABEL}</span>
                <h1>이지스피크 <span class="easy">영어회화 교재</span></h1>
                <p class="rg-lead">{S.esc(lead)} 자체 제작 교재를 먼저, 함께 쓰는 출판사 교재를 이어서 과정별로 정리했습니다.</p>{filter_html}{nav_html}
            </div>
        </section>

{sections}

        <section class="rg-inline-cta">
            <div class="container">
                <div class="rg-inline-cta-inner">
                    <p><strong>어떤 교재로 시작할지 모르겠다면</strong>무료 레벨테스트로 지금 말하기 수준을 먼저 확인해 보세요. 결과를 보고 시작할 과정과 교재를 함께 정합니다.</p>
                    <div class="rg-inline-cta-actions">
                        <a href="{contact}" class="btn btn--solid">무료 레벨테스트 신청</a>
                    </div>
                </div>
            </div>
        </section>{updated_html}"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{S.esc(title)}</title>
    <meta name="description" content="{S.esc(desc)}">
    <link rel="canonical" href="{TB_CANONICAL}">
    <meta property="og:title" content="{S.esc(title)}">
    <meta property="og:description" content="{S.esc(desc)}">
    <meta property="og:url" content="{TB_CANONICAL}">
    <meta property="og:type" content="website">
    <meta property="og:locale" content="ko_KR">

{S.head_common()}
{S.REGION_INLINE_CSS}
{TB_INLINE_CSS}

    <script type="application/ld+json">
{jsonld}
    </script>
</head>
<body>
{S.header_html(SRC)}

    <main class="rg-main">
{body}
    </main>

{S.footer_html(SRC)}
{S.PAGE_SCRIPT}
{TB_LIGHTBOX if groups else ''}
</body>
</html>
"""


class handler(BaseHTTPRequestHandler):

    def _respond(self, status, body, cache, head_only=False):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _handle(self, head_only=False):
        self._respond(200, render_page(), CACHE_OK, head_only=head_only)

    def do_GET(self):
        self._handle(head_only=False)

    def do_HEAD(self):
        self._handle(head_only=True)
