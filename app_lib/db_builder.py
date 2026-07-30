# -*- coding: utf-8 -*-
"""
db_builder.py
=============
엑셀 원본 자체DB(평일기준 병원급 / 휴일·공휴일 기준) -> SQLite 자동 변환 파이프라인.

설계 원칙
---------
1. 병원 리스트/검진종류 데이터는 100% 엑셀 자체DB를 신뢰(Ground Truth)한다.
   AI는 이 데이터를 "가공/추천"할 뿐 새로 만들어내지 않는다.
2. Streamlit Cloud 배포 환경에서는 로컬 디스크가 매 배포마다 초기화될 수 있으므로,
   앱 기동 시점에 엑셀(mtime) 과 SQLite(db meta) 를 비교하여 변경이 있을 때만
   재빌드한다 (기존 프로젝트에서 검증된 "Excel-to-SQLite auto-conversion" 패턴과 동일).
3. 컬럼 스키마가 다르면(엑셀 서식이 바뀌면) 명확한 예외를 던져서 운영자가 바로
   원인을 알 수 있게 한다. (조용히 무시하지 않음)
"""

from __future__ import annotations

import os
import sqlite3
import hashlib
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "checkup_institutions.db")

WEEKDAY_XLSX = os.path.join(DATA_DIR, "checkup_db_weekday.xlsx")
HOLIDAY_XLSX = os.path.join(DATA_DIR, "checkup_db_holiday.xlsx")

SHEET_NAME = "작성양식"

# 엑셀 원본 컬럼명 -> 내부 표준 컬럼명 매핑
COLUMN_MAP = {
    "검진기관명 *": "name",
    "소재지주소 *": "address",
    "우편번호": "postal_code",
    "전화번호": "phone",
    "기관종별": "category",
    "시도명": "sido",
    "시군구명": "sigungu",
    "위도": "lat",
    "경도": "lng",
    "일반건강검진": "ck_general",
    "영유아검진": "ck_infant",
    "구강검진": "ck_dental",
    "위암검진": "ck_gastric",
    "간암검진": "ck_liver",
    "대장암검진": "ck_colon",
    "유방암검진": "ck_breast",
    "자궁경부암검진": "ck_cervical",
    "폐암검진": "ck_lung",
}

# 검진종류 코드 -> 한글 라벨 (UI/AI 프롬프트 공용으로 사용)
CHECKUP_LABELS = {
    "ck_general": "일반건강검진",
    "ck_infant": "영유아검진",
    "ck_dental": "구강검진",
    "ck_gastric": "위암검진",
    "ck_liver": "간암검진",
    "ck_colon": "대장암검진",
    "ck_breast": "유방암검진",
    "ck_cervical": "자궁경부암검진",
    "ck_lung": "폐암검진",
}
CHECKUP_COLS = list(CHECKUP_LABELS.keys())


@dataclass
class BuildResult:
    rebuilt: bool
    total_institutions: int
    weekday_source_rows: int
    holiday_source_rows: int
    message: str


def _file_signature() -> str:
    """두 원본 엑셀 파일의 (경로, 수정시각, 크기)로 서명을 만들어 변경 여부를 감지."""
    parts = []
    for p in (WEEKDAY_XLSX, HOLIDAY_XLSX):
        if os.path.exists(p):
            st = os.stat(p)
            parts.append(f"{p}:{st.st_mtime_ns}:{st.st_size}")
        else:
            parts.append(f"{p}:MISSING")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_sheet(path: str, source_label: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"원본 엑셀 파일을 찾을 수 없습니다: {path}\n"
            f"data/ 폴더에 '{os.path.basename(path)}' 파일이 있는지 확인하세요."
        )
    df = pd.read_excel(path, sheet_name=SHEET_NAME, dtype=str)
    missing_cols = [c for c in COLUMN_MAP.keys() if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"[{source_label}] 엑셀 컬럼 구조가 예상과 다릅니다. 누락된 컬럼: {missing_cols}\n"
            f"업로드 양식이 변경되었다면 utils/db_builder.py의 COLUMN_MAP을 함께 수정해야 합니다."
        )
    df = df.rename(columns=COLUMN_MAP)
    df = df[list(COLUMN_MAP.values())]
    # 이름이 없는(빈) 행 제거
    df = df[df["name"].notna() & (df["name"].str.strip() != "")]

    # 문자열 공백/개행 정리
    for col in ["name", "address", "phone", "category", "sido", "sigungu", "postal_code"]:
        df[col] = df[col].astype(str).str.strip().replace({"nan": None, "None": None})

    # 검진종류 컬럼: 'Y' -> 1, 그 외 -> 0
    for col in CHECKUP_COLS:
        df[col] = df[col].apply(lambda v: 1 if isinstance(v, str) and v.strip().upper() == "Y" else 0)

    # 위경도: 숫자 변환 실패 시 NaN
    for col in ["lat", "lng"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["source"] = source_label
    return df.reset_index(drop=True)


def build_database(force: bool = False) -> BuildResult:
    """
    엑셀 원본을 읽어 SQLite DB를 (필요 시) 재생성한다.

    Parameters
    ----------
    force : bool
        True면 서명이 같아도 무조건 재빌드.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    signature = _file_signature()

    if not force and os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute("SELECT value FROM meta WHERE key = 'signature'")
            row = cur.fetchone()
            if row and row[0] == signature:
                cur2 = conn.execute("SELECT COUNT(*) FROM institutions")
                total = cur2.fetchone()[0]
                return BuildResult(
                    rebuilt=False,
                    total_institutions=total,
                    weekday_source_rows=-1,
                    holiday_source_rows=-1,
                    message="기존 DB가 최신 상태입니다 (재빌드 건너뜀).",
                )
        except sqlite3.OperationalError:
            pass  # meta 테이블이 없으면 재빌드로 진행
        finally:
            conn.close()

    weekday_df = _load_sheet(WEEKDAY_XLSX, "weekday")
    holiday_df = _load_sheet(HOLIDAY_XLSX, "holiday")

    weekday_rows = len(weekday_df)
    holiday_rows = len(holiday_df)

    # 두 소스를 병합. 동일 기관(이름+주소 동일) 은 하나로 합치고 가용성 플래그를 OR.
    weekday_df["available_weekday"] = 1
    weekday_df["available_holiday"] = 0
    holiday_df["available_weekday"] = 0
    holiday_df["available_holiday"] = 1

    combined = pd.concat([weekday_df, holiday_df], ignore_index=True)
    combined["_key"] = (
        combined["name"].fillna("").str.replace(r"\s+", "", regex=True)
        + "|"
        + combined["address"].fillna("").str.replace(r"\s+", "", regex=True)
    )

    agg_dict = {c: "max" for c in CHECKUP_COLS}
    agg_dict.update(
        {
            "postal_code": "first",
            "phone": "first",
            "category": "first",
            "sido": "first",
            "sigungu": "first",
            "lat": "first",
            "lng": "first",
            "name": "first",
            "address": "first",
            "available_weekday": "max",
            "available_holiday": "max",
        }
    )
    merged = combined.groupby("_key", as_index=False).agg(agg_dict)
    merged = merged.drop(columns=["_key"], errors="ignore")
    merged.insert(0, "id", range(1, len(merged) + 1))

    conn = sqlite3.connect(DB_PATH)
    try:
        merged.to_sql("institutions", conn, if_exists="replace", index=False)
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sido_sigungu
            ON institutions (sido, sigungu)
            """
        )
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('signature', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (signature,),
        )
        conn.commit()
    finally:
        conn.close()

    return BuildResult(
        rebuilt=True,
        total_institutions=len(merged),
        weekday_source_rows=weekday_rows,
        holiday_source_rows=holiday_rows,
        message=f"DB 재생성 완료: 평일DB {weekday_rows}건 + 휴일DB {holiday_rows}건 -> 통합 {len(merged)}건",
    )


def get_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        build_database()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_resource(show_spinner="검진기관 데이터베이스를 준비하는 중입니다...")
def ensure_db() -> BuildResult:
    """앱 진입 시 1회만 실행되도록 캐시된 DB 준비 함수. 여러 페이지에서 공용으로 호출한다."""
    return build_database(force=False)


if __name__ == "__main__":
    result = build_database(force=True)
    print(result.message)
    print(f"총 검진기관 수: {result.total_institutions}")
