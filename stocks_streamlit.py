import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import platform
import requests
import zipfile
import xml.etree.ElementTree as ET
import os
from pykrx import stock
import FinanceDataReader as fdr
import dart_fss as dart
from io import BytesIO

# === 0. Streamlit 앱 설정 및 한글 폰트 설정 ===
st.set_page_config(page_title="주식 데이터 크롤링 앱", layout="wide")
st.title("주식 데이터 크롤링 및 분석")

if platform.system() == 'Windows':
    plt.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    plt.rc('font', family='AppleGothic')
plt.rcParams['axes.unicode_minus'] = False

# === 1. API KEY 설정 (secrets.toml 파일에서 불러오기) ===
# st.secrets 딕셔너리에서 API 키를 가져옵니다.
dart_api_key = st.secrets.get("DART_API_KEY")
krx_api_key = st.secrets.get("KRX_API_KEY")

if dart_api_key:
    dart.set_api_key(api_key=dart_api_key)
    st.sidebar.success("DART API KEY가 secrets.toml에서 성공적으로 설정되었습니다.")
else:
    st.sidebar.error("DART API KEY가 secrets.toml에 없습니다. 파일을 확인해주세요.")

if krx_api_key:
    st.sidebar.success("KRX API KEY가 secrets.toml에서 성공적으로 설정되었습니다.")
else:
    st.sidebar.error("KRX API KEY가 secrets.toml에 없습니다. 파일을 확인해주세요.")

# DART 고유번호를 미리 다운로드하여 세션 상태에 저장
if 'corp_code_df' not in st.session_state:
    st.session_state.corp_code_df = None

# DART 기업 고유번호 찾기 및 다운로드 기능
with st.sidebar.expander("DART 기업 고유번호 다운로드"):
    st.markdown("재무 데이터 조회를 위해 기업 고유번호 파일이 필요합니다.")
    if st.button("기업 고유번호 다운로드"):
        if dart_api_key:
            with st.spinner("고유번호를 다운로드 중..."):
                URL = f'https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={dart_api_key}'
                response = requests.get(URL)
                zip_file = BytesIO(response.content)
                with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                    xml_content = zip_ref.read('CORPCODE.xml')
                
                root = ET.fromstring(xml_content)
                corp_list = []
                for corp in root.findall('list'):
                    corp_list.append({
                        'corp_code': corp.find('corp_code').text,
                        'corp_name': corp.find('corp_name').text,
                        'stock_code': corp.find('stock_code').text
                    })
                st.session_state.corp_code_df = pd.DataFrame(corp_list)
            st.success("기업 고유번호 다운로드 및 파싱 완료!")
        else:
            st.warning("DART API KEY가 올바르게 설정되지 않았습니다.")

# === 2. 데이터 크롤링 기능 선택 (탭) ===
tab1, tab2, tab3 = st.tabs(["주가/PER 데이터", "DART 재무 데이터", "KRX API 데이터"])

with tab1:
    st.header("주가 및 PER 데이터 크롤링")
    st.markdown("`FinanceDataReader`와 `pykrx` 라이브러리를 사용합니다.")
    
    stock_code = st.text_input("종목 코드 (예: 005930)", '005930')
    start_date = st.date_input("시작일", pd.to_datetime('2024-01-01'))
    end_date = st.date_input("종료일", pd.to_datetime('2024-12-31'))
    
    if st.button("데이터 가져오기 및 출력"):
        if stock_code:
            try:
                st.subheader("FinanceDataReader 주가 데이터")
                df_fdr = fdr.DataReader(stock_code, start_date, end_date)
                st.dataframe(df_fdr)
                
                fig, ax = plt.subplots(figsize=(10, 6))
                df_fdr['Close'].plot(ax=ax, title=f"{stock_code} 주가")
                ax.set_xlabel('날짜')
                ax.set_ylabel('가격 (KRW)')
                ax.grid(True)
                st.pyplot(fig)
                
                st.subheader("Pykrx 주가 및 PER 데이터")
                daily_prices = stock.get_market_ohlcv_by_date(start_date.strftime('%Y%m%d'), end_date.strftime('%Y%m%d'), stock_code)
                per_data = stock.get_market_fundamental_by_date(start_date.strftime('%Y%m%d'), end_date.strftime('%Y%m%d'), stock_code, freq='d')
                
                st.write("일자별 주가")
                st.dataframe(daily_prices)
                
                st.write("일자별 PER")
                st.dataframe(per_data)

                if not per_data.empty:
                    fig_per, ax_per = plt.subplots(figsize=(10, 6))
                    per_data['PER'].plot(ax=ax_per, title=f"{stock_code} PER 추이")
                    ax_per.set_xlabel('날짜')
                    ax_per.set_ylabel('PER')
                    ax_per.grid(True)
                    st.pyplot(fig_per)
                else:
                    st.warning("Pykrx에서 PER 데이터를 찾을 수 없습니다.")

            except Exception as e:
                st.error(f"데이터를 가져오는 중 오류 발생: {e}")
        else:
            st.warning("종목 코드를 입력해주세요.")

with tab2:
    st.header("DART 재무 데이터 크롤링")
    if not dart_api_key:
        st.warning("DART API KEY가 secrets.toml에 없습니다. 파일을 확인해주세요.")
    elif st.session_state.corp_code_df is None:
        st.warning("먼저 사이드바에서 DART 기업 고유번호 파일을 다운로드해주세요.")
    else:
        corp_name_list = st.session_state.corp_code_df['corp_name'].tolist()
        selected_corp_name = st.selectbox("기업명을 선택하세요", corp_name_list)
        
        corp_code = st.session_state.corp_code_df[st.session_state.corp_code_df['corp_name'] == selected_corp_name]['corp_code'].iloc[0]
        st.write(f"선택된 기업 고유번호: {corp_code}")
    
        bsns_year = st.selectbox("사업연도", list(range(2024, 2014, -1)), index=0)
        reprt_code_dict = {'사업보고서': '11011', '반기보고서': '11012', '1분기보고서': '11013', '3분기보고서': '11014'}
        reprt_code_name = st.selectbox("보고서 종류", list(reprt_code_dict.keys()))
        
        if st.button("주요 계정 가져오기"):
            try:
                reprt_code = reprt_code_dict[reprt_code_name]
                url = f'https://opendart.fss.or.kr/api/fnlttMultiAcnt.json?crtfc_key={dart_api_key}&corp_code={corp_code}&bsns_year={bsns_year}&reprt_code={reprt_code}'
                response = requests.get(url)
                finances = response.json()
                
                if finances.get('status') == '000':
                    df = pd.json_normalize(finances['list'])
                    st.dataframe(df)
                else:
                    st.error(f"API 오류: {finances.get('message')}")
            except Exception as e:
                st.error(f"DART API 호출 중 오류 발생: {e}")

        st.markdown("---")
        
        st.subheader("Dart-fss 라이브러리 사용")
        if st.button("Dart-fss 재무제표 출력"):
            try:
                with st.spinner("재무제표를 추출하고 있습니다..."):
                    corp_list = dart.get_corp_list()
                    samsung = corp_list.find_by_corp_name(selected_corp_name, exactly=True)[0]
                    fs = samsung.extract_fs(bgn_de=f'{bsns_year}0101')
                
                st.subheader(f"{selected_corp_name}의 {bsns_year}년 재무제표")
                
                st.write("포괄손익계산서")
                st.dataframe(fs.df_is)
                
                st.write("재무상태표")
                st.dataframe(fs.df_bs)

                st.write("현금흐름표")
                st.dataframe(fs.df_cf)
                
            except Exception as e:
                st.error(f"Dart-fss를 사용하는 중 오류 발생: {e}")

with tab3:
    st.header("KRX OPEN API 데이터 크롤링")
    if not krx_api_key:
        st.warning("KRX API KEY가 secrets.toml에 없습니다. 파일을 확인해주세요.")
    else:
        krx_date = st.date_input("조회할 날짜", pd.to_datetime('2023-05-21'))
        
        if st.button("종목 기본정보 가져오기"):
            try:
                url = 'http://data-dbg.krx.co.kr/svc/apis/sto/stk_isu_base_info'
                params = {'basDd': krx_date.strftime('%Y%m%d')}
                headers = {'AUTH_KEY': krx_api_key}
                response = requests.get(url, params=params, headers=headers)
                data = response.json()
                df = pd.json_normalize(data['OutBlock_1'])
                st.dataframe(df)
            except Exception as e:
                st.error(f"KRX API 호출 중 오류 발생: {e}")
        
        if st.button("일별 매매정보 가져오기"):
            try:
                url = 'http://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd'
                params = {'basDd': krx_date.strftime('%Y%m%d')}
                headers = {'AUTH_KEY': krx_api_key}
                response = requests.get(url, params=params, headers=headers)
                data = response.json()
                df = pd.json_normalize(data['OutBlock_1'])
                st.dataframe(df)
            except Exception as e:
                st.error(f"KRX API 호출 중 오류 발생: {e}")