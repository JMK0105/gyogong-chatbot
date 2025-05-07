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

        # ✅ 역할별 기여도 분석 (파이차트)
        st.subheader("📌 역할별 기여도 분석")
        roles = team_df["역할 정리"].dropna().str.extractall(r"([가-힣]+)\s*[:：]")
        role_counts = roles[0].value_counts()
        fig, ax = plt.subplots()
        role_counts.plot(kind='pie', autopct='%1.1f%%', startangle=90, ax=ax)
        ax.set_ylabel("")
        ax.set_title("역할별 기여 비율")
        st.pyplot(fig)

        # ✅ 리더 역할 빈도 분석 (막대 차트)
        st.subheader("👑 리더 언급 빈도")
        leaders = team_df["역할 정리"].dropna().str.extractall(r"([가-힣]+)\s*[:：].*리더")
        leader_counts = leaders[0].value_counts()
        if not leader_counts.empty:
            fig, ax = plt.subplots()
            leader_counts.plot(kind='bar', ax=ax)
            ax.set_xlabel("이름")
            ax.set_ylabel("리더 언급 횟수")
            ax.set_title("리더 역할 언급된 횟수")
            st.pyplot(fig)
        else:
            st.info("❗️아직 리더 역할로 명시된 인원이 없습니다.")
    except Exception as e:
        st.error(f"대시보드를 불러오는 데 실패했습니다: {e}")
