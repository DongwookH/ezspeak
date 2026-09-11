#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""지역 페이지 간 본문 유사도 측정.

유사문서 필터(네이버)·중복 콘텐츠(구글) 위험을 수치로 확인한다.
  - 가시 텍스트만 추출 (script/style/nav/footer/header 제외)
  - 공통 boilerplate(모든 페이지에 동일한 문장)를 따로 분리해 '고유 텍스트' 비율 산출
  - 5-gram 셔글 자카드 유사도로 쌍별 비교

사용:  python3 check_similarity.py [샘플수]
"""

import random
import re
import sys
from itertools import combinations

import site_lib as sl

TAG_STRIP = re.compile(
    r"<(script|style|nav|footer|header)\b.*?</\1>", re.S | re.I)
TAGS = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def visible_text(html):
    s = TAG_STRIP.sub(" ", html)
    s = TAGS.sub(" ", s)
    s = (s.replace("&amp;", "&").replace("&nbsp;", " ")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'"))
    return WS.sub(" ", s).strip()


def shingles(text, n=5):
    toks = text.split()
    return {" ".join(toks[i:i + n]) for i in range(max(0, len(toks) - n + 1))}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 10]


def main():
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    site = sl.Site()
    random.seed(42)

    names = [kw["keyword"] for kw in site.all_pages]
    sample = random.sample(names, min(n_sample, len(names)))

    print(f"지역 페이지 유사도 측정 — 무작위 {len(sample)}개 샘플\n" + "=" * 60)

    texts = {}
    for name in sample:
        html = site.region_page(name)
        texts[name] = visible_text(html)

    lens = sorted(len(t) for t in texts.values())
    print(f"\n[본문 길이] 중앙값 {lens[len(lens)//2]:,}자  최소 {lens[0]:,}  최대 {lens[-1]:,}")

    # 공통 boilerplate: 샘플 90% 이상에 등장하는 문장
    from collections import Counter
    sent_count = Counter()
    for t in texts.values():
        for s in set(sentences(t)):
            sent_count[s] += 1
    threshold = len(texts) * 0.9
    boiler = {s for s, c in sent_count.items() if c >= threshold}
    boiler_chars = {k: sum(len(s) for s in sentences(v) if s in boiler)
                    for k, v in texts.items()}
    ratios = sorted(boiler_chars[k] / max(1, len(v)) for k, v in texts.items())
    mid = ratios[len(ratios) // 2]
    print(f"[공통 문장] {len(boiler)}개가 샘플 90%+ 에 공통 등장 "
          f"→ 페이지당 공통 비율 중앙값 {mid:.1%}, 고유 비율 {1-mid:.1%}")

    # 전체 본문 쌍별 유사도
    sh = {k: shingles(v) for k, v in texts.items()}
    pairs = [(a, b, jaccard(sh[a], sh[b])) for a, b in combinations(sample, 2)]
    vals = sorted(p[2] for p in pairs)

    def pct(p):
        return vals[int(len(vals) * p)]

    print(f"\n[전체 본문 유사도] 쌍 {len(pairs):,}개 (5-gram 자카드)")
    print(f"  중앙값 {pct(.5):.1%} | 평균 {sum(vals)/len(vals):.1%} | "
          f"90분위 {pct(.9):.1%} | 최대 {vals[-1]:.1%}")
    worst = sorted(pairs, key=lambda p: -p[2])[:5]
    print("  가장 비슷한 쌍:")
    for a, b, v in worst:
        print(f"    {v:6.1%}  {a} ↔ {b}")

    # 고유 텍스트(공통 문장 제거)만으로 재측정
    uniq = {k: " ".join(s for s in sentences(v) if s not in boiler)
            for k, v in texts.items()}
    ush = {k: shingles(v) for k, v in uniq.items()}
    uvals = sorted(jaccard(ush[a], ush[b]) for a, b in combinations(sample, 2))
    print(f"\n[공통 문장 제외 후] 중앙값 {uvals[len(uvals)//2]:.1%} | "
          f"90분위 {uvals[int(len(uvals)*.9)]:.1%} | 최대 {uvals[-1]:.1%}")

    # 별칭 쌍 (접미사 유무): 신림 ↔ 신림동
    print("\n[별칭 쌍 — 접미사 유무로 갈리는 페이지]")
    alias = []
    nameset = set(names)
    for kw in site.all_pages:
        k = kw["keyword"]
        for suf in ("동", "구", "시", "군", "읍", "면"):
            if k.endswith(suf) and len(k) > len(suf):
                base = k[:-len(suf)]
                if base in nameset:
                    alias.append((base, k))
                break
    print(f"  전체 별칭 쌍 {len(alias):,}개 중 무작위 12개 측정:")
    apick = random.sample(alias, min(12, len(alias)))
    ares = []
    for base, full in apick:
        tb, tf = visible_text(site.region_page(base)), visible_text(site.region_page(full))
        v = jaccard(shingles(tb), shingles(tf))
        ares.append(v)
        print(f"    {v:6.1%}  {base} ↔ {full}")
    if ares:
        ares_sorted = sorted(ares)
        print(f"  → 별칭 쌍 중앙값 {ares_sorted[len(ares_sorted)//2]:.1%} "
              f"(전체 무작위 쌍 중앙값 {pct(.5):.1%})")

    # 판정
    print("\n" + "=" * 60)
    print("[판정 기준] 일반적으로 본문 자카드 70%+ = 중복 위험 높음, "
          "50~70% = 주의, 50% 미만 = 양호")
    v50 = pct(.5)
    verdict = "양호" if v50 < .5 else ("주의" if v50 < .7 else "위험")
    print(f"  무작위 쌍 중앙값 {v50:.1%} → {verdict}")
    if ares:
        am = sorted(ares)[len(ares) // 2]
        averdict = "양호" if am < .5 else ("주의" if am < .7 else "위험")
        print(f"  별칭 쌍  중앙값 {am:.1%} → {averdict}")


if __name__ == "__main__":
    main()
