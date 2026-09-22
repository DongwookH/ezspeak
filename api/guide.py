#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
/guide/{slug} · /guide  질문형 가이드 칼럼 렌더링 (Vercel Python 서버리스 함수)
=====================================================================

vercel.json 리라이트
  /guide            -> /api/guide
  /guide/{slug}     -> /api/guide?slug={slug}

지역 키워드로는 받을 수 없는 질문형 검색("화상영어 전화영어 차이" 등)을 받는 칼럼.
본문 데이터는 api/_data/guides.json, 헤더·푸터·공통 CSS·JSON-LD 는 site_lib 재사용.
api/region.py 와 동일한 핸들러/캐시 구조다.
"""

import os
import sys
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_lib as S  # noqa: E402

CACHE_OK = "public, max-age=0, s-maxage=86400, stale-while-revalidate=604800"
CACHE_404 = "public, max-age=0, s-maxage=300"

GUIDE_PREFIX = "/guide"
GUIDE_CANONICAL = S.BASE_URL + GUIDE_PREFIX
GUIDE_LABEL = "영어회화 가이드"
DATA_PATH = os.path.join(S.DATA_DIR, "guides.json")

# 상담 CTA 유입 슬러그 — /?from=guide#contact (script.js 가 상담폼 hidden 에 넣는다)
SRC = "guide"

_GUIDES = None


def guides():
    """[{slug,title,question,answer,sections,faq,updated}] — 모듈 레벨 캐시."""
    global _GUIDES
    if _GUIDES is None:
        with open(DATA_PATH, encoding="utf-8") as f:
            _GUIDES = json.load(f)["guides"]
    return _GUIDES


def guide_of(slug):
    for g in guides():
        if g["slug"] == slug:
            return g
    return None


def guide_url(slug):
    return "%s/%s" % (GUIDE_PREFIX, slug)


# 칼럼 본문 전용 미세 스타일 — 공용 토큰만 사용. style.css 를 건드리지 않으려고
# 여기 인라인으로 둔다(정적 자산 1년 immutable 캐시 무효화 불필요).
GUIDE_INLINE_CSS = """    <style>
        .gd-body > h2 { margin-top: clamp(34px, 5vw, 52px); font-weight: 800;
            font-size: clamp(20px, 3vw, 26px); line-height: 1.34; letter-spacing: -.02em;
            color: var(--ink); word-break: keep-all; }
        .gd-body > h2:first-child { margin-top: 0; }
        .gd-body p { color: var(--ink-2); line-height: 1.85; word-break: keep-all;
            margin-top: 14px; max-width: 68ch; font-size: clamp(15px, 2.2vw, 16.5px); }
        .gd-fig { margin: 22px 0 0; max-width: 68ch; }
        .gd-fig-imgs { display: flex; flex-wrap: wrap; gap: 12px; }
        .gd-fig img { width: 240px; height: 180px; max-width: 100%; object-fit: contain;
            background: var(--line-2); border: 1px solid var(--line); border-radius: var(--r-md); }
        .gd-fig figcaption { margin-top: 8px; font-size: 13.5px; color: var(--ink-3); }
        .gd-list { margin-top: 4px; }
        .gd-list a.card { display: block; text-decoration: none; transition: border-color .16s; }
        .gd-list a.card:hover { border-color: var(--blue); }
        .gd-list .card__body { padding: 20px 20px 22px; }
    </style>"""


def _crumb_html(last):
    return f"""        <nav class="rg-crumb" aria-label="브레드크럼">
            <div class="container">
                <ol>
                    <li><a href="/">홈</a></li>
                    <li><a href="{GUIDE_PREFIX}">{S.esc(GUIDE_LABEL)}</a></li>
                    <li aria-current="page">{S.esc(last)}</li>
                </ol>
            </div>
        </nav>"""


def _shell(title, desc, canonical, jsonld, body, robots=""):
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{S.esc(title)}</title>
    <meta name="description" content="{S.esc(desc)}">
    <link rel="canonical" href="{S.esc(canonical)}">
{robots}
    <meta property="og:title" content="{S.esc(title)}">
    <meta property="og:description" content="{S.esc(desc)}">
    <meta property="og:url" content="{S.esc(canonical)}">
    <meta property="og:type" content="article">
    <meta property="og:locale" content="ko_KR">

{S.head_common()}
{S.REGION_INLINE_CSS}
{GUIDE_INLINE_CSS}

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
</body>
</html>
"""


def render_guide(g):
    """개별 칼럼 페이지. h1 = 질문, 첫 문단 = 직답."""
    canonical = S.BASE_URL + guide_url(g["slug"])
    contact = S.esc(S.contact_href(SRC))
    faqs = g.get("faq") or []

    # ---- JSON-LD : site_lib.build_jsonld 재사용 (WebPage + BreadcrumbList + FAQPage
    #      + 메인과 동일한 @id 의 EducationalOrganization/WebSite) ----
    crumb = [("홈", S.BASE_URL + "/"),
             (GUIDE_LABEL, GUIDE_CANONICAL),
             (g["title"], canonical)]
    doc = json.loads(S.build_jsonld({"keyword": g["title"]}, canonical,
                                    g["title"], g["answer"], crumb, faqs))
    for node in doc["@graph"]:
        if node.get("@type") == "WebPage":
            node["dateModified"] = g["updated"]
            node["headline"] = g["title"]
    jsonld = json.dumps(doc, ensure_ascii=False, indent=2)

    # ---- 본문 ----
    parts = []
    for s in g["sections"]:
        parts.append(f'                    <h2>{S.esc(s["h2"])}</h2>')
        for p in s["paragraphs"]:
            parts.append(f'                    <p>{S.esc(p)}</p>')
        fig = s.get("figure")  # 선택 필드: {"images": [{"src","alt"}], "caption"}
        if fig and fig.get("images"):
            imgs = "".join(
                f'<img src="{S.esc(i["src"])}" alt="{S.esc(i.get("alt", ""))}" width="240" height="180" loading="lazy" decoding="async">'
                for i in fig["images"])
            cap = f'<figcaption>{S.esc(fig["caption"])}</figcaption>' if fig.get("caption") else ""
            parts.append(f'                    <figure class="gd-fig"><div class="gd-fig-imgs">{imgs}</div>{cap}</figure>')
    body_html = "\n".join(parts)

    faq_html = "\n".join(f"""                <details>
                    <summary>{S.esc(f["q"])}</summary>
                    <div class="rg-faq-a">{S.esc(f["a"])}</div>
                </details>""" for f in faqs)

    faq_section = ""
    if faqs:
        faq_section = f"""
        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">자주 묻는 질문</span>
                    <h2 class="section-title">이 주제에 대해<br>자주 묻는 질문</h2>
                </div>
                <div class="rg-faq">
{faq_html}
                </div>
            </div>
        </section>"""

    others = [o for o in guides() if o["slug"] != g["slug"]]
    other_pills = "\n".join(
        f'                    <a class="pill" href="{S.esc(guide_url(o["slug"]))}">{S.esc(o["question"])}</a>'
        for o in others)

    body = f"""{_crumb_html(g["title"])}

        <article class="rg-hero">
            <div class="container">
                <span class="eyebrow">{S.esc(GUIDE_LABEL)}</span>
                <h1>{S.esc(g["question"])}</h1>
                <p class="rg-lead">{S.esc(g["answer"])}</p>
            </div>
        </article>

        <section class="section">
            <div class="container">
                <div class="gd-body">
{body_html}
                </div>
            </div>
        </section>

        <section class="rg-inline-cta">
            <div class="container">
                <div class="rg-inline-cta-inner">
                    <p><strong>어디서부터 시작할지 정하기 어렵다면</strong>무료 레벨테스트로 지금 말하기 수준을 먼저 확인해 보세요. 약 10분, 온라인으로 진행되며 결과를 보고 시작할 과정과 수업 횟수를 함께 정합니다.</p>
                    <div class="rg-inline-cta-actions">
                        <a href="{contact}" class="btn btn--solid">무료 레벨테스트 신청</a>
                        <a href="{GUIDE_PREFIX}" class="rg-inline-link">가이드 전체 보기</a>
                    </div>
                </div>
            </div>
        </section>
{faq_section}

        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">다른 가이드</span>
                    <h2 class="section-title">함께 보면 좋은 질문</h2>
                </div>
                <div class="rg-pills">
{other_pills}
                </div>
            </div>
        </section>

        <div class="container"><p class="rg-updated">최종 업데이트: {g["updated"].replace("-", ".")}</p></div>"""

    title = "%s - 이지스피크 영어회화" % g["title"]
    return _shell(title, g["answer"], canonical, jsonld, body)


def render_list():
    """/guide 목록 페이지 (CollectionPage + ItemList)."""
    gs = guides()
    canonical = GUIDE_CANONICAL
    desc = ("화상영어와 전화영어의 차이, 왕초보 첫 수업, 무료 레벨테스트 5영역, "
            "주 2회 3개월의 변화, 직장인 학습 유지까지. 이지스피크가 운영 방식을 기준으로 정리한 영어회화 가이드입니다.")
    contact = S.esc(S.contact_href(SRC))

    crumb = [("홈", S.BASE_URL + "/"), (GUIDE_LABEL, canonical)]
    doc = json.loads(S.build_jsonld({"keyword": GUIDE_LABEL}, canonical,
                                    GUIDE_LABEL, desc, crumb, None))
    for node in doc["@graph"]:
        if node.get("@type") == "WebPage":
            node["@type"] = "CollectionPage"
            node["mainEntity"] = {
                "@type": "ItemList",
                "numberOfItems": len(gs),
                "itemListElement": [
                    {"@type": "ListItem", "position": i, "name": g["question"],
                     "url": S.BASE_URL + guide_url(g["slug"])}
                    for i, g in enumerate(gs, start=1)
                ],
            }
    jsonld = json.dumps(doc, ensure_ascii=False, indent=2)

    cards = "\n".join(f"""                <a class="card" href="{S.esc(guide_url(g["slug"]))}">
                    <div class="card__body">
                        <h2 class="card__title">{S.esc(g["question"])}</h2>
                        <p class="card__text">{S.esc(g["answer"])}</p>
                    </div>
                </a>""" for g in gs)

    body = f"""{_crumb_html(GUIDE_LABEL)}

        <section class="rg-hero">
            <div class="container">
                <span class="eyebrow">{S.esc(GUIDE_LABEL)}</span>
                <h1>영어회화를 시작할 때<br><span class="easy">자주 나오는 질문</span></h1>
                <p class="rg-lead">{S.esc(desc)}</p>
                <div class="rg-actions">
                    <a href="{contact}" class="btn btn--solid">무료 레벨테스트 신청</a>
                    <a href="/region" class="btn btn--outline">지역별 영어회화 보기</a>
                </div>
            </div>
        </section>

        <section class="section">
            <div class="container">
                <div class="gd-list card-grid">
{cards}
                </div>
            </div>
        </section>

        <div class="container"><p class="rg-updated">최종 업데이트: {max(g["updated"] for g in gs).replace("-", ".")}</p></div>"""

    return _shell("영어회화 가이드 - 이지스피크", desc, canonical, jsonld, body)


def render_404(requested):
    """가이드 전용 404 — 목록으로 안내. (지역 404 는 site_lib.render_not_found)"""
    items = "\n".join(
        f'                    <a class="pill" href="{S.esc(guide_url(g["slug"]))}">{S.esc(g["question"])}</a>'
        for g in guides())
    body = f"""        <section class="rg-hero">
            <div class="container">
                <span class="eyebrow">404</span>
                <h1>찾을 수 없는 <span class="easy">가이드</span></h1>
                <p class="rg-lead">주소가 바뀌었거나 없는 문서입니다. 요청하신 주소: <code>{S.esc(requested)}</code></p>
                <div class="rg-pills">
{items}
                </div>
                <div class="rg-actions">
                    <a href="{GUIDE_PREFIX}" class="btn btn--solid">영어회화 가이드 전체 보기</a>
                    <a href="/" class="btn btn--outline">이지스피크 홈</a>
                </div>
            </div>
        </section>"""
    return _shell("페이지를 찾을 수 없습니다 (404) - 이지스피크",
                  "요청하신 가이드를 찾을 수 없습니다.", GUIDE_CANONICAL,
                  '{"@context":"https://schema.org","@type":"WebPage","name":"404"}',
                  body, robots='    <meta name="robots" content="noindex, follow">')


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
        query = parse_qs(urlparse(self.path).query)
        slug = (query.get("slug") or [""])[0].strip().strip("/")

        if not slug:
            self._respond(200, render_list(), CACHE_OK, head_only=head_only)
            return

        g = guide_of(slug)
        if g is None:
            self._respond(404, render_404(GUIDE_PREFIX + "/" + slug),
                          CACHE_404, head_only=head_only)
            return

        self._respond(200, render_guide(g), CACHE_OK, head_only=head_only)

    def do_GET(self):
        self._handle(head_only=False)

    def do_HEAD(self):
        self._handle(head_only=True)
