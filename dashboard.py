import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import gspread

def display_dashboard(creds, team_name):
    try:
        # ✅ 구글시트 데이터 로드
        gc = gspread.authorize(creds)
        worksheet = gc.open_by_key("1LNKXL83dNvsHDOHEkw7avxKRsYWCiIIIYKUPiF1PZGY").sheet1
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        df.columns = [col.strip() for col in df.columns]

        # ✅ 필터링 및 전처리
        if '시간' not in df.columns:
            st.warning("시트에 '시간' 컬럼이 없습니다.")
            return
        df['시간'] = pd.to_datetime(df['시간'], errors='coerce')
        df = df[df['팀명'] == team_name].sort_values(by='시간')

        if df.empty:
            st.info("해당 팀의 회의 기록이 아직 없습니다.")
            return

        # ✅ 1. 프로젝트 진행 단계 추이
        if '현재 단계' in df.columns:
            st.subheader("📈 프로젝트 진행 단계 추이")
            df_line = df.dropna(subset=["현재 단계", "시간"]).copy()
            단계순 = sorted(df_line["현재 단계"].dropna().unique())
            df_line["현재 단계"] = pd.Categorical(df_line["현재 단계"], categories=단계순, ordered=True)
            plt.figure(figsize=(10, 4))
            sns.lineplot(data=df_line, x="시간", y="현재 단계", marker="o")
            plt.xticks(rotation=45)
            plt.tight_layout()
            st.pyplot(plt)

        # ✅ 2. 완료/미완료 상태 체크표
        if '현재 단계' in df.columns:
            st.subheader("📋 완료/미완료 체크표")
            status_counts = df['현재 단계'].value_counts()
            st.write(status_counts.to_frame(name="횟수"))

        # ✅ 3. 역할 분담 기여도 분석 (Pie Chart)
        if '역할 정리' in df.columns:
            st.subheader("📌 역할별 기여도 분석")
            roles = df['역할 정리'].dropna().str.extractall(r'([가-힣]+)\s*[:：]')
            role_counts = roles[0].value_counts()
            if not role_counts.empty:
                fig, ax = plt.subplots()
                role_counts.plot(kind='pie', autopct='%1.1f%%', startangle=90, ax=ax)
                ax.set_ylabel("")
                ax.set_title("역할별 기여 비율")
                st.pyplot(fig)
            else:
                st.info("역할 분담 데이터가 충분하지 않습니다.")

        # ✅ 4. 회의별 개선 제안 요약
        if '개선점' in df.columns:
            st.subheader("💡 회의별 개선 제안 요약")
            for _, row in df.iterrows():
                st.markdown(f"**📅 {row['시간'].strftime('%Y-%m-%d %H:%M')} - {row.get('회의록 제목', '')}**")
                st.markdown(f"> {row.get('개선점', '')}")

    except Exception as e:
        st.error(f"❌ 대시보드를 불러오는 중 오류 발생: {e}")
