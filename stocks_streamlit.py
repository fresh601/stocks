import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import platform
import requests
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
import FinanceDataReader as fdr

# ✅ 폰트 설정
st.set_page_config(page_title="주식 분석 앱", layout="wide")
st.title("📊 주식 데이터 분석 플랫폼")

if platform.system() == 'Windows':
    plt.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    plt.rc('font', family='AppleGothic')
plt.rcParams['axes.unicode_minus'] = False

# ✅ API Key 로딩 (Streamlit Cloud의 secrets.toml에서 가져옴)
DART_API_KEY = st.secrets.get("DART_API_KEY")
KRX_API_KEY = st.secrets.get("KRX_API_KEY")

# ✅ 기업 고유번호 다운로드 함수
@st.cache_data
def load_corp_codes(api_key):
    url = f'https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}'
    response = requests.get(url)
    with zipfile.ZipFile(BytesIO(response.content)) as zip_ref:
        xml_data = zip_ref.read('CORPCODE.xml')
    root = ET.fromstring(xml_data)
    data = []
    for corp in root.findall('list'):
        data.append({
            'corp_code': corp.find('corp_code').text,
            'corp_name': corp.find('corp_name').text,
            'stock_code': corp.find('stock_code').text
        })
    return pd.DataFrame(data)

# ✅ 탭 구성
tab1, tab2, tab3 = st.tabs(["📈 주가 데이터", "📑 DART 재무제표", "📡 KRX API"])

# 📈 주가 데이터 탭
with tab1:
    st.subheader("📈 주가 데이터")
    stock_code = st.text_input("종목 코드 (예: 005930)", '005930')
    start_date = st.date_input("시작일", pd.to_datetime('2024-01-01'))
    end_date = st.date_input("종료일", pd.to_datetime('2024-12-31'))

    if st.button("데이터 불러오기"):
        try:
            st.markdown("#### ✅ FDR 주가 데이터")
            df_fdr = fdr.DataReader(stock_code, start_date, end_date)
            st.dataframe(df_fdr)

            fig, ax = plt.subplots(figsize=(10, 4))
            df_fdr['Close'].plot(ax=ax)
            ax.set_title(f"{stock_code} 종가")
            st.pyplot(fig)

        except Exception as e:
            st.error(f"에러 발생: {e}")

# 📑 DART 재무 데이터
with tab2:
    st.subheader("📑 DART 재무제표 조회")
    if not DART_API_KEY:
        st.error("DART API KEY가 설정되지 않았습니다.")
    else:
        corp_df = load_corp_codes(DART_API_KEY)
        selected_corp = st.selectbox("기업명 선택", corp_df['corp_name'].unique())
        selected_year = st.selectbox("사업연도", list(range(2024, 2014, -1)), index=0)
        report_type = st.selectbox("보고서 종류", {
            '사업보고서': '11011',
            '반기보고서': '11012',
            '1분기보고서': '11013',
            '3분기보고서': '11014'
        }.keys())

        if st.button("재무제표 가져오기"):
            corp_code = corp_df[corp_df['corp_name'] == selected_corp]['corp_code'].values[0]
            report_code = {
                '사업보고서': '11011',
                '반기보고서': '11012',
                '1분기보고서': '11013',
                '3분기보고서': '11014'
            }[report_type]

            url = f'https://opendart.fss.or.kr/api/fnlttMultiAcnt.json?crtfc_key={DART_API_KEY}&corp_code={corp_code}&bsns_year={selected_year}&reprt_code={report_code}'
            res = requests.get(url)
            data = res.json()

            if data.get('status') == '000':
                df = pd.json_normalize(data['list'])
                st.dataframe(df)
            else:
                st.warning(f"DART API 오류: {data.get('message')}")

# 📡 KRX OPEN API
with tab3:
    st.subheader("📡 KRX Open API")
    if not KRX_API_KEY:
        st.error("KRX API KEY가 설정되지 않았습니다.")
    else:
        krx_date = st.date_input("조회 날짜", pd.to_datetime('2024-05-21'))

        if st.button("기본정보 조회"):
            url = 'http://data-dbg.krx.co.kr/svc/apis/sto/stk_isu_base_info'
            headers = {'AUTH_KEY': KRX_API_KEY}
            params = {'basDd': krx_date.strftime('%Y%m%d')}
            try:
                response = requests.get(url, headers=headers, params=params)
                df = pd.json_normalize(response.json()['OutBlock_1'])
                st.dataframe(df)
            except Exception as e:
                st.error(f"오류: {e}")

        if st.button("일별 매매정보 조회"):
            url = 'http://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd'
            headers = {'AUTH_KEY': KRX_API_KEY}
            params = {'basDd': krx_date.strftime('%Y%m%d')}
            try:
                response = requests.get(url, headers=headers, params=params)
                df = pd.json_normalize(response.json()['OutBlock_1'])
                st.dataframe(df)
            except Exception as e:
                st.error(f"오류: {e}")
