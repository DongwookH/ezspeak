#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
/rss.xml 실시간 생성 (Vercel Python 서버리스 함수)
=====================================================================

vercel.json 리라이트
  /rss.xml -> /api/rss

네이버 서치어드바이저 RSS 제출용. 메인·허브 + 우선순위 상위 지역 50개.
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
        data = S.render_rss(S.site()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", CACHE)
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def do_GET(self):
        self._handle(head_only=False)

    def do_HEAD(self):
        self._handle(head_only=True)

    def log_message(self, *a):
        pass
