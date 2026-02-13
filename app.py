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
import streamlit.components.v1 as components
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
DATA_FILE = os.path.join(DATA_DIR, "evaluation_data.xlsx")
CATEGORIES_FILE = os.path.join(DATA_DIR, "categories.xlsx")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

KTAS_OPTIONS = [
    "Level 1 - 즉각 소생 (Resuscitation)",
    "Level 2 - 긴급 (Emergency)",
    "Level 3 - 응급 (Urgent)",
    "Level 4 - 준응급 (Less Urgent)",
    "Level 5 - 비응급 (Non-Urgent)",
]

STEP_MAJOR = 0
STEP_SUB = 1
STEP_KTAS = 2
STEP_LABELS = {STEP_MAJOR: "대분류", STEP_SUB: "중분류", STEP_KTAS: "KTAS Level"}


# ─────────────────────────────────────────────
# 데이터 로딩
# ─────────────────────────────────────────────
@st.cache_data
def load_data():
    """evaluation_data.xlsx 엑셀 파일에서 평가 데이터를 로드합니다."""
    if not os.path.exists(DATA_FILE):
        st.error(f"데이터 파일을 찾을 수 없습니다: {DATA_FILE}")
        st.stop()

    df = pd.read_excel(DATA_FILE, engine="openpyxl")

    data = []
    for _, row in df.iterrows():
        raw_conv = row["챗GPT와 대화한 내용"]
        conversation = []
        if isinstance(raw_conv, str):
            try:
                parsed = json.loads(raw_conv)
                if isinstance(parsed, list):
                    conversation = parsed
                else:
                    conversation = raw_conv
            except (json.JSONDecodeError, TypeError):
                conversation = raw_conv
        else:
            conversation = raw_conv

        age_value = str(row.get("나이", "")).strip() if pd.notna(row.get("나이")) else ""

        item = {
            "id": int(row["index"]),
            "conversation": conversation,
            "age": age_value,
            "llm_major": str(row.get("LLM_대분류", "")) if pd.notna(row.get("LLM_대분류")) else "",
            "llm_sub": str(row.get("LLM_중분류", "")) if pd.notna(row.get("LLM_중분류")) else "",
            "llm_ktas": str(row.get("LLM_KTAS_level", "")) if pd.notna(row.get("LLM_KTAS_level")) else "",
        }
        data.append(item)

    return data


@st.cache_data
def load_categories():
    """categories.xlsx에서 대분류-중분류 계층 구조를 로드합니다."""
    if not os.path.exists(CATEGORIES_FILE):
        return None

    all_cat_map = {}
    for sheet_name in ["성인", "소아"]:
        try:
            df = pd.read_excel(CATEGORIES_FILE, sheet_name=sheet_name, engine="openpyxl")
        except Exception:
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
# 세션 상태 초기화
# ─────────────────────────────────────────────
def init_session_state():
    defaults = {
        "page": "login",
        "evaluator_id": "",
        "version": "ver1",
        "current_index": 0,
        "current_step": STEP_MAJOR,
        "results": {},
        "data": None,
        "categories": None,
        "step_start_time": None,
        "start_index": 0,
        "temp_major": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ─────────────────────────────────────────────
# 문진 대화 렌더링 (components.html — iframe)
# ─────────────────────────────────────────────
def render_conversation(conversation):
    """문진 대화를 채팅 형태로 렌더링합니다.
    components.html()을 사용하므로 HTML이 항상 올바르게 표시됩니다.
    """
    chat_bubbles = ""
    msg_count = 0

    if isinstance(conversation, list):
        for entry in conversation:
            speaker = entry.get("speaker", "")
            utterance = str(entry.get("utterance", ""))
            turn = entry.get("turn", "")
            # HTML 이스케이프
            utterance = (
                utterance.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

            if speaker == "I":
                chat_bubbles += (
                    '<div class="msg-row left">'
                    '<div class="bubble bbl-i">'
                    f'<div class="lbl lbl-i">&#x1F9D1;&#x200D;&#x2695;&#xFE0F; 면담자'
                    f' <span class="turn-tag">Turn {turn}</span></div>'
                    f'<div class="txt">{utterance}</div>'
                    '</div></div>'
                )
            elif speaker == "CHATGPT":
                chat_bubbles += (
                    '<div class="msg-row right">'
                    '<div class="bubble bbl-p">'
                    f'<div class="lbl lbl-p">&#x1F916; 환자(ChatGPT)'
                    f' <span class="turn-tag">Turn {turn}</span></div>'
                    f'<div class="txt">{utterance}</div>'
                    '</div></div>'
                )
            else:
                chat_bubbles += (
                    '<div class="msg-row left">'
                    '<div class="bubble bbl-o">'
                    f'<div class="lbl lbl-o">{speaker}'
                    f' <span class="turn-tag">Turn {turn}</span></div>'
                    f'<div class="txt">{utterance}</div>'
                    '</div></div>'
                )
            msg_count += 1

    elif isinstance(conversation, str):
        lines = conversation.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            if any(line.startswith(p) for p in ["의사:", "Doctor:", "I:"]):
                content = line.split(":", 1)[1].strip()
                content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                chat_bubbles += (
                    '<div class="msg-row left"><div class="bubble bbl-i">'
                    '<div class="lbl lbl-i">&#x1F9D1;&#x200D;&#x2695;&#xFE0F; 면담자</div>'
                    f'<div class="txt">{content}</div>'
                    '</div></div>'
                )
            elif any(line.startswith(p) for p in ["환자:", "Patient:", "CHATGPT:"]):
                content = line.split(":", 1)[1].strip()
                content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                chat_bubbles += (
                    '<div class="msg-row right"><div class="bubble bbl-p">'
                    '<div class="lbl lbl-p">&#x1F916; 환자(ChatGPT)</div>'
                    f'<div class="txt">{content}</div>'
                    '</div></div>'
                )
            else:
                chat_bubbles += (
                    '<div class="msg-row left"><div class="bubble bbl-o">'
                    f'<div class="txt">{esc}</div>'
                    '</div></div>'
                )
            msg_count += 1

    estimated_height = max(450, min(msg_count * 72, 700))

    full_html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        '*{margin:0;padding:0;box-sizing:border-box;}'
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,'
        '"Noto Sans KR",sans-serif;background:#F8F9FB;padding:10px 12px;}'
        '.msg-row{display:flex;margin-bottom:8px;}'
        '.msg-row.left{justify-content:flex-start;}'
        '.msg-row.right{justify-content:flex-end;}'
        '.bubble{max-width:82%;padding:10px 14px;border-radius:14px;line-height:1.55;}'
        '.bbl-i{background:#fff;border:1px solid #D6E4F0;border-bottom-left-radius:4px;}'
        '.bbl-p{background:#EEF6FF;border:1px solid #C5DCF0;border-bottom-right-radius:4px;}'
        '.bbl-o{background:#F5F5F5;border:1px solid #E0E0E0;border-bottom-left-radius:4px;}'
        '.lbl{font-size:11.5px;font-weight:700;margin-bottom:3px;}'
        '.lbl-i{color:#2C6FBF;}'
        '.lbl-p{color:#C25700;}'
        '.lbl-o{color:#666;}'
        '.turn-tag{font-weight:400;font-size:10.5px;color:#999;margin-left:4px;}'
        '.txt{font-size:13.5px;color:#2D3748;word-break:keep-all;overflow-wrap:break-word;}'
        '</style></head><body>'
        f'{chat_bubbles}'
        '</body></html>'
    )

    components.html(full_html, height=estimated_height, scrolling=True)


# ─────────────────────────────────────────────
# 단계 진행 표시 (components.html — iframe)
# ─────────────────────────────────────────────
def render_step_indicator(current_step):
    """단계 진행 표시를 components.html로 렌더링합니다."""
    steps_info = [("1", "대분류"), ("2", "중분류"), ("3", "KTAS Level")]
    parts = ""
    for i, (num, label) in enumerate(steps_info):
        if i < current_step:
            c_css = "background:#48BB78;color:#fff;border:2px solid #48BB78;"
            l_css = "color:#48BB78;font-weight:600;"
            icon = "&#10003;"
        elif i == current_step:
            c_css = "background:#4A90D9;color:#fff;border:2px solid #4A90D9;"
            l_css = "color:#4A90D9;font-weight:700;"
            icon = num
        else:
            c_css = "background:#fff;color:#CBD5E0;border:2px solid #CBD5E0;"
            l_css = "color:#A0AEC0;font-weight:400;"
            icon = num

        connector = ""
        if i < len(steps_info) - 1:
            cc = "#48BB78" if i < current_step else "#E2E8F0"
            connector = f'<div style="flex:1;height:2px;background:{cc};margin:0 8px;align-self:center;"></div>'

        parts += (
            '<div style="display:flex;flex-direction:column;align-items:center;min-width:80px;">'
            f'<div style="width:32px;height:32px;border-radius:50%;display:flex;'
            f'align-items:center;justify-content:center;font-size:14px;font-weight:700;{c_css}">{icon}</div>'
            f'<div style="margin-top:4px;font-size:12.5px;{l_css}">{label}</div>'
            f'</div>{connector}'
        )

    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        '*{margin:0;padding:0;box-sizing:border-box;}'
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,'
        '"Noto Sans KR",sans-serif;background:transparent;'
        'display:flex;justify-content:center;padding:6px 0;}'
        '</style></head><body>'
        '<div style="display:flex;align-items:flex-start;justify-content:center;padding:4px 40px;">'
        f'{parts}'
        '</div></body></html>'
    )

    components.html(html, height=70, scrolling=False)


# ─────────────────────────────────────────────
# 카테고리 헬퍼
# ─────────────────────────────────────────────
def _get_cat_map_for_item(item: dict):
    all_cat_map = st.session_state.categories
    if not all_cat_map:
        return None
    age = item.get("age", "")
    if age == "15세 미만":
        return all_cat_map.get("소아")
    return all_cat_map.get("성인")


def get_sub_categories_for_major(major_category: str, item: dict) -> list:
    cat_map = _get_cat_map_for_item(item)
    if cat_map and major_category in cat_map:
        return cat_map[major_category]
    return item.get("sub_categories", [])


def get_major_categories(item: dict) -> list:
    cat_map = _get_cat_map_for_item(item)
    if cat_map:
        return list(cat_map.keys())
    return item.get("major_categories", [])


# ─────────────────────────────────────────────
# 페이지 1: 로그인
# ─────────────────────────────────────────────
def login_page():
    st.markdown("")
    st.markdown("")

    _, col_center, _ = st.columns([1, 2.2, 1])
    with col_center:
        # 타이틀 (components.html)
        components.html(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            '*{margin:0;padding:0;box-sizing:border-box;}'
            'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,'
            '"Noto Sans KR",sans-serif;background:transparent;text-align:center;padding:10px 0;}'
            '.t{font-size:36px;font-weight:800;color:#1E3A5F;letter-spacing:-0.5px;}'
            '.s{font-size:15px;color:#8899AA;margin-top:6px;}'
            '</style></head><body>'
            '<div class="t">&#x1F3E5; 문진 대화 평가 시스템</div>'
            '<div class="s">Medical Triage Conversation Evaluation</div>'
            '</body></html>',
            height=90,
            scrolling=False,
        )

        st.markdown("")

        # 로그인 카드
        with st.container(border=True):
            st.markdown("#### 평가자 로그인")
            st.markdown("")

            evaluator_id = st.text_input(
                "평가자 식별 번호",
                placeholder="예: E001",
                help="본인에게 부여된 식별 번호를 입력하세요.",
            )

            st.markdown("")

            version = st.radio(
                "평가 버전 선택",
                options=["ver1", "ver2"],
                captions=[
                    "기본 평가 (대분류 / 중분류 / KTAS 선택)",
                    "LLM 답변 참고 평가 (각 항목에 LLM 예측값 표시)",
                ],
                horizontal=True,
            )

        st.markdown("")

        # 시작 방식 카드
        with st.container(border=True):
            st.markdown("#### 평가 시작 방식")
            st.markdown("")

            start_mode = st.radio(
                "평가 시작 방식을 선택하세요",
                options=["처음부터 평가", "이어서 평가 (문제 번호 선택)"],
                horizontal=True,
                label_visibility="collapsed",
            )

            start_number = 1
            if start_mode == "이어서 평가 (문제 번호 선택)":
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
        st.markdown("")

        if st.button("평가 시작", type="primary", use_container_width=True):
            if evaluator_id.strip():
                st.session_state.evaluator_id = evaluator_id.strip()
                st.session_state.version = version
                st.session_state.data = load_data()
                st.session_state.categories = load_categories()
                st.session_state.current_index = start_number - 1
                st.session_state.start_index = start_number - 1
                st.session_state.current_step = STEP_MAJOR
                st.session_state.step_start_time = time.time()
                st.session_state.temp_major = None
                st.session_state.page = "evaluation"
                st.rerun()
            else:
                st.error("식별 번호를 입력해주세요.")


# ─────────────────────────────────────────────
# 페이지 2: 평가
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

    if idx >= total:
        st.session_state.page = "result"
        st.rerun()
        return

    item = data[idx]
    item_id = str(item["id"])

    if st.session_state.step_start_time is None:
        st.session_state.step_start_time = time.time()

    # 완료 수 (_temp 제외)
    completed = len({k: v for k, v in st.session_state.results.items() if not k.endswith("_temp")})

    # ── 상단: 진행률 + 평가자 정보 ──
    h1, h2 = st.columns([5, 1])
    with h1:
        progress_ratio = completed / total
        st.progress(progress_ratio, text=f"진행률: {completed} / {total} 완료")
    with h2:
        ver_label = "기본" if st.session_state.version == "ver1" else "LLM참고"
        st.success(f"**{st.session_state.evaluator_id}** ({ver_label})")

    # ── 단계 표시 (components.html) ──
    render_step_indicator(step)

    st.divider()

    # ── 본문: 대화(왼쪽) + 평가(오른쪽) ──
    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        age_label = item.get("age", "")
        age_suffix = f" ({age_label})" if age_label else ""
        st.subheader(f"문진 대화 #{item['id']}{age_suffix}")
        render_conversation(item["conversation"])

    with col_right:
        st.subheader(f"평가: {STEP_LABELS[step]}")

        selected_value = None

        # ── 단계 0: 대분류 ──
        if step == STEP_MAJOR:
            major_options = get_major_categories(item)

            if is_ver2 and item.get("llm_major"):
                st.info(f"**LLM 예측:** {item['llm_major']}")

            st.markdown("**아래에서 대분류를 선택하세요:**")
            selected_value = st.radio(
                "대분류를 선택하세요",
                options=major_options,
                index=None,
                key=f"radio_major_{idx}",
                label_visibility="collapsed",
            )

        # ── 단계 1: 중분류 ──
        elif step == STEP_SUB:
            selected_major = st.session_state.temp_major
            if selected_major:
                sub_options = get_sub_categories_for_major(selected_major, item)
                st.info(f"**선택된 대분류:** {selected_major}")
            else:
                sub_options = item.get("sub_categories", [])

            if is_ver2 and item.get("llm_sub"):
                st.info(f"**LLM 예측:** {item['llm_sub']}")

            st.markdown("**아래에서 중분류를 선택하세요:**")
            selected_value = st.radio(
                "중분류를 선택하세요",
                options=sub_options,
                index=None,
                key=f"radio_sub_{idx}",
                label_visibility="collapsed",
            )

        # ── 단계 2: KTAS Level ──
        elif step == STEP_KTAS:
            selected_major = st.session_state.temp_major
            temp_result = st.session_state.results.get(f"{item_id}_temp", {})
            selected_sub = temp_result.get("sub", "")

            st.info(f"**선택된 대분류:** {selected_major}")
            st.info(f"**선택된 중분류:** {selected_sub}")

            if is_ver2 and item.get("llm_ktas"):
                st.info(f"**LLM 예측:** {item['llm_ktas']}")

            st.markdown("**아래에서 KTAS Level을 선택하세요:**")
            selected_value = st.radio(
                "KTAS Level을 선택하세요",
                options=KTAS_OPTIONS,
                index=None,
                key=f"radio_ktas_{idx}",
                label_visibility="collapsed",
            )

    # ── 하단 네비게이션 ──
    st.divider()
    nav1, nav2, nav3 = st.columns([2, 3, 2])

    with nav1:
        st.caption(f"문제 {idx + 1} / {total}  ·  {STEP_LABELS[step]}")

    with nav2:
        if st.button("평가 완료 및 결과 저장", use_container_width=True):
            st.session_state.page = "result"
            st.rerun()

    with nav3:
        if selected_value is not None:
            if st.button("다음 →", type="primary", use_container_width=True):
                elapsed = time.time() - (st.session_state.step_start_time or time.time())

                if step == STEP_MAJOR:
                    st.session_state.temp_major = selected_value
                    st.session_state.results[f"{item_id}_temp"] = {
                        "major": selected_value,
                        "time_major": round(elapsed, 2),
                    }
                    st.session_state.current_step = STEP_SUB

                elif step == STEP_SUB:
                    temp = st.session_state.results.get(f"{item_id}_temp", {})
                    temp["sub"] = selected_value
                    temp["time_sub"] = round(elapsed, 2)
                    st.session_state.results[f"{item_id}_temp"] = temp
                    st.session_state.current_step = STEP_KTAS

                elif step == STEP_KTAS:
                    temp = st.session_state.results.pop(f"{item_id}_temp", {})
                    st.session_state.results[item_id] = {
                        "major": temp.get("major", ""),
                        "sub": temp.get("sub", ""),
                        "ktas": selected_value,
                        "time_major": temp.get("time_major", 0),
                        "time_sub": temp.get("time_sub", 0),
                        "time_ktas": round(elapsed, 2),
                    }
                    st.session_state.current_index += 1
                    st.session_state.current_step = STEP_MAJOR
                    st.session_state.temp_major = None

                st.session_state.step_start_time = time.time()
                st.rerun()
        else:
            st.button(
                "항목을 선택하세요",
                type="secondary",
                use_container_width=True,
                disabled=True,
            )

    st.caption("※ 다음 화면으로 넘어간 후에는 이전 평가를 번복할 수 없습니다.")


# ─────────────────────────────────────────────
# 페이지 3: 결과
# ─────────────────────────────────────────────
def result_page():
    st.title("📊 평가 결과")

    data = st.session_state.data or []
    total = len(data)

    final_results = {
        k: v for k, v in st.session_state.results.items()
        if not k.endswith("_temp")
    }
    completed = len(final_results)

    if completed == 0:
        st.warning("아직 완료된 평가가 없습니다.")
        if st.button("← 평가 화면으로 돌아가기"):
            st.session_state.page = "evaluation"
            st.rerun()
        return

    if completed < total:
        st.info(f"총 {total}개 중 **{completed}개** 평가 완료 — 현재까지의 결과를 저장할 수 있습니다.")
    else:
        st.success(f"총 **{completed}개**의 평가가 모두 완료되었습니다!")

    st.divider()

    # 결과 DataFrame
    rows = []
    for item in data:
        item_id = str(item["id"])
        if item_id in final_results:
            result = final_results[item_id]
            rows.append({
                "index": item["id"],
                "평가자_식별번호": st.session_state.evaluator_id,
                "나이": item.get("age", ""),
                "대분류": result["major"],
                "중분류": result["sub"],
                "KTAS level": result["ktas"],
                "대분류_소요시간(초)": result.get("time_major", ""),
                "중분류_소요시간(초)": result.get("time_sub", ""),
                "KTAS_소요시간(초)": result.get("time_ktas", ""),
            })

    df = pd.DataFrame(rows)

    # 요약 통계
    st.subheader("평가 요약")
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("평가 완료", f"{completed} / {total}")
    with m2:
        if not df.empty and len(df) > 0:
            st.metric("최다 대분류", df["대분류"].mode().iloc[0])
    with m3:
        if not df.empty and len(df) > 0:
            st.metric("최다 KTAS", df["KTAS level"].mode().iloc[0])

    st.markdown("")

    # 결과 테이블
    st.subheader("결과 미리보기")
    st.dataframe(df, use_container_width=True, height=400)

    st.divider()

    # 다운로드
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"evaluation_{st.session_state.evaluator_id}_{st.session_state.version}_{timestamp}.csv"
    csv_data = df.to_csv(index=False).encode("utf-8-sig")

    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            label="CSV 파일 다운로드",
            data=csv_data,
            file_name=filename,
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )
    with d2:
        if st.button("서버에 결과 저장", use_container_width=True):
            os.makedirs(RESULTS_DIR, exist_ok=True)
            save_path = os.path.join(RESULTS_DIR, filename)
            df.to_csv(save_path, index=False, encoding="utf-8-sig")
            st.success(f"저장 완료: {save_path}")

    st.divider()
    if completed < total:
        if st.button("이어서 평가하기", use_container_width=True):
            st.session_state.page = "evaluation"
            st.rerun()


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="문진 대화 평가 시스템",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

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