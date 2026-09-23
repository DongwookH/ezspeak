#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이지스피크(EZspeak) 사이트 공용 렌더링 모듈  (서버리스 전환판)
=====================================================================

지역 페이지 / 허브 / sitemap / robots / llms 의 **HTML·XML 생성 로직**을 한곳에 모은
순수 라이브러리. 파일을 쓰지 않고 문자열만 돌려준다.

사용처
  - api/region.py   : /region/{slug}, /region  실시간 렌더링
  - api/sitemap.py  : /sitemap.xml            실시간 생성
  - api/legacy.py   : /지역/{한글}-영어회화.html -> /region/{slug} 301
  - build_assets.py : robots.txt / llms.txt 정적 산출 (빌드성 작업)
  - build_slugs.py  : 키워드 로딩·계층 유틸 재사용

읽는 파일 (모두 data/ 아래, 모듈 레벨 캐시)
  - data/regions.json   : 7,334개 키워드 입력 ({keyword,type,parents})
  - data/seo_pools.json : 콘텐츠 변형 풀 (titles/meta/faq/local_intros/body_blocks)
  - data/slugs.json     : 한글 키워드 -> 로마자 슬러그 (7,342개, build_slugs.py 산출)

URL 체계
  - 지역 페이지 : /region/{slug}      (예: /region/sillim-dong)
  - 허브       : /region
  - OG 썸네일   : /og/{slug}.png

Python 3 표준 라이브러리만 사용.
"""

import os
import re
import json
import html
import hashlib
import datetime
from urllib.parse import quote

# 콘텐츠 기준 일자 — sitemap lastmod / JSON-LD dateModified / 가시 "최종 업데이트" 에 사용.
#   ⚠️ 서버리스에서 date.today() 를 쓰면 내용이 그대로인데도 매일 lastmod 가 바뀌어
#      검색엔진에 거짓 신선도 신호를 보내게 된다. 콘텐츠를 실제로 손볼 때만 이 값을 올린다.
#      (배포 환경변수 EZ_BUILD_DATE=YYYY-MM-DD 로도 덮어쓸 수 있다.)
CONTENT_DATE = "2026-09-24"
BUILD_DATE = datetime.date.fromisoformat(os.environ.get("EZ_BUILD_DATE") or CONTENT_DATE)
BUILD_DATE_ISO = BUILD_DATE.isoformat()          # 예: 2026-08-14
BUILD_DATE_DOT = BUILD_DATE.strftime("%Y.%m.%d")  # 예: 2026.08.14

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
ASSET_VER = "20260725b"

# 경로
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
# 데이터는 api/_data/ 에 둔다 — api/ 아래는 정적 파일로 공개되지 않으므로
# 서버 함수는 읽을 수 있고 외부에서는 내려받을 수 없다.
DATA_DIR = os.path.join(ROOT_DIR, "api", "_data")
DEFAULT_INPUT = os.path.join(DATA_DIR, "regions.json")
POOLS_PATH = os.path.join(DATA_DIR, "seo_pools.json")
SLUGS_PATH = os.path.join(DATA_DIR, "slugs.json")
# 칼럼(가이드) 목록 — 다른 빌드 단계가 만든다. 없어도 사이트맵은 정상 동작해야 한다.
GUIDES_PATH = os.path.join(DATA_DIR, "guides.json")
# 교재 데이터 (api/textbooks.py 와 공용). 없어도 지역 페이지는 교재 섹션만 빼고 렌더한다.
TEXTBOOKS_PATH = os.path.join(DATA_DIR, "textbooks.json")
GUIDE_PREFIX = "/guide"

# 지역 페이지 URL 프리픽스 (/region/{slug}) 와 허브 경로 (/region)
REGION_PREFIX = "/region"

# 레거시(정적 HTML) 경로 — 301 리다이렉트 매칭에만 사용한다.
LEGACY_DIRNAME = "지역"
PAGE_SUFFIX = "-영어회화.html"

# OG 썸네일 (generate_og_images.py 산출물). 파일명은 슬러그 기준: og/{slug}.png
#  ⚠️ 이 모듈은 이미지 존재 여부를 검사하지 않고 URL 만 심는다.
#     (지역 페이지는 og/{slug}.png, 허브는 og/hub.png, 메인은 og/main.png)
OG_DIRNAME = "og"
OG_SUFFIX = ".png"
OG_WIDTH = "1200"
OG_HEIGHT = "1200"     # 정방형 카드 (generate_og_images.py 의 W/H 와 일치해야 한다)

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


# 병기형 조사 -> (받침 있을 때, 받침 없을 때)
JOSA_PAIRS = {
    "은(는)": ("은", "는"), "이(가)": ("이", "가"), "을(를)": ("을", "를"),
    "과(와)": ("과", "와"), "와(과)": ("과", "와"),
    "으로(로)": ("으로", "로"), "(으)로": ("으로", "로"),
    "(이)": ("이", ""),   # 서술격: 신림동이라는 / 금정구라는
}
# 긴 패턴 우선 ('이(가)' 가 '(이)' 보다 먼저). 앞 글자 1개를 함께 잡는다.
_JOSA_RE = re.compile(
    r"(.?)(" + "|".join(re.escape(k) for k in sorted(JOSA_PAIRS, key=len, reverse=True)) + ")",
    re.S)


def josa(text):
    """'금정구은(는)' -> '금정구는'. 앞 글자의 받침 유무로 병기형 조사를 확정한다.
    한글 음절이 아니면(영문·숫자·괄호·문두) 받침형을 기본으로 쓴다."""
    def repl(m):
        prev = m.group(1)
        has, no = JOSA_PAIRS[m.group(2)]
        if "가" <= prev <= "힣":
            jong = (ord(prev) - 0xAC00) % 28
            if no == "로" and jong == 8:   # ㄹ 받침 뒤는 '으로' 가 아니라 '로'
                return prev + no
            return prev + (has if jong else no)
        # ponytail: 숫자는 읽는 소리(1=일, 2=이)를 따지지 않음 — 숫자 뒤 병기가 생기면 표 추가
        return prev + has
    return _JOSA_RE.sub(repl, text)


def fmt(text, ctx):
    """풀 문자열의 플레이스홀더 치환 + 병기형 조사 확정.
    str.format 대신 명시적 replace 를 사용해 예기치 못한 중괄호로 인한
    크래시를 방지한다 (seo_spec.md 10절: 4개 키만 존재)."""
    for key in ("keyword", "loc", "parent", "sido"):
        text = text.replace("{" + key + "}", ctx.get(key, ""))
    return josa(text)


def legacy_filename(keyword):
    """폐기된 정적 페이지 파일명 (301 매칭용)."""
    return keyword + PAGE_SUFFIX


# ---------------------------------------------------------------------------
# 슬러그 (data/slugs.json — build_slugs.py 산출) : 모듈 레벨 캐시
# ---------------------------------------------------------------------------

_SLUGS = None       # {한글 키워드: 슬러그}
_SLUG_TO_KW = None  # {슬러그: 한글 키워드}


def slugs():
    """한글 키워드 -> 슬러그 맵. 콜드스타트 1회만 읽고 프로세스 내내 재사용."""
    global _SLUGS, _SLUG_TO_KW
    if _SLUGS is None:
        try:
            with open(SLUGS_PATH, "r", encoding="utf-8") as f:
                _SLUGS = json.load(f)
        except (OSError, ValueError):
            _SLUGS = {}
        _SLUG_TO_KW = {v: k for k, v in _SLUGS.items()}
    return _SLUGS


def slug_to_keyword():
    slugs()
    return _SLUG_TO_KW


def slug_of(keyword):
    """키워드의 슬러그. 맵에 없으면 안전한 폴백(퍼센트 인코딩된 한글)을 쓴다."""
    s = slugs().get(keyword)
    return s if s else quote(keyword)


def keyword_of(slug):
    """슬러그 -> 한글 키워드. 없으면 None."""
    return slug_to_keyword().get(slug)


def region_url_path(keyword):
    """루트 기준 지역 페이지 경로."""
    return REGION_PREFIX + "/" + slug_of(keyword)


def hub_url_path():
    return REGION_PREFIX


def canonical_of(keyword):
    return BASE_URL + region_url_path(keyword)


HUB_CANONICAL = BASE_URL + REGION_PREFIX


def og_image_url(keyword):
    """지역별 OG 썸네일 절대 URL (슬러그 파일명 — 인코딩 불필요)."""
    return BASE_URL + "/" + OG_DIRNAME + "/" + slug_of(keyword) + OG_SUFFIX


def og_image_tags(url, alt):
    """og:image 계열 + twitter 카드 태그. 카카오톡 미리보기 안정성을 위해 width/height 명시."""
    return f"""    <meta property="og:image" content="{esc(url)}">
    <meta property="og:image:secure_url" content="{esc(url)}">
    <meta property="og:image:type" content="image/png">
    <meta property="og:image:width" content="{OG_WIDTH}">
    <meta property="og:image:height" content="{OG_HEIGHT}">
    <meta property="og:image:alt" content="{esc(alt)}">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:image" content="{esc(url)}">
    <meta name="twitter:image:alt" content="{esc(alt)}">"""


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


# 시·도 검색수요 가중치 — 동명 지역의 대표 부모를 고를 때 사전순 대신 쓴다.
# 대략 인구·네이버 검색량 순(서울>경기>부산>인천>대구>대전>광주>울산>경남>경북>
# 충남>전북>충북>강원>전남>세종>제주). 숫자 자체에 의미는 없고 상대 순서만 쓴다.
SIDO_WEIGHT = {
    "서울특별시": 100,
    "경기도": 92,
    "부산광역시": 84,
    "인천광역시": 80,
    "대구광역시": 76,
    "대전광역시": 70,
    "광주특별시": 66,
    "울산광역시": 62,
    "경상남도": 58,
    "경상북도": 54,
    "충청남도": 50,
    "전북특별자치도": 46,
    "충청북도": 42,
    "강원특별자치도": 38,
    "세종특별자치시": 24,
    "제주특별자치도": 20,
}

# 가중치만으로는 틀리는 유명 지명의 대표 부모를 직접 지정한다(검색량 큰 짧은 키워드가
# 엉뚱한 지역에 귀속되면 상위노출 손해가 크다). 값은 regions.json 의 parents 문자열과
# 정확히 일치해야 한다 — validate_overrides() 가 부팅 시 검증한다.
REPRESENTATIVE_OVERRIDES = {
    # 실측 오류 3건
    "광주": "광주특별시",                 # 경기도 광주시가 아니라 광주특별시
    "신림": "서울특별시 관악구",
    "중구": "서울특별시",
    # 가중치가 같은 시·도 안에서 엇갈리는 유명 지명
    "신정": "서울특별시 양천구",
    "신정동": "서울특별시 양천구",
    "궁동": "대전광역시 유성구",           # 충남대 앞 학원가
    "사직": "부산광역시 동래구",
    "지산": "대구광역시 수성구",
    "중동": "경기도 부천시",              # 부천 중동신도시
    "백석": "경기도 고양시 일산동구",
    "백석동": "경기도 고양시 일산동구",
    "화정": "경기도 고양시 덕양구",
    "화정동": "경기도 고양시 덕양구",
    "송내": "경기도 부천시",
    "소사": "경기도 부천시",
    "소사동": "경기도 부천시",
    "옥길": "경기도 부천시",
    "옥길동": "경기도 부천시",
    "월곶": "경기도 시흥시",
    "탄현": "경기도 고양시 일산서구",
    "둔산": "대전광역시 서구",
    "삼산": "인천광역시 부평구",
    "상남동": "경상남도 창원시 성산구",
    "점촌": "경상북도 문경시",
    "점촌동": "경상북도 문경시",
    "쌍용": "충청남도 천안시 서북구",
    "쌍용동": "충청남도 천안시 서북구",
    # 검색량 큰 지명 — 가중치 결과와 같지만 회귀 방지용으로 못박아 둔다
    "강남": "서울특별시",
    "강서": "서울특별시",
    "서초": "서울특별시",
    "구로": "서울특별시",
    "삼성": "서울특별시 강남구",
    "삼성동": "서울특별시 강남구",
    "개포": "서울특별시 강남구",
    "대치": "서울특별시 강남구",
    "논현": "서울특별시 강남구",
    "논현동": "서울특별시 강남구",
    "신사": "서울특별시 강남구",
    "신사동": "서울특별시 강남구",
    "반포": "서울특별시 서초구",
    "목동": "서울특별시 양천구",
    "대림": "서울특별시 영등포구",
    "창동": "서울특별시 도봉구",
    "상봉": "서울특별시 중랑구",
    "장안동": "서울특별시 동대문구",
    "공덕": "서울특별시 마포구",
    "신촌": "서울특별시 서대문구",
    "판교": "경기도 성남시 분당구",
    "정자": "경기도 성남시 분당구",
    "정자동": "경기도 성남시 분당구",
    "일산": "경기도 고양시 일산서구",
    "대화": "경기도 고양시 일산서구",
    "수지": "경기도 용인시",
    "죽전": "경기도 용인시 수지구",
    "평촌": "경기도 안양시 동안구",
    "상동": "경기도 부천시",
    "계수": "경기도 부천시",
    "세교": "경기도 오산시",
    "송도": "인천광역시 연수구",
    "계산": "인천광역시 계양구",
    "범어": "대구광역시 수성구",
    "여수": "광주특별시",
    "양산": "경상남도",
    "영천": "경상북도",
    # 위 축약형과 같은 곳을 가리켜야 하는 긴 형태(신림/신림동 같은 별칭 쌍) 정합용
    "강서구": "서울특별시",
    "계산동": "인천광역시 계양구",
    "계수동": "경기도 부천시",
    "대림동": "서울특별시 영등포구",
    "대화동": "경기도 고양시 일산서구",
    "둔산동": "대전광역시 서구",
    "범어동": "대구광역시 수성구",
    "사직동": "부산광역시 동래구",
    "삼산동": "인천광역시 부평구",
    "상봉동": "서울특별시 중랑구",
    "세교동": "경기도 오산시",
    "송내동": "경기도 부천시",
    "송도동": "인천광역시 연수구",
    "신촌동": "서울특별시 서대문구",
    "일산동": "경기도 고양시 일산서구",
    "죽전동": "경기도 용인시 수지구",
    "지산동": "대구광역시 수성구",
    "평촌동": "경기도 안양시 동안구",
}


def sido_weight(parent_path):
    """대표 부모 후보 경로의 시·도 검색수요 가중치."""
    toks = parent_path.split()
    return SIDO_WEIGHT.get(toks[0], 0)


def representative_parent(kw):
    """seo_spec.md 4.4: 여러 parents 중 대표 1개 선택.
    parents 원소는 '경기도 성남시 분당구' 처럼 공백으로 이어진 조상 경로 문자열."""
    ps = [p.strip() for p in (kw.get("parents") or []) if p and p.strip()]
    if not ps:
        return ""
    if len(ps) == 1:
        return ps[0]
    # (0) 유명 지명 오버라이드 (parents 에 실제로 있는 경로일 때만)
    ov = REPRESENTATIVE_OVERRIDES.get(kw.get("keyword"))
    if ov and ov in ps:
        return ov
    # 시·도 검색수요 가중치 내림차순 → 상위 경로(토큰 수 최소) → 사전순
    rank = lambda p: (-sido_weight(p), len(p.split()), p)
    # (a) 단일 토큰 광역 행정명(서울특별시 등)이 있으면 우선
    bare_sido = [p for p in ps if len(p.split()) == 1 and is_sido_token(p)]
    if bare_sido:
        return sorted(bare_sido, key=rank)[0]
    # (b) 그 외
    return sorted(ps, key=rank)[0]


def validate_overrides(keywords):
    """오버라이드 값이 regions.json 의 실제 parents 에 있는지 검사. 문제 항목 목록 반환."""
    by_kw = {k["keyword"]: (k.get("parents") or []) for k in keywords}
    bad = []
    for kw, parent in REPRESENTATIVE_OVERRIDES.items():
        if kw not in by_kw:
            bad.append((kw, parent, "없는 키워드"))
        elif parent not in by_kw[kw]:
            bad.append((kw, parent, "parents 에 없는 경로"))
    return bad


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
        # 대상별(페르소나) 블록 — 풀이 없으면 해당 섹션을 그냥 렌더하지 않는다.
        self.audience = data.get("audience_blocks") or {}
        # 자체 제작 교재 섹션 문구 — 제목 인덱스("0".."6") 별 {heading, lead} 변형.
        self.textbook_leads = data.get("textbook_leads") or {}


def load_pools(path):
    with open(path, "r", encoding="utf-8") as f:
        return Pools(json.load(f))


def title_index_for(pools, ctx):
    """선택된 제목의 인덱스. 교재 연결이 제목과 항상 일치하도록 같은 해시를 공유한다."""
    return kw_hash(ctx["keyword"], "title") % len(pools.titles)


def title_for(pools, ctx):
    return fmt(pools.titles[title_index_for(pools, ctx)], ctx)


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


def audience_blocks_for(pools, ctx):
    """대상별(유아·초등 / 중등 / 성인·직장인) 블록.

    풀의 그룹 순서(= JSON 기재 순서)를 그대로 쓴다 — 연령 순이라 섞지 않는다.
    소제목·본문은 각각 다른 salt 로 뽑아 조합 수를 늘린다."""
    out = []
    for group, g in pools.audience.items():
        heads, texts = (g or {}).get("headings"), (g or {}).get("texts")
        if not heads or not texts:
            continue
        out.append({
            "heading": fmt(pick(heads, ctx["keyword"], "aud_h_" + group), ctx),
            "text": fmt(pick(texts, ctx["keyword"], "aud_t_" + group), ctx),
        })
    return out


# 제목 인덱스 -> 그 고민에 맞는 자체 제작 교재 후보 (seo_pools.json 의 titles 순서와 1:1).
#   제목이 겨냥한 고민 ↔ 노출 교재가 항상 같은 묶음이 되도록 제목 해시를 그대로 쓴다.
#   주석의 과정명은 후보를 고른 기준이고, 화면에 쓰는 과정명은 textbooks.json 의 group 이름이다.
TITLE_BOOKS = [
    ["icantalk", "regular-1-2", "regular-2", "momentum-a"],                    # 0 왕초보 스피킹
    ["nlife-1", "nlife-2", "nlife-3", "regular-5", "regular-6", "regular-7"],  # 1 중급 정체
    ["regular-3", "regular-4", "nlife-1", "nlife-2"],                          # 2 시간·이동
    ["icantalk", "regular-1-2", "regular-2", "momentum-a"],                    # 3 입문 부담
    ["regular-2", "regular-3", "regular-4", "regular-5"],                      # 4 지속·관리
    ["grammarn-1", "grammarn-2", "grammarn-3", "nlife-2"],                     # 5 문법 -> 발화
    ["regular-1-2", "regular-4", "regular-7", "nlife-1"],                      # 6 레벨 진단
]

# 페이지당 노출 교재 수 (후보가 이보다 적으면 있는 만큼).
BOOKS_PER_PAGE = 4

_TEXTBOOKS = None
_BOOK_GROUPS = None


def _load_textbooks():
    """api/_data/textbooks.json -> (slug별 교재, group id별 이름). 파일이 없거나 깨져도 예외 없이 비어 있는 값."""
    global _TEXTBOOKS, _BOOK_GROUPS
    if _TEXTBOOKS is None:
        try:
            with open(TEXTBOOKS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            _TEXTBOOKS = {b["slug"]: b for b in (data.get("books") or [])
                          if isinstance(b, dict) and b.get("slug")}
            _BOOK_GROUPS = {g["id"]: g["name"] for g in (data.get("groups") or [])
                            if isinstance(g, dict) and g.get("id")}
        except (OSError, ValueError, AttributeError, KeyError):
            _TEXTBOOKS, _BOOK_GROUPS = {}, {}
    return _TEXTBOOKS, _BOOK_GROUPS


def textbooks_by_slug():
    return _load_textbooks()[0]


def book_course(b):
    """교재가 속한 과정 이름 (textbooks.json 의 groups). 없으면 빈 문자열."""
    return _load_textbooks()[1].get(b.get("group"), "")


def textbooks_for(pools, ctx, count=BOOKS_PER_PAGE):
    """제목 인덱스에 맞는 자체 제작 교재 묶음 -> (제목 인덱스, [교재, ...]).
    첫 권은 그 제목의 대표 교재, 나머지 순서도 지역 해시로 정해 지역마다 구성이 달라진다.
    데이터가 없으면 None (섹션 통째 생략)."""
    i = title_index_for(pools, ctx)
    if i >= len(TITLE_BOOKS):
        return None
    books = textbooks_by_slug()
    cands = [sl for sl in TITLE_BOOKS[i] if sl in books]
    if not cands:
        return None
    keyword = ctx["keyword"]
    lead = pick(cands, keyword, "regionbook")
    rest = sorted((sl for sl in cands if sl != lead),
                  key=lambda sl: kw_hash(keyword, "bookorder|" + sl))
    return i, [books[sl] for sl in ([lead] + rest)[:count]]


def textbook_lead_for(pools, ctx, i):
    """제목 인덱스별 교재 섹션 문구 {heading, lead}. 풀이 없으면 None."""
    variants = pools.textbook_leads.get(str(i)) if pools.textbook_leads else None
    if not variants:
        return None
    v = pick(variants, ctx["keyword"], "tblead")
    return {"heading": fmt(v.get("heading") or "", ctx), "lead": fmt(v.get("lead") or "", ctx)}


_ARROW = ('<svg width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="%s" '
          'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="%s"></polyline></svg>')
_ARROW_L = _ARROW % (22, 22, "2.2", "15 18 9 12 15 6")
_ARROW_R = _ARROW % (22, 22, "2.2", "9 18 15 12 9 6")
_BS_ARROW_L = _ARROW % (20, 20, "2", "15 18 9 12 15 6")
_BS_ARROW_R = _ARROW % (20, 20, "2", "9 18 15 12 9 6")


def _stage(shots, label, eager_first):
    """한 번에 한 장 크게 보여주고 좌우로 넘기는 이미지 스테이지.
    마크업·클래스는 index.html / api/textbooks.py 와 동일 (동작은 PAGE_SCRIPT 인라인 JS).
    eager_first=True 인 첫 슬라이드의 표지만 즉시 로드하고 나머지는 전부 lazy."""
    items = "".join(
        '<li class="stage-item"><img src="%s"%s%s decoding="async" alt="%s"></li>'
        % (esc(src), ' width="%d" height="%d"' % (int(w), int(h)) if w and h else "",
           "" if (eager_first and k == 0) else ' loading="lazy"', esc(alt))
        for k, (src, w, h, alt, _) in enumerate(shots))
    tabs = "".join('<button type="button" aria-current="%s">%s</button>'
                   % ("true" if k == 0 else "false", esc(cap))
                   for k, (_, _, _, _, cap) in enumerate(shots))
    return f"""<div class="stage" tabindex="0" aria-roledescription="carousel" aria-label="{esc(label)}">
                                <div class="stage-view">
                                    <ul class="stage-track">{items}</ul>
                                    <button type="button" class="stage-arrow stage-prev" aria-label="이전 이미지">{_ARROW_L}</button>
                                    <button type="button" class="stage-arrow stage-next" aria-label="다음 이미지">{_ARROW_R}</button>
                                </div>
                                <div class="stage-bar"><div class="stage-tabs">{tabs}</div><span class="stage-count" aria-live="polite">1 / {len(shots)}</span></div>
                            </div>"""


def _book_shots(b, keyword):
    """교재 한 권의 스테이지 이미지 (표지 + 속지 2장). alt 에 지역명·과정·교재명을 넣는다."""
    name, course = b.get("name") or "", book_course(b)
    label = ("%s %s 교재 %s" % (keyword, course, name)) if course else ("%s 교재 %s" % (keyword, name))
    shots = []
    cover = b.get("cover") or {}
    if cover.get("src"):
        shots.append((cover["src"], cover.get("w"), cover.get("h"), label + " 표지", "표지"))
    pages = [pg for pg in (b.get("pages") or []) if isinstance(pg, dict) and pg.get("src")]
    for k, pg in enumerate(pages[:2], start=1):
        shots.append((pg["src"], pg.get("w"), pg.get("h"), "%s 속지 %d" % (label, k), "속지 %d" % k))
    return shots


def _book_slide(b, shots, pos, total, first):
    """교재 슬라이더의 한 장 = [이미지 스테이지 | 설명]."""
    name, course = b.get("name") or "", book_course(b)
    en = ' <span class="en">%s</span>' % esc(b["name_en"]) if b.get("name_en") else ""
    meta = "".join("<dt>%s</dt><dd>%s</dd>" % (lb, esc(b[key]))
                   for key, lb in (("audience", "대상"), ("series", "구성")) if b.get(key))
    meta_html = '<dl class="bs-meta">%s</dl>' % meta if meta else ""
    desc = '<p class="bs-desc">%s</p>' % esc(b["description"]) if b.get("description") else ""
    course_html = '<p class="book-course">연결 과정 <b>%s</b></p>' % esc(course) if course else ""
    return f"""<li class="bs-slide" role="group" aria-roledescription="slide" aria-label="{pos} / {total}: {esc(name)}">
                            {_stage(shots, "%s 표지·속지 보기" % name, first)}
                            <div class="bs-body">
                                <span class="book-tag">이지스피크 자체 제작</span>
                                <h3 class="bs-name">{esc(name)}{en}</h3>
                                {meta_html}
                                {desc}
                                {course_html}
                            </div>
                        </li>"""


def textbook_section_html(pools, ctx):
    """제목이 겨냥한 고민 -> 그 과정의 자체 제작 교재 3~4권을 좌우로 넘기는 슬라이더로.
    각 권은 표지+속지 2장 스테이지. 교재 데이터가 없으면 빈 문자열(섹션 통째 생략)."""
    picked = textbooks_for(pools, ctx)
    if not picked:
        return ""
    i, books = picked
    keyword = ctx["keyword"]
    shots = [(b, _book_shots(b, keyword)) for b in books]
    shots = [(b, sh) for b, sh in shots if sh]   # 이미지 없는 교재는 뺀다
    if not shots:
        return ""
    slides = [_book_slide(b, sh, k + 1, len(shots), k == 0) for k, (b, sh) in enumerate(shots)]

    lead = textbook_lead_for(pools, ctx, i)
    heading = (lead or {}).get("heading") or "이지스피크 자체 제작 교재"
    lead_html = ('\n                    <p class="section-sub">%s</p>' % esc(lead["lead"])
                 if lead and lead.get("lead") else "")
    return f"""
        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">교재 소개</span>
                    <h2 class="section-title">{esc(heading)}</h2>{lead_html}
                </div>
                <div class="book-slider" aria-roledescription="carousel" aria-label="{esc(keyword)} 영어회화 수업 교재">
                    <div class="bs-viewport" tabindex="0" aria-live="off">
                        <ul class="bs-track">
                            {"".join(slides)}
                        </ul>
                    </div>
                    <div class="bs-controls">
                        <button type="button" class="bs-btn bs-prev" aria-label="이전 교재">{_BS_ARROW_L}</button>
                        <div class="bs-dots"></div>
                        <button type="button" class="bs-btn bs-next" aria-label="다음 교재">{_BS_ARROW_R}</button>
                    </div>
                </div>
                <p class="rg-books-more"><a href="/textbooks">이지스피크 자체 제작 교재 전체 보기</a></p>
            </div>
        </section>"""


# ---- 기존 인트로/CTA 변형 (loc 활용, seo_spec.md 6절 "기존 유지") -------------

def intro_paragraph(ctx):
    keyword = ctx["keyword"]
    loc = ctx["loc"]
    variants = [
        (f"{loc}에서 영어회화를 시작하려는 분들께. 이지스피크(EZspeak)는 "
         f"{keyword} 지역 학습자를 위한 실전 회화 중심 영어 교육을 100% 온라인으로 제공합니다. "
         f"시험을 위한 영어가 아니라, 실제로 입이 트이는 영어를 목표로 합니다."),
        (f"{keyword} 영어회화, 어디서 시작해야 할지 고민이라면 이지스피크가 함께합니다. "
         f"{loc}에서 생활하고 일하는 분들의 눈높이에 맞춰, 초급부터 고급까지 "
         f"수준별 speaking 커리큘럼을 온라인 1:1 수업으로 진행합니다."),
        (f"복잡한 문법 암기는 이제 그만. {loc} 학습자와 화면으로 만나는 이지스피크는 "
         f"{keyword} 지역 수강생이 실제 상황에서 바로 반응하고 말할 수 있도록 "
         f"1:1 원어민 수업과 밀착 학습 관리를 함께 제공하는 온라인 영어회화 전문 학원입니다."),
        (f"아쉬웠던 영어를 아, 쉬운 영어로. {keyword} 영어회화를 준비하는 "
         f"{loc} 학습자에게 이지스피크는 유아부터 성인까지 누구나 자신의 속도에 맞춰 "
         f"영어가 '부담'이 아닌 '도구'가 되도록 돕습니다. 모든 수업은 온라인으로 진행됩니다."),
        (f"{loc}에서 영어로 말하는 즐거움을 되찾고 싶다면 이지스피크와 함께하세요. "
         f"{keyword} 지역 특성과 수강생 목표에 맞춘 맞춤형 회화 수업으로, "
         f"말할수록 입이 트이고 참여할수록 자신감이 쌓이는 양방향 온라인 수업을 경험할 수 있습니다."),
        (f"{keyword}에서 믿을 수 있는 영어회화 수업을 찾는다면, "
         f"{loc} 학습자를 위한 온라인 영어회화 이지스피크(EZspeak)를 확인해 보세요. "
         f"이동 없이 집에서 듣는 온라인 1:1 수업, 매일 쓰는 표현 중심의 커리큘럼으로 결과를 만듭니다."),
    ]
    return pick(variants, keyword, "intro")


def curriculum_lead(ctx):
    keyword = ctx["keyword"]
    loc = ctx["loc"]
    variants = [
        f"{keyword} 영어학원을 고를 때 가장 중요한 것은 실제로 말하는 시간입니다. 이지스피크의 운영 방식을 확인해 보세요.",
        f"{loc} 수강생을 위한 이지스피크만의 운영 방식은 이렇게 다릅니다.",
        f"말이 트이는 데에는 이유가 있습니다. {keyword} 지역에서도 1:1 원어민 화상 수업과 플래너 관리로 운영하는 이지스피크 학습 시스템.",
        f"{keyword} 원어민 회화부터 학습 관리까지, 이지스피크의 3단계 운영 원칙을 소개합니다.",
        f"이지스피크가 {loc} 학습자의 수업과 학습 관리를 어떻게 운영하는지 정리했습니다.",
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

def head_common():
    """스타일시트만 로드. (본문 전 영역 Pretendard — style.css @import 로 공급.
    지역 페이지에는 별도 웹폰트를 싣지 않아 로딩을 가볍게 유지한다.)
    ⚠️ /region/{slug} 는 경로 깊이가 고정이 아니므로 반드시 루트 절대경로를 쓴다."""
    return f"""    <link rel="icon" type="image/png" href="/favicon.png">
    <link rel="apple-touch-icon" href="/apple-touch-icon.png">
    <link rel="stylesheet" href="/style.css?v={ASSET_VER}">"""


def contact_href(src=None):
    """상담 CTA 링크. src(유입 슬러그)가 있으면 /?from={src}#contact.
    메인 script.js 가 from 쿼리를 읽어 상담폼 hidden 필드에 넣는다 (형식 변경 금지).
    canonical·sitemap·JSON-LD 에는 쓰지 않는다 — 링크 href 전용."""
    return "/?from=%s#contact" % src if src else "/#contact"


def header_html(src=None):
    """index.html 과 동일한 .header 마크업. 링크는 /#앵커 (루트 절대경로)."""
    return f"""    <header class="header">
        <div class="container">
            <div class="logo">
                <a href="/" aria-label="이지스피크 홈"><img src="/logo.png" width="32" height="32" alt="이지스피크 EZspeak 로고"><span class="logo-word">이지스피크</span></a>
            </div>
            <nav class="nav" aria-label="주요 메뉴">
                <ul>
                    <li><a href="/#about">학원소개</a></li>
                    <li><a href="/#programs">커리큘럼</a></li>
                    <li><a href="/#features">운영 방식</a></li>
                    <li><a href="/#reviews">후기</a></li>
                    <li><a href="{esc(contact_href(src))}">상담문의</a></li>
                </ul>
            </nav>
            <button class="mobile-menu-btn" aria-label="메뉴 열기" aria-expanded="false">
                <span></span>
                <span></span>
                <span></span>
            </button>
        </div>
    </header>"""


def footer_html(src=None):
    return f"""    <footer class="site-footer">
        <div class="container">
            <div class="footer-brand">EZspeak</div>
            <p style="margin-bottom:14px;"><a href="{REGION_PREFIX}">전국 지역별 영어회화</a></p>
            <p class="footer-meta">대표: {BUSINESS_OWNER} &nbsp;|&nbsp; 전화: {BUSINESS_PHONE} &nbsp;|&nbsp; 이메일: {BUSINESS_EMAIL}</p>
        </div>
    </footer>

    <nav class="mobile-cta-bar" aria-label="빠른 상담">
        <a href="{esc(contact_href(src))}" class="mc-test">
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
        /* 교재 슬라이더(바깥) + 이미지 스테이지(안쪽) — 메인 script.js 와 같은 동작.
           지역 페이지는 자동 넘김·필터 없이 이전/다음·점·스와이프·키보드만 쓴다. */
        (function () {
            Array.prototype.forEach.call(document.querySelectorAll('.stage-view, .bs-viewport'), function (v) {
                v.addEventListener('scroll', function () { if (v.scrollLeft) v.scrollLeft = 0; }, { passive: true });
            });

            /* 스테이지 안의 키·스와이프는 여기서 멈춰(stopPropagation) 바깥 교재 슬라이더로 가지 않는다 */
            function initStage(root) {
                var track = root.querySelector('.stage-track');
                var items = Array.prototype.slice.call(root.querySelectorAll('.stage-item'));
                var tabs = Array.prototype.slice.call(root.querySelectorAll('.stage-tabs button'));
                var count = root.querySelector('.stage-count');
                var n = items.length, i = 0;
                if (!track || !n) return null;
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
                    e.stopPropagation();
                    go(i + (e.key === 'ArrowRight' ? 1 : -1), true);
                });
                var view = root.querySelector('.stage-view'), x0 = null, y0 = 0;
                view.addEventListener('touchstart', function (e) {
                    e.stopPropagation(); x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
                }, { passive: true });
                view.addEventListener('touchend', function (e) {
                    e.stopPropagation();
                    if (x0 === null) return;
                    var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
                    x0 = null;
                    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) go(i + (dx < 0 ? 1 : -1), true);
                }, { passive: true });
                go(0, false);
                /* 화면 밖에 있는 교재는 전환 없이 표지로 되돌린다 */
                function reset() {
                    if (i === 0) return;
                    track.style.transition = 'none';
                    go(0, false);
                    void track.offsetWidth;
                    track.style.transition = '';
                }
                return { reset: reset, eager: eager };
            }

            Array.prototype.forEach.call(document.querySelectorAll('.book-slider'), function (root) {
                var viewport = root.querySelector('.bs-viewport');
                var track = root.querySelector('.bs-track');
                var slides = Array.prototype.slice.call(root.querySelectorAll('.bs-slide'));
                var dotsBox = root.querySelector('.bs-dots');
                if (!track || !slides.length) return;
                var stages = slides.map(function (sl) {
                    var st = sl.querySelector('.stage');
                    return st ? initStage(st) : null;
                });
                var n = slides.length, index = 0;
                var dots = slides.map(function (_, p) {
                    var b = document.createElement('button');
                    b.type = 'button';
                    b.setAttribute('aria-label', (p + 1) + '번째 교재 보기');
                    b.addEventListener('click', function () { goTo(p); });
                    if (dotsBox) dotsBox.appendChild(b);
                    return b;
                });
                function goTo(p) {
                    index = (p + n) % n;
                    var next = (index + 1) % n;
                    track.style.transform = 'translateX(-' + (index * 100) + '%)';
                    slides.forEach(function (sl, k) {
                        var on = k === index;
                        sl.inert = !on;
                        sl.setAttribute('aria-hidden', String(!on));
                        var st = stages[k];
                        if (!st) return;
                        /* 보고 있는 교재는 표지·속지 1, 다음 교재는 표지만 미리 받는다 */
                        if (on) { st.reset(); st.eager(0); st.eager(1); } else if (k === next) st.eager(0);
                    });
                    dots.forEach(function (d, k) { d.setAttribute('aria-current', String(k === index)); });
                }
                root.querySelector('.bs-prev').addEventListener('click', function () { goTo(index - 1); });
                root.querySelector('.bs-next').addEventListener('click', function () { goTo(index + 1); });
                root.addEventListener('keydown', function (e) {
                    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
                    e.preventDefault();
                    goTo(index + (e.key === 'ArrowRight' ? 1 : -1));
                });
                var x0 = null, y0 = 0;
                viewport.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
                viewport.addEventListener('touchend', function (e) {
                    if (x0 === null) return;
                    var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
                    x0 = null;
                    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) goTo(index + (dx < 0 ? 1 : -1));
                }, { passive: true });
                goTo(0);
            });
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

        /* 핵심 정보 그리드 — AI 답변엔진이 추출하기 쉬운 라벨-값 구조 */
        .rg-facts { margin-top: 26px; max-width: 760px; display: grid;
            grid-template-columns: 1fr 1fr; gap: 0; border: 1px solid var(--line);
            border-radius: var(--r-md); overflow: hidden; background: #fff; }
        .rg-facts > div { display: flex; gap: 12px; padding: 11px 16px;
            border-top: 1px solid var(--line); font-size: 14px; line-height: 1.6; }
        .rg-facts > div:nth-child(-n+2) { border-top: 0; }
        .rg-facts dt { flex: 0 0 74px; color: var(--ink-2); font-weight: 700; word-break: keep-all; }
        .rg-facts dd { color: var(--ink); word-break: keep-all; }
        @media (max-width: 720px) {
            .rg-facts { grid-template-columns: 1fr; }
            .rg-facts > div:nth-child(2) { border-top: 1px solid var(--line); }
        }

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

        /* 대상별(연령대별) 블록 */
        .rg-aud { margin-top: 24px; display: grid; gap: 16px; max-width: 74ch; }
        .rg-aud-item { border-left: 2px solid var(--line-2); padding-left: 18px; }
        .rg-aud-item h3 { font-size: 17px; font-weight: 700; color: var(--ink); word-break: keep-all; }
        .rg-aud-item p { margin-top: 9px; color: var(--ink-2); font-size: 15px; line-height: 1.78; word-break: keep-all; }

        /* 자체 제작 교재 — 제목에 맞는 3~4권을 좌우로 넘기는 슬라이더 (틀은 style.css 의 .book-slider/.bs-*) */
        .rg-books-more { margin-top: 14px; font-size: 14px; }
        .rg-books-more a { color: var(--blue-deep); font-weight: 700;
            text-decoration: underline; text-underline-offset: 3px; }

        /* 이미지 스테이지 — index.html / api/textbooks.py 의 .stage 와 같은 규칙 (여기는 인라인) */
        .stage { min-width: 0; }
        .stage:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
        .stage-view { position: relative; overflow: hidden; overflow: clip; background: #F3F6FA;
            border: 1px solid var(--line-2); border-radius: var(--r-md); touch-action: pan-y; }
        /* overflow: clip — 찾기·포커스 이동으로 틀이 가로 스크롤돼 슬라이드가 어긋나는 것 방지 */
        .bs-viewport { overflow: hidden; overflow: clip; touch-action: pan-y; }
        .stage-track { list-style: none; margin: 0; padding: 0; display: flex; transition: transform .35s ease; }
        .stage-item { flex: 0 0 100%; min-width: 0; height: 520px; padding: 16px 64px;
            display: flex; align-items: center; justify-content: center; }  /* 좌우 64px = 화살표 자리 */
        /* max-width/max-height 로 가두어야 세로형 표지도 잘리지 않는다 */
        .stage-item img { display: block; width: auto; height: auto; max-width: 100%; max-height: 100%; }
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
        @media (max-width: 940px) {
            .stage-item { height: 440px; }
        }
        @media (max-width: 640px) {
            .stage-item { height: 440px; padding: 8px; }
            .stage-arrow { width: 36px; height: 36px; }
            .stage-prev { left: 6px; }
            .stage-next { right: 6px; }
        }

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

        .rg-inline-cta { padding: 4px 0 clamp(30px, 4.5vw, 48px); }
        .rg-inline-cta-inner { background: var(--blue-tint); border: 1px solid var(--line);
            border-radius: var(--r-lg); padding: 22px clamp(18px, 3vw, 28px);
            display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; }
        .rg-inline-cta p { margin: 0; max-width: 56ch; font-size: 15px; color: var(--ink-2);
            line-height: 1.72; word-break: keep-all; }
        .rg-inline-cta p strong { display: block; color: var(--ink); font-weight: 700; }
        .rg-inline-cta-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; }
        .rg-inline-link { color: var(--blue-deep); font-weight: 700; font-size: 14px;
            text-decoration: underline; text-underline-offset: 3px; white-space: nowrap; }

        .rg-cta { text-align: center; }
        .rg-cta .rg-cta-inner { background: var(--blue-deep); color: #fff;
            border-radius: var(--r-lg); padding: clamp(36px, 6vw, 64px) 22px; }
        .rg-cta h2 { font-family: var(--font-body); font-weight: 800; color: #fff;
            font-size: clamp(24px, 4.6vw, 38px); line-height: 1.18; letter-spacing: -.02em; word-break: keep-all; }
        .rg-cta p { margin: 14px auto 24px; max-width: 52ch; color: rgba(255,255,255,.82); word-break: keep-all; }

        .rg-updated { text-align: center; font-size: 12.5px; color: var(--ink-3); margin: 0; padding: 8px 0 26px; }
    </style>"""


# ---------------------------------------------------------------------------
# JSON-LD @graph (seo_spec.md 5.3)
# ---------------------------------------------------------------------------

def build_jsonld(ctx, canonical, title, desc, crumb_items, faqs, og_image=None):
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
            # 조직 정의는 메인 페이지와 완전히 동일해야 한다 — 같은 @id 를 지역별로
            # 다르게(areaServed=Place 등) 선언하면 지식그래프에서 엔티티가 분열된다.
            "@type": "EducationalOrganization",
            "@id": business_id,
            "name": BUSINESS_NAME,
            "alternateName": "EZspeak",
            "url": BASE_URL + "/",
            "telephone": BUSINESS_PHONE,
            "email": BUSINESS_EMAIL,
            "image": BASE_URL + "/logo.png",
            "logo": BASE_URL + "/logo.png",
            "description": ("1:1 원어민 수업과 한국인 플래너의 밀착 학습 관리로 실전 영어회화를 완성하는 "
                            "100% 온라인 영어회화 전문 학원. 모든 수업이 실시간 화상으로 진행되며 "
                            "오프라인 지점·대면 수업은 운영하지 않습니다."),
            "areaServed": {"@type": "Country", "name": "대한민국"},
            "knowsLanguage": ["ko", "en"],
            "founder": {"@type": "Person", "name": BUSINESS_OWNER},
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
            "datePublished": BUILD_DATE_ISO,
            "dateModified": BUILD_DATE_ISO,
            "about": {"@id": business_id},
            "isPartOf": {"@id": website_id},
            "author": {"@id": business_id},
            "publisher": {"@id": business_id},
        },
        {
            "@type": "BreadcrumbList",
            "@id": canonical + "#breadcrumb",
            "itemListElement": breadcrumb_els,
        },
    ]

    if og_image:
        # 지역별 OG 썸네일을 페이지 대표 이미지로도 노출 (SNS/검색 미리보기 일관성)
        webpage = graph[2]
        webpage["primaryImageOfPage"] = {
            "@type": "ImageObject",
            "@id": canonical + "#primaryimage",
            "url": og_image,
            "contentUrl": og_image,
            "width": int(OG_WIDTH),
            "height": int(OG_HEIGHT),
        }
        webpage["image"] = {"@id": canonical + "#primaryimage"}

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
    ("01", "1:1 원어민 온라인 회화 수업",
     "원어민 강사와 1:1로 진행하는 맞춤 회화 수업으로 {kw} 지역 수강생의 실전 스피킹 실력을 키웁니다. 정해진 교재를 읽는 방식이 아니라 실제 상황을 가정한 대화 중심이며, 모든 수업은 실시간 화상으로 진행됩니다."),
    ("02", "1:1 한국인 플래너 밀착 케어",
     "수업 외 시간에도 담당 플래너가 예습·복습과 학습 스케줄을 관리해 혼자서는 이어가기 어려운 꾸준함을 함께 만들어 갑니다."),
    ("03", "레벨별 커리큘럼과 부가 콘텐츠",
     "무료 레벨테스트 결과에 맞춘 단계별 커리큘럼과 복습용 학습 자료로, {kw} 영어학원을 처음 찾는 왕초보부터 실무 회화까지 폭넓게 대응합니다."),
]


def render_region_page(kw, ctx, pools, keyword_set, children, siblings):
    keyword = ctx["keyword"]
    canonical = canonical_of(keyword)
    # 상담 CTA 유입 슬러그 (href 전용, canonical 에는 붙이지 않음)
    src = slug_of(keyword)
    contact = esc(contact_href(src))
    # 지역별 고유 OG 썸네일 (generate_og_images.py 로 미리 생성해 두어야 한다)
    og_image = og_image_url(keyword)
    og_image_alt = "%s 영어회화 - 이지스피크, 집에서 하는 온라인 어학연수" % keyword

    title = title_for(pools, ctx)
    desc = meta_for(pools, ctx)
    intro = intro_paragraph(ctx)
    local_intro = local_intro_for(pools, kw, ctx)
    curlead = curriculum_lead(ctx)
    blocks = body_blocks_for(pools, ctx)
    audiences = audience_blocks_for(pools, ctx)
    faqs = faq_for(pools, ctx, count=5)
    cta = cta_copy(ctx)

    toks = rep_tokens(kw)

    # ---- 브레드크럼 (HTML + JSON-LD 공용 데이터) ----
    crumb = [("홈", BASE_URL + "/"),
             ("전국 지역별 영어회화", HUB_CANONICAL)]
    for t in toks:
        if t in keyword_set:
            crumb.append((t, canonical_of(t)))
        else:
            crumb.append((t, None))
    crumb.append((keyword, canonical))

    # HTML 브레드크럼 (루트 절대경로 링크)
    crumb_html_items = []
    crumb_html_items.append('<li><a href="/">홈</a></li>')
    crumb_html_items.append(f'<li><a href="{REGION_PREFIX}">전국 지역별 영어회화</a></li>')
    for t in toks:
        if t in keyword_set:
            crumb_html_items.append(f'<li><a href="{esc(region_url_path(t))}">{esc(t)}</a></li>')
        else:
            crumb_html_items.append(f'<li>{esc(t)}</li>')
    crumb_html_items.append(f'<li aria-current="page">{esc(keyword)}</li>')
    crumb_html = "\n".join("                    " + x for x in crumb_html_items)

    jsonld = build_jsonld(ctx, canonical, title, desc, crumb, faqs, og_image)

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

    # ---- 대상별 블록 (롱테일: "{지역} 초등/중학생/직장인 영어회화") ----
    audience_section = ""
    if audiences:
        aud_items = "\n".join(f"""                    <div class="rg-aud-item">
                        <h3>{esc(a['heading'])}</h3>
                        <p>{esc(a['text'])}</p>
                    </div>""" for a in audiences)
        audience_section = f"""
        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">대상별 안내</span>
                    <h2 class="section-title">{esc(keyword)} 영어회화<br>대상별로 보기</h2>
                    <p class="section-sub">{esc(josa(keyword + "은(는)"))} 유아·초등부터 중학생, 성인·직장인까지 같은 온라인 1:1 방식으로 수강합니다. 연령대별로 자주 묻는 점을 정리했습니다.</p>
                </div>
                <div class="rg-aud">
{aud_items}
                </div>
            </div>
        </section>"""

    # ---- 자체 제작 교재 (제목이 겨냥한 고민 -> 그 과정의 교재 1권, 표지+속지) ----
    textbook_section = textbook_section_html(pools, ctx)

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
            f'                    <a class="pill" href="{esc(region_url_path(c))}">{esc(c)} 영어회화</a>'
            for c in head)
        rest_html = ""
        if rest:
            rest_pills = "\n".join(
                f'                        <a class="pill" href="{esc(region_url_path(c))}">{esc(c)} 영어회화</a>'
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
            f'                    <a class="pill" href="{esc(region_url_path(s))}">{esc(s)} 영어회화</a>'
            for s in sib_kws)
        nearby_section = f"""
        <section class="section">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">인근 지역</span>
                    <h2 class="section-title">{esc(keyword)} 인근 지역 영어회화</h2>
                    <p class="section-sub">이지스피크는 전 지역 온라인 1:1 수업으로 진행됩니다. 인근 지역 페이지도 함께 살펴보세요.</p>
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
{og_image_tags(og_image, og_image_alt)}
    <meta property="og:url" content="{esc(canonical)}">
    <meta property="og:type" content="website">
    <meta property="og:locale" content="ko_KR">

{head_common()}
{REGION_INLINE_CSS}

    <script type="application/ld+json">
{jsonld}
    </script>
</head>
<body>
{header_html(src)}

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
                <p class="rg-lead">{esc(keyword)} 영어회화는 학원 방문 없이 100% 온라인 1:1 원어민 화상 수업으로 시작할 수 있습니다. 무료 레벨테스트로 현재 말하기 수준을 확인한 뒤, 담당 플래너가 맞는 과정을 안내해 드립니다.</p>
                <dl class="rg-facts">
                    <div><dt>수업 방식</dt><dd>100% 온라인 1:1 원어민 화상 수업 (오프라인 지점 없음)</dd></div>
                    <div><dt>수업 횟수</dt><dd>주 1~5회 중 선택</dd></div>
                    <div><dt>수강 대상</dt><dd>유아·초등·중등·성인 전 연령</dd></div>
                    <div><dt>운영 과정</dt><dd>일상영어회화 · 비즈니스 · 여행영어 · 시사토론 · 중등교과 · 키즈영어 · 문법어휘</dd></div>
                    <div><dt>레벨테스트</dt><dd>무료 · 약 10분 · 온라인 진행</dd></div>
                    <div><dt>수강료</dt><dd>과정·횟수에 따라 상담 시 개별 안내</dd></div>
                    <div><dt>수강 지역</dt><dd>{esc(keyword)} 포함 전국 어디서나 (인터넷만 있으면 수강 가능)</dd></div>
                    <div><dt>상담 방법</dt><dd>홈페이지 상담 폼 · 이메일</dd></div>
                </dl>
                <div class="rg-actions">
                    <a href="{contact}" class="btn btn--solid">무료 레벨테스트 신청</a>
                    <a href="/#programs" class="btn btn--outline">커리큘럼 둘러보기</a>
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
                    <p>{esc(intro)}</p>
                    <p>{esc(local_intro)}</p>
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
{textbook_section}

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
{audience_section}

        <section class="rg-inline-cta">
            <div class="container">
                <div class="rg-inline-cta-inner">
                    <p><strong>{esc(keyword)} 영어회화, 어디서부터 시작할지 고민되시나요?</strong>무료 레벨테스트로 지금 말하기 수준을 확인하고, 나에게 맞는 과정부터 시작해 보세요. 상담과 테스트 모두 온라인으로 진행되어 방문이 필요 없습니다.</p>
                    <div class="rg-inline-cta-actions">
                        <a href="{contact}" class="btn btn--solid">무료 레벨테스트 신청</a>
                        <a href="/#faq" class="rg-inline-link">자주 묻는 질문 먼저 보기</a>
                    </div>
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
                    <a href="{contact}" class="btn btn--ghost">무료 레벨테스트 신청</a>
                </div>
            </div>
        </section>
    </main>

    <div class="container"><p class="rg-updated">최종 업데이트: {BUILD_DATE_DOT}</p></div>

{footer_html(src)}
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
    canonical = HUB_CANONICAL
    desc = (f"전국 {len(sido_list)}개 시·도의 지역별 영어회화·영어학원 정보를 한 곳에서. "
            f"이지스피크(EZspeak)는 100% 온라인 1:1 원어민 수업으로 전국 어디서나 동일하게 이용할 수 있습니다.")

    cards = []
    for name in sido_list:
        cnt = sido_counts.get(name, 0)
        cards.append(f"""                <a class="card hub-card" href="{esc(region_url_path(name))}" data-name="{esc(name)}">
                    <div class="card__body">
                        <h2 class="card__title">{esc(name)} 영어회화</h2>
                        <p class="card__text">{esc(name)} 지역 영어회화 학원 정보 · {cnt}곳</p>
                    </div>
                </a>""")
    cards_html = "\n".join(cards)

    # ---- 허브 JSON-LD (CollectionPage + ItemList + BreadcrumbList + EducationalOrganization) ----
    business_id = BASE_URL + "/#business"
    website_id = BASE_URL + "/#website"
    item_els = []
    for i, name in enumerate(sido_list, start=1):
        item_els.append({
            "@type": "ListItem",
            "position": i,
            "name": name + " 영어회화",
            "url": canonical_of(name),
        })
    hub_graph = [
        {
            "@type": "EducationalOrganization",
            "@id": business_id,
            "name": BUSINESS_NAME,
            "url": BASE_URL + "/",
            "telephone": BUSINESS_PHONE,
            "email": BUSINESS_EMAIL,
            "image": BASE_URL + "/logo.png",
            "description": ("1:1 원어민 수업과 한국인 플래너의 밀착 학습 관리로 실전 영어회화를 완성하는 온라인 영어회화 전문 학원. "
                            "모든 수업은 100% 온라인 실시간 화상으로 진행되며 오프라인 지점·대면 수업은 운영하지 않습니다."),
            "areaServed": {"@type": "Country", "name": "대한민국"},
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
            "@type": "CollectionPage",
            "@id": canonical + "#webpage",
            "url": canonical,
            "name": "전국 지역별 영어회화",
            "description": desc,
            "inLanguage": "ko",
            "datePublished": BUILD_DATE_ISO,
            "dateModified": BUILD_DATE_ISO,
            "isPartOf": {"@id": website_id},
            "about": {"@id": business_id},
            "primaryImageOfPage": {
                "@type": "ImageObject",
                "@id": canonical + "#primaryimage",
                "url": BASE_URL + "/" + quote(OG_DIRNAME) + "/hub.png",
                "contentUrl": BASE_URL + "/" + quote(OG_DIRNAME) + "/hub.png",
                "width": int(OG_WIDTH),
                "height": int(OG_HEIGHT),
            },
            "image": {"@id": canonical + "#primaryimage"},
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": len(sido_list),
                "itemListElement": item_els,
            },
        },
        {
            "@type": "BreadcrumbList",
            "@id": canonical + "#breadcrumb",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "홈", "item": BASE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "전국 지역별 영어회화", "item": canonical},
            ],
        },
    ]
    hub_jsonld = json.dumps({"@context": "https://schema.org", "@graph": hub_graph},
                            ensure_ascii=False, indent=2)

    # ---- 허브 소개 프로즈 (순텍스트 1,500자 이상 — 지역별 영어회화 서비스 소개/이용법/시·도 안내) ----
    sido_names_line = " · ".join(sido_list)
    hub_intro_html = f"""
        <section class="section" style="padding-bottom:0;">
            <div class="container">
                <div class="rg-prose" style="max-width:78ch;">
                    <p>이지스피크(EZspeak)는 시험을 위한 영어가 아니라 실제로 입이 트이는 영어, 곧 &lsquo;말이 되는 영어&rsquo;를 목표로 하는 실전 영어회화 전문 학원입니다. 모든 수업은 100% 온라인 실시간 화상으로 진행되며, 오프라인 지점이나 대면 수업은 운영하지 않습니다. 이 페이지는 전국 {total}개 지역, {len(sido_list)}개 시·도에 걸친 이지스피크 지역별 영어회화 안내를 한곳에 모은 허브입니다. 우리 동네 이름으로 개설된 페이지에서 1:1 원어민 회화 수업, 한국인 플래너의 밀착 학습 관리, 무료 레벨테스트 등 이지스피크가 제공하는 학습 방식을 지역 맥락에 맞춰 확인하실 수 있습니다. 영어회화를 처음 알아보는 분이라면, 먼저 내가 사는 지역 페이지를 열어 어떤 수업이 진행되는지, 어떤 절차로 시작하는지부터 살펴보시길 권합니다.</p>
                    <p>지역별 영어회화 페이지는 단순히 지역명만 바꾼 안내가 아니라, 해당 지역 학습자가 가장 궁금해하는 정보를 중심으로 구성했습니다. 각 페이지에는 이지스피크의 3단계 운영 방식, 즉 원어민 강사와의 1:1 화상 회화 수업, 수업 외 시간까지 챙기는 한국인 플래너의 예·복습 관리, 그리고 레벨테스트 결과에 맞춘 단계별 커리큘럼과 복습 콘텐츠가 정리되어 있습니다. 여기에 수강 안내와 함께 수강료·수업 방식·수업 횟수·대상 연령을 다루는 자주 묻는 질문까지 담아, 상담 전에 궁금증을 미리 해소할 수 있도록 했습니다. 초등학생부터 성인 직장인까지, 그리고 알파벳이 낯선 왕초보부터 실무에서 바로 쓰는 비즈니스 회화까지 각자의 상황에 맞는 시작점을 찾을 수 있습니다.</p>
                    <p>우리 동네 페이지를 찾는 방법은 간단합니다. 위쪽 검색창에 시·도명(예: 서울, 경기, 부산)을 입력하면 해당 시·도 카드가 바로 필터링됩니다. 시·도 페이지로 들어가면 그 안의 시·군·구, 다시 그 아래의 읍·면·동으로 단계별로 좁혀 이동할 수 있어, 내가 생활하고 일하는 동네와 가장 가까운 영어회화 안내까지 확인할 수 있습니다. 반대로 세부 지역 페이지에서는 상위 지역과 인근 지역으로도 자유롭게 이동할 수 있어, 직장이 있는 지역과 사는 지역의 안내를 함께 비교해 보기에도 좋습니다. 수업 자체는 어느 지역 페이지로 들어오시든 동일한 온라인 1:1 방식이므로, 오가는 거리나 교통편을 따질 필요 없이 시간대만 맞추면 됩니다.</p>
                    <p>이지스피크는 일상영어회화, 비즈니스영어회화, 여행영어, 시사토론, 중등교과, 키즈영어, 문법·어휘까지 모두 7개 과정을 운영합니다. 일상 대화가 목표라면 매일 쓰는 표현 중심의 일상영어회화가, 업무에 당장 필요하다면 회의·이메일·프레젠테이션을 다루는 비즈니스영어회화가 적합합니다. 유아와 초등 자녀에게는 놀이로 익히며 자신감을 붙이는 키즈영어, 중학생에게는 내신과 실용 영어를 함께 잡는 중등교과 과정을 마련했습니다. 어떤 과정이 나에게 맞을지는 무료 레벨테스트로 현재 실력을 정확히 진단한 뒤, 담당 플래너가 목표와 일정에 맞춰 함께 정해 드립니다.</p>
                    <p>시작은 부담 없는 무료 레벨테스트 한 번이면 충분합니다. 상담 폼이나 이메일({BUSINESS_EMAIL})로 문의를 남기시면 담당 플래너가 현재 실력을 진단하고, 목표에 맞는 커리큘럼과 수업 횟수(주 1~5회)를 안내해 드립니다. 상담과 레벨테스트, 첫 수업까지 모두 온라인으로 이어져 어디를 방문하실 필요가 없습니다. 수업은 정해진 교재를 읽는 방식이 아니라 실제 상황을 가정한 대화와 롤플레이, 질의응답 중심으로 진행되어, 배운 표현을 바로 말로 꺼내 쓰는 연습을 반복합니다. 직장인을 위한 시간대 운영과 연령별 맞춤 케어까지 갖춰, 바쁜 일정 속에서도 꾸준히 이어갈 수 있도록 돕습니다.</p>
                    <p>현재 안내 중인 시·도는 다음과 같습니다: {sido_names_line}. 아래 카드에서 원하는 지역을 선택해 우리 동네 영어회화 페이지로 이동해 보세요.</p>
                </div>
            </div>
        </section>"""

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
{og_image_tags(BASE_URL + '/' + quote(OG_DIRNAME) + '/hub.png', '전국 지역별 영어회화 - 이지스피크, 집에서 하는 온라인 어학연수')}
    <meta property="og:url" content="{esc(canonical)}">
    <meta property="og:type" content="website">
    <meta property="og:locale" content="ko_KR">

{head_common()}
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

    <script type="application/ld+json">
{hub_jsonld}
    </script>
</head>
<body>
{header_html("region")}

    <main class="rg-main">
        <nav class="rg-crumb" aria-label="브레드크럼">
            <div class="container">
                <ol>
                    <li><a href="/">홈</a></li>
                    <li aria-current="page">전국 지역별 영어회화</li>
                </ol>
            </div>
        </nav>

        <section class="rg-hero">
            <div class="container">
                <span class="eyebrow">전국 지역별 영어회화</span>
                <h1>우리 동네 <span class="easy">영어회화</span></h1>
                <p class="rg-lead">이지스피크(EZspeak)의 지역별 영어회화·영어학원 안내입니다. 총 {total}개 지역, {len(sido_list)}개 시·도 어디서나 100% 온라인 1:1 원어민 회화 수업과 무료 레벨테스트를 이용할 수 있습니다. 시·도를 선택해 우리 동네 페이지로 이동하세요.</p>
                <dl class="rg-facts">
                    <div><dt>수업 방식</dt><dd>100% 온라인 1:1 원어민 화상 수업 (오프라인 지점 없음)</dd></div>
                    <div><dt>수업 횟수</dt><dd>주 1~5회 중 선택</dd></div>
                    <div><dt>수강 대상</dt><dd>유아·초등·중등·성인 전 연령</dd></div>
                    <div><dt>운영 과정</dt><dd>일상영어회화 · 비즈니스 · 여행영어 · 시사토론 · 중등교과 · 키즈영어 · 문법어휘</dd></div>
                    <div><dt>레벨테스트</dt><dd>무료 · 약 10분 · 온라인 진행</dd></div>
                    <div><dt>수강료</dt><dd>과정·횟수에 따라 상담 시 개별 안내</dd></div>
                    <div><dt>수강 지역</dt><dd>전국 {len(sido_list)}개 시·도 {total}개 지역 (인터넷만 있으면 어디서나 수강 가능)</dd></div>
                    <div><dt>상담 방법</dt><dd>홈페이지 상담 폼 · 이메일</dd></div>
                </dl>
                <div class="hub-search">
                    <input type="text" id="sidoSearch" placeholder="시·도명으로 검색 (예: 서울, 경기, 부산)" autocomplete="off" aria-label="시·도 검색">
                </div>
            </div>
        </section>
{hub_intro_html}

        <section class="section" style="padding-top:clamp(28px,5vw,52px);">
            <div class="container">
                <div class="section-head">
                    <span class="eyebrow">시·도 선택</span>
                    <h2 class="section-title">시·도별 영어회화 바로가기</h2>
                </div>
                <div class="card-grid hub-grid" id="sidoGrid">
{cards_html}
                </div>
                <p class="hub-empty" id="hubEmpty">검색 결과가 없습니다.</p>
            </div>
        </section>
    </main>

    <div class="container"><p class="rg-updated">최종 업데이트: {BUILD_DATE_DOT}</p></div>

{footer_html("region")}
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

def guide_slugs():
    """api/_data/guides.json 의 칼럼 슬러그 목록.

    파일이 없거나 비어 있거나 형식이 깨져도 예외 없이 빈 리스트를 돌려준다
    (칼럼 빌드가 늦어도 사이트맵은 나가야 한다)."""
    try:
        with open(GUIDES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    items = data.get("guides") if isinstance(data, dict) else data
    out = []
    for g in items or []:
        slug = g.get("slug") if isinstance(g, dict) else g
        slug = (slug or "").strip().strip("/") if isinstance(slug, str) else ""
        if slug and slug not in out:
            out.append(slug)
    return out


def render_sitemap(keywords):
    """메인 + 허브 + 전체 지역 페이지 (+ 칼럼 목록·상세). keywords 는 {"keyword": ...} dict 또는 문자열 모두 허용."""
    urls = [BASE_URL + "/", HUB_CANONICAL, BASE_URL + "/textbooks"]  # 교재 페이지는 데이터 유무와 무관하게 항상 존재
    guides = guide_slugs()
    if guides:
        urls.append(BASE_URL + GUIDE_PREFIX)
        urls.extend(BASE_URL + GUIDE_PREFIX + "/" + quote(s) for s in guides)
    for kw in keywords:
        urls.append(canonical_of(kw["keyword"] if isinstance(kw, dict) else kw))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        lines.append("  <url><loc>%s</loc><lastmod>%s</lastmod></url>" % (esc(u), BUILD_DATE_ISO))
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def render_rss(site, limit=50):
    """네이버 서치어드바이저 제출용 RSS 2.0.

    RSS 는 '최신 콘텐츠 피드'라 전체 7,344개를 담지 않는다 — 메인·허브 + 우선순위
    상위 지역 페이지(시>구>군>축약, 하위 지역 많은 순)로 limit 개만 담는다.
    """
    pub = datetime.date.fromisoformat(CONTENT_DATE).strftime("%a, %d %b %Y 09:00:00 +0900")

    child_count = {}
    for kw in site.all_pages:
        for t in rep_tokens(kw):
            child_count[t] = child_count.get(t, 0) + 1
    rank = {"시": 0, "구": 1, "군": 2, "축약": 3, "동": 4, "읍": 5, "면": 6}
    top = sorted(site.all_pages,
                 key=lambda kw: (rank.get(kw.get("type") or "동", 4),
                                 -child_count.get(kw["keyword"], 0), kw["keyword"]))

    items = [("이지스피크 영어회화 - 100% 온라인 1:1 원어민 수업", BASE_URL + "/",
              "1:1 원어민 수업과 한국인 플래너 밀착 케어로 완성하는 실전 영어회화."),
             ("전국 지역별 영어회화 안내", HUB_CANONICAL,
              "시·도별 영어회화 페이지 모음. 전국 어디서나 온라인 수강 가능.")]
    for kw in top[:max(0, limit - len(items))]:
        ctx = build_ctx(kw)
        items.append((title_for(site.pools, ctx), canonical_of(kw["keyword"]),
                      meta_for(site.pools, ctx)))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0"><channel>',
             "<title>%s</title>" % esc(BUSINESS_NAME),
             "<link>%s/</link>" % BASE_URL,
             "<description>100% 온라인 1:1 원어민 영어회화 - 전국 지역별 안내</description>",
             "<language>ko</language>",
             "<lastBuildDate>%s</lastBuildDate>" % pub]
    for title, link, desc in items:
        lines.append("<item><title>%s</title><link>%s</link><guid>%s</guid>"
                     "<description>%s</description><pubDate>%s</pubDate></item>"
                     % (esc(title), esc(link), esc(link), esc(desc), pub))
    lines.append("</channel></rss>")
    return "\n".join(lines) + "\n"


def render_llms():
    """AnswerDotAI llms.txt (H1 + 요약 blockquote + 링크 섹션). BASE_URL 로 링크 전파."""
    hub = HUB_CANONICAL
    seoul = canonical_of("서울특별시")
    busan = canonical_of("부산광역시")
    return f"""# 이지스피크 영어회화 (EZspeak)

> 1:1 원어민 수업과 한국인 플래너의 밀착 학습 관리로 실전 영어회화를 완성하는
> 한국의 100% 온라인 영어회화 전문 학원. 모든 수업이 실시간 화상으로 진행되며
> 오프라인 지점·교실·대면 수업은 운영하지 않습니다. 유아부터 성인까지 레벨별
> speaking 중심 커리큘럼과 무료 레벨테스트를 제공하며, 전국 16개 시·도 지역
> 페이지로 안내합니다.

이지스피크는 시험용 영어가 아니라 "말이 되는 영어"를 목표로 합니다.
초급부터 고급까지 7개 과정(일상·비즈니스·여행·시사토론·중등교과·키즈·문법어휘)을
운영하고, 수업 외 시간에도 담당 플래너가 예·복습과 학습 스케줄을 관리합니다.
수업·상담·무료 레벨테스트가 모두 온라인으로 이루어지므로 전국 어느 지역에서나
동일한 방식으로 수강할 수 있고, 방문해야 하는 지점은 따로 없습니다.
지역별 페이지는 지역 학습자 안내용이며, 해당 지역에 오프라인 교실이 있다는 뜻이
아닙니다. 상담·문의는 홈페이지 상담 폼 또는 이메일({BUSINESS_EMAIL})로 받습니다.

## 핵심 페이지
- [이지스피크 홈]({BASE_URL}/): 학원 소개·커리큘럼·운영 방식·상담 신청
- [전국 지역별 영어회화 허브]({hub}): 16개 시·도별 영어회화 안내
- [서울특별시 영어회화]({seoul}): 서울 지역 대표 페이지
- [부산광역시 영어회화]({busan}): 부산 지역 대표 페이지

## 자주 묻는 질문
- 수강료: 목표·현재 실력에 따라 달라져 무료 레벨테스트 후 맞춤 상담에서 안내
- 수업 방식: 1:1 원어민 실시간 화상 수업(100% 온라인), 롤플레이·질의응답 중심
- 수업 장소: PC·스마트폰과 인터넷만 있으면 집·사무실 어디서나. 오프라인 교실 없음
- 상담 방식: 홈페이지 상담 폼·이메일·화상 상담. 방문 상담 절차 없음
- 수업 횟수: 주 1~5회 목표에 맞춰 구성
- 대상: 유아·초등·중등·성인 전 연령, 직장인 시간대 운영

## Optional
- [운영 정보] 대표 {BUSINESS_OWNER} · 전화 {BUSINESS_PHONE} · 이메일 {BUSINESS_EMAIL}
- 최종 업데이트: {BUILD_DATE_DOT}
"""


def render_robots():
    # 전체 크롤러 허용 + 네이버(Yeti)·주요 AI봇 명시 허용. Sitemap 은 BASE_URL 로 전파.
    #   /api/ 는 렌더링 함수의 내부 진입점(리라이트 대상)이므로 색인 대상에서 제외한다.
    #   (/region/... 로의 리라이트는 서버 내부 동작이라 이 규칙의 영향을 받지 않는다.)
    bots = ["*", "Yeti", "GPTBot", "OAI-SearchBot", "ChatGPT-User",
            "ClaudeBot", "Claude-SearchBot", "Claude-User",
            "PerplexityBot", "Perplexity-User", "Google-Extended"]
    blocks = "\n\n".join("User-agent: %s\nAllow: /\nDisallow: /api/\nDisallow: /data/" % b
                       for b in bots)
    return "%s\n\nSitemap: %s/sitemap.xml\n" % (blocks, BASE_URL)


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




# ---------------------------------------------------------------------------
# 404 페이지 (존재하지 않는 슬러그) — 410 이 아니라 404 + 허브 안내
# ---------------------------------------------------------------------------

def render_not_found(requested=""):
    hint = ""
    if requested:
        hint = f'<p class="rg-lead">요청하신 주소: <code>{esc(requested)}</code></p>'
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>페이지를 찾을 수 없습니다 (404) - 이지스피크</title>
    <meta name="robots" content="noindex, follow">
{head_common()}
{REGION_INLINE_CSS}
</head>
<body>
{header_html()}

    <main class="rg-main">
        <section class="rg-hero">
            <div class="container">
                <span class="eyebrow">404</span>
                <h1>찾을 수 없는 <span class="easy">지역 페이지</span></h1>
                <p class="rg-lead">주소가 바뀌었거나 없는 지역입니다. 전국 지역별 영어회화 허브에서 우리 동네 페이지를 찾아보세요.</p>
                {hint}
                <div class="rg-actions">
                    <a href="{REGION_PREFIX}" class="btn btn--solid">전국 지역별 영어회화 보기</a>
                    <a href="/" class="btn btn--outline">이지스피크 홈</a>
                </div>
            </div>
        </section>
    </main>

{footer_html()}
{PAGE_SCRIPT}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 사이트 인덱스 — 데이터 로딩 + 계층 인덱싱 (모듈 레벨 캐시로 콜드스타트 1회)
# ---------------------------------------------------------------------------

class Site:
    """regions.json + seo_pools.json 을 읽어 페이지 렌더링에 필요한 인덱스를 구성한다.

    서버리스 함수에서는 site() 로 프로세스당 1회만 만들고 재사용한다
    (콜드스타트 시 regions.json ~1MB 파싱 1회, 이후 요청은 메모리 히트)."""

    def __init__(self, input_path=DEFAULT_INPUT, pools_path=POOLS_PATH):
        keywords, keyword_set = load_keywords(input_path)
        synth = synthesize_sido(keywords, keyword_set)

        self.pools = load_pools(pools_path)
        self.keywords = keywords
        self.keyword_set = keyword_set
        self.all_pages = keywords + synth
        self.by_keyword = {kw["keyword"]: kw for kw in self.all_pages}

        by_parent_path = {}
        for kw in self.all_pages:
            by_parent_path.setdefault(tuple(rep_tokens(kw)), []).append(kw)
        self.by_parent_path = by_parent_path

        # 허브용: 최상위(조상 없음) 노드 = 시·도
        self.sido_nodes = sorted({kw["keyword"] for kw in self.all_pages if not rep_tokens(kw)})
        counts = {}
        for kw in self.all_pages:
            toks = rep_tokens(kw)
            if toks:
                counts[toks[0]] = counts.get(toks[0], 0) + 1
        self.sido_counts = counts

    # -- 계층 --------------------------------------------------------------
    def children_of(self, kw):
        return self.by_parent_path.get(tuple(rep_tokens(kw) + [kw["keyword"]]), [])

    def siblings_of(self, kw):
        key = tuple(rep_tokens(kw))
        return [s for s in self.by_parent_path.get(key, []) if s["keyword"] != kw["keyword"]]

    # -- 렌더링 ------------------------------------------------------------
    def region_page(self, keyword):
        """키워드의 지역 페이지 HTML. 없는 키워드면 None."""
        kw = self.by_keyword.get(keyword)
        if kw is None:
            return None
        ctx = build_ctx(kw)
        return render_region_page(kw, ctx, self.pools, self.keyword_set,
                                  self.children_of(kw), self.siblings_of(kw))

    def region_page_by_slug(self, slug):
        keyword = keyword_of(slug)
        if not keyword:
            return None
        return self.region_page(keyword)

    def hub_page(self):
        return render_hub_page(self.sido_nodes, self.sido_counts, len(self.all_pages))

    def sitemap(self):
        return render_sitemap(self.all_pages)


_SITE = None


def site():
    """프로세스 수명 동안 재사용되는 Site 싱글턴."""
    global _SITE
    if _SITE is None:
        _SITE = Site()
    return _SITE


# ---------------------------------------------------------------------------
# 레거시 경로 -> 새 경로 (301 매핑)
# ---------------------------------------------------------------------------

def legacy_path_to_slug(name):
    """'신림동-영어회화.html' / '신림동-영어회화' / '신림동' -> 슬러그. 못 찾으면 None."""
    if not name:
        return None
    n = name.strip().strip("/")
    if not n:
        return None
    if n.lower() in ("index.html", "index.htm", "index"):
        return None
    for suffix in (PAGE_SUFFIX, "-영어회화", ".html"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
            break
    return slugs().get(RENAMED_KEYWORDS.get(n, n))


# 폐지된 지명 -> 현행 지명. 옛 이름으로 들어온 레거시 경로가 허브로 떨어지지 않게 한다.
RENAMED_KEYWORDS = {
    "전남광주통합특별시": "광주특별시",   # 공식 약칭 표기로 통일 (2026-09)
}


# 폐지된 /region/{slug} -> 현행 슬러그. 이미 색인/수집요청된 URL 이 404 가 되지 않게 301 한다.
#   jeonnam-gwangju-si: 통합 이전 명칭으로 만들어졌던 시·도 페이지.
#   공식 약칭 표기 페이지로 보낸다.
RETIRED_SLUGS = {
    "jeonnam-gwangju-si": "gwangju-teukbyeolsi",
}


def retired_slug_target(slug):
    """폐지 슬러그면 301 목적지 경로, 아니면 None."""
    new = RETIRED_SLUGS.get((slug or "").strip().strip("/"))
    return REGION_PREFIX + "/" + new if new else None


# ---------------------------------------------------------------------------
# 자체 점검: python3 site_lib.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    s = site()
    bad = validate_overrides(s.all_pages)
    assert not bad, "오버라이드 불일치: %r" % (bad,)
    for kw, expect in (("신림", "서울특별시 관악구"), ("광주", "광주특별시"),
                       ("여수", "광주특별시"), ("광산구", "광주특별시"), ("목포시", "광주특별시"),
                       ("중구", "서울특별시"), ("판교", "경기도 성남시 분당구")):
        got = representative_parent(s.by_keyword[kw])
        assert got == expect, "%s -> %s (기대 %s)" % (kw, got, expect)
    # parents 1개면 그 값을 그대로 쓴다
    assert representative_parent({"keyword": "X", "parents": ["강원특별자치도 원주시"]}) == "강원특별자치도 원주시"
    # 병기형 조사 확정
    for src, want in (("금정구은(는)", "금정구는"), ("신림동은(는)", "신림동은"), ("서울은(는)", "서울은"),
                      ("분당은(는)", "분당은"), ("판교은(는)", "판교는"), ("유가(이)라고", "유가라고"),
                      ("신림동(이)라는", "신림동이라는"), ("서울(으)로", "서울로"), ("신림동(으)로", "신림동으로"),
                      ("판교(으)로", "판교로"), ("분당이(가)", "분당이"), ("EZ은(는)", "EZ은")):
        assert josa(src) == want, "%s -> %s (기대 %s)" % (src, josa(src), want)
    # 상담 CTA 유입 슬러그
    assert contact_href("sillim-dong") == "/?from=sillim-dong#contact" and contact_href() == "/#contact"
    assert "100%%" not in render_rss(s)
    assert s.hub_page().count("<dt>") >= 8
    # 대상별 블록: 3개 모두 렌더되고, 지역명이 소제목에 들어간다
    for name in ("신림동", "금정구", "서울특별시"):
        page = s.region_page(name)
        assert page.count('class="rg-aud-item"') == 3, name
        assert page.count("<h3>" + name) == 3, name
    # 페이지마다 다른 조합이 나오는지 (샘플 300개에서 20종 이상)
    combos = {tuple(a["heading"] + "|" + a["text"] for a in
                    audience_blocks_for(s.pools, build_ctx(kw)))
              for kw in s.all_pages[:300]}
    assert len(combos) >= 20, "대상별 블록 조합이 너무 적다: %d" % len(combos)
    # 자체 제작 교재: 3~4권 슬라이더, 각 권 이미지 3장, 첫 표지만 즉시 로드, alt 에 지역명
    for name in ("신림동", "금정구", "서울특별시"):
        page = s.region_page(name)
        books = page.count('class="bs-slide"')
        assert 3 <= books <= BOOKS_PER_PAGE, (name, books)
        assert page.count('class="stage-item"') == books * 3, name
        assert page.count('alt="%s ' % name) == books * 3, name
        assert page.count('loading="lazy"') == books * 3 - 1, name   # 첫 슬라이드 표지만 eager
        assert 'href="/textbooks"' in page and 'class="bs-dots"' in page, name
        assert 'max-width: 100%; max-height: 100%' in page and "overflow: clip" in page, name
    # 제목 ↔ 교재: 표에 없는 조합이 나오면 안 된다 + 첫 권은 제목 대표 교재 + 문구 변형 2종 이상
    leads, combos = {}, set()
    for kw in s.all_pages[:400]:
        ctx = build_ctx(kw)
        i, books = textbooks_for(s.pools, ctx)
        picked = [b["slug"] for b in books]
        assert len(picked) == len(set(picked)) and 3 <= len(picked) <= BOOKS_PER_PAGE, (kw, picked)
        assert all(sl in TITLE_BOOKS[i] for sl in picked), (kw, i, picked)
        assert picked[0] == pick([sl for sl in TITLE_BOOKS[i] if sl in textbooks_by_slug()],
                                ctx["keyword"], "regionbook"), (kw, picked)
        assert title_for(s.pools, ctx) == fmt(s.pools.titles[i], ctx)
        combos.add((i, tuple(picked)))
        leads.setdefault(i, set()).add(textbook_lead_for(s.pools, ctx, i)["heading"])
    assert len(leads) == len(s.pools.titles) and min(len(v) for v in leads.values()) >= 2, leads
    # 같은 제목이라도 지역마다 교재 구성이 달라야 한다
    assert len(combos) >= 40, "교재 조합이 너무 적다: %d" % len(combos)
    # 사이트맵: guides.json 이 없어도 예외 없이, 있으면 /guide 와 /guide/{slug} 포함
    sm = render_sitemap(s.all_pages[:3])
    assert sm.startswith("<?xml") and ("<loc>%s/guide</loc>" % BASE_URL in sm) == bool(guide_slugs())
    assert "<loc>%s/textbooks</loc>" % BASE_URL in sm
    print("site_lib self-check OK (%d pages, %d overrides)"
          % (len(s.all_pages), len(REPRESENTATIVE_OVERRIDES)))
