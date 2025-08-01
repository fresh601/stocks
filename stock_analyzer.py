import os
import sys # 스크립트 종료를 위해 추가
import pandas as pd
import dart_fss as dart
from pykrx import stock
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from datetime import datetime, timedelta

# --- 설정 ---
# 분석할 회사 이름
TARGET_CORP_NAME = '삼성전자'
# 데이터 조회 기간 (오늘로부터 3년 전까지)
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=3 * 365)
# 날짜 포맷팅
END_DATE_STR = END_DATE.strftime('%Y%m%d')
START_DATE_STR = START_DATE.strftime('%Y%m%d')
# 결과물을 저장할 폴더
OUTPUT_DIR = 'output'

# ===================================================================
# API 키 (GitHub Secrets 또는 로컬 환경변수에서 가져옴)
# ===================================================================
DART_API_KEY = os.getenv('DART_API_KEY')

if not DART_API_KEY:
    print("오류: DART_API_KEY 환경변수가 설정되지 않았습니다.")
    print("스크립트를 종료합니다. GitHub Secrets 또는 로컬 환경에 키를 설정해주세요.")
    sys.exit(1) # 오류 코드와 함께 스크립트 종료
# ===================================================================

def initialize():
    """결과 저장 폴더 생성 및 한글 폰트 설정"""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    # OS에 맞는 한글 폰트 설정
    if os.name == 'nt': # Windows
        font_family = 'Malgun Gothic'
    elif os.name == 'posix': # Linux, Mac
        font_family = 'AppleGothic'
    else:
        font_family = 'NanumGothic' # 기본
    
    try:
        plt.rc('font', family=font_family)
    except:
        try:
            prop = fm.FontProperties(fname='/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf')
            plt.rc('font', family=prop.get_name())
        except:
            print("한글 폰트를 찾을 수 없습니다. 차트의 한글이 깨질 수 있습니다.")
            
    plt.rcParams['axes.unicode_minus'] = False

def get_financial_statements(corp_code):
    """DART에서 재무제표 가져오기"""
    print(f"[{TARGET_CORP_NAME}] 재무제표 다운로드 중...")
    try:
        dart.set_api_key(api_key=DART_API_KEY)
        corp = dart.get_corp_list().find_by_corp_code(corp_code)
        fs = corp.extract_fs(bgn_de=(END_DATE - timedelta(days=5*365)).strftime('%Y%m%d'), fs_tp='fs', report_tp='annual')
        return fs
    except Exception as e:
        print(f"재무제표를 가져오는 중 오류 발생: {e}")
        return None

def get_stock_data(ticker):
    """pykrx로 주가 및 투자 지표 데이터 가져오기"""
    print(f"[{TARGET_CORP_NAME}({ticker})] 주가 정보 다운로드 중...")
    try:
        ohlcv = stock.get_market_ohlcv_by_date(fromdate=START_DATE_STR, todate=END_DATE_STR, ticker=ticker)
        fundamental = stock.get_market_fundamental_by_date(fromdate=START_DATE_STR, todate=END_DATE_STR, ticker=ticker)
        
        df = pd.concat([ohlcv, fundamental], axis=1)
        df.reset_index(inplace=True)
        df.rename(columns={'날짜': 'Date', '시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume', 'DIV': 'DividendYield', 'BPS': 'BookValuePerShare', 'PER': 'PriceEarningsRatio', 'PBR': 'PriceBookRatio'}, inplace=True)
        return df
    except Exception as e:
        print(f"주가 정보를 가져오는 중 오류 발생: {e}")
        return pd.DataFrame()

def create_stock_chart(df, ticker):
    """주가 및 거래량 차트 생성 및 저장"""
    print("주가 차트 생성 중...")
    fig = plt.figure(figsize=(15, 8))
    
    ax1 = fig.add_subplot(2, 1, 1)
    ax1.plot(df['Date'], df['Close'], label='종가', color='blue', linewidth=2)
    ax1.set_title(f'{TARGET_CORP_NAME} ({ticker}) 주가 및 거래량', fontsize=16)
    ax1.set_ylabel('주가 (KRW)')
    ax1.legend(loc='upper left')
    ax1.grid(True)

    ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
    ax2.bar(df['Date'], df['Volume'], label='거래량', color='grey', alpha=0.7)
    ax2.set_ylabel('거래량')
    ax2.set_xlabel('날짜')
    ax2.legend(loc='upper left')
    ax2.grid(True)
    
    plt.tight_layout()
    chart_path = os.path.join(OUTPUT_DIR, 'stock_chart.png')
    plt.savefig(chart_path)
    plt.close()
    print(f"차트가 '{chart_path}'에 저장되었습니다.")
    return chart_path

def save_to_excel(data_dict):
    """여러 데이터프레임을 하나의 엑셀 파일에 시트별로 저장"""
    excel_path = os.path.join(OUTPUT_DIR, 'stock_data.xlsx')
    print(f"데이터를 엑셀 파일로 저장 중: {excel_path}")
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        for sheet_name, df in data_dict.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    print("엑셀 파일 저장이 완료되었습니다.")

def create_html_report(chart_path, excel_path):
    """결과를 보여줄 HTML 파일 생성"""
    html_path = os.path.join(OUTPUT_DIR, 'index.html')
    print(f"HTML 리포트 생성 중: {html_path}")
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{TARGET_CORP_NAME} 주식 분석 리포트</title>
        <style>
            body {{ font-family: sans-serif; margin: 40px; }}
            .container {{ max-width: 1000px; margin: auto; }}
            h1 {{ color: #333; }}
            img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
            a {{ text-decoration: none; color: #0077cc; font-weight: bold; }}
            .footer {{ margin-top: 20px; font-size: 0.8em; color: #777; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{TARGET_CORP_NAME} 분석 리포트</h1>
            <p><strong>리포트 생성 시각:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            
            <h2>주가 차트</h2>
            <img src="{os.path.basename(chart_path)}" alt="{TARGET_CORP_NAME} 주가 차트">
            
            <h2>상세 데이터</h2>
            <p><a href="{os.path.basename(excel_path)}" download>엑셀 파일 다운로드</a></p>
            
            <div class="footer">
                <p>이 리포트는 GitHub Actions를 통해 자동으로 생성되었습니다.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("HTML 리포트 생성이 완료되었습니다.")

def main():
    """메인 실행 함수"""
    initialize()
    
    krx_list = pd.DataFrame(stock.get_market_ticker_list(market="ALL"))
    krx_list.columns = ['Ticker']
    krx_list['Name'] = krx_list['Ticker'].apply(lambda x: stock.get_market_ticker_name(x))
    
    target_info = krx_list[krx_list['Name'] == TARGET_CORP_NAME]
    if target_info.empty:
        print(f"'{TARGET_CORP_NAME}'을 찾을 수 없습니다. 회사명을 확인해주세요.")
        return
        
    ticker = target_info['Ticker'].iloc[0]
    
    dart_list = dart.get_corp_list()
    corp_code = dart_list.find_by_corp_name(TARGET_CORP_NAME, exactly=True)[0].corp_code

    stock_df = get_stock_data(ticker)
    fs_dict = get_financial_statements(corp_code)
    
    if not stock_df.empty:
        chart_path = create_stock_chart(stock_df, ticker)
        excel_path = os.path.join(OUTPUT_DIR, 'stock_data.xlsx')
        
        data_to_save = {'Stock_Data': stock_df}
        if fs_dict:
            for item in fs_dict:
                sheet_name = item.title.replace(' ', '_')[:31]
                data_to_save[sheet_name] = item.to_df()

        save_to_excel(data_to_save)
        create_html_report(chart_path, excel_path)
    else:
        print("주가 데이터를 가져오지 못해 리포트를 생성할 수 없습니다.")

if __name__ == "__main__":
    main()