# -*- coding: utf-8 -*-
"""
gemini_helper.py
================
Gemini API 연동 레이어.

역할 범위 (중요):
- Gemini는 절대 "새로운 병원을 만들어내거나" DB에 없는 기관을 언급하지 않는다.
- Gemini에게 전달하는 후보 리스트는 반드시 search_engine.py 를 거쳐 나온,
  자체DB 100% 사실에 기반한 목록만 사용한다.
- Gemini의 역할은 (1) 자연어 상담 -> 구조화 필터 파싱, (2) 후보 목록에 대한
  사람이 이해하기 쉬운 추천 사유/비교 코멘트 생성, 두 가지로 한정한다.

모델: gemini-2.5-flash (무료 티어에서 사용 가능한 경량/고속 모델)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional

import streamlit as st

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover
    genai = None
    genai_types = None

from utils.db_builder import CHECKUP_LABELS

MODEL_NAME = "gemini-2.5-flash"


def _get_api_key() -> Optional[str]:
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def _build_client(api_key: str):
    """api_key 값 자체를 캐시 키로 사용한다.
    이렇게 해야 '키가 없던 시점'의 결과가 캐시로 굳어버리지 않고,
    나중에 Streamlit Cloud 시크릿에 키를 추가하면 바로 새로 인식된다."""
    return genai.Client(api_key=api_key)


def _get_client():
    api_key = _get_api_key()
    if not api_key or genai is None:
        return None  # 이 None은 캐시되지 않으므로 다음 호출 때 다시 확인한다
    return _build_client(api_key)


def is_ai_available() -> bool:
    return _get_client() is not None


def ai_status() -> str:
    """AI 사용 불가 시 원인을 구분해서 보여주기 위한 진단 함수."""
    if genai is None:
        return "라이브러리 미설치: requirements.txt에 google-genai가 설치되지 않았습니다."
    api_key = _get_api_key()
    if not api_key:
        return "API 키 없음: .streamlit/secrets.toml (또는 Streamlit Cloud Secrets)에 GEMINI_API_KEY가 없습니다."
    if _get_client() is None:
        return "클라이언트 생성 실패: API 키 형식을 다시 확인해주세요."
    return "정상"


# ---------------------------------------------------------------------------
# 1) 자연어 상담 -> 구조화 필터 파싱
# ---------------------------------------------------------------------------

_INTENT_SCHEMA_HINT = """
아래 JSON 스키마로만 응답하세요. 다른 설명, 접두어, 마크다운 코드블록 없이 순수 JSON만 출력합니다.

{
  "sido": "시도명 문자열 또는 null (예: '대구광역시', '서울특별시')",
  "sigungu": "시군구명 문자열 또는 null",
  "checkup_types": ["ck_general", "ck_infant", "ck_dental", "ck_gastric", "ck_liver", "ck_colon", "ck_breast", "ck_cervical", "ck_lung"] 중 해당하는 코드 배열,
  "weekday_only": true 또는 false,
  "holiday_only": true 또는 false,
  "category": "의원" 또는 "병원" 또는 "종합병원" 또는 null,
  "keyword": "특정 기관명을 언급했다면 그 이름, 아니면 null",
  "clarification_needed": "지역이나 검진종류를 전혀 특정할 수 없을 때만 사용자에게 되물을 질문. 그 외에는 null"
}

검진종류 매핑 참고:
- ck_general: 일반건강검진 (전반적 건강검진)
- ck_infant: 영유아검진
- ck_dental: 구강검진
- ck_gastric: 위암검진 (위내시경)
- ck_liver: 간암검진
- ck_colon: 대장암검진 (분변잠혈, 대장내시경)
- ck_breast: 유방암검진
- ck_cervical: 자궁경부암검진
- ck_lung: 폐암검진 (흉부CT)

사용자가 '건강검진 전반적으로 받고 싶다'처럼 애매하게 말하면 ck_general을 기본 포함하세요.
'주말'/'토요일'/'일요일'/'공휴일'/'평일에는 시간이 안 된다' 표현이 있으면 holiday_only=true.
'평일에만 가능한 병원' 같은 명시적 언급이 있을 때만 weekday_only=true로 하세요 (기본은 false).
"""


def parse_user_intent(user_text: str) -> dict:
    """자유 텍스트 상담 내용을 구조화된 필터 딕셔너리로 변환."""
    client = _get_client()
    if client is None:
        return {"error": "AI_UNAVAILABLE"}

    prompt = (
        "당신은 국민건강보험 검진기관 안내 도우미입니다. "
        "아래 사용자 발화를 분석해 구조화된 검색 조건으로 변환하세요.\n\n"
        f"사용자 발화: \"{user_text}\"\n\n"
        f"{_INTENT_SCHEMA_HINT}"
    )
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        text = response.text.strip()
        text = re.sub(r"^```json|```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# 2) 후보 목록에 대한 AI 추천 코멘트 생성
# ---------------------------------------------------------------------------

def generate_recommendation_comments(
    candidates: List[dict],
    requested_checkup_labels: List[str],
    user_context: str = "",
) -> dict:
    """
    candidates: search_engine.search()+score_and_rank() 결과에서 뽑은 상위 N개
                (딕셔너리 리스트, id/name/address/category/checkup 여부 등 포함)
    반환: {"summary": "...", "items": {institution_id: "추천사유 코멘트"}}
    """
    client = _get_client()
    if client is None:
        return {"error": "AI_UNAVAILABLE"}
    if not candidates:
        return {"summary": "", "items": {}}

    compact = []
    for c in candidates:
        compact.append(
            {
                "id": c["id"],
                "name": c["name"],
                "category": c.get("category"),
                "sigungu": c.get("sigungu"),
                "available_weekday": bool(c.get("available_weekday")),
                "available_holiday": bool(c.get("available_holiday")),
                "checkup_items": [
                    CHECKUP_LABELS[k] for k in CHECKUP_LABELS if c.get(k)
                ],
            }
        )

    schema_hint = """
다음 JSON 형식으로만 응답하세요. 마크다운, 코드블록, 다른 텍스트 없이 순수 JSON만 출력합니다.
{
  "summary": "전체 후보에 대한 2~3문장 요약 (친절하고 신뢰감 있는 톤, 존댓말)",
  "items": {
    "<id>": "해당 기관을 추천하는 1~2문장 코멘트 (해당 기관이 실제로 제공하는 검진 항목/평일-휴일 가능 여부 등 주어진 사실만 근거로 작성. 없는 정보를 지어내지 말 것)"
  }
}
"""
    prompt = (
        "당신은 국민건강보험 검진기관을 안내하는 신뢰할 수 있는 AI 상담사입니다. "
        "아래는 자체 데이터베이스에서 규칙 기반으로 필터링·정렬된 검진기관 후보 목록입니다. "
        "이 목록에 있는 사실(검진 항목, 평일/휴일 가능 여부, 기관 종별)만 근거로 삼아 "
        "사용자에게 도움이 되는 추천 코멘트를 작성하세요. 목록에 없는 정보(가격, 대기시간, 의료진 평판 등)는 "
        "절대로 지어내지 마세요.\n\n"
        f"사용자 요청 맥락: {user_context or '(특이사항 없음)'}\n"
        f"사용자가 원하는 검진종류: {', '.join(requested_checkup_labels) if requested_checkup_labels else '전체'}\n\n"
        f"후보 목록(JSON):\n{json.dumps(compact, ensure_ascii=False, indent=2)}\n\n"
        f"{schema_hint}"
    )
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.4,
                response_mime_type="application/json",
            ),
        )
        text = response.text.strip()
        text = re.sub(r"^```json|```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def generate_prep_tips(checkup_labels: List[str]) -> str:
    """선택한 검진종류에 대한 검진 전 준비사항/주의사항을 생성 (일반 정보 안내용)."""
    client = _get_client()
    if client is None or not checkup_labels:
        return ""
    prompt = (
        "다음 국가건강검진 항목을 받으러 가는 환자에게 검진 전 준비사항과 주의사항을 "
        "친절한 존댓말로, 항목별로 불릿 포인트를 사용해 간결하게 안내해주세요. "
        "의학적 진단이나 처방은 하지 말고, 공복 여부·지참물·생활 주의사항 등 실무적인 안내만 하세요.\n\n"
        f"검진 항목: {', '.join(checkup_labels)}"
    )
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=genai_types.GenerateContentConfig(temperature=0.5),
        )
        return response.text.strip()
    except Exception as e:  # noqa: BLE001
        return f"(AI 안내 생성 실패: {e})"
