import gspread
from datetime import datetime
import json
import streamlit as st
import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
import altair as alt
import base64

# 팀 코드 입력 및 회의록 선택 복구
st.set_page_config(page_title="교공이", layout="centered")
st.title("🤖 교공이 챗봇")
team_codes = {"A팀": "2025", "B팀": "2024"}
folder_ids = {"A팀": "1-9vL1B5O2LoS1uyBzPK3Y6kIfOSKG-Fo", "B팀": "1BFqy-38ZOFEvxvqPBwRo5-SOaVSoK-oL"}

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "team_name" not in st.session_state:
    st.session_state.team_name = ""
if "meeting_text" not in st.session_state:
    st.session_state.meeting_text = ""
if "result_text" not in st.session_state:
    st.session_state.result_text = ""
if "selected_file" not in st.session_state:
    st.session_state.selected_file = ""

if not st.session_state.authenticated:
    code_input = st.text_input("✅ 팀 코드를 입력하세요", type="password")
    if code_input:
        team_name = next((team for team, code in team_codes.items() if code_input == code), None)
        if team_name:
            st.session_state.authenticated = True
            st.session_state.team_name = team_name
            st.success(f"🎉 인증 완료: {team_name}")
        else:
            st.error("❌ 팀 코드가 올바르지 않습니다.")

# 분석 결과 파싱 함수 (시스템 프롬프트 기반)
def extract_structured_feedback(text):
    sections = {"잘한 점": "", "개선점": "", "다음 회의 추천": ""}
    for key in sections:
        if key in text:
            try:
                after = text.split(key)[1]
                for next_key in sections:
                    if next_key != key and next_key in after:
                        after = after.split(next_key)[0]
                sections[key] = after.strip()
            except:
                sections[key] = ""
    return sections

# 팀 회의 데이터 불러오기
def load_team_history(gc, team_name):
    sh = gc.open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY")
    worksheet = sh.sheet1
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    df['시간'] = pd.to_datetime(df['시간'])
    team_df = df[df['팀명'] == team_name].sort_values(by='시간')
    return team_df

# 회의 맥락 요약
def build_context_summary(team_df):
    if team_df.empty:
        return "※ 과거 회의 요약이 없습니다. 이번 회의 내용을 중심으로 분석을 진행해주세요.\n"
    summary = ""
    for _, row in team_df.iterrows():
        summary += f"[{row['시간']}] {row.get('회의록 제목', row.get('회의록 회차 선택', '제목 없음'))}\n"
        summary += f"- 역할 정리: {row.get('역할 정리', '')}\n"
        summary += f"- 참여도: {row.get('참여도', '')}\n"
        summary += f"- 현재 단계: {row.get('현재 단계', '')}\n"
        summary += f"- 개선 제안: {row.get('개선 제안', '')}\n\n"
    return summary

# 대시보드 함수
def display_dashboard(gc, team_name):
    df = load_team_history(gc, team_name)
    st.header(f"\U0001F4CA {team_name} 대시보드")

    if '현재 단계' in df.columns:
        st.subheader("1️⃣ 프로젝트 단계 추이")
        chart = alt.Chart(df).mark_line(point=True).encode(
            x='시간:T', y='현재 단계:N', tooltip=['시간', '현재 단계']
        )
        st.altair_chart(chart, use_container_width=True)

    st.subheader("2️⃣ 주요 과업 진행 체크리스트")
    tasks = [
        ("강의안 초안 작성", True),
        ("PBL 수업 설계안 초안 작성", True),
        ("에듀테크 도구 검토", False),
        ("사례 구체화", False),
        ("슬라이드 정리", False)
    ]
    for task, done in tasks:
        st.checkbox(task, value=done, disabled=True)

    if '역할 정리' in df.columns:
        st.subheader("3️⃣ 역할 분담 빈도 분석")
        roles = df['역할 정리'].dropna().str.extractall(r'([\w가-힣]+)\s*[:：]\s*[^,\n]+')
        counts = roles[0].value_counts().reset_index()
        counts.columns = ['역할자', '기여도']
        pie = alt.Chart(counts).mark_arc().encode(
            theta='기여도:Q', color='역할자:N', tooltip=['역할자', '기여도']
        )
        st.altair_chart(pie, use_container_width=True)

    if '개선 제안' in df.columns:
        st.subheader("4️⃣ 회의별 개선 제안 요약")
        for _, row in df.iterrows():
            st.markdown(f"**\U0001F4C5 {row['시간'].strftime('%Y-%m-%d %H:%M')} - {row.get('회의록 제목', row.get('회의록 회차 선택', ''))}**")
            st.markdown(f"> {row.get('개선 제안', '')}")
