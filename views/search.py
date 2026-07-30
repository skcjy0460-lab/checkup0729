# -*- coding: utf-8 -*-
import streamlit as st

from app_lib import search_engine as se
from app_lib import gemini_helper as gh
from app_lib.db_builder import CHECKUP_LABELS

st.title("🔍 조건별 검진기관 찾기")
st.caption("지역과 원하는 검진종류를 선택하면 자체DB에서 정확히 일치하는 기관을 찾아드리고, AI가 맞춤 추천 코멘트를 더해드립니다.")

# ---------------------------------------------------------------------------
# 사이드바: 필터
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("검색 조건")

    sido_list = ["전체"] + se.list_sido()
    sido = st.selectbox("시도", sido_list)
    sido_val = None if sido == "전체" else sido

    sigungu_val = None
    if sido_val:
        sigungu_list = ["전체"] + se.list_sigungu(sido_val)
        sigungu = st.selectbox("시군구", sigungu_list)
        sigungu_val = None if sigungu == "전체" else sigungu

    st.divider()
    st.subheader("검진종류")

    # 홈 화면의 자동판별 결과가 있으면 기본값으로 반영
    default_codes = st.session_state.get("eligible_checkup_codes", [])
    if default_codes:
        st.caption("✅ 홈 화면 대상 자동판별 결과가 기본 선택되어 있습니다.")

    checkup_codes = []
    for code, label in CHECKUP_LABELS.items():
        checked = st.checkbox(label, value=(code in default_codes), key=f"ck_{code}")
        if checked:
            checkup_codes.append(code)

    st.divider()
    st.subheader("운영일 조건")
    weekday_only = st.checkbox("평일 검진 가능 기관만")
    holiday_only = st.checkbox("주말·공휴일 검진 가능 기관만")

    st.divider()
    category = st.selectbox("기관 종별", ["전체", "종합병원", "병원", "의원"])
    category_val = None if category == "전체" else category

    keyword = st.text_input("기관명 검색어 (선택)", placeholder="예: 성모병원")

    search_clicked = st.button("🔍 검색하기", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# 검색 실행
# ---------------------------------------------------------------------------
if search_clicked or "last_results" in st.session_state:
    if search_clicked:
        filters = se.SearchFilter(
            sido=sido_val,
            sigungu=sigungu_val,
            checkup_types=checkup_codes,
            weekday_only=weekday_only,
            holiday_only=holiday_only,
            category=category_val,
            keyword=keyword or None,
        )
        df = se.search(filters, limit=300)
        df = se.score_and_rank(df, filters)
        st.session_state["last_results"] = df
        st.session_state["last_filters"] = filters
        st.session_state.pop("ai_comments", None)  # 새 검색 시 AI 코멘트 초기화

    df = st.session_state["last_results"]
    filters = st.session_state["last_filters"]

    if df.empty:
        st.warning("조건에 맞는 검진기관이 없습니다. 조건을 조금 넓혀서 다시 검색해보세요.")
    else:
        st.success(f"조건에 맞는 검진기관 **{len(df):,}개**를 찾았습니다.")

        top_n = st.slider("AI 추천을 받을 상위 기관 수", min_value=3, max_value=15, value=5)
        requested_labels = [CHECKUP_LABELS[c] for c in filters.checkup_types] if filters.checkup_types else []

        ai_clicked = st.button("🤖 AI 추천 코멘트 생성", use_container_width=True)

        if ai_clicked:
            if not gh.is_ai_available():
                st.error(
                    f"AI 추천을 사용할 수 없습니다: {gh.ai_status()}\n\n"
                    "(API 키 없이도 아래 목록은 정상 이용 가능합니다)"
                )
            else:
                with st.spinner("AI가 후보 기관들을 분석해 추천 코멘트를 작성하는 중입니다..."):
                    top_df = df.head(top_n)
                    candidates = top_df.to_dict(orient="records")
                    result = gh.generate_recommendation_comments(
                        candidates, requested_labels, user_context=keyword or ""
                    )
                st.session_state["ai_comments"] = result

        ai_comments = st.session_state.get("ai_comments")
        if ai_comments and "error" not in ai_comments:
            st.markdown("#### 🤖 AI 추천 요약")
            st.info(ai_comments.get("summary", ""))
        elif ai_comments and "error" in ai_comments:
            st.error(f"AI 추천 생성 중 오류가 발생했습니다: {ai_comments['error']}")

        st.divider()
        st.markdown(f"#### 검색 결과 ({len(df):,}건)")

        items_dict = (ai_comments or {}).get("items", {}) if ai_comments else {}

        for idx, row in df.head(50).iterrows():
            labels = se.checkup_labels_for_row(row)
            with st.container(border=True):
                head_col, badge_col = st.columns([4, 1])
                with head_col:
                    st.markdown(f"**{row['name']}**  <span style='color:#888'>({row['category']})</span>", unsafe_allow_html=True)
                    st.caption(f"📍 {row['address']}")
                with badge_col:
                    if row.get("available_weekday"):
                        st.markdown("🗓️ 평일")
                    if row.get("available_holiday"):
                        st.markdown("🎌 휴일·공휴일")

                st.write("**제공 검진:** " + (", ".join(labels) if labels else "정보 없음"))

                if row["id"] in items_dict:
                    st.success(f"🤖 {items_dict[row['id']]}")
                elif str(row["id"]) in items_dict:
                    st.success(f"🤖 {items_dict[str(row['id'])]}")

                link_col1, link_col2, link_col3 = st.columns(3)
                with link_col1:
                    if row.get("phone"):
                        st.markdown(f"📞 {row['phone']}")
                with link_col2:
                    naver_url = se.build_map_search_url(row["name"], row["address"])
                    st.markdown(f"[🗺️ 네이버지도에서 보기]({naver_url})")
                with link_col3:
                    kakao_url = se.build_kakao_map_url(row["name"], row["address"])
                    st.markdown(f"[🗺️ 카카오맵에서 보기]({kakao_url})")

        if len(df) > 50:
            st.caption(f"상위 50건만 표시됩니다. 조건을 좁혀서 더 정확한 결과를 확인해보세요. (전체 {len(df):,}건)")

        # 검진 전 준비사항 안내
        st.divider()
        with st.expander("📋 선택한 검진 항목의 검진 전 준비사항 안내 (AI 생성)"):
            if requested_labels and gh.is_ai_available():
                if st.button("준비사항 안내 보기"):
                    with st.spinner("안내 문구를 생성하는 중입니다..."):
                        tips = gh.generate_prep_tips(requested_labels)
                    st.markdown(tips)
            elif not requested_labels:
                st.caption("검진종류를 선택하면 해당 항목의 준비사항을 안내해드립니다.")
            else:
                st.caption("AI 기능을 사용하려면 Gemini API 키가 필요합니다.")
else:
    st.info("왼쪽 사이드바에서 조건을 선택하고 **검색하기** 버튼을 눌러주세요.")
