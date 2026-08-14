#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IndexNow 제출 스크립트 (네이버·빙·얀덱스 즉시 색인 요청)
=========================================================

사이트 전체 URL(메인 + 허브 + /region/{slug} 7,342개)을 IndexNow API 로 전송해
크롤링을 앞당긴다. 구글은 IndexNow 를 지원하지 않으므로 서치콘솔 sitemap 제출로 커버한다.

URL 목록은 site_lib.py 에서 직접 만든다 — sitemap.xml 은 이제 정적 파일이 아니라
api/sitemap.py 가 요청 시 생성하므로 로컬에 파일이 없다.

사용법
  python3 submit_indexnow.py              # 전체 URL 제출
  python3 submit_indexnow.py --dry-run    # 전송 없이 대상만 확인
  python3 submit_indexnow.py --region seoul-si sillim-dong   # 특정 슬러그만
  python3 submit_indexnow.py URL [URL...] # 특정 URL 만 제출

※ 색인 API 는 남용 시 차단될 수 있다. 내용이 실제로 바뀐 URL 만,
  하루 몇 회 이내로 제출하는 것을 권장한다.

Python 3 표준 라이브러리만 사용.
"""

import json
import os
import sys
import urllib.request
import urllib.error

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

import site_lib as S  # noqa: E402

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

def all_urls():
    """메인 + 허브 + 전체 지역 페이지 (= /sitemap.xml 이 내보내는 것과 동일한 집합)."""
    site = S.site()
    urls = [BASE_URL + "/", BASE_URL + S.REGION_PREFIX]
    urls += [S.canonical_of(kw["keyword"]) for kw in site.all_pages]
    return urls


def region_urls(slugs):
    """슬러그 목록 -> 절대 URL. 알 수 없는 슬러그는 즉시 중단한다."""
    unknown = [s for s in slugs if not S.keyword_of(s)]
    if unknown:
        raise SystemExit("[오류] data/slugs.json 에 없는 슬러그: %s" % ", ".join(unknown))
    return [BASE_URL + S.REGION_PREFIX + "/" + s for s in slugs]


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
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    args = [a for a in argv if a != "--dry-run"]

    if args and args[0] == "--region":
        urls = region_urls(args[1:])
    elif args:
        urls = args
    else:
        urls = all_urls()
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
