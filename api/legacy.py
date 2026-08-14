#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
레거시 정적 경로 -> 새 URL 301 리다이렉트 (Vercel Python 서버리스 함수)
=====================================================================

vercel.json 리라이트
  /지역                        -> /api/legacy                 => 301 /region
  /지역/                       -> /api/legacy                 => 301 /region
  /지역/index.html             -> /api/legacy?file=index.html => 301 /region
  /지역/{한글}-영어회화.html     -> /api/legacy?file=...        => 301 /region/{slug}
  /og/{한글}-영어회화.png        -> /api/legacy?og=...          => 301 /og/{slug}.png
                                  (og 는 정적 파일이 없을 때만 리라이트가 발동한다)
  매칭 실패                                                    => 301 /region

인코딩 주의
  Vercel 이 리라이트 파라미터를 인코딩된 채로 넘길지 디코딩해서 넘길지에 의존하지 않도록,
  값이 더 이상 변하지 않을 때까지 반복 unquote 한 뒤 슬러그 맵을 조회한다.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_lib as S  # noqa: E402

# 리다이렉트 자체는 오래 캐시해도 안전하다 (매핑이 재배포 전에는 바뀌지 않는다).
CACHE = "public, max-age=0, s-maxage=86400, stale-while-revalidate=604800"


def _decode(value):
    """퍼센트 인코딩이 몇 겹이든 원문 한글로 되돌린다 (최대 3회)."""
    out = value or ""
    for _ in range(3):
        dec = unquote(out)
        if dec == out:
            break
        out = dec
    return out


def _target(query):
    """리다이렉트 목적지 경로를 정한다."""
    og = _decode((query.get("og") or [""])[0]).strip().strip("/")
    if og:
        name = og[:-4] if og.lower().endswith(".png") else og
        if name.endswith("-영어회화"):
            name = name[: -len("-영어회화")]
        slug = S.slugs().get(name)
        if slug:
            return "/og/" + slug + ".png"
        return S.REGION_PREFIX

    name = _decode((query.get("file") or [""])[0])
    slug = S.legacy_path_to_slug(name)
    if slug:
        return S.REGION_PREFIX + "/" + slug
    # 허브(index.html)·빈 값·미매칭은 전부 허브로 301
    return S.REGION_PREFIX


class handler(BaseHTTPRequestHandler):

    def _handle(self, head_only=False):
        query = parse_qs(urlparse(self.path).query)
        location = _target(query)
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", CACHE)
        self.end_headers()

    def do_GET(self):
        self._handle(head_only=False)

    def do_HEAD(self):
        self._handle(head_only=True)
