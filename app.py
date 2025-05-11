from datetime import datetime
import json
import streamlit as st
import pandas as pd
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from fpdf import FPDF
import openai
import difflib

# ✅ Streamlit 기본 설정
st.set_page_config(page_title="교공이", layout="centered")
st.title("🤖 교공이 챗봇")

team_codes = {"A팀": "2025", "B팀": "2024"}
folder_ids = {"A팀": "1-9vL1B5O2LoS1uyBzPK3Y6kIfOSKG-Fo", "B팀": "1BFqy-38ZOFEvxvqPBwRo5-SOaVSoK-oL"}

for key in ["authenticated", "team_name", "meeting_text", "result_text", "selected_file"]:
    if key not in st.session_state:
        st.session_state[key] = "" if key != "authenticated" else False

# ✅ 분석 결과 파싱 함수
def extract_structured_feedback(text):
    sections = {
        "역할 정리": "", "자기조절": "", "메타인지": "", "정서적 피드백": "",
        "개선 제안": "", "진행 요약": "", "다음 회의 제안": ""
    }
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

# ✅ 회의 기록 불러오기
def load_team_history(creds, team_name):
    sh = gspread.authorize(creds).open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY")
    worksheet = sh.sheet1
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    df.columns = [str(col).strip() for col in df.columns]
    if '시간' not in df.columns:
        return pd.DataFrame()
    df['시간'] = pd.to_datetime(df['시간'], errors='coerce')
    return df[df['팀명'] == team_name].sort_values(by='시간')

# ✅ 과거 회의 요약 생성
def build_context_summary(team_df):
    if team_df.empty:
        return "※ 과거 회의 요약이 없습니다. 이번 회의를 잘 시작해보세요!"

    latest_row = team_df.iloc[-1]
    summary = f"[{latest_row['시간']}] {latest_row.get('회의록 제목', '제목 없음')}\n"
    summary += f"- 역할 정리: {latest_row.get('역할 정리', '')}\n"
    summary += f"- 자기조절: {latest_row.get('자기조절', '')}\n"
    summary += f"- 메타인지: {latest_row.get('메타인지', '')}\n"
    summary += f"- 정서적 피드백: {latest_row.get('정서적 피드백', '')}\n"
    summary += f"- 개선 제안: {latest_row.get('개선 제안', '')}\n"
    summary += f"- 진행 요약: {latest_row.get('진행 요약', '')}\n"
    summary += f"- 다음 회의 제안: {latest_row.get('다음 회의 제안', '')}\n"
    return summary

# ✅ 유사도 체크 함수
def is_similar_to_previous(meeting_text, team_df, threshold=0.9):
    if team_df.empty:
        return False
    last_text = "\n".join([
        str(team_df.iloc[-1].get("개선 제안", "")),
        str(team_df.iloc[-1].get("진행 요약", "")),
        str(team_df.iloc[-1].get("다음 회의 제안", ""))
    ])
    seq = difflib.SequenceMatcher(None, meeting_text.strip(), last_text.strip())
    return seq.ratio() >= threshold

# ✅ PDF 저장
def export_pdf(result_text, file_name):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in result_text.split('\n'):
        pdf.multi_cell(0, 10, line)
    pdf.output(file_name)
    return file_name

# ✅ 시트 저장 (7개 항목 저장)
def save_to_sheet(gc, team_name, title, parsed):
    try:
        worksheet = gc.open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY").sheet1
        worksheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            team_name,
            title,
            parsed.get("역할 정리", ""),
            parsed.get("자기조절", ""),
            parsed.get("메타인지", ""),
            parsed.get("정서적 피드백", ""),
            parsed.get("개선 제안", ""),
            parsed.get("진행 요약", ""),
            parsed.get("다음 회의 제안", "")
        ])
        return True
    except Exception as e:
        st.error(f"❌ 저장 실패: {e}")
        return False

# ✅ 사용자에게 보여줄 3개 요약 출력
def display_summary_feedback(parsed):
    st.subheader("📋 회의 요약 피드백")
    st.markdown(f"**👍 잘한 점**\n\n{parsed.get('역할 정리', '')}\n{parsed.get('자기조절', '')}")
    st.markdown(f"**⚠️ 개선할 점**\n\n{parsed.get('개선 제안', '')}\n{parsed.get('진행 요약', '')}")
    st.markdown(f"**✨ 다음 회의 제안**\n\n{parsed.get('다음 회의 제안', '')}")
