# -*- coding: utf-8 -*-
"""
eligibility.py
==============
국민건강보험공단 국가건강검진 대상 여부를 나이/성별/직장가입자 구분/흡연력/
간질환 고위험군 여부로 자동 판별하는 규칙 엔진.

기준: 2026년(짝수년도) 국가건강검진 공고 기준
  - 일반건강검진: 만 20세 이상, 2년 주기. 2026년은 출생연도 끝자리가 짝수인 경우 대상
    (직장가입자 중 비사무직은 매년 대상)
  - 구강검진: 일반건강검진 대상자와 동일 주기로 함께 시행
  - 위암검진: 만 40세 이상, 2년 주기 (위내시경)
  - 대장암검진: 만 50세 이상, 매년 (분변잠혈검사, 이상 시 대장내시경)
  - 간암검진: 만 40세 이상 '고위험군'(간경변증, B형·C형 간염 바이러스 보유자 등), 6개월 주기
  - 유방암검진: 만 40세 이상 여성, 2년 주기
  - 자궁경부암검진: 만 20세 이상 여성, 2년 주기
  - 폐암검진: 만 54~74세 '고위험군'(30갑년 이상 흡연력의 현재 흡연자 또는 금연 15년 이내), 2년 주기
  - 영유아검진: 생후 4개월 ~ 만 6세(71개월) 대상, 개월수별 정해진 검진 시기

주의: 세부 기준(보험료 구간별 본인부담 면제 등)은 매년 바뀔 수 있으므로,
정확한 확인은 국민건강보험공단(1577-1000, The건강보험 앱)을 통해 다시 안내한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


CURRENT_YEAR = 2026


@dataclass
class EligibilityInput:
    birth_year: int
    gender: str  # "남성" | "여성"
    is_non_office_worker: bool = False   # 비사무직 직장가입자 여부
    smoking_pack_years: float = 0.0      # 갑년(하루 담배 갑수 x 흡연 년수)
    is_current_or_recent_quit_smoker: bool = True  # 현재 흡연 또는 금연 15년 이내
    liver_high_risk: bool = False        # 간경변증/B·C형 간염 보유자 등


@dataclass
class EligibilityItem:
    code: str
    label: str
    eligible: bool
    reason: str
    cycle: str


def _age(birth_year: int) -> int:
    """
    국가건강검진 대상 판정에 쓰이는 '해당 연도에 도달하는 나이' 계산.
    국민건강보험공단은 생일이 지났는지와 무관하게 '검진 연도 - 출생연도'로
    대상 연령을 판정한다 (예: 1986년생은 2026년에 만 40세 검진 대상).
    실제 생일이 지났는지는 고려하지 않는 근사치이며, 이는 공식 판정 방식과 동일하다.
    """
    return CURRENT_YEAR - birth_year


def evaluate(inp: EligibilityInput) -> List[EligibilityItem]:
    age = _age(inp.birth_year)
    is_female = inp.gender == "여성"
    results: List[EligibilityItem] = []

    # 일반건강검진
    even_birth_year = (inp.birth_year % 2 == 0)
    general_eligible = age >= 20 and (inp.is_non_office_worker or even_birth_year)
    if age < 20:
        reason = "만 20세 미만은 일반건강검진 대상이 아닙니다."
    elif inp.is_non_office_worker:
        reason = "비사무직 직장가입자는 출생연도와 무관하게 매년 대상입니다."
    elif even_birth_year:
        reason = f"{CURRENT_YEAR}년은 짝수년도이며, 출생연도 끝자리가 짝수({inp.birth_year}년생)라 대상입니다."
    else:
        reason = (
            f"{CURRENT_YEAR}년은 짝수년도 출생자가 대상입니다. "
            f"{inp.birth_year}년생은 홀수년도이므로 내년(2027년) 검진 대상입니다."
        )
    results.append(EligibilityItem("ck_general", "일반건강검진", general_eligible, reason, "2년 주기"))

    # 구강검진 (일반검진과 동일 주기로 동행 시행)
    results.append(
        EligibilityItem(
            "ck_dental", "구강검진", general_eligible,
            "구강검진은 일반건강검진 대상자와 동일한 주기로 함께 진행됩니다." if general_eligible
            else "일반건강검진 비대상 연도이므로 구강검진도 이번 해에는 해당되지 않습니다.",
            "2년 주기",
        )
    )

    # 위암검진
    gastric_eligible = age >= 40
    results.append(
        EligibilityItem(
            "ck_gastric", "위암검진", gastric_eligible,
            "만 40세 이상 남녀는 2년마다 위내시경 검사 대상입니다." if gastric_eligible
            else f"만 40세 이상부터 대상이며, 현재 만 {age}세는 해당되지 않습니다.",
            "2년 주기(위내시경)",
        )
    )

    # 대장암검진
    colon_eligible = age >= 50
    results.append(
        EligibilityItem(
            "ck_colon", "대장암검진", colon_eligible,
            "만 50세 이상은 매년 분변잠혈검사 대상이며, 이상 소견 시 대장내시경이 지원됩니다." if colon_eligible
            else f"만 50세 이상부터 대상이며, 현재 만 {age}세는 해당되지 않습니다.",
            "매년(분변잠혈검사)",
        )
    )

    # 간암검진 (고위험군)
    liver_eligible = age >= 40 and inp.liver_high_risk
    if age < 40:
        liver_reason = "만 40세 이상 고위험군(간경변증, B형·C형 간염 바이러스 보유자 등)이 대상입니다."
    elif not inp.liver_high_risk:
        liver_reason = "만 40세 이상이지만, 간경변증/B형·C형 간염 바이러스 보유 등 고위험군에 해당하지 않아 국가 간암검진 대상은 아닙니다."
    else:
        liver_reason = "만 40세 이상 고위험군에 해당하여 6개월마다 간초음파+혈액검사(AFP) 대상입니다."
    results.append(EligibilityItem("ck_liver", "간암검진", liver_eligible, liver_reason, "6개월 주기(고위험군)"))

    # 유방암검진 (여성)
    breast_eligible = is_female and age >= 40
    if not is_female:
        breast_reason = "여성만 해당하는 검진입니다."
    elif age < 40:
        breast_reason = f"만 40세 이상 여성이 대상이며, 현재 만 {age}세는 해당되지 않습니다."
    else:
        breast_reason = "만 40세 이상 여성은 2년마다 유방촬영 검사 대상입니다."
    results.append(EligibilityItem("ck_breast", "유방암검진", breast_eligible, breast_reason, "2년 주기"))

    # 자궁경부암검진 (여성)
    cervical_eligible = is_female and age >= 20
    if not is_female:
        cervical_reason = "여성만 해당하는 검진입니다."
    elif age < 20:
        cervical_reason = f"만 20세 이상 여성이 대상이며, 현재 만 {age}세는 해당되지 않습니다."
    else:
        cervical_reason = "만 20세 이상 여성은 2년마다 자궁경부세포 검사 대상입니다."
    results.append(EligibilityItem("ck_cervical", "자궁경부암검진", cervical_eligible, cervical_reason, "2년 주기"))

    # 폐암검진 (고위험 흡연자)
    lung_age_ok = 54 <= age <= 74
    lung_smoke_ok = inp.smoking_pack_years >= 30 and inp.is_current_or_recent_quit_smoker
    lung_eligible = lung_age_ok and lung_smoke_ok
    if not lung_age_ok:
        lung_reason = f"만 54~74세가 대상 연령입니다. 현재 만 {age}세는 해당되지 않습니다."
    elif not lung_smoke_ok:
        lung_reason = "30갑년 이상 흡연력을 가진 현재 흡연자 또는 금연 15년 이내인 고위험군이 대상입니다."
    else:
        lung_reason = "만 54~74세 고위험 흡연군으로 2년마다 저선량 흉부 CT 대상입니다."
    results.append(EligibilityItem("ck_lung", "폐암검진", lung_eligible, lung_reason, "2년 주기(저선량 흉부CT)"))

    return results
