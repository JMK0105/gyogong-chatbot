from datetime import datetime
import json
import streamlit as st
import openai
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build


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


def load_team_history(creds, team_name):
    gc = gspread.authorize(creds)
    sh = gc.open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY")
    worksheet = sh.sheet1
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    df["시간"] = pd.to_datetime(df["시간"])
    team_df = df[df['팀명'] == team_name].sort_values(by='시간')
    return team_df


def build_context_summary(team_df):
    summary = ""
    for idx, row in team_df.iterrows():
        summary += f"[{row['시간']}] {row['회의록 제목'] if '회의록 제목' in row else row['회의록 회차 선택']}\n"
        summary += f"- 역할 정리: {row['역할 정리']}\n"
        summary += f"- 참여도: {row['참여도']}\n"
        summary += f"- 현재 단계: {row['현재 단계']}\n"
        summary += f"- 개선 제안: {row['개선 제안']}\n\n"
    return summary


def display_dashboard(creds, team_name):
    try:
        team_df = load_team_history(creds, team_name)

        st.subheader("📈 프로젝트 진행 단계 추이")
        plt.figure(figsize=(10, 4))
        sns.lineplot(data=team_df, x="시간", y="현재 단계", marker="o")
        plt.xticks(rotation=45)
        st.pyplot(plt)

        st.subheader("👥 참여도 분포")
        fig, ax = plt.subplots(figsize=(10, 4))
        team_df["참여도"].value_counts().plot(kind="bar", ax=ax)
        ax.set_ylabel("횟수")
        ax.set_xlabel("참여도 유형")
        st.pyplot(fig)

        st.subheader("🔧 개선 제안 요약")
        for i, row in team_df.iterrows():
            st.markdown(f"**{row['시간'].strftime('%Y-%m-%d %H:%M')}** - {row['회의록 회차 선택']}")
            st.write(f"💡 {row['개선 제안']}")
    except Exception as e:
        st.error(f"대시보드를 불러오는 데 실패했습니다: {e}")
