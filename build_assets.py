#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
정적 빌드 산출물 생성 스크립트 (robots.txt / llms.txt)
=====================================================================

지역 페이지·허브·sitemap.xml 은 더 이상 정적 파일이 아니다 — api/ 서버리스 함수가
요청 시점에 site_lib.py 로 렌더링한다. 이 스크립트에는 "요청마다 만들 이유가 없는"
루트 텍스트 파일만 남는다.

  robots.txt : 크롤러 허용 정책 + Sitemap 위치
  llms.txt   : AI 검색 엔진용 사이트 요약 (AnswerDotAI llms.txt)

같이 확인하는 것
  og/{slug}.png 가 data/slugs.json 과 1:1 로 맞는지 (누락/여분 리포트)

사용법
  python3 build_assets.py            # robots.txt / llms.txt 갱신 + og 정합성 점검
  python3 build_assets.py --check    # 파일을 쓰지 않고 점검만
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

import site_lib as S  # noqa: E402

OG_DIR = os.path.join(ROOT_DIR, "og")
BRAND_OG = {"main.png", "hub.png"}


def audit_og():
    """og/{slug}.png 커버리지 점검. (누락 수, 여분 수) 반환."""
    if not os.path.isdir(OG_DIR):
        print(" og/            : 폴더 없음 — 점검 건너뜀")
        return 0, 0
    have = {f for f in os.listdir(OG_DIR) if f.endswith(".png")} - BRAND_OG
    want = {slug + ".png" for slug in S.slugs().values()}
    missing, extra = want - have, have - want
    print(" og/{slug}.png  : 기대 %d · 실제 %d · 누락 %d · 여분 %d"
          % (len(want), len(have), len(missing), len(extra)))
    for f in sorted(missing)[:10]:
        print("    - 누락:", f)
    for f in sorted(extra)[:10]:
        print("    - 여분:", f)
    return len(missing), len(extra)


def main():
    check_only = "--check" in sys.argv

    site = S.site()
    outputs = [("robots.txt", S.render_robots()), ("llms.txt", S.render_llms())]

    print("=" * 60)
    print(" 이지스피크 정적 자산 빌드")
    print("=" * 60)
    print(" BASE_URL       : %s" % S.BASE_URL)
    print(" 콘텐츠 기준일  : %s" % S.BUILD_DATE_ISO)
    print(" 지역 페이지    : %d 개 (요청 시 렌더링, sitemap %d URL)"
          % (len(site.all_pages), len(site.all_pages) + 2))

    if not check_only:
        for name, body in outputs:
            with open(os.path.join(ROOT_DIR, name), "w", encoding="utf-8") as f:
                f.write(body)
            print(" %-14s : %d bytes 기록" % (name, len(body.encode("utf-8"))))
    else:
        for name, body in outputs:
            print(" %-14s : %d bytes (미기록)" % (name, len(body.encode("utf-8"))))

    missing, extra = audit_og()
    print("=" * 60)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
