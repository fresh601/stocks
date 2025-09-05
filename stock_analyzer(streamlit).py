# -*- coding: utf-8 -*-
"""
Streamlit 클라우드 대응:
- DART_API_KEY: 환경변수 또는 st.secrets 양쪽 지원
- 회사명 검색 UI: 입력/선택 지원 (기본: 삼성전자)
- 기존 구조 유지: initialize → get_corp_code → get_financial_statements → get_stock_data → create_html_report → main
- HTML 리포트(Chart.js) 파일 생성 + Streamlit 내 차트도 즉시 표시
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

# ─────────────────────────────────────────────────────────────
# Streamlit 환경 로더 (Secrets + 경고 배너)
# ─────────────────────────────────────────────────────────────
try:
    import streamlit as st
except Exception:
    st = None

def get_secret(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if (not v) and st is not None:
        try:
            v = st.secrets.get(name, default)
        except Exception:
            v = default
    return str(v).strip() if v is not None else default

def ping_dart_key_once(api_key: str) -> bool:
    if not api_key:
        msg = "DART_API_KEY가 설정되어 있지 않습니다. (Streamlit Cloud → App → Settings → Secrets)"
        if st:
            st.warning(msg)
        else:
            print(msg)
        return False
    try:
        r = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": api_key},
            timeout=10,
        )
        # ⚠️ Content-Type을 믿지 말고 바로 ZIP 시도
        content = r.content or b""
        # 1) 빠른 시그니처 체크 (선택)
        if not content.startswith(b"PK\x03\x04"):
            # 일부 서버는 앞에 공백/바이트가 섞일 수도 있으니 곧바로 ZipFile 시도
            pass
        # 2) 실제 ZipFile로 열어보며 최종 판정
        import io, zipfile
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            # 파일 목록에 CORPCODE.xml이 있으면 정상
            if "CORPCODE.xml" in zf.namelist():
                if st:
                    st.success("DART 키 연결 정상 ✅")
                else:
                    print("DART 키 연결 정상")
                return True
            else:
                if st:
                    st.error("DART corpCode ZIP은 받았지만 CORPCODE.xml이 없습니다.")
                else:
                    print("DART corpCode ZIP은 받았지만 CORPCODE.xml이 없습니다.")
                return False
    except zipfile.BadZipFile:
        # 진짜로 ZIP이 아니면 여기서 잡힘
        snippet = (r.text or "")[:160]
        if st:
            st.error(f"[DART] corpCode 응답이 ZIP이 아닙니다. 응답: {snippet}")
        else:
            print(f"[DART] corpCode 응답이 ZIP이 아닙니다. 응답: {snippet}")
        return False
    except Exception as e:
        if st:
            st.error(f"[DART] 접속/파싱 실패: {e}")
        else:
            print(f"[DART] 접속/파싱 실패: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────
TARGET_CORP_NAME_DEFAULT = "삼성전자"
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=3 * 365)
END_DATE_STR = END_DATE.strftime("%Y%m%d")
START_DATE_STR = START_DATE.strftime("%Y%m%d")
OUTPUT_DIR = "output"

DART_API_KEY = get_secret("DART_API_KEY")
# 스트림릿이면 시작 시 한번 점검(강추)
ping_dart_key_once(DART_API_KEY)

# ─────────────────────────────────────────────────────────────
# 유틸/초기화
# ─────────────────────────────────────────────────────────────
def initialize():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

@st.cache_data(show_spinner=False)
def get_all_krx_symbols():
    # 전체 티커/이름 목록 캐시
    tickers = stock.get_market_ticker_list(market="ALL")
    df = pd.DataFrame({"Ticker": tickers})
    df["Name"] = df["Ticker"].apply(lambda x: stock.get_market_ticker_name(x))
    return df

# ─────────────────────────────────────────────────────────────
# DART: 기업코드/재무
# ─────────────────────────────────────────────────────────────
def get_corp_code(corp_name: str):
    if not DART_API_KEY:
        return None
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    try:
        r = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=10)
    except Exception as e:
        if st: st.info(f"corpCode.xml 요청 실패: {e}")
        return None

    # 메모리상에서 ZIP 처리
    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        xml_bytes = zf.read("CORPCODE.xml")
    except Exception:
        if st: st.info("corpCode.zip 해제 실패 또는 응답이 ZIP 아님 (키/호출 오류 가능)")
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        if st: st.info(f"CORPCODE.xml 파싱 실패: {e}")
        return None

    for node in root.findall("list"):
        nm = (node.findtext("corp_name", "") or "").strip()
        if nm == corp_name:
            return (node.findtext("corp_code", "") or "").strip()
    return None

def get_financial_statements(corp_code: str):
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
                "reprt_code": "11011",  # 사업보고서(연간)
                "fs_div": fs_div,
            }
            try:
                res = requests.get(
                    "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                    params=params,
                    timeout=10,
                ).json()
            except Exception as e:
                if st: st.info(f"{year}년 {fs_div} 요청 실패: {e}")
                continue

            if res.get("status") != "000":
                if st: st.info(f"[DART] {year} {fs_div} status={res.get('status')} message={res.get('message')}")
                continue

            if "list" in res and isinstance(res["list"], list) and len(res["list"]) > 0:
                df = pd.DataFrame(res["list"])
                keep_cols = ["account_nm", "thstrm_amount"]
                cols = [c for c in keep_cols if c in df.columns]
                if not cols:
                    continue
                df = df[cols].copy()
                df["account_nm"] = df["account_nm"].astype(str).str.strip()
                df["thstrm_amount"] = df["thstrm_amount"].astype(str).str.replace(",", "").str.strip()
                fs_data[str(year)] = df
                found_data = True
                break
        if not found_data:
            fs_data[str(year)] = pd.DataFrame({"account_nm": [], "thstrm_amount": []})
    return fs_data

# ─────────────────────────────────────────────────────────────
# KRX: 주가/기초지표
# ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def get_stock_data(ticker: str):
    try:
        ohlcv = stock.get_market_ohlcv_by_date(START_DATE_STR, END_DATE_STR, ticker)
        fundamental = stock.get_market_fundamental_by_date(START_DATE_STR, END_DATE_STR, ticker)
        df = pd.concat([ohlcv, fundamental], axis=1)
        df.reset_index(inplace=True)
        df.rename(
            columns={
                "날짜": "Date",
                "시가": "Open",
                "고가": "High",
                "저가": "Low",
                "종가": "Close",
                "거래량": "Volume",
                "DIV": "DividendYield",
                "BPS": "BookValuePerShare",
                "PER": "PriceEarningsRatio",
                "PBR": "PriceBookRatio",
            },
            inplace=True,
        )
        return df
    except Exception as e:
        if st: st.info(f"주가 정보를 가져오는 중 오류: {e}")
        return pd.DataFrame()

# ─────────────────────────────────────────────────────────────
# HTML 리포트 (Chart.js) 파일 생성
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
    const stockWrap = document.getElementById('stockSec');
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
# 메인 (Streamlit UI)
# ─────────────────────────────────────────────────────────────
def main():
    initialize()

    st.title("📊 KRX 주가 & DART 재무 리포트")
    st.caption("회사명으로 검색하고, 주가/재무 차트를 즉시 확인하세요. HTML 리포트와 엑셀 다운로드를 함께 제공합니다.")

    # 회사 선택 UI
    krx_df = get_all_krx_symbols()
    col1, col2 = st.columns([1, 2])
    with col1:
        default_name = TARGET_CORP_NAME_DEFAULT
        name_input = st.text_input("회사명 검색", value=default_name, help="예: 삼성전자, SK하이닉스, 현대차 ...")
    with col2:
        # 부분일치 추천
        candidates = krx_df[krx_df["Name"].str.contains(name_input.strip(), na=False)]
        picked = st.selectbox(
            "검색 결과에서 선택",
            options=candidates["Name"].tolist() if not candidates.empty else [name_input],
            index=0,
        )
    target_name = picked.strip()

    # 티커 매핑
    target_info = krx_df[krx_df["Name"] == target_name]
    if target_info.empty:
        st.error(f"'{target_name}' 을(를) KRX에서 찾을 수 없습니다.")
        return
    ticker = target_info["Ticker"].iloc[0]
    st.write(f"**선택된 종목:** {target_name} ({ticker})")

    # DART 기업코드 & 재무
    corp_code = get_corp_code(target_name)
    if not corp_code:
        st.info("DART 기업코드를 찾지 못했습니다. (키 미설정/호출 제한/미등록 기업 등)")
    fs_data = get_financial_statements(corp_code) if corp_code else {"재무제표": pd.DataFrame({"메시지": ["데이터 없음"]})}

    # 주가
    stock_df = get_stock_data(ticker)

    # 주가 JSON (차트용)
    stock_chart_data = {}
    if not stock_df.empty and "Date" in stock_df.columns:
        for col in stock_df.columns:
            if col != "Date" and pd.api.types.is_numeric_dtype(stock_df[col]):
                stock_chart_data[col] = {
                    str(d.date()): (None if pd.isna(v) else float(v)) for d, v in zip(stock_df["Date"], stock_df[col])
                }

    # 재무 유효본만 골라서 JSON
    valid_fs = {}
    for year, df in fs_data.items():
        if isinstance(df, pd.DataFrame) and not df.empty and {"account_nm", "thstrm_amount"}.issubset(df.columns):
            valid_fs[year] = df.copy()

    fs_chart_data = {}
    if valid_fs:
        metrics = set()
        for df in valid_fs.values():
            names = df["account_nm"].dropna().astype(str).str.strip()
            metrics.update([n for n in names if n])

        def to_trillion(x):
            try:
                s = str(x).replace(",", "").strip()
                if not s or s.lower() == "nan":
                    return None
                v = float(s) / 1_0000_0000_0000  # 원 → 조원
                return round(v, 2)
            except Exception:
                return None

        years_sorted = sorted(valid_fs.keys())
        for metric in sorted(metrics):
            fs_chart_data[metric] = {}
            for y in years_sorted:
                ser = valid_fs[y].loc[valid_fs[y]["account_nm"] == metric, "thstrm_amount"]
                val = to_trillion(ser.iloc[0]) if len(ser) else None
                fs_chart_data[metric][y] = val

    # 화면용 간단 차트(스트림릿) — 주가 종가 & PER 등
    st.subheader("📈 주가(종가) 추이")
    if not stock_df.empty:
        show_cols = ["Date", "Close"]
        st.line_chart(stock_df[show_cols].set_index("Date"))
    else:
        st.info("주가 데이터가 비어 있습니다.")

    st.subheader("🏦 재무제표(핵심 지표 미리보기)")
    if fs_chart_data:
        # 대표 지표 후보
        preferred = ["자산총계", "부채총계", "자본총계", "매출액", "영업이익", "당기순이익"]
        picks = [m for m in preferred if m in fs_chart_data][:6] or list(fs_chart_data.keys())[:6]
        if picks:
            # 가로로 2열 미리보기
            cols = st.columns(2)
            for i, metric in enumerate(picks):
                ys = list(fs_chart_data[metric].keys())
                vs = list(fs_chart_data[metric].values())
                small_df = pd.DataFrame({"연도": ys, metric: vs}).set_index("연도")
                with cols[i % 2]:
                    st.write(f"**{metric}** (단위: 조원)")
                    st.line_chart(small_df)
        else:
            st.info("표시할 핵심 지표가 없습니다.")
    else:
        st.info("재무제표 데이터가 비어 있습니다.")

    # 엑셀 저장(원본 유지)
    excel_path = os.path.join(OUTPUT_DIR, "stock_data.xlsx")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        if not stock_df.empty:
            stock_df.to_excel(writer, sheet_name="Stock_Data", index=False)
        for year, df in fs_data.items():
            sheet_name = f"FS_{year}" if str(year).isdigit() else str(year)[:28]
            try:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            except Exception:
                # 엑셀 시트명 충돌 방지
                safe_name = f"FS_{len(writer.book.sheetnames)+1}"
                df.to_excel(writer, sheet_name=safe_name, index=False)

    # HTML 리포트 생성 (Chart.js)
    html_path = create_html_report(target_name, stock_chart_data, fs_chart_data, os.path.basename(excel_path))

    # 다운로드 섹션
    st.subheader("⬇️ 다운로드")
    with open(excel_path, "rb") as f:
        st.download_button("엑셀 다운로드", data=f, file_name="stock_data.xlsx")
    with open(html_path, "rb") as f:
        st.download_button("HTML 리포트 다운로드", data=f, file_name="index.html")

    st.caption("⚙️ 리포트는 로컬/클라우드 어디서든 열 수 있도록 self-contained(Chart.js CDN)로 생성됩니다.")

# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if st:
        main()
    else:
        # Streamlit 없이도 로컬에서 최소 동작(기본 회사 저장/리포트 생성)
        initialize()
        krx_df = get_all_krx_symbols()
        target_name = TARGET_CORP_NAME_DEFAULT
        info = krx_df[krx_df["Name"] == target_name]
        if info.empty:
            print(f"{target_name}을(를) 찾을 수 없습니다.")
        else:
            ticker = info["Ticker"].iloc[0]
            corp_code = get_corp_code(target_name)
            fs_data = get_financial_statements(corp_code) if corp_code else {"재무제표": pd.DataFrame({"메시지": ["데이터 없음"]})}
            stock_df = get_stock_data(ticker)
            stock_chart_data = {}
            if not stock_df.empty and "Date" in stock_df.columns:
                for col in stock_df.columns:
                    if col != "Date" and pd.api.types.is_numeric_dtype(stock_df[col]):
                        stock_chart_data[col] = {
                            str(d.date()): (None if pd.isna(v) else float(v)) for d, v in zip(stock_df["Date"], stock_df[col])
                        }
            valid_fs = {y: df for y, df in fs_data.items() if isinstance(df, pd.DataFrame) and not df.empty and {"account_nm","thstrm_amount"}.issubset(df.columns)}
            fs_chart_data = {}
            if valid_fs:
                metrics = set()
                for df in valid_fs.values():
                    metrics.update(df["account_nm"].dropna().astype(str).str.strip().tolist())
                def to_trillion(x):
                    try:
                        s = str(x).replace(",", "").strip()
                        if not s or s.lower() == "nan":
                            return None
                        return round(float(s) / 1_0000_0000_0000, 2)
                    except:
                        return None
                years_sorted = sorted(valid_fs.keys())
                for m in sorted(metrics):
                    fs_chart_data[m] = {}
                    for y in years_sorted:
                        ser = valid_fs[y].loc[valid_fs[y]["account_nm"] == m, "thstrm_amount"]
                        fs_chart_data[m][y] = to_trillion(ser.iloc[0]) if len(ser) else None

            excel_path = os.path.join(OUTPUT_DIR, "stock_data.xlsx")
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                if not stock_df.empty:
                    stock_df.to_excel(writer, sheet_name="Stock_Data", index=False)
                for year, df in fs_data.items():
                    sheet_name = f"FS_{year}" if str(year).isdigit() else str(year)[:28]
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            html_path = create_html_report(target_name, stock_chart_data, fs_chart_data, os.path.basename(excel_path))
            print("리포트 생성 완료:", html_path)

