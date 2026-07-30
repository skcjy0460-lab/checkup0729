# -*- coding: utf-8 -*-
"""
search_engine.py
================
자체DB(SQLite)를 대상으로 하는 규칙기반 필터링/정렬 엔진.

여기서 나온 결과는 100% 자체DB 사실에 근거한다 (AI가 병원을 지어내거나
DB에 없는 기관을 언급하지 않도록, AI 단계로 넘기기 전에 반드시 이 엔진을
거치도록 설계했다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
import urllib.parse

import pandas as pd

from utils.db_builder import get_connection, CHECKUP_COLS, CHECKUP_LABELS


@dataclass
class SearchFilter:
    sido: Optional[str] = None
    sigungu: Optional[str] = None
    checkup_types: List[str] = field(default_factory=list)  # ck_general 등 내부 코드
    weekday_only: bool = False      # 평일 검진 가능 기관만
    holiday_only: bool = False      # 휴일/공휴일 검진 가능 기관만
    category: Optional[str] = None  # 의원/병원/종합병원
    keyword: Optional[str] = None   # 기관명 검색어


def list_sido() -> List[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT sido FROM institutions WHERE sido IS NOT NULL ORDER BY sido"
        ).fetchall()
        return [r["sido"] for r in rows]
    finally:
        conn.close()


def list_sigungu(sido: str) -> List[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT sigungu FROM institutions WHERE sido = ? AND sigungu IS NOT NULL "
            "ORDER BY sigungu",
            (sido,),
        ).fetchall()
        return [r["sigungu"] for r in rows]
    finally:
        conn.close()


def search(filters: SearchFilter, limit: int = 200) -> pd.DataFrame:
    conn = get_connection()
    try:
        query = "SELECT * FROM institutions WHERE 1=1"
        params: list = []

        if filters.sido:
            query += " AND sido = ?"
            params.append(filters.sido)
        if filters.sigungu:
            query += " AND sigungu = ?"
            params.append(filters.sigungu)
        if filters.category:
            query += " AND category = ?"
            params.append(filters.category)
        if filters.keyword:
            query += " AND name LIKE ?"
            params.append(f"%{filters.keyword}%")
        if filters.weekday_only:
            query += " AND available_weekday = 1"
        if filters.holiday_only:
            query += " AND available_holiday = 1"
        for ck in filters.checkup_types:
            if ck in CHECKUP_COLS:
                query += f" AND {ck} = 1"

        query += " LIMIT ?"
        params.append(limit)

        df = pd.read_sql_query(query, conn, params=params)
        return df
    finally:
        conn.close()


def score_and_rank(df: pd.DataFrame, filters: SearchFilter) -> pd.DataFrame:
    """
    AI 호출 전, 결정적(deterministic) 규칙 기반 1차 스코어링.
    - 요청한 검진종류를 얼마나 커버하는지
    - 종합병원 > 병원 > 의원 순 가중치 (검진 항목이 많을수록 대체로 종합병원이 유리)
    - 평일/휴일 모두 가능하면 가산점 (선택 유연성)
    이 스코어는 순수 규칙 기반이며, 이후 Gemini는 이 순위를 참고해 '설명'만 덧붙인다.
    """
    if df.empty:
        return df

    df = df.copy()
    requested = filters.checkup_types or CHECKUP_COLS

    def _row_score(row) -> float:
        score = 0.0
        # 요청 검진종류 충족 개수
        score += sum(row.get(c, 0) for c in requested) * 10
        # 기관 종별 가중치
        cat_weight = {"종합병원": 3, "병원": 2, "의원": 1}.get(row.get("category"), 0)
        score += cat_weight
        # 평일+휴일 모두 가능하면 가산점
        if row.get("available_weekday") and row.get("available_holiday"):
            score += 2
        elif row.get("available_holiday"):
            score += 1
        return score

    df["_score"] = df.apply(_row_score, axis=1)
    df = df.sort_values("_score", ascending=False).reset_index(drop=True)
    return df


def checkup_labels_for_row(row) -> List[str]:
    return [CHECKUP_LABELS[c] for c in CHECKUP_COLS if row.get(c)]


def build_map_search_url(name: str, address: str) -> str:
    """위경도 데이터 신뢰도가 낮으므로, 주소 기반 지도 검색 링크로 대체."""
    q = urllib.parse.quote(f"{name} {address}")
    return f"https://map.naver.com/p/search/{q}"


def build_kakao_map_url(name: str, address: str) -> str:
    q = urllib.parse.quote(f"{name} {address}")
    return f"https://map.kakao.com/?q={q}"
