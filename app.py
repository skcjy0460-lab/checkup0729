# -*- coding: utf-8 -*-
"""
app.py
======
앱 진입점(라우터). 실제 화면 내용은 views/ 폴더의 각 파일에 있다.

두 가지 안전장치:
1. 프로젝트 루트를 sys.path에 명시적으로 추가한다.
   Streamlit Cloud에서 st.Page로 views/ 하위 스크립트를 실행할 때,
   프로젝트 루트(app_lib 폴더가 있는 위치)가 import 경로에 없어
   ImportError가 나는 경우가 보고되어 있어, 이를 확실히 방지한다.
2. 로컬 유틸리티 패키지 이름을 "utils"가 아닌 "app_lib"으로 사용한다.
   PyPI에는 실제로 "utils"라는 범용 패키지가 존재하며, 배포 환경에 따라
   이 패키지가 로컬 utils/ 폴더보다 먼저 잡혀서 엉뚱한 모듈을 참조하는
   충돌 사례가 보고되어 있어, 이름 자체를 고유하게 바꿔 원천 차단한다.

파일명을 전부 ASCII로 유지하는 이유:
Windows 탐색기의 기본 압축 프로그램은 zip 안의 파일명이 UTF-8 언어 인코딩
플래그 없이 저장된 경우, 한글/이모지가 포함된 파일명을 깨진 문자로 잘못
해석해 압축 해제에 실패하거나 파일을 건너뛰는 경우가 있다. 이를 원천적으로
피하기 위해 실제 파일명은 ASCII로 두고, 사이드바에 표시되는 한글/이모지
제목은 아래 st.Page(title=..., icon=...)로 분리해서 지정한다.
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st

st.set_page_config(
    page_title="검진기관 찾기 | 국민건강보험 검진기관 안내",
    page_icon="🏥",
    layout="wide",
)

pg = st.navigation(
    [
        st.Page("views/home.py", title="홈", icon="🏠", default=True),
        st.Page("views/search.py", title="검진기관 찾기", icon="🔍"),
        st.Page("views/chat.py", title="AI 상담", icon="💬"),
    ]
)
pg.run()
