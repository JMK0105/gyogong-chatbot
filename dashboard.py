from datetime import datetime
import json
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import gspread
from google.oauth2 import service_account

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

# ✅ 대시보드 함수

def display_dashboard(creds, team_name):
    team_df = load_team_history(creds, team_name)
    if team_df.empty:
        st.info("❗ 아직 회의 기록이 없습니다. 첫 회의를 진행해보세요!")
        return

    st.subheader("📈 프로젝트 진행 단계 추이")
    plt.figure(figsize=(10, 4))
    sns.lineplot(data=team_df, x="시간", y="현재 단계", marker="o")
    plt.xticks(rotation=45)
    st.pyplot(plt)

    st.subheader("📋 완료/미완료 체크표")
    if "현재 단계" in team_df.columns:
        status_counts = team_df["현재 단계"].value_counts()
        st.write(status_counts.to_frame(name="횟수"))

    if "역할 정리" in team_df.columns:
        st.subheader("📌 역할별 기여도 분석")
        roles = team_df["역할 정리"].dropna().str.extractall(r"([가-힣]+)\s*[:：]")
        role_counts = roles[0].value_counts()
        if not role_counts.empty:
            fig, ax = plt.subplots()
            role_counts.plot(kind='pie', autopct='%1.1f%%', startangle=90, ax=ax)
            ax.set_ylabel("")
            ax.set_title("역할별 기여 비율")
            st.pyplot(fig)
        else:
            st.info("🔍 역할 분담 정보가 충분하지 않습니다.")

    st.subheader("💡 회의별 개선 제안 요약")
    for _, row in team_df.iterrows():
        st.markdown(f"**📅 {row['시간'].strftime('%Y-%m-%d %H:%M')} - {row.get('회의록 제목', '')}**")
        st.markdown(f"> {row.get('개선점', '')}")
