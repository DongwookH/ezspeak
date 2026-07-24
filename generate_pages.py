#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이지스피크(EZspeak) 지역 SEO 페이지 대량 생성 스크립트  (재작성판)
=====================================================================

"{지역} 영어회화" 키워드 상위노출용 지역 SEO 페이지를
  (1) 새 디자인 시스템(흰 바탕 + 로고 파랑 주색 / Pretendard 단일, style.css 공용 클래스)
  (2) data/seo_spec.md + data/seo_pools.json 스펙
에 맞춰 생성한다.

읽는 파일
  - data/regions.json      : 7,334개 키워드 입력 ({keyword,type,parents})
  - data/seo_pools.json    : 콘텐츠 변형 풀 (titles/meta/faq/local_intros/body_blocks)

생성물
  - 지역/{keyword}-영어회화.html   : 최말단 + 중간(구/군/시) + 시·도 지역 페이지
  - 지역/{시도}-영어회화.html       : 시·도 중간 페이지 (도-level 은 합성 생성)
  - 지역/index.html               : 허브 (시·도 링크 + 검색)
  - sitemap.xml                   : 메인 + 허브 + 전체 지역 페이지
  - robots.txt                    : 없을 때만 생성

Python 3 표준 라이브러리만 사용.

사용법
  python3 generate_pages.py                          # data/regions.json
  python3 generate_pages.py data/regions.sample.json # 다른 입력(테스트)

⚠️  BASE_URL 은 실제 배포 도메인으로 맞춰서 사용하세요 (아래 설정 참고).
"""

import sys
import os
import re
import json
import html
import hashlib
from urllib.parse import quote

# ---------------------------------------------------------------------------
# 설정 (사용자가 나중에 바꿀 수 있는 값)
# ---------------------------------------------------------------------------

# ★ 실제 배포 도메인. index.html 의 canonical 과 동일하게 맞춰 둔 기본값.
#   canonical / og:url / JSON-LD / sitemap.xml / robots.txt 에 사용됩니다.
#   자체 도메인 확정 시 이 한 줄만 바꾸면 전체 산출물에 반영됩니다.
BASE_URL = "https://ezspeak.vercel.app"

# 학원 대표 정보 (JSON-LD EducationalOrganization / 푸터에 사용)
BUSINESS_NAME = "이지스피크 영어회화"
BUSINESS_OWNER = "황동욱"
BUSINESS_PHONE = "010-2311-6543"
BUSINESS_EMAIL = "ft9990@naver.com"

# 캐시버스팅 버전 (index.html 과 동일하게 유지)
ASSET_VER = "20260724d"

# 출력 경로
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
REGION_DIRNAME = "지역"
REGION_DIR = os.path.join(ROOT_DIR, REGION_DIRNAME)
DEFAULT_INPUT = os.path.join(ROOT_DIR, "data", "regions.json")
POOLS_PATH = os.path.join(ROOT_DIR, "data", "seo_pools.json")

PAGE_SUFFIX = "-영어회화.html"

# 광역 행정단위 접미사 (시·도 판별용)
SIDO_SUFFIXES = ("특별시", "광역시", "특별자치시", "특별자치도", "도")

# 콘텐츠 QA 기준 (seo_spec.md 8절)
MIN_VISIBLE_CHARS = 1200


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------

def kw_hash(keyword, salt=""):
    """키워드+salt 기반 안정적 정수 해시 (변형 결정적 선택용)."""
    h = hashlib.md5((salt + "|" + keyword).encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def pick(variants, keyword, salt):
    """키워드 해시로 변형 리스트 중 하나를 결정적으로 선택."""
    return variants[kw_hash(keyword, salt) % len(variants)]


def pick_indices(n, count, keyword, salt_prefix):
    """0..n-1 중 count 개를 결정적·중복없이 선택.
    각 인덱스에 salt_prefix+i 해시를 매겨 정렬 후 앞에서 count 개."""
    order = sorted(range(n), key=lambda i: kw_hash(keyword, "%s%d" % (salt_prefix, i)))
    return order[:min(count, n)]


def esc(s):
    return html.escape(s, quote=True)


def fmt(text, ctx):
    """풀 문자열의 플레이스홀더 치환.
    str.format 대신 명시적 replace 를 사용해 예기치 못한 중괄호로 인한
    크래시를 방지한다 (seo_spec.md 10절: 4개 키만 존재)."""
    for key in ("keyword", "loc", "parent", "sido"):
        text = text.replace("{" + key + "}", ctx.get(key, ""))
    return text


def page_filename(keyword):
    return keyword + PAGE_SUFFIX


def region_url_path(keyword):
    """루트 기준 지역 페이지 경로 (URL 인코딩)."""
    return "/" + quote(REGION_DIRNAME) + "/" + quote(page_filename(keyword))


def canonical_of(keyword):
    return BASE_URL + region_url_path(keyword)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def visible_len(doc_html):
    """<script>/<style>/<nav>/<footer>/<header> 제외 대략적인 가시 텍스트 길이."""
    body = doc_html
    for tag in ("script", "style"):
        body = re.sub(r"<%s\b.*?</%s>" % (tag, tag), " ", body, flags=re.S | re.I)
    # 헤더/푸터/브레드크럼 내비는 본문 분량에서 제외 (seo_spec.md 0절 기준)
    body = re.sub(r"<header\b.*?</header>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<footer\b.*?</footer>", " ", body, flags=re.S | re.I)
    body = re.sub(r'<nav\b[^>]*aria-label="브레드크럼".*?</nav>', " ", body, flags=re.S | re.I)
    text = _TAG_RE.sub(" ", body)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return len(text)


# ---------------------------------------------------------------------------
# 지역 계층 (representative parent / breadcrumb / children / siblings)
# ---------------------------------------------------------------------------

def is_sido_token(tok):
    return tok.endswith(SIDO_SUFFIXES)


def representative_parent(kw):
    """seo_spec.md 4.4: 여러 parents 중 대표 1개 선택.
    parents 원소는 '경기도 성남시 분당구' 처럼 공백으로 이어진 조상 경로 문자열."""
    ps = [p.strip() for p in (kw.get("parents") or []) if p and p.strip()]
    if not ps:
        return ""
    if len(ps) == 1:
        return ps[0]
    # (a) 단일 토큰 광역 행정명(서울특별시 등)이 있으면 우선
    bare_sido = [p for p in ps if len(p.split()) == 1 and is_sido_token(p)]
    if bare_sido:
        return sorted(bare_sido, key=lambda p: (len(p), p))[0]
    # (b) 그 외: 가장 상위(토큰 수 최소) → 사전순
    return sorted(ps, key=lambda p: (len(p.split()), p))[0]


def rep_tokens(kw):
    rp = representative_parent(kw)
    return rp.split() if rp else []


def build_ctx(kw):
    """풀 치환용 컨텍스트."""
    keyword = kw["keyword"]
    toks = rep_tokens(kw)
    rp = " ".join(toks)
    loc = (rp + " " + keyword).strip() if rp else keyword
    parent = toks[-1] if toks else keyword
    sido = toks[0] if toks else keyword
    return {"keyword": keyword, "loc": loc, "parent": parent, "sido": sido}


# ---------------------------------------------------------------------------
# 콘텐츠 풀 로딩 & 선택자
# ---------------------------------------------------------------------------

class Pools:
    def __init__(self, data):
        self.titles = data["titles"]
        self.metas = data["meta_descriptions"]
        self.faq = data["faq"]
        self.local_intros = data["local_intros"]
        self.body_blocks = data["body_blocks"]


def load_pools(path):
    with open(path, "r", encoding="utf-8") as f:
        return Pools(json.load(f))


def title_for(pools, ctx):
    return fmt(pick(pools.titles, ctx["keyword"], "title"), ctx)


def meta_for(pools, ctx):
    """meta description 선택 + 110자 초과 시 문장 경계로 안전 절단."""
    text = fmt(pick(pools.metas, ctx["keyword"], "meta"), ctx)
    if len(text) <= 110:
        return text
    cut = text[:110]
    # 마지막 문장부호까지 되돌려 자름
    m = list(re.finditer(r"[.!?]", cut))
    if m and m[-1].end() >= 60:
        return cut[:m[-1].end()]
    return cut.rstrip()


def local_intro_for(pools, kw, ctx):
    t = kw.get("type") or "동"
    pool = pools.local_intros.get(t) or pools.local_intros.get("동")
    return fmt(pick(pool, ctx["keyword"], "local_intro"), ctx)


def faq_for(pools, ctx, count=5):
    idxs = pick_indices(len(pools.faq), count, ctx["keyword"], "faq")
    out = []
    for i in idxs:
        item = pools.faq[i]
        out.append({"q": fmt(item["q"], ctx), "a": fmt(item["a"], ctx)})
    return out


def body_blocks_for(pools, ctx):
    # 페이지마다 2 또는 3개 (해시로 결정)
    count = 2 + (kw_hash(ctx["keyword"], "bodycount") % 2)
    idxs = pick_indices(len(pools.body_blocks), count, ctx["keyword"], "body")
    out = []
    for i in idxs:
        b = pools.body_blocks[i]
        out.append({"title": fmt(b["title"], ctx), "text": fmt(b["text"], ctx)})
    return out


# ---- 기존 인트로/CTA 변형 (loc 활용, seo_spec.md 6절 "기존 유지") -------------

def intro_paragraph(ctx):
    keyword = ctx["keyword"]
    loc = ctx["loc"]
    variants = [
        (f"{loc} 인근에서 영어회화 학원을 찾고 계신가요? 이지스피크(EZspeak)는 "
         f"{keyword} 지역 학습자를 위한 실전 회화 중심 영어 교육을 제공합니다. "
         f"시험을 위한 영어가 아니라, 실제로 입이 트이는 영어를 목표로 합니다."),
        (f"{keyword} 영어회화, 어디서 시작해야 할지 고민이라면 이지스피크가 함께합니다. "
         f"{loc}에서 생활하고 일하는 분들의 눈높이에 맞춰, 초급부터 고급까지 "
         f"수준별 speaking 커리큘럼으로 자연스럽게 말이 되는 영어를 완성합니다."),
        (f"복잡한 문법 암기는 이제 그만. {loc}에서 만나는 이지스피크는 "
         f"{keyword} 지역 수강생이 실제 상황에서 바로 반응하고 말할 수 있도록 "
         f"1:1 원어민 수업과 밀착 학습 관리를 함께 제공하는 영어회화 전문 학원입니다."),
        (f"아쉬웠던 영어를 아, 쉬운 영어로. {keyword} 영어회화를 준비하는 "
         f"{loc} 학습자에게 이지스피크는 유아부터 성인까지 누구나 자신의 속도에 맞춰 "
         f"영어가 '부담'이 아닌 '도구'가 되도록 돕습니다."),
        (f"{loc}에서 영어로 말하는 즐거움을 되찾고 싶다면 이지스피크와 함께하세요. "
         f"{keyword} 지역 특성과 수강생 목표에 맞춘 맞춤형 회화 수업으로, "
         f"말할수록 입이 트이고 참여할수록 자신감이 쌓이는 양방향 수업을 경험할 수 있습니다."),
        (f"{keyword} 근처에서 믿을 수 있는 영어회화 학원을 찾는다면, "
         f"{loc} 학습자들이 눈여겨보는 이지스피크(EZspeak)를 확인해 보세요. "
         f"실전에서 바로 쓰는 영어, 매일 쓰는 표현 중심의 커리큘럼으로 결과를 만듭니다."),
    ]
    return pick(variants, keyword, "intro")


def curriculum_lead(ctx):
    keyword = ctx["keyword"]
    loc = ctx["loc"]
    variants = [
        f"{keyword} 영어학원을 고를 때 가장 중요한 것은 실제로 말하는 시간입니다. 이지스피크의 운영 방식을 확인해 보세요.",
        f"{loc} 수강생을 위한 이지스피크만의 운영 방식은 이렇게 다릅니다.",
        f"말이 트이는 데에는 이유가 있습니다. {keyword} 지역에서 검증된 이지스피크 학습 시스템.",
        f"{keyword} 원어민 회화부터 학습 관리까지, 이지스피크의 3단계 운영 원칙을 소개합니다.",
        f"이지스피크가 {loc} 학습자에게 꾸준히 선택받는 이유를 정리했습니다.",
    ]
    return pick(variants, keyword, "curlead")


def cta_copy(ctx):
    keyword = ctx["keyword"]
    loc = ctx["loc"]
    variants = [
        f"{keyword} 영어회화, 지금 무료 레벨테스트로 내 실력부터 정확히 확인해 보세요.",
        f"{loc}에서 영어의 첫걸음을 이지스피크와 함께. 무료 레벨테스트를 신청하세요.",
        f"고민만 하기엔 시간이 아깝습니다. {keyword} 지역 맞춤 상담을 무료로 받아보세요.",
        f"내게 맞는 커리큘럼이 궁금하다면? {keyword} 영어회화 무료 레벨테스트로 시작하세요.",
        f"부담 없이 시작하는 {loc} 영어회화. 무료 레벨테스트와 상담을 신청해 보세요.",
        f"{keyword}에서 통하는 영어, 이지스피크에서 만드세요. 지금 무료 레벨테스트를 신청할 수 있습니다.",
    ]
    return pick(variants, keyword, "cta")


# ---------------------------------------------------------------------------
# 공통 마크업 (헤더 / 푸터 / 스크립트) — index.html 과 동일 구조/클래스
# ---------------------------------------------------------------------------

def head_common(home_prefix="../"):
    """스타일시트만 로드. (본문 전 영역 Pretendard — style.css @import 로 공급.
    지역 페이지에는 별도 웹폰트를 싣지 않아 로딩을 가볍게 유지한다.)"""
    return f"""    <link rel="icon" type="image/png" href="{home_prefix}favicon.png">
    <link rel="apple-touch-icon" href="{home_prefix}apple-touch-icon.png">
    <link rel="stylesheet" href="{home_prefix}style.css?v={ASSET_VER}">"""


def header_html(home_prefix="../"):
    """index.html 과 동일한 .header 마크업. 링크는 ../index.html#앵커."""
    return f"""    <header class="header">
        <div class="container">
            <div class="logo">
                <a href="{home_prefix}index.html" aria-label="이지스피크 홈"><img src="{home_prefix}logo.png" alt="이지스피크 EZspeak 로고"><span class="logo-word">이지스피크</span></a>
            </div>
            <nav class="nav" aria-label="주요 메뉴">
                <ul>
                    <li><a href="{home_prefix}index.html#about">학원소개</a></li>
                    <li><a href="{home_prefix}index.html#programs">커리큘럼</a></li>
                    <li><a href="{home_prefix}index.html#features">운영 방식</a></li>
                    <li><a href="{home_prefix}index.html#reviews">후기</a></li>
                    <li><a href="{home_prefix}index.html#contact">상담문의</a></li>
                </ul>
            </nav>
            <button class="mobile-menu-btn" aria-label="메뉴 열기" aria-expanded="false">
                <span></span>
                <span></span>
                <span></span>
            </button>
        </div>
    </header>"""


def footer_html(home_prefix="../"):
    return f"""    <footer class="site-footer">
        <div class="container">
            <div class="footer-brand">EZspeak</div>
            <p style="margin-bottom:14px;"><a href="{home_prefix}{quote(REGION_DIRNAME)}/index.html">전국 지역별 영어회화</a></p>
            <p class="footer-meta">대표: {BUSINESS_OWNER} &nbsp;|&nbsp; 전화: {BUSINESS_PHONE} &nbsp;|&nbsp; 이메일: {BUSINESS_EMAIL}</p>
        </div>
    </footer>

    <nav class="mobile-cta-bar" aria-label="빠른 상담">
        <a href="http://pf.kakao.com/_NmPfn/chat" target="_blank" rel="noopener" class="mc-kakao">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
            카톡 상담
        </a>
        <a href="{home_prefix}index.html#contact" class="mc-test">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"></path></svg>
            레벨테스트
        </a>
    </nav>"""


PAGE_SCRIPT = """    <script>
        (function () {
            var btn = document.querySelector('.mobile-menu-btn');
            var nav = document.querySelector('.nav');
            if (btn && nav) {
                btn.addEventListener('click', function () {
                    var open = nav.classList.toggle('active');
                    btn.classList.toggle('open', open);
                    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
                });
            }
            var header = document.querySelector('.header');
            if (header) {
                var onScroll = function () { header.classList.toggle('scrolled', window.scrollY > 8); };
                onScroll();
                window.addEventListener('scroll', onScroll, { passive: true });
            }
        })();
    </script>"""


# 지역 페이지 전용 미세 스타일 (공용 토큰만 사용, 최소한)
REGION_INLINE_CSS = """    <style>
        .rg-main { padding-top: var(--header-h); }
        .rg-crumb { font-size: 13px; color: var(--ink-3); padding: 18px 0 0; }
        .rg-crumb ol { list-style: none; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 0; margin: 0; }
        .rg-crumb a { color: var(--ink-2); text-decoration: none; }
        .rg-crumb a:hover { color: var(--blue); text-decoration: underline; }
        .rg-crumb li::after { content: "›"; margin-left: 6px; color: var(--line); }
        .rg-crumb li:last-child::after { content: ""; }
        .rg-crumb li[aria-current] { color: var(--ink); font-weight: 700; }

        .rg-hero { padding: 26px 0 clamp(36px, 6vw, 64px); }
        .rg-hero h1 { font-family: var(--font-body); font-weight: 800; line-height: 1.16;
            letter-spacing: -.03em; font-size: clamp(30px, 7vw, 54px); color: var(--ink); word-break: keep-all; }
        .rg-hero h1 .easy { color: var(--blue); font-weight: 800; }
        .rg-lead { margin-top: 18px; max-width: 62ch; font-size: clamp(15px, 2.3vw, 17px);
            color: var(--ink-2); line-height: 1.78; word-break: keep-all; }
        .rg-actions { margin-top: 26px; display: flex; flex-wrap: wrap; gap: 10px; }

        .rg-prose p { color: var(--ink-2); line-height: 1.8; word-break: keep-all; margin-top: 13px; max-width: 68ch; }

        .rg-dark { background: var(--blue-deep); color: #fff; border-radius: var(--r-lg);
            margin-inline: clamp(0px, 2vw, 12px); padding-block: clamp(40px, 6vw, 76px); }
        .rg-dark .section-title { color: #fff; }
        .rg-dark .section-sub { color: rgba(255,255,255,.78); }
        .rg-dark .eyebrow { color: #BFE0FA; }
        .rg-dark .timeline { border-top-color: rgba(255,255,255,.2); }
        .rg-dark .timeline__step { border-bottom-color: rgba(255,255,255,.2); }
        .rg-dark .timeline__num { color: #fff; background: rgba(255,255,255,.16); }
        .rg-dark .timeline__title { color: #fff; }
        .rg-dark .timeline__desc { color: rgba(255,255,255,.8); }

        .rg-blocks { margin-top: 28px; }
        .rg-blocks .card__body { padding: 20px 20px 22px; }
        .rg-blocks .card__title { font-size: 17px; }
        .rg-blocks .card__text { color: var(--ink-2); font-size: 14.5px; line-height: 1.7; }

        .rg-faq { margin-top: 22px; display: grid; gap: 10px; }
        .rg-faq details { background: #fff; border: 1px solid var(--line);
            border-radius: var(--r-md); overflow: hidden; }
        .rg-faq summary { list-style: none; cursor: pointer; padding: 17px 20px; font-weight: 700;
            color: var(--ink); display: flex; gap: 10px; align-items: flex-start; word-break: keep-all; }
        .rg-faq summary::-webkit-details-marker { display: none; }
        .rg-faq summary::before { content: "Q"; font-weight: 800; color: var(--blue);
            flex: 0 0 auto; line-height: 1.3; }
        .rg-faq summary::after { content: "+"; margin-left: auto; color: var(--ink-3); font-size: 20px; line-height: 1; }
        .rg-faq details[open] summary::after { content: "–"; }
        .rg-faq .rg-faq-a { padding: 0 20px 18px 44px; color: var(--ink-2); line-height: 1.78;
            word-break: keep-all; font-size: 15px; }

        .rg-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 22px; }
        .rg-pills a.pill { text-decoration: none; transition: border-color .16s, color .16s, background-color .16s; }
        .rg-pills a.pill:hover { border-color: var(--blue); color: var(--blue); background: var(--blue-tint); }
        .rg-more { margin-top: 12px; }
        .rg-more summary { cursor: pointer; color: var(--blue-deep); font-weight: 700; font-size: 14px; }
        .rg-more summary::-webkit-details-marker { display: none; }

        .rg-cta { text-align: center; }
        .rg-cta .rg-cta-inner { background: var(--blue-deep); color: #fff;
            border-radius: var(--r-lg); padding: clamp(36px, 6vw, 64px) 22px; }
        .rg-cta h2 { font-family: var(--font-body); font-weight: 800; color: #fff;
            font-size: clamp(24px, 4.6vw, 38px); line-height: 1.18; letter-spacing: -.02em; word-break: keep-all; }
        .rg-cta p { margin: 14px auto 24px; max-width: 52ch; color: rgba(255,255,255,.82); word-break: keep-all; }
    </style>"""


# ---------------------------------------------------------------------------
# JSON-LD @graph (seo_spec.md 5.3)
# ---------------------------------------------------------------------------

def build_jsonld(ctx, canonical, title, desc, crumb_items, faqs):
    keyword = ctx["keyword"]
    business_id = BASE_URL + "/#business"
    website_id = BASE_URL + "/#website"

    breadcrumb_els = []
    for i, (name, url) in enumerate(crumb_items, start=1):
        el = {"@type": "ListItem", "position": i, "name": name}
        if url:
            el["item"] = url
        breadcrumb_els.append(el)

    graph = [
        {
            "@type": "EducationalOrganization",
            "@id": business_id,
            "name": BUSINESS_NAME,
            "url": BASE_URL + "/",
            "telephone": BUSINESS_PHONE,
            "email": BUSINESS_EMAIL,
            "image": BASE_URL + "/logo.png",
            "areaServed": {"@type": "Place", "name": ctx["loc"]},
            "knowsLanguage": ["ko", "en"],
        },
        {
            "@type": "WebSite",
            "@id": website_id,
            "url": BASE_URL + "/",
            "name": BUSINESS_NAME,
            "inLanguage": "ko",
        },
        {
            "@type": "WebPage",
            "@id": canonical + "#webpage",
            "url": canonical,
            "name": title,
            "description": desc,
            "inLanguage": "ko",
            "about": {"@id": business_id},
            "isPartOf": {"@id": website_id},
        },
        {
            "@type": "BreadcrumbList",
            "@id": canonical + "#breadcrumb",
            "itemListElement": breadcrumb_els,
        },
    ]

    if faqs:
        graph.append({
            "@type": "FAQPage",
            "@id": canonical + "#faq",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": f["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": f["a"]},
                }
                for f in faqs
            ],
        })

    doc = {"@context": "https://schema.org", "@graph": graph}
    return json.dumps(doc, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 지역 페이지 렌더링
# ---------------------------------------------------------------------------

TIMELINE_STEPS = [
    ("01", "1:1 원어민 회화 수업",
     "검증된 원어민 강사와 함께하는 1:1 맞춤 회화 수업으로 {kw} 지역 수강생의 실전 스피킹 실력을 키웁니다. 정해진 교재를 읽는 방식이 아니라 실제 상황을 가정한 대화 중심으로 진행됩니다."),
    ("02", "1:1 한국인 플래너 밀착 케어",
     "수업 외 시간에도 담당 플래너가 예습·복습과 학습 스케줄을 관리해 혼자서는 이어가기 어려운 꾸준함을 함께 만들어 갑니다."),
    ("03", "레벨별 커리큘럼과 부가 콘텐츠",
     "무료 레벨테스트 결과에 맞춘 단계별 커리큘럼과 복습용 학습 자료로, {kw} 영어학원을 처음 찾는 왕초보부터 실무 회화까지 폭넓게 대응합니다."),
]


def render_region_page(kw, ctx, pools, keyword_set, children, siblings):
    keyword = ctx["keyword"]
    canonical = canonical_of(keyword)
    og_image = BASE_URL + "/logo.png"

    title = title_for(pools, ctx)
    desc = meta_for(pools, ctx)
    intro = intro_paragraph(ctx)
    local_intro = local_intro_for(pools, kw, ctx)
    curlead = curriculum_lead(ctx)
    blocks = body_blocks_for(pools, ctx)
    faqs = faq_for(pools, ctx, count=5)
    cta = cta_copy(ctx)

    toks = rep_tokens(kw)

    # ---- 브레드크럼 (HTML + JSON-LD 공용 데이터) ----
    crumb = [("홈", BASE_URL + "/"),
             ("전국 지역별 영어회화", BASE_URL + "/" + quote(REGION_DIRNAME) + "/index.html")]
    for t in toks:
        if t in keyword_set:
            crumb.append((t, canonical_of(t)))
        else:
            crumb.append((t, None))
    crumb.append((keyword, canonical))

    # HTML 브레드크럼 (상대경로 링크)
    crumb_html_items = []
    crumb_html_items.append(f'<li><a href="../index.html">홈</a></li>')
    crumb_html_items.append(f'<li><a href="index.html">전국 지역별 영어회화</a></li>')
    for t in toks:
        if t in keyword_set:
            crumb_html_items.append(f'<li><a href="{esc(page_filename(t))}">{esc(t)}</a></li>')
        else:
            crumb_html_items.append(f'<li>{esc(t)}</li>')
    crumb_html_items.append(f'<li aria-current="page">{esc(keyword)}</li>')
    crumb_html = "\n".join("                    " + x for x in crumb_html_items)

    jsonld = build_jsonld(ctx, canonical, title, desc, crumb, faqs)

    # ---- 커리큘럼 타임라인 ----
    steps_html = []
    for num, t, d in TIMELINE_STEPS:
        steps_html.append(f"""                <div class="timeline__step">
                    <span class="timeline__num">{num}</span>
                    <div>
                        <h3 class="timeline__title">{esc(t)}</h3>
                        <p class="timeline__desc">{esc(d.replace("{kw}", keyword))}</p>
                    </div>
                </div>""")
    steps_html = "\n".join(steps_html)

    # ---- body_blocks 카드 ----
    blocks_html = []
    for b in blocks:
        blocks_html.append(f"""                <div class="card">
                    <div class="card__body">
                        <h3 class="card__title">{esc(b['title'])}</h3>
                        <p class="card__text">{esc(b['text'])}</p>
                    </div>
                </div>""")
    blocks_html = "\n".join(blocks_html)

    # ---- FAQ ----
    faq_html = []
    for f in faqs:
        faq_html.append(f"""                <details>
                    <summary>{esc(f['q'])}</summary>
                    <div class="rg-faq-a">{esc(f['a'])}</div>
                </details>""")
    faq_html = "\n".join(faq_html)

    # ---- 하향(children) 섹션 ----
    children_section = ""
    if children:
        child_kws = sorted({c["keyword"] for c in children})
        head = child_kws[:12]
        rest = child_kws[12:]
        head_pills = "\n".join(
            f'                    <a class="pill" href="{esc(page_filename(c))}">{esc(c)} 영어회화</a>'
            for c in head)
        rest_html = ""
        if rest:
            rest_pills = "\n".join(
                f'                        <a class="pill" href="{esc(page_filename(c))}">{esc(c)} 영어회화</a>'
                for c in rest)
            rest_html = f"""
                <details class="rg-more">
                    <summary>{esc(keyword)} 전체 하위 지역 {len(child_kws)}곳 모두 보기</summary>
                    <div class="rg-pills">
{rest_pills}
                    </div>
                </details>"""
        children_section = f"""
        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">세부 지역</span>
                    <h2 class="section-title">{esc(keyword)} 지역별 영어회화 바로가기</h2>
                    <p class="section-sub">{esc(keyword)} 안의 세부 지역별 영어회화·영어학원 페이지에서 우리 동네에 맞는 정보를 확인해 보세요.</p>
                </div>
                <div class="rg-pills">
{head_pills}
                </div>{rest_html}
            </div>
        </section>"""

    # ---- 측면(siblings) 섹션 ----
    nearby_section = ""
    if siblings:
        sib_kws = sorted({s["keyword"] for s in siblings})[:10]
        sib_pills = "\n".join(
            f'                    <a class="pill" href="{esc(page_filename(s))}">{esc(s)} 영어회화</a>'
            for s in sib_kws)
        nearby_section = f"""
        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">인근 지역</span>
                    <h2 class="section-title">{esc(keyword)} 인근 지역 영어회화</h2>
                    <p class="section-sub">가까운 지역의 영어회화 학원 정보도 함께 살펴보세요.</p>
                </div>
                <div class="rg-pills">
{sib_pills}
                </div>
            </div>
        </section>"""

    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{esc(title)}</title>
    <meta name="description" content="{esc(desc)}">
    <link rel="canonical" href="{esc(canonical)}">

    <meta property="og:title" content="{esc(title)}">
    <meta property="og:description" content="{esc(desc)}">
    <meta property="og:image" content="{esc(og_image)}">
    <meta property="og:url" content="{esc(canonical)}">
    <meta property="og:type" content="website">
    <meta property="og:locale" content="ko_KR">

{head_common("../")}
{REGION_INLINE_CSS}

    <script type="application/ld+json">
{jsonld}
    </script>
</head>
<body>
{header_html("../")}

    <main class="rg-main">
        <nav class="rg-crumb" aria-label="브레드크럼">
            <div class="container">
                <ol>
{crumb_html}
                </ol>
            </div>
        </nav>

        <section class="rg-hero">
            <div class="container">
                <span class="eyebrow">지역별 영어회화</span>
                <h1>{esc(keyword)} <span class="easy">영어회화</span></h1>
                <p class="rg-lead">{esc(intro)}</p>
                <div class="rg-actions">
                    <a href="../index.html#contact" class="btn btn--solid">무료 레벨테스트 신청</a>
                    <a href="../index.html#programs" class="btn btn--outline">커리큘럼 둘러보기</a>
                </div>
            </div>
        </section>

        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">동네 안내</span>
                    <h2 class="section-title">{esc(keyword)}에서 영어회화,<br>이렇게 시작하세요</h2>
                </div>
                <div class="rg-prose">
                    <p>{esc(local_intro)}</p>
                    <p>{esc(intro)}</p>
                </div>
            </div>
        </section>

        <section class="rg-dark section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">수업 운영</span>
                    <h2 class="section-title">이지스피크 {esc(keyword)}<br>커리큘럼 &amp; 운영 방식</h2>
                    <p class="section-sub">{esc(curlead)}</p>
                </div>
                <div class="timeline">
{steps_html}
                </div>
            </div>
        </section>

        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">수강 안내</span>
                    <h2 class="section-title">{esc(keyword)} 영어학원<br>수강 안내</h2>
                    <p class="section-sub">{esc(keyword)} 지역 학습자가 자주 확인하는 실질 정보를 정리했습니다.</p>
                </div>
                <div class="rg-blocks card-grid">
{blocks_html}
                </div>
            </div>
        </section>

        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">자주 묻는 질문</span>
                    <h2 class="section-title">{esc(keyword)} 영어회화<br>자주 묻는 질문</h2>
                </div>
                <div class="rg-faq">
{faq_html}
                </div>
            </div>
        </section>
{children_section}{nearby_section}

        <section class="section rg-cta">
            <div class="container">
                <div class="rg-cta-inner">
                    <h2>{esc(keyword)}에서<br>영어로 말하는 즐거움</h2>
                    <p>{esc(cta)}</p>
                    <a href="../index.html#contact" class="btn btn--ghost">무료 레벨테스트 신청</a>
                </div>
            </div>
        </section>
    </main>

{footer_html("../")}
{PAGE_SCRIPT}
</body>
</html>
"""
    return doc


# ---------------------------------------------------------------------------
# 허브 페이지 (지역/index.html) — 시·도 링크 + 검색
# ---------------------------------------------------------------------------

def render_hub_page(sido_list, sido_counts, total):
    """sido_list: (keyword, has_page) 정렬된 시·도 노드 목록."""
    canonical = BASE_URL + "/" + quote(REGION_DIRNAME) + "/index.html"
    desc = (f"전국 {len(sido_list)}개 시·도의 지역별 영어회화·영어학원 정보를 한 곳에서. "
            f"이지스피크(EZspeak) 지역 페이지에서 우리 동네 영어회화를 찾아보세요.")

    cards = []
    for name in sido_list:
        cnt = sido_counts.get(name, 0)
        cards.append(f"""                <a class="card hub-card" href="{esc(page_filename(name))}" data-name="{esc(name)}">
                    <div class="card__body">
                        <h2 class="card__title">{esc(name)} 영어회화</h2>
                        <p class="card__text">{esc(name)} 지역 영어회화 학원 정보 · {cnt}곳</p>
                    </div>
                </a>""")
    cards_html = "\n".join(cards)

    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>전국 지역별 영어회화 | 시·도별 영어학원 안내 - 이지스피크</title>
    <meta name="description" content="{esc(desc)}">
    <link rel="canonical" href="{esc(canonical)}">

    <meta property="og:title" content="전국 지역별 영어회화 | 이지스피크 EZspeak">
    <meta property="og:description" content="{esc(desc)}">
    <meta property="og:image" content="{esc(BASE_URL + '/logo.png')}">
    <meta property="og:url" content="{esc(canonical)}">
    <meta property="og:type" content="website">
    <meta property="og:locale" content="ko_KR">

{head_common("../")}
{REGION_INLINE_CSS}
    <style>
        .hub-search {{ max-width: 520px; margin-top: 26px; }}
        .hub-search input {{ width: 100%; font-family: var(--font-body); font-size: 16px; color: var(--ink);
            background: var(--paper-2); border: 1.5px solid var(--line-2); border-radius: var(--r-pill);
            padding: 15px 22px; box-shadow: var(--sh-1); }}
        .hub-search input:focus {{ outline: none; border-color: var(--blue); box-shadow: 0 0 0 3px rgba(29,111,194,.14); }}
        .hub-grid {{ margin-top: 8px; }}
        a.hub-card {{ text-decoration: none; }}
        a.hub-card .card__title {{ font-family: var(--font-body); }}
        .hub-empty {{ display: none; color: var(--ink-3); margin-top: 26px; }}
    </style>
</head>
<body>
{header_html("../")}

    <main class="rg-main">
        <nav class="rg-crumb" aria-label="브레드크럼">
            <div class="container">
                <ol>
                    <li><a href="../index.html">홈</a></li>
                    <li aria-current="page">전국 지역별 영어회화</li>
                </ol>
            </div>
        </nav>

        <section class="rg-hero">
            <div class="container">
                <span class="eyebrow">전국 지역별 영어회화</span>
                <h1>우리 동네 <span class="easy">영어회화</span></h1>
                <p class="rg-lead">이지스피크(EZspeak)의 지역별 영어회화·영어학원 안내입니다. 총 {total}개 지역, {len(sido_list)}개 시·도에서 1:1 원어민 회화 수업과 무료 레벨테스트를 제공합니다. 시·도를 선택해 우리 동네 페이지로 이동하세요.</p>
                <div class="hub-search">
                    <input type="text" id="sidoSearch" placeholder="시·도명으로 검색 (예: 서울, 경기, 부산)" autocomplete="off" aria-label="시·도 검색">
                </div>
            </div>
        </section>

        <section class="section" style="padding-top:0;">
            <div class="container">
                <div class="card-grid hub-grid" id="sidoGrid">
{cards_html}
                </div>
                <p class="hub-empty" id="hubEmpty">검색 결과가 없습니다.</p>
            </div>
        </section>
    </main>

{footer_html("../")}
    <script>
        (function () {{
            var btn = document.querySelector('.mobile-menu-btn');
            var nav = document.querySelector('.nav');
            if (btn && nav) {{
                btn.addEventListener('click', function () {{
                    var open = nav.classList.toggle('active');
                    btn.classList.toggle('open', open);
                    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
                }});
            }}
            var header = document.querySelector('.header');
            if (header) {{
                var onScroll = function () {{ header.classList.toggle('scrolled', window.scrollY > 8); }};
                onScroll(); window.addEventListener('scroll', onScroll, {{ passive: true }});
            }}
            var input = document.getElementById('sidoSearch');
            var cards = Array.prototype.slice.call(document.querySelectorAll('.hub-card'));
            var empty = document.getElementById('hubEmpty');
            if (input) {{
                input.addEventListener('input', function () {{
                    var q = this.value.trim().toLowerCase();
                    var any = false;
                    cards.forEach(function (c) {{
                        var match = c.getAttribute('data-name').toLowerCase().indexOf(q) !== -1;
                        c.style.display = match ? '' : 'none';
                        if (match) any = true;
                    }});
                    empty.style.display = any ? 'none' : 'block';
                }});
            }}
        }})();
    </script>
</body>
</html>
"""
    return doc


# ---------------------------------------------------------------------------
# sitemap.xml / robots.txt
# ---------------------------------------------------------------------------

def render_sitemap(keywords):
    urls = [BASE_URL + "/", BASE_URL + "/" + quote(REGION_DIRNAME) + "/index.html"]
    for kw in keywords:
        urls.append(canonical_of(kw["keyword"]))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        lines.append("  <url><loc>%s</loc></url>" % esc(u))
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def render_robots():
    return ("User-agent: *\n"
            "Allow: /\n\n"
            "Sitemap: %s/sitemap.xml\n" % BASE_URL)


# ---------------------------------------------------------------------------
# 로딩 / 시·도 합성 / 인덱스
# ---------------------------------------------------------------------------

def load_keywords(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    keywords = data.get("keywords", [])
    cleaned = []
    seen = set()
    for kw in keywords:
        k = (kw.get("keyword") or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        kw["keyword"] = k
        kw.setdefault("type", "")
        kw["parents"] = [p for p in (kw.get("parents") or []) if p]
        cleaned.append(kw)
    return cleaned, seen


def synthesize_sido(keywords, keyword_set):
    """parents 첫 토큰(시·도)에 대응하는 페이지가 없으면 시·도 중간 페이지를 합성 생성.
    (예: 경기도, 경상남도 등 '도' 단위는 regions.json 에 keyword 로 존재하지 않음.)"""
    sido_tokens = []
    seen = set()
    for kw in keywords:
        toks = rep_tokens(kw)
        if toks:
            t = toks[0]
            if t not in seen:
                seen.add(t)
                sido_tokens.append(t)
    synth = []
    for t in sido_tokens:
        if t not in keyword_set:
            synth.append({"keyword": t, "type": "시", "parents": []})
            keyword_set.add(t)
    return synth


def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT

    if not os.path.exists(input_path):
        print("[오류] 입력 파일이 없습니다: %s" % input_path)
        print("       data/regions.sample.json 으로 테스트하거나 regions.json 을 준비하세요.")
        sys.exit(1)
    if not os.path.exists(POOLS_PATH):
        print("[오류] 콘텐츠 풀이 없습니다: %s" % POOLS_PATH)
        sys.exit(1)

    pools = load_pools(POOLS_PATH)
    keywords, keyword_set = load_keywords(input_path)
    if not keywords:
        print("[오류] 키워드가 비어 있습니다: %s" % input_path)
        sys.exit(1)

    # 시·도 중간 페이지 합성
    synth = synthesize_sido(keywords, keyword_set)
    all_pages = keywords + synth

    # 계층 인덱스: rep_tokens(조상 경로) -> 자식 목록
    by_parent_path = {}
    for kw in all_pages:
        key = tuple(rep_tokens(kw))
        by_parent_path.setdefault(key, []).append(kw)

    def children_of(kw):
        full = tuple(rep_tokens(kw) + [kw["keyword"]])
        return by_parent_path.get(full, [])

    def siblings_of(kw):
        key = tuple(rep_tokens(kw))
        return [s for s in by_parent_path.get(key, []) if s["keyword"] != kw["keyword"]]

    os.makedirs(REGION_DIR, exist_ok=True)

    # 시·도 노드 (허브용): 최상위(조상 없음) 노드들
    sido_nodes = sorted({kw["keyword"] for kw in all_pages if not rep_tokens(kw)})
    # 시·도별 전체 하위 페이지 수
    sido_counts = {}
    for kw in all_pages:
        toks = rep_tokens(kw)
        if toks:
            sido_counts[toks[0]] = sido_counts.get(toks[0], 0) + 1

    # 지역 페이지 생성 + QA
    page_count = 0
    min_len = 10 ** 9
    min_len_kw = ""
    short_pages = 0
    combo_counter = {}
    for kw in all_pages:
        ctx = build_ctx(kw)
        doc = render_region_page(kw, ctx, pools, keyword_set,
                                 children_of(kw), siblings_of(kw))
        out_path = os.path.join(REGION_DIR, page_filename(kw["keyword"]))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(doc)
        page_count += 1
        vlen = visible_len(doc)
        if vlen < min_len:
            min_len, min_len_kw = vlen, kw["keyword"]
        if vlen < MIN_VISIBLE_CHARS:
            short_pages += 1
        # 조합 유일성 카운트 (title/meta/intro/local/faq/body salt 결과)
        combo = (
            kw_hash(ctx["keyword"], "title") % len(pools.titles),
            kw_hash(ctx["keyword"], "meta") % len(pools.metas),
            kw_hash(ctx["keyword"], "intro") % 6,
            tuple(pick_indices(len(pools.faq), 5, ctx["keyword"], "faq")),
        )
        combo_counter[combo] = combo_counter.get(combo, 0) + 1

    dup_combos = sum(1 for v in combo_counter.values() if v > 1)

    # 허브
    hub_path = os.path.join(REGION_DIR, "index.html")
    with open(hub_path, "w", encoding="utf-8") as f:
        f.write(render_hub_page(sido_nodes, sido_counts, len(all_pages)))

    # sitemap
    sitemap_path = os.path.join(ROOT_DIR, "sitemap.xml")
    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write(render_sitemap(all_pages))

    # robots (없을 때만)
    robots_path = os.path.join(ROOT_DIR, "robots.txt")
    robots_created = False
    if not os.path.exists(robots_path):
        with open(robots_path, "w", encoding="utf-8") as f:
            f.write(render_robots())
        robots_created = True

    print("=" * 60)
    print(" 이지스피크 지역 SEO 페이지 생성 완료")
    print("=" * 60)
    print(" 입력 파일          : %s" % input_path)
    print(" BASE_URL           : %s" % BASE_URL)
    print(" 입력 키워드        : %d 개" % len(keywords))
    print(" 시·도 합성 페이지  : %d 개 (%s)" % (
        len(synth), ", ".join(s["keyword"] for s in synth) if synth else "-"))
    print(" 총 지역 페이지     : %d 개  ->  %s/" % (page_count, REGION_DIRNAME))
    print(" 허브 페이지        : %s/index.html (시·도 %d개)" % (REGION_DIRNAME, len(sido_nodes)))
    print(" sitemap.xml        : 총 %d URL" % (page_count + 2))
    print(" robots.txt         : %s" % ("새로 생성" if robots_created else "기존 유지"))
    print(" -- QA --")
    print(" 최소 가시 텍스트   : %d자 (%s)" % (min_len, min_len_kw))
    print(" 1200자 미만 페이지 : %d 개" % short_pages)
    print(" 중복 핵심조합 그룹 : %d 개" % dup_combos)
    print("=" * 60)


if __name__ == "__main__":
    main()
