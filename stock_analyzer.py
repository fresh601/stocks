import os
import sys
import requests
import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
import zipfile
import xml.etree.ElementTree as ET
import json

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

def initialize():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

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
                keep_cols = ['account_nm', 'thstrm_amount']
                df = df[[c for c in keep_cols if c in df.columns]]
                fs_data[str(year)] = df
                found_data = True
                break
        if not found_data:
            fs_data[str(year)] = pd.DataFrame({"account_nm": [], "thstrm_amount": []})
    return fs_data

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

def create_html_report(stock_chart_data, fs_chart_data, excel_path):
    html_path = os.path.join(OUTPUT_DIR, 'index.html')
    stock_json = json.dumps(stock_chart_data, ensure_ascii=False)
    fs_json = json.dumps(fs_chart_data, ensure_ascii=False)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>{TARGET_CORP_NAME} 주식/재무제표 분석 리포트</title>
        <style>
            body {{ font-family: 'Nanum Gothic', sans-serif; }}
            .checkbox-group label {{ margin-right: 15px; }}
        </style>
    </head>
    <body>
        <h1>{TARGET_CORP_NAME} 분석 리포트</h1>
        <p>리포트 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>주가 및 지표 선택</h2>
        <div class="checkbox-group" id="stockCheckboxes"></div>
        <canvas id="stockChart" height="100"></canvas>

        <h2>재무제표 지표 선택</h2>
        <div class="checkbox-group" id="fsCheckboxes"></div>
        <canvas id="fsChart" height="100"></canvas>

        <h2>다운로드</h2>
        <a href="{os.path.basename(excel_path)}" download>엑셀 다운로드</a>

        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
        const stockData = {stock_json};
        const fsData = {fs_json};
        
        function getRandomColor() {{
            return 'hsl(' + 360 * Math.random() + ', 70%, 50%)';
        }}

        // 주가 체크박스 생성
        const stockCheckboxes = document.getElementById('stockCheckboxes');
        Object.keys(stockData).forEach(metric => {{
            const label = document.createElement('label');
            label.innerHTML = `<input type="checkbox" value="${metric}" checked> ${metric}`;
            stockCheckboxes.appendChild(label);
        }});

        // 재무제표 체크박스 생성
        const fsCheckboxes = document.getElementById('fsCheckboxes');
        Object.keys(fsData).forEach(metric => {{
            const label = document.createElement('label');
            label.innerHTML = `<input type="checkbox" value="${metric}"> ${metric}`;
            fsCheckboxes.appendChild(label);
        }});

        let stockChartInstance, fsChartInstance;

        function updateStockChart() {{
            const checked = Array.from(document.querySelectorAll('#stockCheckboxes input:checked')).map(cb => cb.value);
            const labels = Object.keys(stockData[Object.keys(stockData)[0]]);
            const datasets = checked.map(metric => {{
                return {{
                    label: metric,
                    data: Object.values(stockData[metric]),
                    borderColor: getRandomColor(),
                    fill: false,
                    tension: 0.3
                }};
            }});
            if (stockChartInstance) stockChartInstance.destroy();
            stockChartInstance = new Chart(document.getElementById('stockChart'), {{
                type: 'line',
                data: {{ labels: labels, datasets: datasets }},
                options: {{ spanGaps: true }}
            }});
        }}

        function updateFsChart() {{
            const checked = Array.from(document.querySelectorAll('#fsCheckboxes input:checked')).map(cb => cb.value);
            const labels = Object.keys(fsData[Object.keys(fsData)[0]]);
            const datasets = checked.map(metric => {{
                return {{
                    label: metric,
                    data: Object.values(fsData[metric]),
                    borderColor: getRandomColor(),
                    fill: false,
                    tension: 0.3
                }};
            }});
            if (fsChartInstance) fsChartInstance.destroy();
            fsChartInstance = new Chart(document.getElementById('fsChart'), {{
                type: 'line',
                data: {{ labels: labels, datasets: datasets }},
                options: {{ spanGaps: true }}
            }});
        }}

        document.querySelectorAll('#stockCheckboxes input').forEach(cb => cb.addEventListener('change', updateStockChart));
        document.querySelectorAll('#fsCheckboxes input').forEach(cb => cb.addEventListener('change', updateFsChart));

        updateStockChart();
        updateFsChart();
        </script>
    </body>
    </html>
    """
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    return html_path

def main():
    initialize()
    krx_list = pd.DataFrame(stock.get_market_ticker_list(market="ALL"), columns=['Ticker'])
    krx_list['Name'] = krx_list['Ticker'].apply(lambda x: stock.get_market_ticker_name(x))
    target_info = krx_list[krx_list['Name'] == TARGET_CORP_NAME]
    if target_info.empty:
        print(f"{TARGET_CORP_NAME}을 찾을 수 없습니다.")
        return
    ticker = target_info['Ticker'].iloc[0]
    corp_code = get_corp_code(TARGET_CORP_NAME)
    stock_df = get_stock_data(ticker)
    fs_data = get_financial_statements(corp_code)

    # 주가 데이터 JSON 변환
    stock_chart_data = {}
    for col in stock_df.columns:
        if col != "Date":
            stock_chart_data[col] = {str(d.date()): None if pd.isna(v) else float(v) for d, v in zip(stock_df["Date"], stock_df[col])}

    # 재무제표 데이터 JSON 변환
    fs_chart_data = {}
    metrics = set()
    for df in fs_data.values():
        metrics.update(df['account_nm'].unique())
    for metric in metrics:
        fs_chart_data[metric] = {}
        for year, df in fs_data.items():
            try:
                val = df.loc[df['account_nm'] == metric, 'thstrm_amount'].values[0]
                val = str(val).replace(',', '').strip()
                if val:
                    val = int(val) / 1_0000_0000_0000  # 원 → 조원
                    val = round(val, 2)
                else:
                    val = None
            except:
                val = None
            fs_chart_data[metric][year] = val

    excel_path = os.path.join(OUTPUT_DIR, 'stock_data.xlsx')
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        if not stock_df.empty:
            stock_df.to_excel(writer, sheet_name='Stock_Data', index=False)
        for year, df in fs_data.items():
            df.to_excel(writer, sheet_name=f'FS_{year}', index=False)

    html_path = create_html_report(stock_chart_data, fs_chart_data, excel_path)
    print("리포트 생성 완료:", html_path)

if __name__ == "__main__":
    main()
