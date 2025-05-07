import gspread
from datetime import datetime
import json
import streamlit as st
import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
import altair as alt

# 초기 세션 상태 설정
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
    sections = {"역할 정리": "", "누락": "", "참여도": "", "현재 단계": "", "개선 제안": ""}
    for key in sections.keys():
        if key in text:
            try:
                after = text.split(key)[1]
                for next_key in sections.keys():
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
    summary = ""
    for _, row in team_df.iterrows():
        summary += f"[{row['시간']}] {row.get('회의록 제목', row.get('회의록 회차 선택', '제목 없음'))}\n"
        summary += f"- 역할 정리: {row['역할 정리']}\n"
        summary += f"- 참여도: {row['참여도']}\n"
        summary += f"- 현재 단계: {row['현재 단계']}\n"
        summary += f"- 개선 제안: {row['개선 제안']}\n\n"
    return summary

# 대시보드 함수
def display_dashboard(gc, team_name):
    df = load_team_history(gc, team_name)
    st.header(f"\U0001F4CA {team_name} 대시보드")

    if '현재 단계' in df.columns:
        st.subheader("1️⃣ 프로젝트 단계 추이")
        chart = alt.Chart(df).mark_line(point=True).encode(
            x='시간:T', y='현재 단계:N'
        )
        st.altair_chart(chart, use_container_width=True)

    if '참여도' in df.columns:
        st.subheader("2️⃣ 참여도 분포")
        st.bar_chart(df['참여도'].value_counts())

    if '역할 정리' in df.columns:
        st.subheader("3️⃣ 역할별 기여도")
        roles = df['역할 정리'].dropna().str.extractall(r'([\w가-힣]+)\s*[:：]\s*[^,\n]+')
        counts = roles[0].value_counts().reset_index()
        counts.columns = ['역할자', '기여도']
        pie = alt.Chart(counts).mark_arc().encode(
            theta='기여도:Q', color='역할자:N', tooltip=['역할자', '기여도']
        )
        st.altair_chart(pie, use_container_width=True)

        st.subheader("4️⃣ 리더 역할 빈도 분석")
        leaders = df['역할 정리'].dropna().str.extractall(r'([\w가-힣]+)\s*[:：]\s*.*리더')
        freq = leaders[0].value_counts().reset_index()
        freq.columns = ['이름', '리더 언급 횟수']
        if not freq.empty:
            bar = alt.Chart(freq).mark_bar().encode(
                x='이름:N', y='리더 언급 횟수:Q', tooltip=['이름', '리더 언급 횟수']
            )
            st.altair_chart(bar, use_container_width=True)
        else:
            st.info("\U0001F50D 아직 리더로 언급된 인원이 없습니다.")

    if '개선 제안' in df.columns:
        st.subheader("5️⃣ 회의별 개선 제안 요약")
        for _, row in df.iterrows():
            st.markdown(f"**\U0001F4C5 {row['시간'].strftime('%Y-%m-%d %H:%M')} - {row.get('회의록 제목', row.get('회의록 회차 선택', ''))}**")
            st.markdown(f"> {row['개선 제안']}")

# 메인 앱 실행
st.set_page_config(page_title="교공이", layout="centered")
st.title("\U0001F916 교공이 챗봇 - 팀 프로젝트 회의록 분석")

team_codes = {"A팀": "2025", "B팀": "2024"}
folder_ids = {"A팀": "1-9vL1B5O2LoS1uyBzPK3Y6kIfOSKG-Fo", "B팀": "1BFqy-38ZOFEvxvqPBwRo5-SOaVSoK-oL"}

# 인증 처리
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

# 인증 이후 실행
if st.session_state.authenticated:
    team_name = st.session_state.team_name
    folder_id = folder_ids[team_name]
    openai_client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive.readonly',
        'https://www.googleapis.com/auth/documents.readonly'
    ]
    creds_info = json.loads(st.secrets["google"]["GOOGLE_SERVICE_ACCOUNT"])
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)

    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document'",
        pageSize=10,
        fields="files(id, name, createdTime)"
    ).execute()
    files = results.get('files', [])

    if not files:
        st.warning("이 팀 폴더에 회의록이 없습니다.")
    else:
        file_dict = {f["name"]: f["id"] for f in sorted(files, key=lambda x: x['createdTime'])}
        selected_file = st.selectbox("📝 회의록 회차 선택", list(file_dict.keys()), key="file_select")
        st.session_state.selected_file = selected_file

        if st.button("🔍 회의록 분석 시작", key="analyze"):
            doc = docs_service.documents().get(documentId=file_dict[selected_file]).execute()
            elements = doc.get("body", {}).get("content", [])
            meeting_text = ''.join(
                elem['textRun']['content']
                for v in elements if 'paragraph' in v
                for elem in v['paragraph'].get('elements', []) if 'textRun' in elem
            )
            st.session_state.meeting_text = meeting_text

            history_df = load_team_history(gc, team_name)
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

        if st.session_state.result_text:
            st.subheader("📋 분석 결과")
            st.write(st.session_state.result_text)

            parsed = extract_structured_feedback(st.session_state.result_text)
            if parsed:
                if st.button("💾 분석 결과 저장", key="save"):
                    try:
                        worksheet = gc.open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY").sheet1
                        worksheet.append_row([
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            team_name,
                            st.session_state.selected_file,
                            parsed.get("역할 정리", ""),
                            parsed.get("누락", ""),
                            parsed.get("참여도", ""),
                            parsed.get("현재 단계", ""),
                            parsed.get("개선 제안", "")
                        ])
                        st.success("📌 스프레드시트에 저장되었습니다.")
                    except Exception as e:
                        st.error(f"❌ 저장 실패: {e}")

        if st.button("📊 대시보드 보기", key="dashboard"):
            display_dashboard(gc, team_name)
