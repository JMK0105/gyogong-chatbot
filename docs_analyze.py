from google.oauth2 import service_account
from googleapiclient.discovery import build
import openai
from dotenv import load_dotenv
import os

# 환경 변수 불러오기
load_dotenv()
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 문서 ID
DOCUMENT_ID = "19PY1QoY8OP9gfJLTmwFywakoJEPEhxzXpsX75ernoyI"

# Google Docs API 연결
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']
creds = service_account.Credentials.from_service_account_file(
    'gyogong-sheets-key.json', scopes=SCOPES)
service = build('docs', 'v1', credentials=creds)

# 문서 불러오기
doc = service.documents().get(documentId=DOCUMENT_ID).execute()
doc_content = doc.get("body").get("content")

# 본문 텍스트 추출
def extract_text(elements):
    text = ''
    for v in elements:
        if 'paragraph' in v:
            for elem in v['paragraph']['elements']:
                if 'textRun' in elem:
                    text += elem['textRun']['content']
    return text

meeting_text = extract_text(doc_content)

# GPT에 분석 요청
response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": """
당신은 팀 프로젝트 회의록을 분석하는 교육용 챗봇입니다. 아래 회의 내용을 보고 다음을 알려주세요:

1. 발언자별 역할 정리
2. 누락된 역할이나 미정 항목
3. 참여도 분석 (소극적 참여자, 리더 역할 등)
4. 전체 프로젝트 흐름에서 현재 단계 진단
5. 긍정적인 피드백과 개선 제안
"""},
        {"role": "user", "content": meeting_text}
    ]
)

print("📋 회의록 분석 결과:\n")
print(response.choices[0].message.content)