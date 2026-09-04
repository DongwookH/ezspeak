#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
/api/lead  상담신청 접수 (Vercel Python 서버리스 함수)

브라우저 -> /api/lead -> ① 구글 앱스 스크립트(시트 저장) ② 텔레그램 알림.
프론트가 앱스 스크립트에 직접 no-cors 로 쏘던 걸 서버로 옮겨 응답을 읽을 수 있게 했다.
환경변수: TG_TOKEN(필수), TG_CHAT_ID(없으면 봇의 최근 대화에서 자동 조회)
"""

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler

SCRIPT_URL = "https://script.google.com/macros/s/AKfycbx5nP_Q7hM6oWC8KEw6NWQ4Yao4uTdFIDNMjcXRZPuV0dc_r7FRvKdlTSEE4CVdXXHl/exec"
TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

FIELDS = [("name", "이름"), ("phone", "연락처"), ("gender", "성별"), ("prevStudy", "학습경험"),
          ("level", "레벨"), ("reason", "목적"), ("source", "유입경로"),
          ("contactMethod", "연락방법"), ("request", "요청사항")]


def _post(url, payload, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _chat_id():
    global TG_CHAT_ID
    if TG_CHAT_ID:
        return TG_CHAT_ID
    # ponytail: 환경변수 없으면 봇에게 마지막으로 말 건 사람의 chat_id 사용
    with urllib.request.urlopen("https://api.telegram.org/bot%s/getUpdates" % TG_TOKEN, timeout=10) as r:
        for u in reversed(json.load(r).get("result", [])):
            chat = (u.get("message") or u.get("my_chat_member") or {}).get("chat", {})
            if chat.get("id"):
                TG_CHAT_ID = str(chat["id"])
                return TG_CHAT_ID
    return ""


def notify_telegram(data):
    if not TG_TOKEN:
        return "no-token"
    chat_id = _chat_id()
    if not chat_id:
        return "no-chat"
    lines = ["📩 이지스피크 상담신청"] + ["%s: %s" % (label, data.get(k) or "-") for k, label in FIELDS]
    status, body = _post("https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN,
                         {"chat_id": chat_id, "text": "\n".join(lines)})
    return "ok" if status == 200 else body[:200]


class handler(BaseHTTPRequestHandler):

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"ok": False, "error": "bad json"})
        if not isinstance(data, dict) or not data.get("name") or not data.get("phone"):
            return self._json(400, {"ok": False, "error": "name/phone required"})
        data = {k: str(data.get(k, ""))[:500] for k, _ in FIELDS}

        try:
            sheet_status, _ = _post(SCRIPT_URL, data, timeout=20)
            sheet = "ok" if sheet_status < 400 else "http %s" % sheet_status
        except Exception as e:  # 시트 실패는 접수 실패
            return self._json(502, {"ok": False, "error": "sheet: %s" % e})

        try:
            tg = notify_telegram(data)
        except Exception as e:  # 알림 실패는 접수 성공에 영향 없음
            tg = "error: %s" % e
        self._json(200, {"ok": True, "sheet": sheet, "telegram": tg})

    def do_GET(self):
        self._json(405, {"ok": False, "error": "POST only"})

    def log_message(self, *a):
        pass
