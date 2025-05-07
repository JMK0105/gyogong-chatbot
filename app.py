import gspread
from datetime import datetime
import json
import streamlit as st
import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ✅ 분석 결과 정리 함수 추가
def extract_structured_feedback(text):
    sections = {
        "역할 정리": "",
        "누락": "",
        "참여도": "",
        "현재 단계": "",
        "개선 제안": ""
    }
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

# ✅ 0. 환경 설정
openai_client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# ✅ 1. 팀 코드 설정
team_codes = {
    "A팀": "2025",
    "B팀": "2024"
}

folder_ids = {
    "A팀": "1-9vL1B5O2LoS1uyBzPK3Y6kIfOSKG-Fo",
    "B팀": "1BFqy-38ZOFEvxvqPBwRo5-SOaVSoK-oL"
}

# ✅ 2. 팀 코드 입력
st.set_page_config(page_title="교공이", layout="centered")
st.title("🤖 교공이 챗봇 - 팀 프로젝트 회의록 분석")

code_input = st.text_input("✅ 팀 코드를 입력하세요", type="password")

team_name = None
for team, code in team_codes.items():
    if code_input == code:
        team_name = team
        break

if team_name:
    st.success(f"🎉 인증 완료: {team_name}")
    folder_id = folder_ids[team_name]

    # ✅ 3. Drive API 연결
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly',
              'https://www.googleapis.com/auth/documents.readonly']
    
    google_service_account_info = st.secrets["google"]["GOOGLE_SERVICE_ACCOUNT"]
    credentials_info = json.loads(google_service_account_info)
    
    creds = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=SCOPES
    )

    drive_service = build('drive', 'v3', credentials=creds)
    docs_service = build('docs', 'v1', credentials=creds)

    # ✅ 4. 팀 폴더에서 회차별 문서 목록 불러오기
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
        selected_file = st.selectbox("📝 회의록 회차 선택", list(file_dict.keys()))

        if st.button("분석 시작"):
            # ✅ 5. 문서 내용 불러오기
            doc = docs_service.documents().get(documentId=file_dict[selected_file]).execute()
            doc_content = doc.get("body").get("content")

            def extract_text(elements):
                text = ''
                for v in elements:
                    if 'paragraph' in v:
                        for elem in v['paragraph']['elements']:
                            if 'textRun' in elem:
                                text += elem['textRun']['content']
                return text

            meeting_text = extract_text(doc_content)

            # ✅ 6. GPT 분석 요청
            with st.spinner("GPT가 회의록을 분석 중입니다..."):
                response = openai_client.chat.completions.create(
                    model="gpt-4",  
                    messages=[
                        {"role": "system", "content": """
당신은 팀 프로젝트 회의록을 분석하는 교육용 챗봇입니다. 아래 회의 내용을 보고 다음을 알려주세요:

1. 프로젝트 진행 사항 파악
2. 역할 정리
3. 누락된 역할이나 미정 항목
4. 참여도 분석 (소극적 참여자, 리더 역할 등)
5. 전체 프로젝트 흐름에서 현재 단계 진단 및 앞으로의 방향 피드백
6. 긍정적인 피드백과 개선 제안
""" },
                        {"role": "user", "content": meeting_text}
                    ] 
                ) 
                result_text = response.choices[0].message.content
                st.subheader("📋 분석 결과") 
                st.write(result_text) 

                # ✅ 분석 결과 정리
                parsed_result = extract_structured_feedback(result_text)

                # ✅ Google Sheets에 저장
                try:
                    gc = gspread.authorize(creds)
                    sh = gc.open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY")
                    worksheet = sh.sheet1  # 첫 시트 사용

                    worksheet.append_row([
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        team_name,
                        selected_file,
                        parsed_result["역할 정리"],
                        parsed_result["누락"],
                        parsed_result["참여도"],
                        parsed_result["현재 단계"],
                        parsed_result["개선 제안"]
                    ])
                    st.success("✅ 분석 결과가 스프레드시트에 저장되었습니다.")
                except Exception as e:
                    st.error(f"❌ Sheets 저장 실패: {e}")

else:
    if code_input != "":
        st.error("❌ 팀 코드가 올바르지 않습니다.")
