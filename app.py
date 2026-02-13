"""
문진 대화 평가 시스템 (Medical Triage Conversation Evaluation System)
=====================================================================
Streamlit 기반 평가 웹앱
- ver1: 기본 평가 (대분류, 중분류, KTAS Level 선택)
- ver2: LLM 답변 표시 포함 평가

실행 방법:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import json
import os
import time
from datetime import datetime

# ─────────────────────────────────────────────
# 설정 (Configuration)
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "evaluation_data.xlsx")  # 엑셀 파일
CATEGORIES_FILE = os.path.join(DATA_DIR, "categories.xlsx")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

KTAS_OPTIONS = [
    "Level 1 - 즉각 소생 (Resuscitation)",
    "Level 2 - 긴급 (Emergency)",
    "Level 3 - 응급 (Urgent)",
    "Level 4 - 준응급 (Less Urgent)",
    "Level 5 - 비응급 (Non-Urgent)",
]

# 평가 단계: 하나의 문진 대화에 대해 3단계로 나뉨
STEP_MAJOR = 0
STEP_SUB = 1
STEP_KTAS = 2
STEP_LABELS = {STEP_MAJOR: "대분류", STEP_SUB: "중분류", STEP_KTAS: "KTAS Level"}


# ─────────────────────────────────────────────
# 데이터 로딩 (Data Loading)
# ─────────────────────────────────────────────
@st.cache_data
def load_data():
    """evaluation_data.xlsx 엑셀 파일에서 평가 데이터를 로드합니다.

    엑셀 컬럼:
        - index: 문진 대화 고유 번호
        - 나이: '15세 이상' 또는 '15세 미만' (카테고리 시트 결정용)
        - 챗GPT와 대화한 내용: JSON 형식의 대화 데이터
        - LLM_대분류: LLM이 예측한 대분류 (ver2용)
        - LLM_중분류: LLM이 예측한 중분류 (ver2용)
        - LLM_KTAS_level: LLM이 예측한 KTAS 레벨 (ver2용)
    """
    if not os.path.exists(DATA_FILE):
        st.error(f"데이터 파일을 찾을 수 없습니다: {DATA_FILE}")
        st.stop()

    df = pd.read_excel(DATA_FILE, engine="openpyxl")

    data = []
    for _, row in df.iterrows():
        # 대화 내용 파싱: JSON 문자열 → list[dict]
        raw_conv = row["챗GPT와 대화한 내용"]
        if isinstance(raw_conv, str):
            try:
                conversation = json.loads(raw_conv)
            except json.JSONDecodeError:
                conversation = raw_conv  # 파싱 실패 시 원본 문자열 유지
        else:
            conversation = raw_conv

        # 나이 컬럼 읽기: '15세 이상' 또는 '15세 미만'
        age_value = str(row.get("나이", "")).strip() if pd.notna(row.get("나이")) else ""

        item = {
            "id": int(row["index"]),
            "conversation": conversation,  # JSON list 또는 문자열
            "age": age_value,  # '15세 이상' 또는 '15세 미만'
            "llm_major": str(row.get("LLM_대분류", "")) if pd.notna(row.get("LLM_대분류")) else "",
            "llm_sub": str(row.get("LLM_중분류", "")) if pd.notna(row.get("LLM_중분류")) else "",
            "llm_ktas": str(row.get("LLM_KTAS_level", "")) if pd.notna(row.get("LLM_KTAS_level")) else "",
        }
        data.append(item)

    return data


@st.cache_data
def load_categories():
    """categories.xlsx에서 대분류-중분류 계층 구조를 로드합니다.
    엑셀 파일에 '성인', '소아' 두 시트가 있으며, 각 시트는 대분류/중분류 컬럼을 포함.
    반환: { '성인': { '대분류1': ['중분류A', ...], ... }, '소아': { ... } }
    """
    if not os.path.exists(CATEGORIES_FILE):
        return None

    all_cat_map = {}
    for sheet_name in ["성인", "소아"]:
        try:
            df = pd.read_excel(CATEGORIES_FILE, sheet_name=sheet_name, engine="openpyxl")
        except ValueError:
            continue
        cat_map = {}
        for _, row in df.iterrows():
            major = str(row["대분류"]).strip()
            sub = str(row["중분류"]).strip()
            if major not in cat_map:
                cat_map[major] = []
            if sub not in cat_map[major]:
                cat_map[major].append(sub)
        all_cat_map[sheet_name] = cat_map

    return all_cat_map if all_cat_map else None


# ─────────────────────────────────────────────
# 세션 상태 초기화 (Session State)
# ─────────────────────────────────────────────
def init_session_state():
    defaults = {
        "page": "login",             # login | evaluation | result
        "evaluator_id": "",
        "version": "ver1",
        "current_index": 0,          # 현재 평가 중인 문진 대화 인덱스 (0-based)
        "current_step": STEP_MAJOR,   # 현재 평가 단계 (0: 대분류, 1: 중분류, 2: KTAS)
        "results": {},               # { "conv_id": { major, sub, ktas, time_major, time_sub, time_ktas } }
        "data": None,
        "categories": None,          # 대분류-중분류 계층 구조
        "step_start_time": None,     # 현재 단계 시작 시간
        "start_index": 0,            # 이어서 평가 시 시작 인덱스
        "temp_major": None,          # 현재 문진의 선택된 대분류 (임시 저장)
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ─────────────────────────────────────────────
# 문진 대화 렌더링
# ─────────────────────────────────────────────
def render_conversation(conversation):
    """문진 대화를 채팅 형태로 렌더링합니다.

    conversation은 다음 형식 중 하나:
    - list[dict]: [{"turn": 1, "speaker": "I", "utterance": "..."}, ...]
      - speaker "I" → 면담자(의사), "CHATGPT" → 환자(챗봇)
    - str: 기존 "의사: ... \n 환자: ..." 텍스트 형식
    """
    chat_html = ""

    if isinstance(conversation, list):
        # JSON list 형식 (엑셀 데이터)
        for entry in conversation:
            speaker = entry.get("speaker", "")
            utterance = entry.get("utterance", "")
            turn = entry.get("turn", "")

            if speaker == "I":
                label = f"면담자 (Turn {turn})"
                bg_color = "#DCF2FF"
                border_color = "#A8D8F0"
                align = "left"
                label_color = "#1A73E8"
            elif speaker == "CHATGPT":
                label = f"환자-ChatGPT (Turn {turn})"
                bg_color = "#FFF3E0"
                border_color = "#FFCC80"
                align = "right"
                label_color = "#E65100"
            else:
                label = f"{speaker} (Turn {turn})"
                bg_color = "#F5F5F5"
                border_color = "#E0E0E0"
                align = "left"
                label_color = "#555555"

            chat_html += f"""
            <div style="text-align:{align}; margin-bottom:8px;">
                <div style="display:inline-block; max-width:85%; text-align:left;
                            background-color:{bg_color}; border:1px solid {border_color};
                            border-radius:12px; padding:10px 14px;">
                    <span style="font-weight:bold; font-size:12px; color:{label_color};">
                        {label}
                    </span><br/>
                    <span style="font-size:14px; line-height:1.6;">{utterance}</span>
                </div>
            </div>
            """
    elif isinstance(conversation, str):
        # 기존 텍스트 형식 (fallback)
        lines = conversation.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("의사:") or line.startswith("Doctor:") or line.startswith("I:"):
                label = "면담자"
                content = line.split(":", 1)[1].strip()
                bg_color = "#DCF2FF"
                border_color = "#A8D8F0"
                align = "left"
                label_color = "#1A73E8"
            elif line.startswith("환자:") or line.startswith("Patient:") or line.startswith("CHATGPT:"):
                label = "환자-ChatGPT"
                content = line.split(":", 1)[1].strip()
                bg_color = "#FFF3E0"
                border_color = "#FFCC80"
                align = "right"
                label_color = "#E65100"
            else:
                if ":" in line:
                    label = line.split(":")[0].strip()
                    content = line.split(":", 1)[1].strip()
                else:
                    label = ""
                    content = line
                bg_color = "#F5F5F5"
                border_color = "#E0E0E0"
                align = "left"
                label_color = "#555555"

            chat_html += f"""
            <div style="text-align:{align}; margin-bottom:8px;">
                <div style="display:inline-block; max-width:85%; text-align:left;
                            background-color:{bg_color}; border:1px solid {border_color};
                            border-radius:12px; padding:10px 14px;">
                    <span style="font-weight:bold; font-size:12px; color:{label_color};">
                        {label}
                    </span><br/>
                    <span style="font-size:14px; line-height:1.6;">{content}</span>
                </div>
            </div>
            """

    return f"""
    <div style="background-color:#FAFAFA; padding:16px; border-radius:12px;
                max-height:550px; overflow-y:auto; border:1px solid #E0E0E0;">
        {chat_html}
    </div>
    """


# ─────────────────────────────────────────────
# 페이지 1: 로그인 (Login Page)
# ─────────────────────────────────────────────
def login_page():
    st.markdown(
        "<h1 style='text-align:center;'>문진 대화 평가 시스템</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;color:gray;'>Medical Triage Conversation Evaluation</p>",
        unsafe_allow_html=True,
    )

    st.markdown("---")

    _, col_center, _ = st.columns([1, 2, 1])

    with col_center:
        st.subheader("평가자 로그인")

        evaluator_id = st.text_input(
            "평가자 식별 번호",
            placeholder="예: E001",
            help="본인에게 부여된 식별 번호를 입력하세요.",
        )

        version = st.radio(
            "평가 버전 선택",
            options=["ver1", "ver2"],
            captions=[
                "기본 평가 (대분류 / 중분류 / KTAS 선택)",
                "LLM 답변 참고 평가 (각 항목에 LLM 예측값 표시)",
            ],
            horizontal=True,
        )

        st.markdown("---")

        # ── 평가 시작 방식 선택 ──
        st.markdown("#### 평가 시작 방식")
        start_mode = st.radio(
            "평가 시작 방식을 선택하세요",
            options=["처음부터 평가", "이어서 평가 (문제 번호 선택)"],
            horizontal=True,
            label_visibility="collapsed",
        )

        start_number = 1
        if start_mode == "이어서 평가 (문제 번호 선택)":
            # 데이터를 미리 로드하여 총 개수 파악
            preview_data = load_data()
            total_count = len(preview_data)
            start_number = st.number_input(
                "시작할 문제 번호를 입력하세요",
                min_value=1,
                max_value=total_count,
                value=1,
                step=1,
                help=f"1 ~ {total_count} 사이의 번호를 입력하세요.",
            )

        st.markdown("")

        if st.button("평가 시작", type="primary", use_container_width=True):
            if evaluator_id.strip():
                st.session_state.evaluator_id = evaluator_id.strip()
                st.session_state.version = version
                st.session_state.data = load_data()
                st.session_state.categories = load_categories()
                st.session_state.current_index = start_number - 1  # 0-based
                st.session_state.start_index = start_number - 1
                st.session_state.current_step = STEP_MAJOR
                st.session_state.step_start_time = time.time()
                st.session_state.temp_major = None
                st.session_state.page = "evaluation"
                st.rerun()
            else:
                st.error("식별 번호를 입력해주세요.")


# ─────────────────────────────────────────────
# 나이에 따른 카테고리 시트 결정
# ─────────────────────────────────────────────
def _get_cat_map_for_item(item: dict) -> dict | None:
    """item의 '나이' 값에 따라 '성인' 또는 '소아' 카테고리 맵을 반환합니다."""
    all_cat_map = st.session_state.categories
    if not all_cat_map:
        return None
    age = item.get("age", "")
    if age == "15세 미만":
        return all_cat_map.get("소아")
    else:
        # '15세 이상' 또는 값이 없는 경우 기본적으로 성인 시트 사용
        return all_cat_map.get("성인")


# ─────────────────────────────────────────────
# 대분류에 대한 중분류 후보 가져오기
# ─────────────────────────────────────────────
def get_sub_categories_for_major(major_category: str, item: dict) -> list:
    """선택된 대분류에 해당하는 중분류 목록을 반환합니다.
    나이에 따라 categories.xlsx의 '성인' 또는 '소아' 시트에서 조회합니다.
    """
    cat_map = _get_cat_map_for_item(item)
    if cat_map and major_category in cat_map:
        return cat_map[major_category]
    # fallback: 데이터에 포함된 sub_categories 사용
    return item.get("sub_categories", [])


# ─────────────────────────────────────────────
# 대분류 후보 가져오기
# ─────────────────────────────────────────────
def get_major_categories(item: dict) -> list:
    """대분류 후보 목록을 반환합니다.
    나이에 따라 categories.xlsx의 '성인' 또는 '소아' 시트에서 조회합니다.
    """
    cat_map = _get_cat_map_for_item(item)
    if cat_map:
        return list(cat_map.keys())
    return item.get("major_categories", [])


# ─────────────────────────────────────────────
# 페이지 2: 평가 (Evaluation Page)
# ─────────────────────────────────────────────
def evaluation_page():
    data = st.session_state.data
    if data is None:
        st.session_state.page = "login"
        st.rerun()
        return

    total = len(data)
    idx = st.session_state.current_index
    step = st.session_state.current_step
    is_ver2 = st.session_state.version == "ver2"

    # 모든 평가 완료 확인
    if idx >= total:
        st.session_state.page = "result"
        st.rerun()
        return

    item = data[idx]
    item_id = str(item["id"])

    # 시간 측정 시작 (첫 렌더 시)
    if st.session_state.step_start_time is None:
        st.session_state.step_start_time = time.time()

    # 완료된 평가 수 계산
    completed = len(st.session_state.results)

    # ── 상단 헤더: 진행률 + 평가자 정��� ──
    header_col1, header_col2 = st.columns([4, 1])

    with header_col1:
        progress_ratio = completed / total
        st.progress(progress_ratio, text=f"진행률: {completed} / {total} 완료")

    with header_col2:
        st.markdown(
            f"""
            <div style="background-color:#E8F5E9; border-radius:8px; padding:8px 12px;
                        text-align:center; border:1px solid #A5D6A7;">
                <span style="font-size:12px; color:#2E7D32;">평가자</span><br/>
                <span style="font-weight:bold; color:#1B5E20;">{st.session_state.evaluator_id}</span>
                <span style="font-size:11px; color:#558B2F;"> ({st.session_state.version})</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 현재 단계 표시
    step_labels_display = ["1. 대분류", "2. 중분류", "3. KTAS Level"]
    step_indicators = ""
    for i, label in enumerate(step_labels_display):
        if i < step:
            color = "#4CAF50"  # 완료
            icon = "&#10003;"
        elif i == step:
            color = "#1A73E8"  # 현재
            icon = "&#9679;"
        else:
            color = "#BDBDBD"  # 미완료
            icon = "&#9675;"
        step_indicators += (
            f"<span style='color:{color}; font-weight:{"bold" if i == step else "normal"}; "
            f"margin-right:16px; font-size:14px;'>"
            f"{icon} {label}</span>"
        )

    st.markdown(
        f"<div style='text-align:center; padding:8px 0;'>{step_indicators}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── 본문: 왼쪽(대화) + 오른쪽(평가) ──
    col_left, col_right = st.columns([1, 1], gap="large")

    # ─── 왼쪽: 문진 대화 (모든 단계에서 고정) ───
    with col_left:
        st.subheader(f"문진 대화 #{item['id']}")
        conversation_html = render_conversation(item["conversation"])
        st.markdown(conversation_html, unsafe_allow_html=True)

    # ─── 오른쪽: 현재 단계의 평가 항목만 표시 ───
    with col_right:
        st.subheader(f"평가: {STEP_LABELS[step]}")

        selected_value = None

        # ── 단계 0: 대분류 선택 ──
        if step == STEP_MAJOR:
            major_options = get_major_categories(item)

            if is_ver2 and item.get("llm_major"):
                st.info(f"**LLM의 답변:** {item['llm_major']}")

            st.markdown("##### 아래에서 대분류를 선택하세요:")
            selected_value = st.radio(
                "대분류를 선택하세요",
                options=major_options,
                index=None,
                key=f"radio_major_{idx}",
                label_visibility="collapsed",
            )

        # ── 단계 1: 중분류 선택 ──
        elif step == STEP_SUB:
            # 이전 단계에서 선택된 대분류에 따라 중분류 후보 결정
            selected_major = st.session_state.temp_major
            if selected_major:
                sub_options = get_sub_categories_for_major(selected_major, item)
                st.markdown(
                    f"<div style='background-color:#E3F2FD; border-radius:8px; padding:8px 12px; "
                    f"margin-bottom:12px; border:1px solid #90CAF9;'>"
                    f"<span style='font-size:12px; color:#1565C0;'>선택된 대분류:</span> "
                    f"<strong style='color:#0D47A1;'>{selected_major}</strong></div>",
                    unsafe_allow_html=True,
                )
            else:
                sub_options = item.get("sub_categories", [])

            if is_ver2 and item.get("llm_sub"):
                st.info(f"**LLM의 답변:** {item['llm_sub']}")

            st.markdown("##### 아래에서 중분류를 선택하세요:")
            selected_value = st.radio(
                "중분류를 선택하세요",
                options=sub_options,
                index=None,
                key=f"radio_sub_{idx}",
                label_visibility="collapsed",
            )

        # ── 단계 2: KTAS Level 선택 ──
        elif step == STEP_KTAS:
            selected_major = st.session_state.temp_major
            temp_result = st.session_state.results.get(f"{item_id}_temp", {})
            selected_sub = temp_result.get("sub", "")

            st.markdown(
                f"<div style='background-color:#E3F2FD; border-radius:8px; padding:8px 12px; "
                f"margin-bottom:12px; border:1px solid #90CAF9;'>"
                f"<span style='font-size:12px; color:#1565C0;'>선택된 대분류:</span> "
                f"<strong style='color:#0D47A1;'>{selected_major}</strong> &nbsp;|&nbsp; "
                f"<span style='font-size:12px; color:#1565C0;'>중분류:</span> "
                f"<strong style='color:#0D47A1;'>{selected_sub}</strong></div>",
                unsafe_allow_html=True,
            )

            if is_ver2 and item.get("llm_ktas"):
                st.info(f"**LLM의 답변:** {item['llm_ktas']}")

            st.markdown("##### 아래에서 KTAS Level을 선택하세요:")
            selected_value = st.radio(
                "KTAS Level을 선택하세요",
                options=KTAS_OPTIONS,
                index=None,
                key=f"radio_ktas_{idx}",
                label_visibility="collapsed",
            )

    # ── 하단 네비게이션 ──
    st.markdown("---")
    nav_col1, nav_col2, nav_col3 = st.columns([2, 3, 2])

    with nav_col1:
        st.markdown(
            f"<div style='text-align:left; padding-top:6px; color:gray; font-size:14px;'>"
            f"문제 {idx + 1} / {total} &middot; {STEP_LABELS[step]}"
            f"</div>",
            unsafe_allow_html=True,
        )

    with nav_col2:
        # 중간 저장 및 평가 완료 버튼
        if st.button("평가 완료 및 결과 저장", use_container_width=True):
            st.session_state.page = "result"
            st.rerun()

    with nav_col3:
        # '다음' 버튼 (선택하지 않으면 비활성)
        if selected_value is not None:
            if st.button("다음", type="primary", use_container_width=True):
                elapsed = time.time() - (st.session_state.step_start_time or time.time())

                if step == STEP_MAJOR:
                    # 대분류 선택 저장 (임시)
                    st.session_state.temp_major = selected_value
                    st.session_state.results[f"{item_id}_temp"] = {
                        "major": selected_value,
                        "time_major": round(elapsed, 2),
                    }
                    st.session_state.current_step = STEP_SUB

                elif step == STEP_SUB:
                    # 중분류 선택 저장 (임시)
                    temp = st.session_state.results.get(f"{item_id}_temp", {})
                    temp["sub"] = selected_value
                    temp["time_sub"] = round(elapsed, 2)
                    st.session_state.results[f"{item_id}_temp"] = temp
                    st.session_state.current_step = STEP_KTAS

                elif step == STEP_KTAS:
                    # KTAS 선택 저장 → 최종 결과 확정
                    temp = st.session_state.results.pop(f"{item_id}_temp", {})
                    st.session_state.results[item_id] = {
                        "major": temp.get("major", ""),
                        "sub": temp.get("sub", ""),
                        "ktas": selected_value,
                        "time_major": temp.get("time_major", 0),
                        "time_sub": temp.get("time_sub", 0),
                        "time_ktas": round(elapsed, 2),
                    }
                    # 다음 문진 대화로 이동
                    st.session_state.current_index += 1
                    st.session_state.current_step = STEP_MAJOR
                    st.session_state.temp_major = None

                # 시간 측정 리셋
                st.session_state.step_start_time = time.time()
                st.rerun()
        else:
            st.button(
                "다음 (항목을 선택하세요)",
                type="secondary",
                use_container_width=True,
                disabled=True,
            )

    # ── 되돌리기 불가 안내 ──
    st.caption("* 다음 화면으로 넘어간 후에는 이전 평가를 번복할 수 없습니다.")


# ─────────────────────────────────────────────
# 페이지 3: 결과 (Result Page)
# ─────────────────────────────────────────────
def result_page():
    st.markdown(
        "<h1 style='text-align:center;'>평가 결과</h1>",
        unsafe_allow_html=True,
    )

    data = st.session_state.data or []
    total = len(data)

    # 최종 확정된 결과만 필터 (임시 _temp 제외)
    final_results = {
        k: v for k, v in st.session_state.results.items()
        if not k.endswith("_temp")
    }
    completed = len(final_results)

    if completed == 0:
        st.warning("아직 완료된 평가가 없습니다.")
        if st.button("평가 화면으로 돌아가기"):
            st.session_state.page = "evaluation"
            st.rerun()
        return

    if completed < total:
        st.info(
            f"총 {total}개 중 {completed}개까지 평가가 완료되었습니다. "
            f"현재까지의 결과를 저장할 수 있습니다."
        )
    else:
        st.success(f"총 {completed}개의 평가가 모두 완료되었습니다!")

    st.markdown("---")

    # 결과 데이터프레임 생성 (요구된 column: index / 평가자_식별번호 / 대분류 / 중분류 / KTAS level)
    rows = []
    for item in data:
        item_id = str(item["id"])
        if item_id in final_results:
            result = final_results[item_id]
            row = {
                "index": item["id"],
                "평가자_식별번호": st.session_state.evaluator_id,
                "나이": item.get("age", ""),
                "대분류": result["major"],
                "중분류": result["sub"],
                "KTAS level": result["ktas"],
                "대분류_소요시간(초)": result.get("time_major", ""),
                "중분류_소요시간(초)": result.get("time_sub", ""),
                "KTAS_소요시간(초)": result.get("time_ktas", ""),
            }
            rows.append(row)

    df = pd.DataFrame(rows)

    # 결과 미리보기
    st.subheader("결�� 미리보기")
    st.dataframe(df, use_container_width=True, height=400)

    # 요약 통계
    st.subheader("평가 요약")
    summary_col1, summary_col2, summary_col3 = st.columns(3)
    with summary_col1:
        st.metric("평가 완료 수", f"{completed} / {total}")
    with summary_col2:
        if not df.empty:
            most_common_major = df["대분류"].mode().iloc[0] if len(df) > 0 else "-"
            st.metric("최다 대분류", most_common_major)
    with summary_col3:
        if not df.empty:
            most_common_ktas = df["KTAS level"].mode().iloc[0] if len(df) > 0 else "-"
            st.metric("최다 KTAS", most_common_ktas)

    st.markdown("---")

    # CSV 다운로드 버튼
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"evaluation_{st.session_state.evaluator_id}_{st.session_state.version}_{timestamp}.csv"

    csv_data = df.to_csv(index=False).encode("utf-8-sig")

    st.download_button(
        label="결과 CSV 파일 다운로드",
        data=csv_data,
        file_name=filename,
        mime="text/csv",
        type="primary",
        use_container_width=True,
    )

    # 서버 측에도 저장
    st.markdown("")
    if st.button("서버에 결과 저장", use_container_width=True):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        save_path = os.path.join(RESULTS_DIR, filename)
        df.to_csv(save_path, index=False, encoding="utf-8-sig")
        st.success(f"저장 완료: {save_path}")

    # 이어서 평가하기 버튼
    st.markdown("---")
    if completed < total:
        if st.button("이어서 평가하기", use_container_width=True):
            st.session_state.page = "evaluation"
            st.rerun()


# ─────────────────────────────────────────────
# 메인 (Main)
# ─────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="문진 대화 평가 시스템",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # 사이드바: 전체 초기화 버튼
    with st.sidebar:
        st.header("설정")
        if st.button("처음부터 다시 시작", type="secondary"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    init_session_state()

    if st.session_state.page == "login":
        login_page()
    elif st.session_state.page == "evaluation":
        evaluation_page()
    elif st.session_state.page == "result":
        result_page()


if __name__ == "__main__":
    main()