# -*- coding: utf-8 -*-
"""
Streamlit KRX + DART 재무 리포트 (최종 안정화판)
- 회사 검색
- 연도/보고서(11011/11012/11013/11014) 선택
- 연결/별도(CFS/OFS) 모드 선택
- "데이터 불러오기/갱신" 버튼을 눌렀을 때만 네트워크 조회
- 선택(체크/멀티셀렉트) 변경 시엔 세션 캐시로 즉시 차트 갱신 (네트워크 호출 0)
- 모든 네트워크 함수는 st.cache_data로 2중 방어 (동일 파라미터면 재호출 없음)
- HTML 리포트 + 엑셀 다운로드

실행: streamlit run app.py
필수: pip install streamlit pykrx pandas requests openpyxl
"""

import os
import io
import json
import zipfile
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pykrx import stock

try:
    import streamlit as st
except Exception:
    st = None  # 안전 가드

# ─────────────────────────────────────────────────────────────
# 전역 설정
# ─────────────────────────────────────────────────────────────
TARGET_CORP_NAME_DEFAULT = "삼성전자"
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=3 * 365)
END_DATE_STR = END_DATE.strftime("%Y%m%d")
START_DATE_STR = START_DATE.strftime("%Y%m%d")
OUTPUT_DIR = "output"

def initialize():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_secret(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if (not v) and st is not None:
        try:
            v = st.secrets.get(name, default)
        except Exception:
            v = default
    return str(v).strip() if v is not None else default

DART_API_KEY = get_secret("DART_API_KEY")

# ─────────────────────────────────────────────────────────────
# 키 점검: 최초 1회만
# ─────────────────────────────────────────────────────────────
def ping_dart_key_once(api_key: str) -> bool:
    if not api_key:
        if st: st.warning("DART_API_KEY가 설정되어 있지 않습니다. (Streamlit Cloud → App → Settings → Secrets)")
        return False
    try:
        r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                         params={"crtfc_key": api_key}, timeout=10)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            if "CORPCODE.xml" in zf.namelist():
                if st: st.success("DART 키 연결 정상 ✅")
                return True
            if st: st.error("DART corpCode ZIP은 받았지만 CORPCODE.xml이 없습니다.")
            return False
    except zipfile.BadZipFile:
        if st: st.error("[DART] corpCode 응답이 ZIP이 아닙니다.")
        return False
    except Exception as e:
        if st: st.error(f"[DART] 접속/파싱 실패: {e}")
        return False

# ─────────────────────────────────────────────────────────────
# 데이터 소스: 모두 cache_data로 보호
# ─────────────────────────────────────────────────────────────
if st:
    @st.cache_data(show_spinner=False)
    def get_all_krx_symbols():
        tickers = stock.get_market_ticker_list(market="ALL")
        df = pd.DataFrame({"Ticker": tickers})
        df["Name"] = df["Ticker"].apply(lambda x: stock.get_market_ticker_name(x))
        return df
else:
    def get_all_krx_symbols():
        tickers = stock.get_market_ticker_list(market="ALL")
        df = pd.DataFrame({"Ticker": tickers})
        df["Name"] = df["Ticker"].apply(lambda x: stock.get_market_ticker_name(x))
        return df

if st:
    @st.cache_data(show_spinner=False, ttl=86400)
    def fetch_corp_code(corp_name: str, api_key: str):
        try:
            r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                             params={"crtfc_key": api_key}, timeout=10)
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            xml_bytes = zf.read("CORPCODE.xml")
            root = ET.fromstring(xml_bytes)
            for node in root.findall("list"):
                nm = (node.findtext("corp_name", "") or "").strip()
                if nm == corp_name:
                    return (node.findtext("corp_code", "") or "").strip()
            return None
        except Exception:
            return None
else:
    def fetch_corp_code(corp_name: str, api_key: str):
        try:
            r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                             params={"crtfc_key": api_key}, timeout=10)
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            xml_bytes = zf.read("CORPCODE.xml")
            root = ET.fromstring(xml_bytes)
            for node in root.findall("list"):
                nm = (node.findtext("corp_name", "") or "").strip()
                if nm == corp_name:
                    return (node.findtext("corp_code", "") or "").strip()
            return None
        except Exception:
            return None

if st:
    @st.cache_data(show_spinner=True, ttl=3600)
    def fetch_financials(corp_code: str,
                         current_year: int,
                         reprt_overrides_tuple: tuple,  # e.g., ((2025,'11014'),)
                         fs_mode: str,
                         api_key: str):
        # tuple → dict
        reprt_overrides = dict(reprt_overrides_tuple)
        return _get_financial_statements_impl(corp_code, current_year, reprt_overrides, fs_mode, api_key)
else:
    def fetch_financials(corp_code: str,
                         current_year: int,
                         reprt_overrides_tuple: tuple,
                         fs_mode: str,
                         api_key: str):
        reprt_overrides = dict(reprt_overrides_tuple)
        return _get_financial_statements_impl(corp_code, current_year, reprt_overrides, fs_mode, api_key)

def _get_financial_statements_impl(corp_code: str,
                                   current_year: int,
                                   reprt_overrides: dict | None,
                                   fs_mode: str,
                                   api_key: str):
    fs_data = {}
    if not api_key or not corp_code:
        fs_data["재무제표"] = pd.DataFrame({"메시지": ["데이터 없음 (API 키 없음 또는 corp_code 없음)"]})
        return fs_data

    if fs_mode == "CFS_ONLY":
        fs_div_order = ["CFS"]
    elif fs_mode == "OFS_ONLY":
        fs_div_order = ["OFS"]
    elif fs_mode == "AUTO_OFS_CFS":
        fs_div_order = ["OFS", "CFS"]
    else:
        fs_div_order = ["CFS", "OFS"]

    def try_one_year(year: int):
        if reprt_overrides and year in reprt_overrides:
            reprt_codes = [reprt_overrides[year]]
        else:
            reprt_codes = (["11011", "11012", "11013", "11014"]
                           if year < current_year else
                           ["11014", "11013", "11012", "11011"])

        for fs_div in fs_div_order:
            for reprt_code in reprt_codes:
                params = {
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": reprt_code,
                    "fs_div": fs_div,
                }
                try:
                    res = requests.get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                                       params=params, timeout=10).json()
                except Exception:
                    continue

                if res.get("status") == "000" and isinstance(res.get("list"), list) and len(res["list"]) > 0:
                    df = pd.DataFrame(res["list"])
                    keep_cols = ["account_nm", "thstrm_amount"]
                    cols = [c for c in keep_cols if c in df.columns]
                    if not cols:
                        continue
                    df = df[cols].copy()
                    df["account_nm"] = df["account_nm"].astype(str).str.strip()
                    df["thstrm_amount"] = df["thstrm_amount"].astype(str).str.replace(",", "").str.strip()
                    return df
        return None

    for year in range(current_year - 5, current_year + 1):
        df = try_one_year(year)
        fs_data[str(year)] = df if df is not None else pd.DataFrame({"account_nm": [], "thstrm_amount": []})
    return fs_data

if st:
    @st.cache_data(show_spinner=False, ttl=3600)
    def fetch_stock_data(ticker: str, start: str, end: str):
        try:
            ohlcv = stock.get_market_ohlcv_by_date(start, end, ticker)
            fundamental = stock.get_market_fundamental_by_date(start, end, ticker)
            df = pd.concat([ohlcv, fundamental], axis=1)
            df.reset_index(inplace=True)
            df.rename(columns={
                "날짜": "Date", "시가": "Open", "고가": "High", "저가": "Low",
                "종가": "Close", "거래량": "Volume",
                "DIV": "DividendYield", "BPS": "BookValuePerShare",
                "PER": "PriceEarningsRatio", "PBR": "PriceBookRatio",
            }, inplace=True)
            return df
        except Exception:
            return pd.DataFrame()
else:
    def fetch_stock_data(ticker: str, start: str, end: str):
        try:
            ohlcv = stock.get_market_ohlcv_by_date(start, end, ticker)
            fundamental = stock.get_market_fundamental_by_date(start, end, ticker)
            df = pd.concat([ohlcv, fundamental], axis=1)
            df.reset_index(inplace=True)
            df.rename(columns={
                "날짜": "Date", "시가": "Open", "고가": "High", "저가": "Low",
                "종가": "Close", "거래량": "Volume",
                "DIV": "DividendYield", "BPS": "BookValuePerShare",
                "PER": "PriceEarningsRatio", "PBR": "PriceBookRatio",
            }, inplace=True)
            return df
        except Exception:
            return pd.DataFrame()

# ─────────────────────────────────────────────────────────────
# HTML 리포트
# ─────────────────────────────────────────────────────────────
def create_html_report(target_corp_name: str, stock_chart_data: dict, fs_chart_data: dict, excel_basename: str):
    html_path = os.path.join(OUTPUT_DIR, "index.html")
    stock_json = json.dumps(stock_chart_data, ensure_ascii=False)
    fs_json = json.dumps(fs_chart_data, ensure_ascii=False)

    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{target_corp_name} 주식/재무제표 분석 리포트</title>
<style>
  body {{ font-family: 'Nanum Gothic', sans-serif; line-height: 1.5; }}
  .checkbox-group label {{ margin-right: 12px; display:inline-block; margin-bottom:6px; }}
  .muted {{ color: #666; }}
</style>
</head>
<body>
  <h1>{target_corp_name} 분석 리포트</h1>
  <p>리포트 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

  <h2>주가 지표</h2>
  <div id="stockSec">
    <div class="checkbox-group" id="stockCheckboxes"></div>
    <canvas id="stockChart" height="100"></canvas>
    <p id="stockEmpty" class="muted" style="display:none;">표시할 주가 데이터가 없습니다.</p>
  </div>

  <h2>재무제표 지표</h2>
  <div id="fsSec">
    <div class="checkbox-group" id="fsCheckboxes"></div>
    <canvas id="fsChart" height="100"></canvas>
    <p id="fsEmpty" class="muted" style="display:none;">표시할 재무 데이터가 없습니다.</p>
  </div>

  <h2>다운로드</h2>
  <a href="{excel_basename}" download>엑셀 다운로드</a>

  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script>
    const stockData = {stock_json};
    const fsData = {fs_json};

    function getRandomColor() {{
      return 'hsl(' + Math.floor(360*Math.random()) + ',70%,50%)';
    }}
    function firstKey(o) {{
      const ks = Object.keys(o || {{}}); return ks.length ? ks[0] : null;
    }}

    // 주가
    const stockFirst = firstKey(stockData);
    const stockBox = document.getElementById('stockCheckboxes');
    const stockEmpty = document.getElementById('stockEmpty');
    if (stockFirst) {{
      Object.keys(stockData).forEach(k => {{
        const label = document.createElement('label');
        label.innerHTML = `<input type="checkbox" value="${{k}}" checked> ${{k}}`;
        stockBox.appendChild(label);
      }});
    }} else {{
      document.getElementById('stockChart').style.display = 'none';
      stockEmpty.style.display = 'block';
    }}

    // 재무
    const fsFirst = firstKey(fsData);
    const fsBox = document.getElementById('fsCheckboxes');
    const fsEmpty = document.getElementById('fsEmpty');
    if (fsFirst) {{
      Object.keys(fsData).forEach(k => {{
        const label = document.createElement('label');
        label.innerHTML = `<input type="checkbox" value="${{k}}"> ${{k}}`;
        fsBox.appendChild(label);
      }});
    }} else {{
      document.getElementById('fsChart').style.display = 'none';
      fsEmpty.style.display = 'block';
    }}

    let stockChart, fsChart;

    function updateStockChart() {{
      if (!stockFirst) return;
      const checked = Array.from(document.querySelectorAll('#stockCheckboxes input:checked')).map(x=>x.value);
      const labels = Object.keys(stockData[stockFirst] || {{}}); // 날짜들
      const datasets = checked.map(m => {{
        return {{ label: m, data: Object.values(stockData[m]||{{}}), borderColor: getRandomColor(), fill:false, tension:0.3 }};
      }});
      if (stockChart) stockChart.destroy();
      stockChart = new Chart(document.getElementById('stockChart'), {{
        type: 'line',
        data: {{ labels, datasets }},
        options: {{ spanGaps:true, animation:false }}
      }});
    }}

    function updateFsChart() {{
      if (!fsFirst) return;
      const checked = Array.from(document.querySelectorAll('#fsCheckboxes input:checked')).map(x=>x.value);
      const labels = Object.keys(fsData[fsFirst] || {{}}); // 연도들
      const datasets = checked.map(m => {{
        return {{ label: m, data: Object.values(fsData[m]||{{}}), borderColor: getRandomColor(), fill:false, tension:0.3 }};
      }});
      if (fsChart) fsChart.destroy();
      fsChart = new Chart(document.getElementById('fsChart'), {{
        type: 'line',
        data: {{ labels, datasets }},
        options: {{ spanGaps:true, animation:false }}
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
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path

# ─────────────────────────────────────────────────────────────
# 세션 관리: 버튼 클릭 시에만 네트워크 조회
# ─────────────────────────────────────────────────────────────
def params_key(target_name: str, ticker: str, sel_year: int, sel_code: str, fs_mode: str):
    return f"{target_name}|{ticker}|{sel_year}|{sel_code}|{fs_mode}"

def load_data_once_by_button(target_name, ticker, sel_year, sel_code, fs_mode):
    key = params_key(target_name, ticker, sel_year, sel_code, fs_mode)

    # 최초 또는 파라미터 변경 시에만 네트워크 조회
    if "DATA_KEY" not in st.session_state or st.session_state.DATA_KEY != key:
        corp_code = fetch_corp_code(target_name, DART_API_KEY)
        if not corp_code:
            fs_data = {"재무제표": pd.DataFrame({"메시지": ["데이터 없음"]})}
        else:
            reprt_overrides_tuple = tuple(sorted([(sel_year, sel_code)]))
            fs_data = fetch_financials(
                corp_code=corp_code,
                current_year=END_DATE.year,
                reprt_overrides_tuple=reprt_overrides_tuple,
                fs_mode=fs_mode,
                api_key=DART_API_KEY,
            )
        stock_df = fetch_stock_data(ticker, START_DATE_STR, END_DATE_STR)

        st.session_state.DATA_KEY = key
        st.session_state.STOCK_DF = stock_df
        st.session_state.FS_DATA = fs_data

    # 이후에는 세션 데이터만 사용 (네트워크 호출 0)
    return st.session_state.get("STOCK_DF", pd.DataFrame()), st.session_state.get("FS_DATA", {})

# ─────────────────────────────────────────────────────────────
# 메인 UI
# ─────────────────────────────────────────────────────────────
def main():
    initialize()

    # 키 점검: 최초 1회만
    if st and not st.session_state.get("KEY_CHECKED", False):
        ping_dart_key_once(DART_API_KEY)
        st.session_state["KEY_CHECKED"] = True

    st.title("📊 KRX 주가 & DART 재무 — 버튼 조회 + 즉시 갱신")
    st.caption("회사/연도/보고서/연결 기준을 정해 한 번만 데이터를 불러오고, 항목 선택은 세션 데이터로 즉시 반영됩니다.")

    # 회사 검색/선택
    krx_df = get_all_krx_symbols()
    col1, col2 = st.columns([1, 2])
    with col1:
        name_input = st.text_input("회사명 검색", value=TARGET_CORP_NAME_DEFAULT, help="예: 삼성전자, SK하이닉스, 현대차 ...")
    with col2:
        cand = krx_df[krx_df["Name"].str.contains(name_input.strip(), na=False)]
        picked = st.selectbox("검색 결과에서 선택",
                              options=cand["Name"].tolist() if not cand.empty else [name_input],
                              index=0)
    target_name = picked.strip()

    info = krx_df[krx_df["Name"] == target_name]
    if info.empty:
        st.error(f"'{target_name}' 을(를) KRX에서 찾을 수 없습니다.")
        return
    ticker = info["Ticker"].iloc[0]
    st.write(f"**선택된 종목:** {target_name} ({ticker})")

    # 보고서 연도/종류 선택
    st.subheader("보고서 종류 선택")
    year_options = list(range(END_DATE.year - 5, END_DATE.year + 1))
    sel_year = st.selectbox("연도", options=year_options, index=len(year_options) - 1)
    reprt_map = {
        "연간(사업보고서) 11011": "11011",
        "반기보고서 11012": "11012",
        "3분기보고서 11013": "11013",
        "분기보고서 11014": "11014",
    }
    default_code = "11014" if sel_year == END_DATE.year else "11011"
    default_idx = list(reprt_map.values()).index(default_code)
    sel_label = st.selectbox("보고서 종류", options=list(reprt_map.keys()), index=default_idx)
    sel_code = reprt_map[sel_label]

    # 연결/별도 선택
    st.subheader("연결/별도 선택")
    fs_mode_label = st.selectbox(
        "연결 기준",
        options=["AUTO: CFS→OFS (권장)", "AUTO: OFS→CFS", "연결만(CFS)", "별도만(OFS)"],
        index=0,
        help="데이터가 없을 때 지정한 순서로 대체 조회합니다.",
    )
    fs_mode = {
        "AUTO: CFS→OFS (권장)": "AUTO_CFS_OFS",
        "AUTO: OFS→CFS": "AUTO_OFS_CFS",
        "연결만(CFS)": "CFS_ONLY",
        "별도만(OFS)": "OFS_ONLY",
    }[fs_mode_label]

    # 조회 버튼: 눌렀을 때만 네트워크 호출
    st.write("---")
    colA, colB = st.columns([1, 1])
    with colA:
        fetch = st.button("📥 데이터 불러오기 / 갱신", use_container_width=True)
    with colB:
        st.caption("아래 선택(체크/멀티셀렉트) 변경은 네트워크 재조회 없이 즉시 차트로 반영됩니다.")
    if fetch or "STOCK_DF" not in st.session_state:
        stock_df, fs_data = load_data_once_by_button(target_name, ticker, sel_year, sel_code, fs_mode)
    else:
        stock_df = st.session_state.get("STOCK_DF", pd.DataFrame())
        fs_data = st.session_state.get("FS_DATA", {})

    st.write("---")

    # 주가 JSON & 선택 항목
    stock_chart_data = {}
    stock_numeric_cols = []
    if not stock_df.empty and "Date" in stock_df.columns:
        for col in stock_df.columns:
            if col != "Date" and pd.api.types.is_numeric_dtype(stock_df[col]):
                stock_numeric_cols.append(col)
                stock_chart_data[col] = {str(d.date()): (None if pd.isna(v) else float(v))
                                         for d, v in zip(stock_df["Date"], stock_df[col])}

    # 재무 JSON & 전체 항목
    valid_fs = {y: df for y, df in fs_data.items()
                if isinstance(df, pd.DataFrame) and not df.empty and {"account_nm", "thstrm_amount"}.issubset(df.columns)}

    fs_chart_data, fs_all_metrics = {}, []
    if valid_fs:
        metrics = set()
        for df in valid_fs.values():
            metrics.update(df["account_nm"].dropna().astype(str).str.strip().tolist())
        fs_all_metrics = sorted([m for m in metrics if m])

        def to_trillion(x):
            try:
                s = str(x).replace(",", "").strip()
                if not s or s.lower() == "nan":
                    return None
                return round(float(s) / 1_0000_0000_0000, 2)
            except Exception:
                return None

        years_sorted = sorted(valid_fs.keys())
        for metric in fs_all_metrics:
            fs_chart_data[metric] = {}
            for y in years_sorted:
                ser = valid_fs[y].loc[valid_fs[y]["account_nm"] == metric, "thstrm_amount"]
                fs_chart_data[metric][y] = to_trillion(ser.iloc[0]) if len(ser) else None

    # 탭
    tab_p, tab_f, tab_d = st.tabs(["📈 주가(자유 선택)", "🏦 재무(자유 선택)", "⬇️ 리포트·다운로드"])

    with tab_p:
        if stock_numeric_cols:
            default_price_cols = ["Close", "PriceEarningsRatio", "PriceBookRatio"]
            defaults = [c for c in default_price_cols if c in stock_numeric_cols] or [stock_numeric_cols[0]]
            sel_cols = st.multiselect("표시할 주가/지표 선택", options=stock_numeric_cols, default=defaults)
            if sel_cols:
                st.line_chart(stock_df[["Date"] + sel_cols].set_index("Date"))
            else:
                st.info("표시할 항목을 선택하세요.")
        else:
            st.info("주가 데이터가 비어 있습니다.")

    with tab_f:
        if fs_all_metrics:
            preferred = ["자산총계", "부채총계", "자본총계", "매출액", "영업이익", "당기순이익"]
            defaults = [m for m in preferred if m in fs_all_metrics][:6] or fs_all_metrics[:6]
            sel_metrics = st.multiselect("표시할 재무 항목 선택 (단위: 조원)", options=fs_all_metrics, default=defaults)
            if sel_metrics:
                years = sorted(next(iter(fs_chart_data.values())).keys()) if fs_chart_data else []
                wide = pd.DataFrame(index=years)
                for m in sel_metrics:
                    wide[m] = [fs_chart_data.get(m, {}).get(y) for y in years]
                wide.index.name = "연도"
                st.line_chart(wide)
            else:
                st.info("표시할 항목을 선택하세요.")
        else:
            st.info("재무제표 데이터가 비어 있습니다.")

    with tab_d:
        excel_path = os.path.join(OUTPUT_DIR, "stock_data.xlsx")
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            if not stock_df.empty:
                stock_df.to_excel(writer, sheet_name="Stock_Data", index=False)
            for year, df in fs_data.items():
                sheet = f"FS_{year}" if str(year).isdigit() else str(year)[:28]
                try:
                    df.to_excel(writer, sheet_name=sheet, index=False)
                except Exception:
                    df.to_excel(writer, sheet_name=f"FS_{len(writer.book.sheetnames)+1}", index=False)

        html_path = create_html_report(target_name, stock_chart_data, fs_chart_data, os.path.basename(excel_path))

        st.write("**다운로드**")
        with open(excel_path, "rb") as f:
            st.download_button("엑셀 다운로드", data=f, file_name="stock_data.xlsx")
        with open(html_path, "rb") as f:
            st.download_button("HTML 리포트 다운로드", data=f, file_name="index.html")
        st.caption("리포트는 Chart.js CDN을 사용하며, 로컬/클라우드 어디서든 열 수 있습니다.")

# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if st:
        main()
    else:
        initialize()
        # 로컬 콘솔 실행용 최소 플로우
        krx_df = get_all_krx_symbols()
        target_name = TARGET_CORP_NAME_DEFAULT
        info = krx_df[krx_df["Name"] == target_name]
        if info.empty:
            print(f"{target_name}을(를) 찾을 수 없습니다.")
        else:
            ticker = info["Ticker"].iloc[0]
            corp_code = fetch_corp_code(target_name, DART_API_KEY)
            fs_data = {}
            if corp_code:
                fs_data = _get_financial_statements_impl(
                    corp_code, END_DATE.year, {END_DATE.year: "11014"}, "AUTO_CFS_OFS", DART_API_KEY
                )
            stock_df = fetch_stock_data(ticker, START_DATE_STR, END_DATE_STR)
            # 간단 저장
            excel_path = os.path.join(OUTPUT_DIR, "stock_data.xlsx")
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                if not stock_df.empty:
                    stock_df.to_excel(writer, sheet_name="Stock_Data", index=False)
                for year, df in fs_data.items():
                    (df if isinstance(df, pd.DataFrame) else pd.DataFrame()).to_excel(
                        writer, sheet_name=f"FS_{year}", index=False
                    )
            print("완료:", excel_path)
