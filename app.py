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
    df.columns = [str(col).strip() for col in df.columns]  # 컬럼명 공백 제거
    if '시간' not in df.columns:
        return pd.DataFrame()  # 경고 제거, 대신 빈 DF 반환
    df['시간'] = pd.to_datetime(df['시간'], errors='coerce')
    team_df = df[df['팀명'] == team_name].sort_values(by='시간')
    return team_df

# 회의 맥락 요약
def build_context_summary(team_df):
    if team_df.empty:
        return "※ 과거 회의 요약이 없습니다. 이번 회의 내용을 중심으로 분석을 잘 시작해보세요!\n"
    summary = ""
    for _, row in team_df.iterrows():
        summary += f"[{row['시간']}] {row.get('회의록 제목', '제목 없음')}\n"
        summary += f"- 잘한 점: {row.get('잘한 점', '')}\n"
        summary += f"- 개선점: {row.get('개선점', '')}\n"
        summary += f"- 다음 회의 추천: {row.get('다음회의 추천', '')}\n\n"
    return summary

# GPT 분석 수행
if st.session_state.authenticated:
    creds_info = json.loads(st.secrets["google"]["GOOGLE_SERVICE_ACCOUNT"])
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.readonly',
            'https://www.googleapis.com/auth/documents.readonly'
        ]
    )
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)
    openai_client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

    folder_id = folder_ids[st.session_state.team_name]
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

            history_df = load_team_history(gc, st.session_state.team_name)
            context_summary = build_context_summary(history_df)

            with st.spinner("GPT가 회의록을 분석 중입니다..."):
                response = openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": f"""
당신은 교육공학 수업의 기말 프로젝트를 수행 중인 예비 교사 팀의 회의 내용을 분석하는 챗봇입니다.  
이 팀은 중등 교사가 되어 교사 대상 원격 직무연수 콘텐츠인 「에듀테크 활용 PBL 수업 실천법」 과정을 설계하고 있습니다.  
학생들은 이 프로젝트를 통해 실제 교육 현장에서 적용 가능한 수업 사례가 포함된, 강의 콘텐츠를 설계해야 합니다.

회의 내용을 바탕으로 아래의 두 가지 관점에서 팀의 현재 상태를 분석해주세요.
---
[1️⃣ 팀워크 관점 분석]
아래 요소들을 고려해서 팀의 협업 상황을 분석해줘. 다만, 학생들이 부담 느끼지 않도록 가장 중요한 2~3가지 항목만 추려서 알려줘.
- 역할 분담이 명확하고 균형적이었는지
- 아이디어가 다양하고 창의적이었는지
- 의견 조율, 갈등 해결, 결론 도출 등 협업의 질이 어땠는지
- 회의 마무리에서 다음 회의 준비나 성찰이 있었는지

[2️⃣ 콘텐츠 방향성 분석]
회의 중 논의된 강의안/수업지도안/사례 제안 등이 다음 평가 기준에 얼마나 잘 맞는지 판단해줘:
- 중등교사 대상 ‘에듀테크 활용 PBL 수업 실천 연수’라는 과정에 적합한 흐름인지
- 제시된 수업 사례가 교과 맥락에 맞고 교육적으로 타당한지
- 교사가 실제 수업에 적용할 수 있을 만큼 구체적인지
- 콘텐츠 전체 구조와 흐름이 자연스러운지
- 교사가 듣고 쉽게 이해하고 따라할 수 있는 전달력이 있는지

[출력 형식 예시]
1. 👍 잘한 점: (간단한 칭찬 1~2개, 구체적으로)
2. ⚠️ 주요 개선점: (팀워크/콘텐츠 중 가장 시급하거나 중요한 2~3가지 개선 제안)
3. ✨ 다음 회의 추천 포인트: (다음 회의에서 다뤄야 할 핵심 목표 또는 조언)
※ 말투는 교수처럼 딱딱하지 않고, 팀 선배처럼 따뜻하고 실용적인 조언 스타일로 해주세요.

다음은 이 팀의 과거 회의 내용 요약입니다. 이 맥락을 바탕으로 최신 회의 내용을 분석하고 다음을 제시하세요.

[과거 회의 요약]
{context_summary}

[이번 회의 내용]"""},
                        {"role": "user", "content": meeting_text}
                    ]
                )
                st.session_state.result_text = response.choices[0].message.content
                st.success("✅ GPT 분석 완료!")

    else:
        st.warning("이 팀 폴더에 회의록이 없습니다. 먼저 회의록을 업로드해주세요.")

# GPT 분석 결과 저장 버튼
if st.session_state.result_text:
    st.subheader("📋 분석 결과")
    st.write(st.session_state.result_text)
    if st.button("💾 분석 결과 저장"):
        try:
            worksheet = gspread.authorize(service_account.Credentials.from_service_account_info(
                json.loads(st.secrets["google"]["GOOGLE_SERVICE_ACCOUNT"]),
                scopes=[
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive.readonly',
                    'https://www.googleapis.com/auth/documents.readonly'
                ]
            )).open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY").sheet1
            parsed = extract_structured_feedback(st.session_state.result_text)
            worksheet.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                st.session_state.team_name,
                st.session_state.selected_file,
                parsed.get("잘한 점", ""),
                parsed.get("개선점", ""),
                parsed.get("다음 회의 추천", "")
            ])
            st.success("✅ 분석 결과가 구글시트에 저장되었습니다.")
        except Exception as e:
            st.error(f"❌ 저장 실패: {e}")
