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

team_codes = {"A팀": "2025", "B팀": "2024", "C팀": "2023", "D팀": "2022", "E팀": "2021", "F팀": "2020"}
folder_ids = {"A팀": "1-9vL1B5O2LoS1uyBzPK3Y6kIfOSKG-Fo", "B팀": "1BFqy-38ZOFEvxvqPBwRo5-SOaVSoK-oL", 
              "C팀": "1Ey9nh0vICcDOtQrIQg0XbLEehqNIShYb", "D팀": "1kAb13Qipe-0xw2o6WbLXLi2xrcqjuxoc",
              "E팀": "1dkSXOSTMDewbt0oGj-FZvWHPCFpTe8vK", "F팀": "17C8Yfjvr8d3kR1XLJtjfcx80xBjaON1p"}

for key in ["authenticated", "team_name", "meeting_text", "result_text", "selected_file"]:
    if key not in st.session_state:
        st.session_state[key] = "" if key != "authenticated" else False

# ✅ 팀 코드 인증 및 회의록 선택
# ✅ 인증 및 회의록 선택
code_input = st.text_input("✅ 팀 코드를 입력하세요", type="password")
if code_input:
    team_name = next((team for team, code in team_codes.items() if code_input == code), None)
    if team_name:
        st.session_state.authenticated = True
        st.session_state.team_name = team_name
        st.success(f"🎉 인증 완료: {team_name}")

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
            context_summary = "\n".join([
                f"[{row['시간']}] {row.get('회의록 제목', '')}" for _, row in team_df.iterrows()
            ])

            with st.spinner("GPT가 회의록을 분석 중입니다..."):
                response = openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"[과거 회의 요약]\n{context_summary}\n\n[이번 회의 내용]\n{meeting_text}"}
                    ]
                )
                result_text = response.choices[0].message.content
                st.session_state.result_text = result_text
                st.success("✅ 분석 완료!")

            parsed = extract_structured_feedback(result_text)
            if parsed:
                if save_to_sheet(gc, team_name, selected_file, parsed):
                    st.success("📌 구글시트에 저장되었습니다.")
                display_summary_feedback(parsed)

        if st.session_state.result_text:
            if st.button("📄 분석 결과 PDF로 저장"):
                filename = f"{selected_file}_분석결과.pdf"
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                for line in st.session_state.result_text.split('\n'):
                    pdf.multi_cell(0, 10, line)
                pdf.output(filename)
                with open(filename, "rb") as f:
                    st.download_button("⬇️ PDF 다운로드", f, file_name=filename)

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

# ✅ 시스템 프롬프트
SYSTEM_PROMPT = """
당신은 교육공학 기반의 협력학습을 지원하는 지능형 피드백 챗봇입니다.
이 팀은 중등 교사 대상 원격 직무연수 콘텐츠인 「에듀테크 활용 PBL 수업 실천법」을 설계하고 있으며,
학생들은 실제 교육 현장에서 적용 가능한 수업 사례가 포함된 강의 콘텐츠를 개발해야 합니다.

아래는 이 팀의 누적 회의 내용 요약과 이번 회의 내용입니다.
이를 바탕으로 다음 7가지 영역에 따라 회의 내용을 분석하고, **'잘한 점, 개선점, 다음 회의 추천 포인트'의 3개 항목 중심으로 요약하여 응답을 생성하세요.**

7가지 분석 영역:
1. 역할 정리: 누가 어떤 역할을 맡았는지, 참여 균형 여부
2. 자기조절: 목표·계획·전략 사용 여부, 부족한 부분
3. 메타인지: 현재 단계 판단과 필요한 사고 제안
4. 정서적 피드백: 발언 속 분위기 분석과 응원 메시지
5. 개선 제안: 발전된 점과 구체적 개선 방향 2~3가지
6. 진행 요약: 이전 회의와 비교해 달라진 점 정리
7. 다음 회의 제안: 다음 회의에서 다루면 좋을 핵심 목표 제시

[응답 형식 예시]
**👍 잘한 점**
- (1~2개 문장으로 요약)

**⚠️ 개선할 점**
- (구체적 개선 제안 위주)

**✨ 다음 회의 제안**
- (다음 회의의 목표나 과제 제안)

"""

# ✅ 사용자에게 보여줄 3개 요약 출력
def display_summary_feedback(parsed):
    st.subheader("📋 회의 요약 피드백")
    st.markdown(f"**👍 잘한 점**\n\n{parsed.get('역할 정리', '')}\n{parsed.get('자기조절', '')}")
    st.markdown(f"**⚠️ 개선할 점**\n\n{parsed.get('개선 제안', '')}\n{parsed.get('진행 요약', '')}")
    st.markdown(f"**✨ 다음 회의 제안**\n\n{parsed.get('다음 회의 제안', '')}")
