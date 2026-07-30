# -*- coding: utf-8 -*-
"""
views/home.py
=============
홈 화면: 소개 + DB 현황 + 국가검진 대상 자동판별기.
파일명은 ASCII로 유지하고(Windows 압축해제 인코딩 문제 방지), 사이드바에 보이는
한글/이모지 제목은 app.py의 st.Page(title=...) 에서 지정한다.
"""

import streamlit as st

from app_lib.db_builder import ensure_db, CHECKUP_LABELS
from app_lib import eligibility

db_result = ensure_db()

# ---------------------------------------------------------------------------
# 스타일
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .hero-box {
        background: linear-gradient(135deg, #0f3d3e 0%, #1a5f5f 100%);
        color: white;
        padding: 2rem 2.2rem;
        border-radius: 14px;
        margin-bottom: 1.5rem;
    }
    .hero-box h1 { color: white; margin-bottom: 0.4rem; }
    .hero-box p { color: #dff5f0; font-size: 1.05rem; margin: 0; }
    .metric-card {
        background: #f7f9fa;
        border: 1px solid #e5e9ea;
        border-radius: 10px;
        padding: 1rem 1.2rem;
    }
    .footer-note {
        color: #8a9296;
        font-size: 0.8rem;
        margin-top: 3rem;
        border-top: 1px solid #e5e9ea;
        padding-top: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-box">
        <h1>🏥 검진기관 찾기</h1>
        <p>내 지역·원하는 검진종류에 딱 맞는 국가건강검진 지정기관을 자체 데이터베이스 + AI 추천으로 안내해드립니다.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.metric("등록 검진기관 수", f"{db_result.total_institutions:,}개")
    st.markdown("</div>", unsafe_allow_html=True)
with col2:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.metric("검진 항목 종류", f"{len(CHECKUP_LABELS)}종")
    st.markdown("</div>", unsafe_allow_html=True)
with col3:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.metric("데이터 기준", "자체DB 100%")
    st.markdown("</div>", unsafe_allow_html=True)
with col4:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.metric("AI 추천 엔진", "Gemini 3.6 Flash")
    st.markdown("</div>", unsafe_allow_html=True)

st.write("")
st.info(
    "👈 왼쪽 사이드바에서 **🔍 검진기관 찾기**(조건 체크박스 검색) 또는 "
    "**💬 AI 상담**(말로 편하게 물어보기) 페이지로 이동하세요.",
    icon="ℹ️",
)

st.divider()

# ---------------------------------------------------------------------------
# 국가건강검진 대상 자동판별기
# ---------------------------------------------------------------------------
st.header("✅ 내가 올해 국가검진 대상인지 자동으로 확인해보세요")
st.caption(
    "2026년 국가건강검진 공고 기준입니다. 정확한 대상 여부는 국민건강보험공단(☎ 1577-1000) "
    "또는 The건강보험 앱에서도 다시 확인해보시는 것을 권장드립니다."
)

with st.form("eligibility_form"):
    c1, c2, c3 = st.columns(3)
    with c1:
        birth_year = st.number_input(
            "출생연도", min_value=1920, max_value=2026, value=1986, step=1
        )
        gender = st.radio("성별", ["남성", "여성"], horizontal=True)
    with c2:
        is_non_office = st.checkbox("직장가입자이며 비사무직입니다")
        liver_risk = st.checkbox(
            "간경변증 또는 B형·C형 간염 바이러스 보유자입니다 (간암 고위험군)"
        )
    with c3:
        smoking_years = st.number_input(
            "흡연 갑년 (하루 담배 갑수 × 흡연 년수)", min_value=0.0, max_value=100.0,
            value=0.0, step=1.0,
            help="예: 하루 1갑씩 30년 흡연 = 30갑년. 폐암검진 대상 판정에 사용됩니다.",
        )
        current_smoker = st.checkbox("현재 흡연 중이거나 금연한 지 15년 이내입니다")

    submitted = st.form_submit_button("대상 여부 확인하기", type="primary", use_container_width=True)

if submitted:
    inp = eligibility.EligibilityInput(
        birth_year=int(birth_year),
        gender=gender,
        is_non_office_worker=is_non_office,
        smoking_pack_years=smoking_years,
        is_current_or_recent_quit_smoker=current_smoker,
        liver_high_risk=liver_risk,
    )
    results = eligibility.evaluate(inp)

    eligible_items = [r for r in results if r.eligible]
    st.success(
        f"총 **{len(eligible_items)}개** 항목의 국가검진 대상에 해당합니다."
        if eligible_items
        else "현재 입력 기준으로 해당하는 국가검진 항목이 없습니다."
    )

    for r in results:
        icon = "✅" if r.eligible else "⬜"
        with st.expander(f"{icon} {r.label}  ·  {r.cycle}", expanded=r.eligible):
            st.write(r.reason)

    if eligible_items:
        st.session_state["eligible_checkup_labels"] = [r.label for r in eligible_items]
        st.session_state["eligible_checkup_codes"] = [r.code for r in eligible_items]
        st.info(
            "💡 이 결과를 그대로 **🔍 검진기관 찾기** 페이지에서 불러와 검진종류를 자동으로 "
            "체크할 수 있습니다.",
            icon="💡",
        )

st.markdown(
    '<div class="footer-note">'
    "본 서비스는 국민건강보험공단 공식 서비스가 아니며, 참고용 안내 도구입니다. "
    "검진 대상·비용·절차의 최종 확인은 국민건강보험공단을 통해 진행하시기 바랍니다.<br>"
    "© 주식회사 메디엄"
    "</div>",
    unsafe_allow_html=True,
)
