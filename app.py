import streamlit as st
import pandas as pd
import gspread
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
import openai
import difflib
from fpdf import FPDF
import time
from collections import Counter
from wordcloud import WordCloud
import matplotlib.pyplot as plt


# ✅ 시스템 프롬프트
SYSTEM_PROMPT = """
당신은 교육공학 기반의 협력학습을 지원하는 지능형 피드백 챗봇입니다.
이 팀은 중등 교사 대상 원격 직무연수 콘텐츠인 「에듀테크 활용 PBL 수업 실천법」을 설계하고 있으며,
학생들은 실제 교육 현장에서 적용 가능한 수업 사례가 포함된 강의 콘텐츠를 개발해야 합니다.

본 프로젝트는 다음 평가 기준에 기반하여 수행됩니다. 회의 내용을 분석할 때 이 기준과 부합하는지 판단하고, 그에 따른 분석과 피드백을 제공하세요:

[과제 평가 기준]
1. 과정 적합성: 콘텐츠 흐름과 컨셉이 ‘중등교사 대상 PBL 수업 실천 연수’에 적절한가?
2. 사례의 구체성과 정확성: 제시된 수업 사례가 교과 및 학습자 맥락에 맞고, 교육적 타당성을 갖추었는가?
3. 적용 가능성: 교사가 실제 적용 가능한 구체성과 현실성을 갖추었는가?
4. 콘텐츠 구조 및 흐름: 강의의 전체 구성과 흐름이 논리적이고 자연스러운가?
5. 내용 전달력: 교사가 듣고 쉽게 이해하고 따라할 수 있도록 구성되었는가?

아래는 이 팀의 누적 회의 내용 요약과 이번 회의 내용입니다.
이를 바탕으로 다음 7가지 영역에 따라 회의 내용을 분석하세요. 각 항목 이름을 그대로 소제목으로 사용하여 구분하세요.
마지막에 '잘한 점', '개선할 점', '다음 회의 제안'을 요약 포인트로 제공하세요.

7가지 분석 영역:
1. 역할 정리: 누가 어떤 역할을 맡았는지, 참여 균형 여부
2. 자기조절: 목표·계획·전략 사용 여부, 부족한 부분
3. 메타인지: 현재 단계 판단과 필요한 사고 제안
4. 정서적 피드백: 발언 속 분위기 분석과 응원 메시지
5. 개선 제안: 발전된 점과 구체적 개선 방향 2~3가지
6. 진행 요약: 이전 회의와 비교해 달라진 점 정리
7. 다음 회의 제안: 다음 회의에서 다루면 좋을 핵심 목표 제시

[응답 형식 예시]
역할 정리:
...
자기조절:
...
메타인지:
...
정서적 피드백:
...
개선 제안:
...
진행 요약:
...
다음 회의 제안:
...

--- 요약 ---

👍 잘한 점
...

⚠️ 개선할 점
...

✨ 다음 회의 제안
...
"""


st.set_page_config(page_title="교공이", layout="centered")
st.title("🤖 교공이 챗봇")

team_codes = {
    "A팀": "2025", "B팀": "2024", "C팀": "2023", "D팀": "2022",
    "E팀": "2021", "F팀": "2020"
}

folder_ids = {
    "A팀": "1-9vL1B5O2LoS1uyBzPK3Y6kIfOSKG-Fo",
    "B팀": "1BFqy-38ZOFEvxvqPBwRo5-SOaVSoK-oL",
    "C팀": "1Ey9nh0vICcDOtQrIQg0XbLEehqNIShYb",
    "D팀": "1kAb13Qipe-0xw2o6WbLXLi2xrcqjuxoc",
    "E팀": "1dkSXOSTMDewbt0oGj-FZvWHPCFpTe8vK",
    "F팀": "17C8Yfjvr8d3kR1XLJtjfcx80xBjaON1p"
}

for key in ["authenticated", "team_name", "meeting_text", "result_text", "selected_file"]:
    if key not in st.session_state:
        st.session_state[key] = "" if key != "authenticated" else False

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

# ✅ 분석 결과 파싱 함수
def extract_structured_feedback(text):
    keys = ["역할 정리", "자기조절", "메타인지", "정서적 피드백", "개선 제안", "진행 요약", "다음 회의 제안"]
    result = {k: "" for k in keys}
    for k in keys:
        if k in text:
            try:
                after = text.split(k)[1]
                for other in keys:
                    if other != k and other in after:
                        after = after.split(other)[0]
                result[k] = after.strip()
            except:
                result[k] = ""
    return result

# ✅ 시트 저장
def save_to_sheet(gc, team_name, title, parsed, full_text=""):
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
            parsed.get("다음 회의 제안", ""),
            full_text  # ✅ 전체 회의록 추가
            ])
        return True
    except Exception as e:
        st.error(f"❌ 저장 실패: {e}")
        return False

# ✅ 회의 요약 요점 출력
def display_summary_feedback(parsed):
    st.subheader("📋 회의 요약 피드백")
    st.markdown(f"**👍 잘한 점**\n\n{parsed.get('역할 정리', '')}\n{parsed.get('자기조절', '')}")
    st.markdown(f"**⚠️ 개선할 점**\n\n{parsed.get('개선 제안', '')}\n{parsed.get('진행 요약', '')}")
    st.markdown(f"**✨ 다음 회의 제안**\n\n{parsed.get('다음 회의 제안', '')}")

def add_dashboard(df):
    import altair as alt
    from gensim import corpora
    from gensim.models.ldamodel import LdaModel

    st.header("📊 팀 회의 대시보드")

    def clean_korean_text(text):
        import re
        text = re.sub(r"[^가-힣\s]", "", text)
        words = text.split()
        stopwords = set([
            "그리고", "그러나", "때문에", "등",
            "위한", "하는", "있다", "있습니다", "이다", "된다", "같다",
            "경우", "정도", "부분", "내용", "방법", "활동", "결과", "제시",
            "대한", "대해", "이에", "로서",
            "으로", "것이", "로부터", "에게", "된다면", "합니다", "있어요"
        ])
        return [w for w in words if len(w) > 1 and w not in stopwords and len(w) <= 6]

    df["분석텍스트"] = df["전체 회의록"].fillna("")

    # 1️⃣ 워드클라우드 & 키워드 변화 추이
    with st.expander("🔍 회차별 핵심 키워드 & 키워드 변화 추이", expanded=False):
        col1, col2 = st.columns([1, 1.5])

        with col1:
                if len(df) == 1:
                    selected_idx = 1
                else:
                    selected_idx = st.slider("WordCloud 회차 선택", 1, len(df) - 1, 1, key="wordcloud_slider")
                text = " ".join(clean_korean_text(df.iloc[selected_idx - 1]["분석텍스트"]))
                if not text.strip():
                    st.info("⚠️ 해당 회차에는 표시할 키워드가 충분하지 않습니다.")
                else:
                    wordcloud = WordCloud(
                        font_path="fonts/malgun.ttf",
                        background_color='white',
                        width=600,
                        height=400,
                        max_words=50,
                        max_font_size=90,
                        prefer_horizontal=0.9,
                        colormap='Dark2'
                    ).generate(text)
                    fig1, ax1 = plt.subplots(figsize=(6, 4))
                    ax1.imshow(wordcloud, interpolation='bilinear')
                    ax1.axis("off")
                    st.pyplot(fig1)


        

        
        with col2:
            tokenized = df["분석텍스트"].apply(clean_korean_text)
            all_words = [word for row in tokenized for word in row if len(word) <= 6]
            top_keywords = [kw for kw, _ in Counter(all_words).most_common(4)]
            trend_data = [[row.count(kw) for kw in top_keywords] for row in tokenized]
            trend_df = pd.DataFrame(trend_data, columns=top_keywords)
            trend_df["회차"] = [f"{i+1}회차" for i in range(len(df))]
            trend_df_melted = trend_df.melt(id_vars="회차", var_name="키워드", value_name="빈도")

            chart = alt.Chart(trend_df_melted).mark_line(point=True).encode(
                x=alt.X("회차:N", title="회의 회차", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("빈도:Q", title="등장 빈도수", scale=alt.Scale(domain=[0, trend_df_melted["빈도"].max() + 1])),
                color=alt.Color("키워드:N", title="주요 키워드"),
                tooltip=["회차", "키워드", "빈도"]
            ).properties(
                title="회차별 주요 키워드 등장 빈도 변화",
                width=500, height=300
            )
            st.altair_chart(chart, use_container_width=True)

    # 2️⃣ LDA 분석 & 요약
    with st.expander("🧠 전체 회차 누적 데이터 LDA 분석", expanded=False):
        selected_indexes = st.multiselect("분석할 회차 선택", df.index, format_func=lambda i: df.loc[i, "회의록 제목"] or f"{i+1}회차")

        if selected_indexes:
            selected_texts = df.loc[selected_indexes, "분석텍스트"].apply(clean_korean_text).tolist()
            dictionary = corpora.Dictionary(selected_texts)
            corpus = [dictionary.doc2bow(text) for text in selected_texts]

            if len(dictionary) > 0 and len(corpus) > 0:
                lda_model = LdaModel(corpus=corpus, id2word=dictionary, num_topics=3, random_state=42)

                topic_keywords = []
                for i in range(3):
                    for word, prob in lda_model.show_topic(i, topn=5):
                        topic_keywords.append({"토픽": f"토픽 {i+1}", "키워드": word, "확률": prob})

                topic_df = pd.DataFrame(topic_keywords)
                chart = alt.Chart(topic_df).mark_bar().encode(
                    x=alt.X("토픽:N", title="토픽"),
                    y=alt.Y("확률:Q", title="비중"),
                    color=alt.Color("키워드:N"),
                    tooltip=["토픽", "키워드", "확률"]
                ).properties(width=700, height=400)
                st.altair_chart(chart, use_container_width=True)

                # 3️⃣ GPT 요약
                try:
                    topic_summaries = []
                    for i in range(3):
                        keywords = ", ".join([word for word, _ in lda_model.show_topic(i, topn=5)])
                        topic_summaries.append(f"토픽 {i+1}: {keywords}")

                    summary_prompt = f"""
다음은 회의 내용에서 LDA분석을 통해 추출된 주요 토픽입니다.
각 토픽은 자주 등장한 핵심 키워드들로 구성되어 있습니다:

{chr(10).join(topic_summaries)}

이 키워드를 바탕으로 이 회의에서 어떤 주제가 논의되었는지 3줄로 간결하게 요약해주세요.
항목마다 이모지를 붙여주세요.
"""

                    openai_client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

                    topic_response = openai_client.chat.completions.create(
                        model="gpt-4-turbo",
                        messages=[
                            {"role": "system", "content": "당신은 교육 회의 내용을 요약하는 조력자입니다."},
                            {"role": "user", "content": summary_prompt}
                        ]
                    )
                    summary_text = topic_response.choices[0].message.content
                    st.markdown("### 🧠 이번 회의에서 논의된 주제 요약")
                    st.info(summary_text)

                except Exception as e:
                    st.warning(f"토픽 요약 생성 실패: {e}")

        else:
            st.info("⚠️ 선택된 회차에 대한 LDA 모델링을 위한 충분한 데이터가 없습니다.")


            
# ✅ 인증 및 회의록 선택
code_input = st.text_input("✅ 팀 코드를 입력하세요", type="password")
if code_input:
    team_name = next((team for team, code in team_codes.items() if code_input == code), None)
    if team_name:
        st.session_state.authenticated = True
        st.session_state.team_name = team_name
        st.success(f"🎉 인증 완료: {team_name}")

# ✅ 본문 실행 로직
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

    team_df = load_team_history(creds, team_name)
    if not team_df.empty:
        add_dashboard(team_df)

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

        if st.button("🔍 회의록 분석 시작", disabled=st.session_state.get("button_disabled", False)):
            st.session_state["show_dashboard"] = False  # ✅ 대시보드 상태 초기화
            st.session_state.button_disabled = True
            time.sleep(2)

            try:
                doc = docs_service.documents().get(documentId=file_dict[selected_file]).execute()
                elements = doc.get("body", {}).get("content", [])
                meeting_text = ''.join(
                    elem['textRun']['content']
                    for v in elements if 'paragraph' in v
                    for elem in v['paragraph'].get('elements', []) if 'textRun' in elem
                )
                st.session_state.meeting_text = meeting_text

                context_summary = "\n".join([
                    f"[{row['시간']}] {row.get('회의록 제목', '')}" for _, row in team_df.iterrows()
                ])

                if team_df.shape[0] > 0:
                    last_text = str(team_df.iloc[-1].get("개선 제안", "")) + str(team_df.iloc[-1].get("진행 요약", ""))
                    similarity = difflib.SequenceMatcher(None, meeting_text.strip(), last_text.strip()).ratio()
                    if similarity >= 0.9:
                        st.info("⚠️ 이전 회의와 매우 유사합니다. 동일 회의일 수 있습니다.")

                with st.spinner("GPT가 회의록을 분석 중입니다..."):
                    response = openai_client.chat.completions.create(
                        model="gpt-4-turbo",
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
                        if save_to_sheet(gc, team_name, selected_file, parsed, meeting_text):
                            st.success("📌 구글시트에 저장되었습니다.")
                        display_summary_feedback(parsed)

            except openai.RateLimitError:
                st.warning("⏱️ 요청이 너무 빠릅니다. 5초 후 다시 시도해주세요.")
            except Exception as e:
                st.error(f"❌ 오류 발생: {str(e)}")
            finally:
                st.session_state.button_disabled = False

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
