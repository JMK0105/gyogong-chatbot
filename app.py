from datetime import datetime
import json
import streamlit as st
import pandas as pd
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from fpdf import FPDF
import openai

# ✅ Streamlit 기본 설정
st.set_page_config(page_title="교공이", layout="centered")
st.title("🤖 교공이 챗봇")

team_codes = {"A팀": "2025", "B팀": "2024"}
folder_ids = {"A팀": "1-9vL1B5O2LoS1uyBzPK3Y6kIfOSKG-Fo", "B팀": "1BFqy-38ZOFEvxvqPBwRo5-SOaVSoK-oL"}

# ✅ 세션 상태 초기화
for key in ["authenticated", "team_name", "meeting_text", "result_text", "selected_file"]:
    if key not in st.session_state:
        st.session_state[key] = "" if key != "authenticated" else False

# ✅ 분석 결과 파싱 함수
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

# ✅ 팀 회의 기록 불러오기
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

# ✅ 과거 회의 맥락 요약 생성
def build_context_summary(team_df):
    if team_df.empty:
        return "※ 과거 회의 요약이 없습니다. 이번 회의를 잘 시작해보세요!"

    # 최근 회의 1건만 추출
    latest_row = team_df.iloc[-1]  # 가장 마지막 회의
    summary = f"[{latest_row['시간']}] {latest_row.get('회의록 제목', '제목 없음')}
"
    summary += f"- 잘한 점: {latest_row.get('잘한 점', '')}
"
    summary += f"- 개선점: {latest_row.get('개선점', '')}
"
    summary += f"- 다음 회의 추천: {latest_row.get('다음회의 추천', '')}
"
    return summary

# ✅ 분석 결과 PDF 저장
def export_pdf(result_text, file_name):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in result_text.split('\n'):
        pdf.multi_cell(0, 10, line)
    pdf.output(file_name)
    return file_name

# ✅ 분석 결과 구글시트 저장
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

# ✅ 인증 및 분석 로직 실행
code_input = st.text_input("✅ 팀 코드를 입력하세요", type="password")
if code_input:
    team_name = next((team for team, code in team_codes.items() if code_input == code), None)
    if team_name:
        st.session_state.authenticated = True
        st.session_state.team_name = team_name
        st.success(f"🎉 인증 완료: {team_name}")
    else:
        st.error("❌ 팀 코드가 올바르지 않습니다.")

if st.session_state.authenticated:
    team_name = st.session_state.team_name
    folder_id = folder_ids[team_name]
    creds_info = json.loads(st.secrets["google"]["GOOGLE_SERVICE_ACCOUNT"])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive.readonly',
        'https://www.googleapis.com/auth/documents.readonly'
    ]
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
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

            team_df = load_team_history(creds, team_name)
            context_summary = build_context_summary(team_df)

            with st.spinner("GPT가 회의록을 분석 중입니다..."):
                response = openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": f"""
당신은 교육공학 기반의 협력학습을 지원하는 지능형 피드백 챗봇입니다.
이 프로젝트는 교육공학 수업의 기말 프로젝트로, 중등 교사 대상 원격 직무연수 콘텐츠인 「에듀테크 활용 PBL 수업 실천법」을 설계하는 것입니다.
학생들은 실제 교육 현장에서 적용 가능한 수업 사례가 포함된 강의 콘텐츠를 개발해야 합니다.

아래는 이 팀의 누적 회의 내용 요약과 이번 회의 내용입니다.
이를 바탕으로 다음 5가지 영역에 따라 교육적 피드백을 생성하세요.

1. [참여 인식 유도]
2. [자기조절 촉진]
3. [메타인지 강화]
4. [정서적 지지]
5. [개선 중심 제안]

추가로 다음도 포함하세요:
6. [진행 상황 요약] 이전 회의 대비 이번 회의에서 진전된 점을 간결히 정리하세요.
7. [다음 회의 제안] 다음 회의에서 논의할 우선순위 항목을 제시하세요.

---
[과거 회의 요약]  
{context_summary}

[이번 회의 내용]  
{meeting_text}

[피드백 출력 형식 예시]  
- 역할 정리:  
- 자기조절 분석 및 제안:  
- 메타인지 피드백:  
- 정서적 피드백:  
- 개선 제안:  
- 진행 상황 요약:  
- 다음 회의 제안:
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

            if st.button("📄 분석 결과 PDF로 저장"):
                filename = f"{selected_file}_분석결과.pdf"
                export_pdf(st.session_state.result_text, filename)
                with open(filename, "rb") as f:
                    st.download_button("⬇️ PDF 다운로드", f, file_name=filename)
