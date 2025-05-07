import gspread
from datetime import datetime
import json
import streamlit as st
import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from fpdf import FPDF

# 기본 설정
st.set_page_config(page_title="교공이", layout="centered")
st.title("🤖 교공이 챗봇")
team_codes = {"A팀": "2025", "B팀": "2024"}
folder_ids = {"A팀": "1-9vL1B5O2LoS1uyBzPK3Y6kIfOSKG-Fo", "B팀": "1BFqy-38ZOFEvxvqPBwRo5-SOaVSoK-oL"}

# 세션 초기화
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

# 분석 결과 파싱 함수

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

# 구글시트 데이터 불러오기

def load_team_history(gc, team_name):
    sh = gc.open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY")
    worksheet = sh.sheet1
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    df.columns = [str(col).strip() for col in df.columns]
    if '시간' not in df.columns:
        return pd.DataFrame()
    df['시간'] = pd.to_datetime(df['시간'], errors='coerce')
    team_df = df[df['팀명'] == team_name].sort_values(by='시간')
    return team_df

# 맥락 요약 생성

def build_context_summary(team_df):
    if team_df.empty:
        return "※ 과거 회의 요약이 없습니다. 이번 회의 내용을 중심으로 분석을 잘 시작해보세요!"
    summary = ""
    for _, row in team_df.iterrows():
        summary += f"[{row['시간']}] {row.get('회의록 제목', '제목 없음')}\n"
        summary += f"- 잘한 점: {row.get('잘한 점', '')}\n"
        summary += f"- 개선점: {row.get('개선점', '')}\n"
        summary += f"- 다음 회의 추천: {row.get('다음회의 추천', '')}\n\n"
    return summary

# 결과 PDF로 저장

def export_pdf(result_text, file_name):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in result_text.split('\n'):
        pdf.multi_cell(0, 10, line)
    pdf.output(file_name)
    return file_name

# 대시보드 표시

def display_dashboard(gc, team_name):
    team_df = load_team_history(gc, team_name)
    if team_df.empty:
        st.info("아직 회의 기록이 없습니다. 첫 회의 기록을 저장해 주세요!")
        return

    if "현재 단계" in team_df.columns:
        st.subheader("📈 프로젝트 진행 단계 추이")
        plt.figure(figsize=(10, 4))
        sns.lineplot(data=team_df, x="시간", y="현재 단계", marker="o")
        plt.xticks(rotation=45)
        st.pyplot(plt)

    if "역할 정리" in team_df.columns:
        st.subheader("📌 역할별 기여도 분석")
        roles = team_df["역할 정리"].dropna().str.extractall(r"([가-힣]+)\s*[:：]")
        role_counts = roles[0].value_counts()
        fig, ax = plt.subplots()
        role_counts.plot(kind='pie', autopct='%1.1f%%', startangle=90, ax=ax)
        ax.set_ylabel("")
        ax.set_title("역할별 기여 비율")
        st.pyplot(fig)

    st.subheader("📋 완료/미완료 체크표")
    if "현재 단계" in team_df.columns:
        status_counts = team_df["현재 단계"].value_counts()
        st.write(status_counts.to_frame(name="횟수"))

    st.subheader("💡 회의별 개선 제안 요약")
    for _, row in team_df.iterrows():
        st.markdown(f"**📅 {row['시간'].strftime('%Y-%m-%d %H:%M')} - {row.get('회의록 제목', '')}**")
        st.markdown(f"> {row.get('개선점', '')}")

# 시트 저장 함수

def save_to_sheet(gc, team_name, title, parsed):
    try:
        worksheet = gc.open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY").sheet1
        worksheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            team_name,
            title,
            parsed.get("잘한 점", ""),
            parsed.get("개선점", ""),
            parsed.get("다음 회의 추천", "")
        ])
        return True
    except Exception as e:
        st.error(f"❌ 저장 실패: {e}")
        return False

# 인증 처리 및 회의록 선택
code_input = st.text_input("✅ 팀 코드를 입력하세요", type="password")
if code_input:
    team_name = next((team for team, code in team_codes.items() if code_input == code), None)
    if team_name:
        st.session_state.authenticated = True
        st.session_state.team_name = team_name
        st.success(f"🎉 인증 완료: {team_name}")
    else:
        st.error("❌ 팀 코드가 올바르지 않습니다.")

# 인증 후 실행
if st.session_state.authenticated:
    team_name = st.session_state.team_name
    folder_id = folder_ids[team_name]
    creds_info = json.loads(st.secrets["google"]["GOOGLE_SERVICE_ACCOUNT"])
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive.readonly',
        'https://www.googleapis.com/auth/documents.readonly'
    ]
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)
    openai_client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document'",
        pageSize=10,
        fields="files(id, name, createdTime)"
    ).execute()
    files = results.get('files', [])

    if files:
        file_dict = {f["name"]: f["id"] for f in sorted(files, key=lambda x: x['createdTime'])}
        selected_file = st.selectbox("📝 회의록 회차 선택", list(file_dict.keys()))
        st.session_state.selected_file = selected_file

        if st.button("🔍 회의록 분석 시작"):
            doc = docs_service.documents().get(documentId=file_dict[selected_file]).execute()
            elements = doc.get("body", {}).get("content", [])
            meeting_text = ''.join(
                elem['textRun']['content']
                for v in elements if 'paragraph' in v
                for elem in v['paragraph'].get('elements', []) if 'textRun' in elem
            )
            st.session_state.meeting_text = meeting_text

            team_df = load_team_history(gc, team_name)
            context_summary = build_context_summary(team_df)

            with st.spinner("GPT가 회의록을 분석 중입니다..."):
                response = openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": f"""
당신은 교육공학 수업의 기말 프로젝트를 수행 중인 예비 교사 팀의 회의 내용을 분석하는 챗봇입니다.
이 팀은 중등 교사 대상 원격 직무연수 콘텐츠인 「에듀테크 활용 PBL 수업 실천법」을 설계하고 있습니다.
학생들은 실제 교육 현장에서 적용 가능한 수업 사례가 포함된 강의 콘텐츠를 개발해야 합니다.

회의록을 읽고 다음과 같은 분석을 진행하세요:
1. 👍 잘한 점
2. ⚠️ 주요 개선점
3. ✨ 다음 회의 추천 포인트
"""},
                        {"role": "user", "content": f"[과거 회의 요약]\n{context_summary}\n\n[이번 회의 내용]\n{meeting_text}"}
                    ]
                )
                st.session_state.result_text = response.choices[0].message.content
                st.success("✅ 분석 완료!")

            parsed = extract_structured_feedback(st.session_state.result_text)
            if parsed:
                saved = save_to_sheet(gc, team_name, selected_file, parsed)
                if saved:
                    st.success("📌 구글시트에 저장되었습니다.")

        if st.session_state.result_text:
            st.subheader("📋 분석 결과")
            st.write(st.session_state.result_text)
            if st.button("📄 결과 PDF로 저장"):
                filename = f"분석결과_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                export_pdf(st.session_state.result_text, filename)
                with open(filename, "rb") as f:
                    st.download_button("⬇️ PDF 다운로드", f, file_name=filename)

    if st.button("📊 대시보드 보기"):
        display_dashboard(gc, team_name)
