#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IndexNow 제출 스크립트 (네이버·빙·얀덱스 즉시 색인 요청)
=========================================================

sitemap.xml 의 전체 URL 을 IndexNow API 로 전송해 크롤링을 앞당긴다.
구글은 IndexNow 를 지원하지 않으므로 서치콘솔 sitemap 제출로 커버한다.

사용법
  python3 submit_indexnow.py              # sitemap.xml 전체 제출
  python3 submit_indexnow.py --dry-run    # 전송 없이 대상만 확인
  python3 submit_indexnow.py URL [URL...] # 특정 URL 만 제출

※ 색인 API 는 남용 시 차단될 수 있다. 내용이 실제로 바뀐 URL 만,
  하루 몇 회 이내로 제출하는 것을 권장한다.

Python 3 표준 라이브러리만 사용.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# 설정 — 도메인 변경 시 BASE_URL / KEY 를 함께 갱신
# ---------------------------------------------------------------------------
BASE_URL = "https://ezspeak.vercel.app"
HOST = BASE_URL.split("//", 1)[1]

# 인증 키. 같은 이름의 {KEY}.txt 파일이 사이트 루트에 배포되어 있어야 한다.
KEY = "c7c27d99185ee6781e06d384ed1fdc62"
KEY_LOCATION = f"{BASE_URL}/{KEY}.txt"

# IndexNow 참여 엔진 (한 곳에 보내면 나머지로 전파되지만, 네이버에 직접 보낸다)
ENDPOINT = "https://searchadvisor.naver.com/indexnow"

# 요청당 URL 상한 (스펙 기준 10,000)
BATCH_SIZE = 10000

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SITEMAP_PATH = os.path.join(ROOT_DIR, "sitemap.xml")


def urls_from_sitemap(path):
    with open(path, "r", encoding="utf-8") as f:
        return re.findall(r"<loc>(.*?)</loc>", f.read())


def submit(urls):
    payload = {
        "host": HOST,
        "key": KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls,
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.status, res.read().decode("utf-8", "replace")[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except urllib.error.URLError as e:
        return None, str(e)


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv

    urls = args if args else urls_from_sitemap(SITEMAP_PATH)
    if not urls:
        print("제출할 URL이 없습니다.")
        return 1

    print(f"대상 URL: {len(urls)}개  (host={HOST})")
    print(f"키 파일 : {KEY_LOCATION}")
    if dry:
        for u in urls[:5]:
            print("  ", u)
        print("   ... (--dry-run: 전송하지 않음)")
        return 0

    ok = True
    for i in range(0, len(urls), BATCH_SIZE):
        batch = urls[i:i + BATCH_SIZE]
        status, body = submit(batch)
        print(f"[{i + 1}~{i + len(batch)}] HTTP {status} {body}".rstrip())
        # 200/202 는 정상 수신
        if status not in (200, 202):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
