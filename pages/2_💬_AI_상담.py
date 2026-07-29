# -*- coding: utf-8 -*-
import streamlit as st

from utils import search_engine as se
from utils import gemini_helper as gh
from utils.db_builder import CHECKUP_LABELS, CHECKUP_COLS

st.set_page_config(page_title="AI 상담", page_icon="💬", layout="wide")

st.title("💬 AI 검진기관 상담")
st.caption(
    "체크박스 대신, 편하게 말로 물어보세요. 예: \"대구에서 주말에 유방암 검진 받을 수 있는 병원 알려줘\""
)

if not gh.is_ai_available():
    st.warning(
        "Gemini API 키가 설정되어 있지 않아 AI 상담 기능을 사용할 수 없습니다. "
        "`.streamlit/secrets.toml`에 `GEMINI_API_KEY`를 등록한 뒤 다시 시도해주세요.\n\n"
        "대신 **🔍 검진기관 찾기** 페이지에서 체크박스로 직접 검색하실 수 있습니다.",
        icon="⚠️",
    )
    st.stop()

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("예: 서울 영등포구에서 위암, 대장암 검진 같이 받을 수 있는 종합병원 찾아줘")

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("요청을 분석하는 중입니다..."):
            intent = gh.parse_user_intent(user_input)

        if "error" in intent:
            reply = f"죄송합니다, 요청을 이해하는 중 오류가 발생했습니다: {intent['error']}"
            st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
        elif intent.get("clarification_needed"):
            reply = intent["clarification_needed"]
            st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
        else:
            filters = se.SearchFilter(
                sido=intent.get("sido"),
                sigungu=intent.get("sigungu"),
                checkup_types=[c for c in (intent.get("checkup_types") or []) if c in CHECKUP_COLS],
                weekday_only=bool(intent.get("weekday_only")),
                holiday_only=bool(intent.get("holiday_only")),
                category=intent.get("category"),
                keyword=intent.get("keyword"),
            )
            df = se.search(filters, limit=300)
            df = se.score_and_rank(df, filters)

            condition_bits = []
            if filters.sido:
                condition_bits.append(filters.sido)
            if filters.sigungu:
                condition_bits.append(filters.sigungu)
            if filters.checkup_types:
                condition_bits.append(", ".join(CHECKUP_LABELS[c] for c in filters.checkup_types))
            if filters.holiday_only:
                condition_bits.append("주말·공휴일 가능")
            if filters.weekday_only:
                condition_bits.append("평일 가능")
            condition_text = " / ".join(condition_bits) if condition_bits else "전체"

            if df.empty:
                reply = f"**분석된 조건:** {condition_text}\n\n조건에 맞는 검진기관을 찾지 못했습니다. 지역이나 검진종류를 조금 넓혀서 다시 물어봐주세요."
                st.markdown(reply)
                st.session_state.chat_history.append({"role": "assistant", "content": reply})
            else:
                st.markdown(f"**분석된 조건:** {condition_text}  ·  **{len(df):,}개** 기관을 찾았습니다.")

                top_df = df.head(5)
                candidates = top_df.to_dict(orient="records")
                requested_labels = (
                    [CHECKUP_LABELS[c] for c in filters.checkup_types] if filters.checkup_types else []
                )
                with st.spinner("AI가 추천 사유를 작성하는 중입니다..."):
                    ai_result = gh.generate_recommendation_comments(
                        candidates, requested_labels, user_context=user_input
                    )

                summary_text = ""
                items_dict = {}
                if ai_result and "error" not in ai_result:
                    summary_text = ai_result.get("summary", "")
                    items_dict = ai_result.get("items", {})
                    st.info(summary_text)

                for _, row in top_df.iterrows():
                    labels = se.checkup_labels_for_row(row)
                    with st.container(border=True):
                        st.markdown(f"**{row['name']}** ({row['category']})")
                        st.caption(f"📍 {row['address']}  ·  📞 {row.get('phone') or '정보없음'}")
                        st.write("제공 검진: " + (", ".join(labels) if labels else "정보 없음"))
                        comment = items_dict.get(row["id"]) or items_dict.get(str(row["id"]))
                        if comment:
                            st.success(f"🤖 {comment}")
                        naver_url = se.build_map_search_url(row["name"], row["address"])
                        st.markdown(f"[🗺️ 지도에서 보기]({naver_url})")

                if len(df) > 5:
                    st.caption(
                        f"이 외에도 {len(df) - 5}개 기관이 더 있습니다. "
                        "**🔍 검진기관 찾기** 페이지에서 전체 목록과 엑셀 다운로드를 이용하실 수 있습니다."
                    )

                reply_summary = summary_text or f"조건에 맞는 {len(df)}개 기관을 찾았습니다."
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": f"**분석된 조건:** {condition_text}\n\n{reply_summary}"}
                )

st.divider()
if st.button("대화 초기화"):
    st.session_state.chat_history = []
    st.rerun()
