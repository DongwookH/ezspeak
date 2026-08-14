#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/slugs.json 생성 스크립트 — 한글 지역 키워드 → 로마자(Revised Romanization) 슬러그 맵.

입력
  - data/regions.json (7,334개 키워드) + site_lib.synthesize_sido() 가 합성하는
    시·도 8개(경기도/강원특별자치도/충청북도/충청남도/전북특별자치도/경상북도/경상남도/제주특별자치도)
    = 총 7,342개 키워드 전부를 커버한다.
    (site_lib 을 import 해서 load_keywords/synthesize_sido 를 그대로 재사용 —
     실제 페이지가 렌더링되는 키워드 집합과 100% 일치시키기 위함.)

변환 방식
  - korean-romanizer 패키지(pip3 install --user korean-romanizer)를 기본 로마자 변환기로 사용.
    단, 이 패키지는 음절 경계 간 비음화(ㄹ→ㄴ)·유음화(ㄴ+ㄹ/ㄹ+ㄴ→ll) 규칙을 구현하지 않아
    "신림"을 sinrim, "종로"를 jongro 로 잘못 출력한다.
  - 따라서 자모 분해 기반 전처리 단계를 자체 구현해 위 동화 규칙을 먼저 한글 텍스트에
    반영(신림→실림, 종로→종노, 독립문→동님문)한 뒤 korean-romanizer 에 넘긴다.
    (단, 행정 접미사 하이픈 경계 앞뒤로는 이 동화 규칙을 적용하지 않는다 —
     국어의 로마자 표기법 규정 "붙임표 앞뒤에서 일어나는 음운 변화는 표기에 반영하지 않는다".)
  - 광역단체(시·도) 16개(+축약형)는 관용 표기 하드코딩 테이블로 대체.
    축약형이 깨끗한 슬러그(서울 -> seoul), 전체형은 행정단위 접미사(서울특별시 -> seoul-si,
    경기도 -> gyeonggi-do)를 갖는다.
"""

import sys
import os
import re
import json

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

import site_lib as gp  # noqa: E402

try:
    from korean_romanizer.romanizer import Romanizer
except ImportError:
    print("[오류] korean-romanizer 가 설치되어 있지 않습니다. "
          "pip3 install --user korean-romanizer 후 다시 실행하세요.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 1) 자모 분해 기반 동화(assimilation) 전처리
#    - ㄴ+ㄹ → ll (유음화)      : 신림 -> 실림 -> sillim
#    - ㄹ+ㄴ → ll (유음화)      : 별내 -> 별래 -> byeollae
#    - ㅇ/ㅁ + ㄹ → ㅇ/ㅁ + ㄴ  (비음화, ㄹ→ㄴ만) : 종로 -> 종노 -> jongno
#    - ㄱ/ㄷ/ㅂ + ㄹ → 비음+ㄴ  (비음화, 양쪽 다) : 독립 -> 동닙 (독립문 -> 동님문 -> dongnimmun)
#    - ㄱ/ㄷ/ㅂ + ㄴ/ㅁ → 비음  (일반 비음화)      : 국민 -> 궁민 -> gungmin
#    나머지(격음화 ㅎ, 겹받침 대표음, 연음)는 korean-romanizer 자체 로직에 위임한다.
# ---------------------------------------------------------------------------

LEAD = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
TAIL = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")
LEAD_IDX = {c: i for i, c in enumerate(LEAD)}
TAIL_IDX = {c: i for i, c in enumerate(TAIL)}

TAIL_REPR = {
    "": None,
    "ㄱ": "ㄱ", "ㄲ": "ㄱ", "ㄳ": "ㄱ", "ㄺ": "ㄱ", "ㅋ": "ㄱ",
    "ㄴ": "ㄴ", "ㄵ": "ㄴ", "ㄶ": "ㄴ",
    "ㄷ": "ㄷ", "ㅅ": "ㄷ", "ㅆ": "ㄷ", "ㅈ": "ㄷ", "ㅊ": "ㄷ", "ㅌ": "ㄷ", "ㅎ": "ㄷ",
    "ㄹ": "ㄹ", "ㄼ": "ㄹ", "ㄽ": "ㄹ", "ㄾ": "ㄹ", "ㅀ": "ㄹ",
    "ㅁ": "ㅁ", "ㄻ": "ㅁ",
    "ㅂ": "ㅂ", "ㅍ": "ㅂ", "ㅄ": "ㅂ", "ㄿ": "ㅂ",
    "ㅇ": "ㅇ",
}
NASALIZE = {"ㄱ": "ㅇ", "ㄷ": "ㄴ", "ㅂ": "ㅁ"}


def _is_syll(ch):
    return "가" <= ch <= "힣"


def assimilate(text):
    """음절 경계 간 유음화·비음화 규칙을 적용한 한글 문자열을 반환."""
    chars = list(text)
    dec = []
    for ch in chars:
        if _is_syll(ch):
            code = ord(ch) - 0xAC00
            l = code // 588
            v = (code % 588) // 28
            t = code % 28
            dec.append([l, v, t])
        else:
            dec.append(None)

    n = len(dec)
    for i in range(n - 1):
        cur = dec[i]
        nxt = dec[i + 1]
        if cur is None or nxt is None:
            continue
        cur_tail_ch = TAIL[cur[2]]
        if cur_tail_ch == "":
            continue
        nxt_lead_ch = LEAD[nxt[0]]
        repr_t = TAIL_REPR.get(cur_tail_ch)

        if repr_t == "ㄴ" and nxt_lead_ch == "ㄹ":          # 유음화 (ㄴ+ㄹ)
            cur[2] = TAIL_IDX["ㄹ"]
            continue
        if repr_t == "ㄹ" and nxt_lead_ch == "ㄴ":          # 유음화 (ㄹ+ㄴ)
            nxt[0] = LEAD_IDX["ㄹ"]
            continue
        if nxt_lead_ch == "ㄹ" and repr_t in ("ㅇ", "ㅁ"):   # 비음 뒤 ㄹ→ㄴ
            nxt[0] = LEAD_IDX["ㄴ"]
            continue
        if nxt_lead_ch == "ㄹ" and repr_t in ("ㄱ", "ㄷ", "ㅂ"):  # 파열음+ㄹ 상호비음화
            cur[2] = TAIL_IDX[NASALIZE[repr_t]]
            nxt[0] = LEAD_IDX["ㄴ"]
            continue
        if nxt_lead_ch in ("ㄴ", "ㅁ") and repr_t in ("ㄱ", "ㄷ", "ㅂ"):  # 일반 비음화
            cur[2] = TAIL_IDX[NASALIZE[repr_t]]
            continue

    out = []
    for orig, d in zip(chars, dec):
        if d is None:
            out.append(orig)
        else:
            l, v, t = d
            out.append(chr(0xAC00 + (l * 21 + v) * 28 + t))
    return "".join(out)


def romanize_unit(text):
    """동화 전처리 + korean-romanizer. 숫자 등 비한글 문자는 그대로 통과.

    korean-romanizer 는 받침 ㄹ(coda, "l") 뒤에 초성 ㄹ(onset, "r") 이 오는 경우를
    "ll" 로 합치지 않고 "l"+"r" 그대로 이어 붙인다 (예: 실라 -> silra, 별래 -> byeolrae).
    로마자 표기법상 "lr" 조합은 이 경우에만 발생하므로, 결과 문자열에서 일괄
    "lr" -> "ll" 로 치환해 표준 표기(실라->silla, 별래->byeollae)에 맞춘다.
    """
    if not text:
        return ""
    processed = assimilate(text)
    out = Romanizer(processed).romanize()
    return out.replace("lr", "ll")


# ---------------------------------------------------------------------------
# 2) 광역단체(시·도) 16개 — 관용 표기 하드코딩
# ---------------------------------------------------------------------------

#   규칙
#     - 축약형(서울/부산/…)이 "깨끗한" 슬러그(seoul/busan/…)를 가진다.
#       검색·공유에서 실제로 쓰이는 표기가 축약형이고, URL 도 짧게 유지된다.
#     - 전체형은 행정단위 접미사를 붙인다.
#         특별시·광역시·특별자치시  -> -si   (서울특별시 -> seoul-si)
#         도·특별자치도            -> -do   (경기도 -> gyeonggi-do, 강원특별자치도 -> gangwon-do)
#         전남광주통합특별시        -> jeonnam-gwangju-si
#     - 축약형도 하드코딩한다. 자동 로마자화는 '대구'를 행정 접미사 '구'로 오인해
#       dae-gu 로 잘라내기 때문(관용 표기는 daegu).
SIDO_FULL_SLUG = {
    "서울특별시": "seoul-si",
    "부산광역시": "busan-si",
    "대구광역시": "daegu-si",
    "인천광역시": "incheon-si",
    "전남광주통합특별시": "jeonnam-gwangju-si",
    "대전광역시": "daejeon-si",
    "울산광역시": "ulsan-si",
    "세종특별자치시": "sejong-si",
    "경기도": "gyeonggi-do",
    "강원특별자치도": "gangwon-do",
    "충청북도": "chungbuk-do",
    "충청남도": "chungnam-do",
    "전북특별자치도": "jeonbuk-do",
    "경상북도": "gyeongbuk-do",
    "경상남도": "gyeongnam-do",
    "제주특별자치도": "jeju-do",
}

SIDO_ABBR_SLUG = {
    "서울": "seoul",
    "부산": "busan",
    "대구": "daegu",
    "인천": "incheon",
    "광주": "gwangju",
    "전남": "jeonnam",
    "대전": "daejeon",
    "울산": "ulsan",
    "세종": "sejong",
    "경기": "gyeonggi",
    "강원": "gangwon",
    "충북": "chungbuk",
    "충남": "chungnam",
    "전북": "jeonbuk",
    "경북": "gyeongbuk",
    "경남": "gyeongnam",
    "제주": "jeju",
}

# 하드코딩 우선 테이블 (전체형 + 축약형). 충돌 처리에서도 이 항목이 우선권을 갖는다.
SIDO_SLUG = dict(SIDO_FULL_SLUG)
SIDO_SLUG.update(SIDO_ABBR_SLUG)

ADMIN_SUFFIX_CHARS = {"시", "구", "군", "읍", "면", "동"}
NUMGA_RE = re.compile(r"([0-9]+가)$")


def split_units(keyword):
    """keyword -> (stem, [suffix_unit, ...]) 하이픈 분리용.
    행정 접미사(시/구/군/읍/면/동)와 '숫자+가'(1가,2가...) 를 오른쪽부터 최대 1개씩 떼어낸다."""
    s = keyword
    tails = []

    m = NUMGA_RE.search(s)
    if m:
        tails.append(m.group(1))
        s = s[: m.start()]

    if s and s[-1] in ADMIN_SUFFIX_CHARS and len(s) > 1:
        tails.append(s[-1])
        s = s[:-1]

    tails.reverse()
    return s, tails


_SANITIZE_RE = re.compile(r"[^a-z0-9-]+")
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")


def sanitize(slug):
    slug = slug.lower()
    slug = slug.replace("·", "-")
    slug = _SANITIZE_RE.sub("-", slug)
    slug = _MULTI_HYPHEN_RE.sub("-", slug)
    return slug.strip("-")


def base_slug_of(keyword):
    """하드코딩(시·도) 우선, 그 외에는 접미사 분리 + 동화 전처리 로마자화."""
    if keyword in SIDO_SLUG:
        return SIDO_SLUG[keyword]
    stem, tails = split_units(keyword)
    parts = [romanize_unit(stem)] + [romanize_unit(t) for t in tails]
    return sanitize("-".join(parts))


# ---------------------------------------------------------------------------
# 3) 전체 키워드 로드 (regions.json + 합성 시·도 8개)
# ---------------------------------------------------------------------------

def load_all_keywords():
    keywords, keyword_set = gp.load_keywords(gp.DEFAULT_INPUT)
    synth = gp.synthesize_sido(keywords, keyword_set)
    return keywords + synth


# 충돌 처리 접미사용 "시·도 축약 슬러그" (전체형 슬러그에서 -si/-do 를 뗀 형태).
# 예: 복내면 -> bongnae-myeon-jeonnam-gwangju (…-si 가 아니라 축약형을 붙인다)
SIDO_BASE_SLUG = {k: v.rsplit("-", 1)[0] for k, v in SIDO_FULL_SLUG.items()}


def sido_slug_for(kw):
    """kw 의 대표 상위 시·도 토큰의 슬러그(충돌 처리용 접미사)."""
    toks = gp.rep_tokens(kw)
    if not toks:
        return None
    return SIDO_BASE_SLUG.get(toks[0])


# ---------------------------------------------------------------------------
# 4) 충돌 처리
# ---------------------------------------------------------------------------

def resolve_collisions(all_kw):
    base = {kw["keyword"]: base_slug_of(kw["keyword"]) for kw in all_kw}

    groups = {}
    for kw in all_kw:
        groups.setdefault(base[kw["keyword"]], []).append(kw)

    used = set()
    result = {}
    collisions_report = []

    # 안정적 처리 순서: 원본 리스트 순서 그대로
    for kw in all_kw:
        keyword = kw["keyword"]
        b = base[keyword]
        group = groups[b]

        if len(group) == 1:
            slug = b
        else:
            is_locked = keyword in SIDO_SLUG
            # 그룹 내 우선순위: (a) 시·도 하드코딩 항목 (b) 비-축약형 (c) 원본 순서상 먼저 나온 것
            def priority(k):
                return (
                    0 if k["keyword"] in SIDO_SLUG else 1,
                    0 if k.get("type") != "축약" else 1,
                    all_kw.index(k),
                )
            winner = sorted(group, key=priority)[0]
            if keyword == winner["keyword"] and b not in used:
                slug = b
            else:
                psl = sido_slug_for(kw)
                slug = None
                if psl and psl != b:
                    cand = sanitize(b + "-" + psl)
                    if cand not in used:
                        slug = cand
                if slug is None:
                    n = 2
                    while True:
                        cand = "%s-%d" % (b, n)
                        if cand not in used:
                            slug = cand
                            break
                        n += 1

        used.add(slug)
        result[keyword] = slug

    for b, group in groups.items():
        if len(group) > 1:
            collisions_report.append(
                (b, [(k["keyword"], result[k["keyword"]]) for k in group])
            )

    return result, collisions_report


# ---------------------------------------------------------------------------
# 5) 검증
# ---------------------------------------------------------------------------

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate(slugs):
    problems = []
    seen = {}
    for kw, slug in slugs.items():
        if not SLUG_RE.match(slug):
            problems.append("정규식 불합격: %r -> %r" % (kw, slug))
        if slug in seen:
            problems.append("중복 슬러그: %r, %r -> %r" % (seen[slug], kw, slug))
        else:
            seen[slug] = kw
    return problems


def main():
    all_kw = load_all_keywords()
    print("전체 키워드 수:", len(all_kw))

    slugs, collisions = resolve_collisions(all_kw)

    problems = validate(slugs)

    out_path = os.path.join(ROOT_DIR, "data", "slugs.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(slugs, f, ensure_ascii=False, indent=2, sort_keys=False)

    print("=" * 70)
    print("슬러그 총수:", len(slugs))
    print("유니크 슬러그 수:", len(set(slugs.values())))
    print("검증 문제:", len(problems))
    for p in problems[:50]:
        print("  -", p)
    print("-" * 70)
    print("충돌 그룹(베이스 슬러그 기준) 수:", len(collisions))
    for b, members in collisions:
        print("  base=%r" % b)
        for k, s in members:
            print("     %r -> %r" % (k, s))
    print("-" * 70)

    samples = ["신림동", "신림", "강남구", "강남", "해운대구", "수원시",
               "종로구", "종로", "중구", "전남광주통합특별시", "상왕십리", "동소문동1가",
               "종로1가", "서울특별시", "서울", "부산광역시", "부산", "경기도", "남면",
               "청량리동"]
    print("샘플 20개(+):")
    for s in samples:
        if s in slugs:
            print("  %-14s -> %s" % (s, slugs[s]))
        else:
            print("  %-14s -> (데이터 없음)" % s)
    print("=" * 70)
    print("출력:", out_path)


if __name__ == "__main__":
    main()
