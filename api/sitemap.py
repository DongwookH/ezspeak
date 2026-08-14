#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
/sitemap.xml 실시간 생성 (Vercel Python 서버리스 함수)
=====================================================================

vercel.json 리라이트
  /sitemap.xml -> /api/sitemap

메인 + 허브 + 지역 7,342개 = 7,344 URL. 정적 sitemap.xml 은 삭제했다
(정적 파일이 있으면 리라이트보다 우선 적용되어 함수가 호출되지 않는다).
sitemap 은 지역 페이지보다 짧게(1시간) 캐시한다.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_lib as S  # noqa: E402

CACHE = "public, max-age=0, s-maxage=3600, stale-while-revalidate=604800"


class handler(BaseHTTPRequestHandler):

    def _handle(self, head_only=False):
        data = S.site().sitemap().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", CACHE)
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def do_GET(self):
        self._handle(head_only=False)

    def do_HEAD(self):
        self._handle(head_only=True)
