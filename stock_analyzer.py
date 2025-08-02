import os
import sys
import requests
import pandas as pd
from pykrx import stock
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from datetime import datetime, timedelta
import zipfile
import xml.etree.ElementTree as ET

# --- 설정 ---
TARGET_CORP_NAME = '삼성전자'
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=3 * 365)
END_DATE_STR = END_DATE.strftime('%Y%m%d')
START_DATE_STR = START_DATE.strftime('%Y%m%d')
OUTPUT_DIR = 'output'

# API 키
DART_API_KEY = os.getenv('DART_API_KEY')

if not DART_API_KEY:
    print("경고: DART_API_KEY 환경변수가 설정되지 않았습니다. 재무제표 데이터는 '데이터 없음'으로 표시됩니다.")

# ===================================================================
# 폰트 설정
# ===================================================================
nanum_font = None

def initialize():
    """결과 저장 폴더 생성 및 한글 폰트 설정"""
    global nanum_font

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    custom_font_path = os.path.join(os.getcwd(), 'NanumGothic.otf')
    if os.path.exists(custom_font_path):
        nanum_font = fm.FontProperties(fname=custom_font_path)
        plt.rcParams['font.family'] = nanum_font.get_name()
        print(f"사용자 지정 폰트 적용: {nanum_font.get_name()}")
    else:
        if os.name == 'nt':
            plt.rcParams['font.family'] = 'Malgun Gothic'
        elif os.name == 'posix':
            plt.rcParams['font.family'] = 'AppleGothic'
        else:
            plt.rcParams['font.family'] = 'NanumGothic'
        print("기본 시스템 폰트 적용")

    plt.rcParams['axes.unicode_minus'] = False

# ===================================================================
# 회사 코드 조회
# ===================================================================
def get_corp_code(corp_name):
    if not DART_API_KEY:
        return None

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    try:
        r = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=10)
    except Exception as e:
        print(f"corpCode.xml 요청 실패: {e}")
        return None

    zip_path = os.path.join(OUTPUT_DIR, "corpCode.zip")
    with open(zip_path, 'wb') as f:
        f.write(r.content)

    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(OUTPUT_DIR)

    xml_path = os.path.join(OUTPUT_DIR, "CORPCODE.xml")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for child in root.findall('list'):
        if child.find('corp_name').text == corp_name:
            return child.find('corp_code').text
    return None

# ===================================================================
# 재무제표 수집
# ===================================================================
def get_financial_statements(corp_code):
    fs_data = {}
    if not DART_API_KEY or not corp_code:
        fs_data["재무제표"] = pd.DataFrame({"메시지": ["데이터 없음 (API 키 없음 또는 corp_code 없음)"]})
        return fs_data

    current_year = END_DATE.year

    for year in range(current_year - 5, current_year + 1):
        found_data = False
        for fs_div in ["CFS", "OFS"]:
            params = {
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": "11011",
                "fs_div": fs_div
            }
            try:
                res = requests.get(
                    "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                    params=params,
                    timeout=10
                ).json()
            except Exception as e:
                print(f"{year}년 {fs_div} 요청 실패: {e}")
                continue

            if res.get("status") == "000" and "list" in res:
                df = pd.DataFrame(res["list"])
                keep_cols = ['sj_div', 'sj_nm', 'account_nm', 'thstrm_amount',
                             'frmtrm_amount', 'bfefrmtrm_amount']
                df = df[[c for c in keep_cols if c in df.columns]]
                fs_data[str(year)] = df
                print(f"{year}년 {fs_div} 재무제표 수집 완료")
                found_data = True
                break

        if not found_data:
            fs_data[str(year)] = pd.DataFrame({"메시지": [f"{year}년 데이터 없음"]})

    return fs_data

# ===================================================================
# 주가 데이터
# ===================================================================
def get_stock_data(ticker):
    try:
        ohlcv = stock.get_market_ohlcv_by_date(START_DATE_STR, END_DATE_STR, ticker)
        fundamental = stock.get_market_fundamental_by_date(START_DATE_STR, END_DATE_STR, ticker)
        df = pd.concat([ohlcv, fundamental], axis=1)
        df.reset_index(inplace=True)
        df.rename(columns={
            '날짜': 'Date',
            '시가': 'Open',
            '고가': 'High',
            '저가': 'Low',
            '종가': 'Close',
            '거래량': 'Volume',
            'DIV': 'DividendYield',
            'BPS': 'BookValuePerShare',
            'PER': 'PriceEarningsRatio',
            'PBR': 'PriceBookRatio'
        }, inplace=True)
        return df
    except Exception as e:
        print(f"주가 정보를 가져오는 중 오류 발생: {e}")
        return pd.DataFrame()

# ===================================================================
# 주가 차트
# ===================================================================
def create_stock_chart(df, ticker):
    fig = plt.figure(figsize=(15, 8))
    ax1 = fig.add_subplot(2, 1, 1)
    ax1.plot(df['Date'], df['Close'], label='종가', color='blue', linewidth=2)
    ax1.set_title(f'{TARGET_CORP_NAME} ({ticker}) 주가 및 거래량', fontproperties=nanum_font)
    ax1.set_ylabel('주가 (KRW)', fontproperties=nanum_font)
    ax1.legend(prop=nanum_font, loc='upper left')
    ax1.grid(True)

    ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
    ax2.bar(df['Date'], df['Volume'], label='거래량', color='grey', alpha=0.7)
    ax2.set_ylabel('거래량', fontproperties=nanum_font)
    ax2.set_xlabel('날짜', fontproperties=nanum_font)
    ax2.legend(prop=nanum_font, loc='upper left')
    ax2.grid(True)

    plt.tight_layout()
    chart_path = os.path.join(OUTPUT_DIR, 'stock_chart.png')
    plt.savefig(chart_path, bbox_inches='tight')
    plt.close()
    return chart_path

# ===================================================================
# 재무제표 그래프
# ===================================================================
def create_fs_chart(fs_data):
    metrics = ["매출액", "영업이익", "당기순이익"]
    years = []
    chart_data = {m: [] for m in metrics}

    for year, df in fs_data.items():
        years.append(year)
        for m in metrics:
            try:
                val = df.loc[df['account_nm'] == m, 'thstrm_amount'].values[0]
                val = int(str(val).replace(',', '').strip())
            except:
                val = None
            chart_data[m].append(val)

    fig, ax = plt.subplots(figsize=(10, 6))
    for m in metrics:
        ax.plot(years, chart_data[m], marker='o', label=m)

    ax.set_title("최근 5년 재무제표 추이", fontproperties=nanum_font)
    ax.set_ylabel("금액(백만원)", fontproperties=nanum_font)
    ax.legend(prop=nanum_font)
    ax.grid(True)

    chart_path = os.path.join(OUTPUT_DIR, 'fs_chart.png')
    plt.savefig(chart_path, bbox_inches='tight')
    plt.close()
    return chart_path

# ===================================================================
# 엑셀 저장
# ===================================================================
def save_to_excel(stock_df, fs_data):
    excel_path = os.path.join(OUTPUT_DIR, 'stock_data.xlsx')
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        if not stock_df.empty:
            stock_df.to_excel(writer, sheet_name='Stock_Data', index=False)
        for year, df in fs_data.items():
            df.to_excel(writer, sheet_name=f'FS_{year}', index=False)
    return excel_path

# ===================================================================
# HTML 리포트
# ===================================================================
def create_html_report(stock_chart_path, fs_chart_path, excel_path):
    html_path = os.path.join(OUTPUT_DIR, 'index.html')

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>{TARGET_CORP_NAME} 주식 분석 리포트</title>
        <style>
            body {{ font-family: 'Nanum Gothic', sans-serif; }}
            img {{ max-width: 100%; height: auto; }}
        </style>
    </head>
    <body>
        <h1>{TARGET_CORP_NAME} 분석 리포트</h1>
        <p>리포트 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>주가 차트</h2>
        <img src="{os.path.basename(stock_chart_path)}" alt="주가 차트">

        <h2>재무제표 추이</h2>
        <img src="{os.path.basename(fs_chart_path)}" alt="재무제표 추이">

        <h2>다운로드</h2>
        <a href="{os.path.basename(excel_path)}" download>엑셀 다운로드</a>
    </body>
    </html>
    """
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    return html_path

# ===================================================================
# main
# ===================================================================
def main():
    initialize()

    # 주가 코드 찾기
    krx_list = pd.DataFrame(stock.get_market_ticker_list(market="ALL"), columns=['Ticker'])
    krx_list['Name'] = krx_list['Ticker'].apply(lambda x: stock.get_market_ticker_name(x))
    target_info = krx_list[krx_list['Name'] == TARGET_CORP_NAME]
    if target_info.empty:
        print(f"{TARGET_CORP_NAME}을 찾을 수 없습니다.")
        return
    ticker = target_info['Ticker'].iloc[0]

    # 회사 코드 찾기
    corp_code = get_corp_code(TARGET_CORP_NAME)

    # 데이터 수집
    stock_df = get_stock_data(ticker)
    fs_data = get_financial_statements(corp_code)

    # 차트 생성
    stock_chart_path = create_stock_chart(stock_df, ticker) if not stock_df.empty else None
    fs_chart_path = create_fs_chart(fs_data)

    # 저장
    excel_path = save_to_excel(stock_df, fs_data)

    # HTML 리포트 생성
    html_path = create_html_report(stock_chart_path, fs_chart_path, excel_path)
    print("리포트 생성 완료:", html_path)

if __name__ == "__main__":
    main()
