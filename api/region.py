#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
/region/{slug} · /region  실시간 렌더링 (Vercel Python 서버리스 함수)
=====================================================================

vercel.json 리라이트
  /region            -> /api/region
  /region/{slug}     -> /api/region?slug={slug}

데이터·템플릿은 전부 루트의 site_lib.py 공용 모듈에서 온다.
Site 인스턴스는 모듈 레벨 캐시(site_lib.site())라 콜드스타트에서만 JSON 을 파싱하고
이후 요청은 메모리 히트다. 응답에는 엣지 캐시 헤더를 붙여 첫 요청 이후 정적 수준 속도를 낸다.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 번들 루트(= 프로젝트 루트)를 import 경로에 추가 — site_lib.py / data/*.json 접근용
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_lib as S  # noqa: E402

# 하루 신선, 일주일 stale-while-revalidate — 콘텐츠가 바뀌는 건 재배포 시점뿐이다.
CACHE_OK = "public, max-age=0, s-maxage=86400, stale-while-revalidate=604800"
CACHE_404 = "public, max-age=0, s-maxage=300"


class handler(BaseHTTPRequestHandler):

    def _respond(self, status, body, cache, ctype="text/html; charset=utf-8", head_only=False):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _handle(self, head_only=False):
        query = parse_qs(urlparse(self.path).query)
        slug = (query.get("slug") or [""])[0].strip().strip("/")

        site = S.site()

        # 슬러그 없음 -> 허브 (/region)
        if not slug:
            self._respond(200, site.hub_page(), CACHE_OK, head_only=head_only)
            return

        html = site.region_page_by_slug(slug)
        if html is None:
            # 존재하지 않는 슬러그: 410 이 아니라 404 (검색엔진 혼동 방지) + 허브 안내
            self._respond(404, S.render_not_found(S.REGION_PREFIX + "/" + slug),
                          CACHE_404, head_only=head_only)
            return

        self._respond(200, html, CACHE_OK, head_only=head_only)

    def do_GET(self):
        self._handle(head_only=False)

    def do_HEAD(self):
        self._handle(head_only=True)
