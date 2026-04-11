from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import requests
import io
import zipfile
import xml.etree.ElementTree as ET
import pandas as pd

load_dotenv()

# ==========================================
# 1. 전역 상태 및 캐시 변수
# ==========================================
CORP_LIST = []
CORP_BY_STOCK_CODE = {}
STARTUP_STATUS = {
    "corp_loaded": False,
    "message": "not_loaded"
}

KIWOOM_TOKEN = None
TOKEN_EXPIRES_AT = None


# ==========================================
# 2. 공통 유틸리티
# ==========================================
def clean_number(value, keep_sign: bool = False):
    """콤마/부호가 포함된 숫자 문자열을 int 또는 float로 변환"""
    if value is None:
        return None

    value = str(value).strip().replace(",", "")
    if value == "":
        return None

    if keep_sign:
        try:
            return float(value)
        except Exception:
            return value

    if value.startswith("+") or value.startswith("-"):
        value = value[1:]

    try:
        return int(value)
    except Exception:
        try:
            return float(value)
        except Exception:
            return value


def verify_api_key(x_api_key: str | None):
    if x_api_key != "my-secret-key":
        raise HTTPException(status_code=401, detail="Invalid API key")


def refresh_corp_data():
    dart_api_key = os.getenv("DART_API_KEY")
    if not dart_api_key:
        raise ValueError("DART_API_KEY가 설정되지 않았습니다.")

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": dart_api_key}

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    xml_data = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_data)

    corp_list = []
    corp_by_stock_code = {}

    for item in root.findall("list"):
        corp_name = (item.findtext("corp_name") or "").strip()
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()

        if not stock_code:
            continue

        row = {
            "corp_name": corp_name,
            "stock_code": stock_code,
            "corp_code": corp_code,
            "corp_name_clean": corp_name.lower().replace(" ", "")
        }

        corp_list.append(row)
        corp_by_stock_code[stock_code] = row

    return corp_list, corp_by_stock_code


def ensure_corp_data_loaded():
    global CORP_LIST, CORP_BY_STOCK_CODE, STARTUP_STATUS

    if CORP_LIST and CORP_BY_STOCK_CODE:
        return

    try:
        corp_list, corp_by_stock_code = refresh_corp_data()
        CORP_LIST = corp_list
        CORP_BY_STOCK_CODE = corp_by_stock_code
        STARTUP_STATUS = {
            "corp_loaded": True,
            "message": f"corp data loaded lazily: {len(CORP_LIST)}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"고유번호 로드 실패: {str(e)}")


def get_kiwoom_token():
    """키움 토큰 발급 또는 재사용"""
    global KIWOOM_TOKEN, TOKEN_EXPIRES_AT

    now = datetime.now()
    if KIWOOM_TOKEN and TOKEN_EXPIRES_AT and now < TOKEN_EXPIRES_AT:
        return KIWOOM_TOKEN

    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")

    if not app_key or not secret_key:
        raise HTTPException(
            status_code=500,
            detail="KIWOOM_APP_KEY 또는 KIWOOM_SECRET_KEY가 설정되지 않았습니다."
        )

    url = "https://api.kiwoom.com/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("token")
        if not token:
            raise HTTPException(status_code=500, detail=f"키움 토큰 발급 실패: {data}")

        KIWOOM_TOKEN = token
        TOKEN_EXPIRES_AT = now + timedelta(hours=12)
        return KIWOOM_TOKEN
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"키움 API 토큰 발급 실패: {str(e)}")


# ==========================================
# 3. FastAPI 설정
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global CORP_LIST, CORP_BY_STOCK_CODE, STARTUP_STATUS

    try:
        corp_list, corp_by_stock_code = refresh_corp_data()
        CORP_LIST = corp_list
        CORP_BY_STOCK_CODE = corp_by_stock_code
        STARTUP_STATUS = {
            "corp_loaded": True,
            "message": f"corp data loaded: {len(CORP_LIST)}"
        }
    except Exception as e:
        CORP_LIST = []
        CORP_BY_STOCK_CODE = {}
        STARTUP_STATUS = {
            "corp_loaded": False,
            "message": f"startup corp load failed: {str(e)}"
        }

    yield


app = FastAPI(title="Stock GPT Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# 4. 기본 엔드포인트
# ==========================================
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "서버 정상 작동 중",
        "startup": STARTUP_STATUS,
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "startup": STARTUP_STATUS,
        "corp_list_count": len(CORP_LIST),
        "env": {
            "DART_API_KEY": bool(os.getenv("DART_API_KEY")),
            "KIWOOM_APP_KEY": bool(os.getenv("KIWOOM_APP_KEY")),
            "KIWOOM_SECRET_KEY": bool(os.getenv("KIWOOM_SECRET_KEY")),
        },
    }


@app.post("/resolve-stock")
def resolve_stock(query: str, x_api_key: str | None = Header(default=None)):
    verify_api_key(x_api_key)

    if query in ["한미반도체", "042700"]:
        return {
            "stock_code": "042700",
            "company_name": "한미반도체",
            "market": "KOSPI",
            "status": "ok",
        }

    return {"status": "not_found", "query": query}


# ==========================================
# 5. 개별 점검용 엔드포인트
# ==========================================
@app.get("/dart-financial-simple")
def dart_financial_simple(corp_code: str):
    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DART_API_KEY가 설정되지 않았습니다.")

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": "2024",
        "reprt_code": "11011",
        "fs_div": "CFS",
    }

    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        raise HTTPException(status_code=500, detail="DART 서버 응답 실패")

    result = {
        "status": data.get("status"),
        "corp_code": corp_code,
        "매출액": None,
        "영업이익": None,
        "당기순이익": None,
    }

    if data.get("status") != "000":
        return result

    for item in data.get("list", []):
        name = item.get("account_nm")
        if name in ["매출액", "수익(매출액)", "영업수익", "매출", "Revenue"]:
            result["매출액"] = item.get("thstrm_amount")
        elif "영업이익" in str(name):
            result["영업이익"] = item.get("thstrm_amount")
        elif "당기순이익" in str(name):
            result["당기순이익"] = item.get("thstrm_amount")

    return result


@app.get("/analysis-fundamental")
def analysis_fundamental(corp_code: str):
    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DART_API_KEY가 설정되지 않았습니다.")

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": "2024",
        "reprt_code": "11011",
        "fs_div": "CFS",
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    sales = op = net = None

    for item in data.get("list", []):
        name = item.get("account_nm")
        if name in ["매출액", "수익(매출액)", "영업수익", "매출"]:
            sales = int(item.get("thstrm_amount") or 0)
        elif "영업이익" in str(name):
            op = int(item.get("thstrm_amount") or 0)
        elif "당기순이익" in str(name):
            net = int(item.get("thstrm_amount") or 0)

    result = "부적격"
    reason = []

    if sales and sales != 0 and op is not None and net is not None:
        margin = op / sales
        if op > 0:
            reason.append("영업이익 흑자")
        if net > 0:
            reason.append("순이익 흑자")
        if margin > 0.15:
            reason.append("고수익 구조")

        if len(reason) >= 3:
            result = "적격"
        elif len(reason) == 2:
            result = "조건부"

    return {
        "status": "ok",
        "판정": result,
        "근거": reason,
        "매출액": sales,
        "영업이익": op,
        "순이익": net,
        "영업이익률": round(op / sales, 2) if sales and sales != 0 else None,
    }


@app.get("/kiwoom-price-simple")
def kiwoom_price_simple(stock_code: str):
    app_key = os.getenv("KIWOOM_APP_KEY")
    if not app_key:
        raise HTTPException(status_code=500, detail="KIWOOM_APP_KEY가 설정되지 않았습니다.")

    access_token = get_kiwoom_token()
    price_url = "https://api.kiwoom.com/api/dostk/stkinfo"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10001",
    }
    body = {"stk_cd": stock_code}

    try:
        response = requests.post(price_url, headers=headers, json=body, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        raise HTTPException(status_code=500, detail="키움 API 통신 실패")

    return {
        "status": "ok",
        "종목코드": data.get("stk_cd"),
        "종목명": data.get("stk_nm"),
        "현재가": clean_number(data.get("cur_prc")),
        "250일최고가": clean_number(data.get("250hgst")),
        "250일최저가": clean_number(data.get("250lwst")),
        "매출액": clean_number(data.get("sale_amt")),
        "영업이익": clean_number(data.get("bus_pro")),
        "당기순이익": clean_number(data.get("cup_nga")),
        "PER": clean_number(data.get("per"), keep_sign=True),
        "PBR": clean_number(data.get("pbr"), keep_sign=True),
        "거래량": clean_number(data.get("trde_qty")),
        "등락률": clean_number(data.get("flu_rt"), keep_sign=True),
    }


@app.get("/kiwoom-ma-test")
def kiwoom_ma_test(stock_code: str):
    app_key = os.getenv("KIWOOM_APP_KEY")
    if not app_key:
        raise HTTPException(status_code=500, detail="KIWOOM_APP_KEY가 설정되지 않았습니다.")

    access_token = get_kiwoom_token()

    chart_url = "https://api.kiwoom.com/api/dostk/chart"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10081",
    }
    body = {
        "stk_cd": stock_code,
        "base_dt": datetime.now().strftime("%Y%m%d"),
        "upd_stkpc_tp": "1",
    }

    try:
        response = requests.post(chart_url, headers=headers, json=body, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        raise HTTPException(status_code=500, detail="키움 차트 API 통신 실패")

    rows = data.get("stk_dt_pole_chart_qry", [])
    if not rows:
        return {"status": "error", "message": "일봉 데이터가 비어 있습니다.", "raw": data}

    closes = [
        clean_number(row.get("cur_prc"))
        for row in rows
        if clean_number(row.get("cur_prc")) is not None
    ]

    if len(closes) < 20:
        return {"status": "error", "message": "이평선 계산 불가(데이터 20개 미만)"}

    df = pd.DataFrame({"close": closes})
    ma20 = round(df["close"].head(20).mean(), 2) if len(df) >= 20 else None
    ma60 = round(df["close"].head(60).mean(), 2) if len(df) >= 60 else None
    ma150 = round(df["close"].head(150).mean(), 2) if len(df) >= 150 else None
    ma200 = round(df["close"].head(200).mean(), 2) if len(df) >= 200 else None

    return {
        "status": "ok",
        "stock_code": stock_code,
        "일봉개수": len(closes),
        "최근5개종가": closes[:5],
        "ma20": ma20,
        "ma60": ma60,
        "ma150": ma150,
        "ma200": ma200,
    }


# ==========================================
# 6. 메인 분석 로직
# ==========================================
def _run_stock_analysis_internal(query: str):
    app_key = os.getenv("KIWOOM_APP_KEY")
    dart_api_key = os.getenv("DART_API_KEY")

    ensure_corp_data_loaded()

    if not query or not str(query).strip():
        return {"status": "error", "message": "query 값이 비어 있습니다."}

    if not dart_api_key:
        return {"status": "error", "message": "DART_API_KEY 설정 안됨"}

    if not app_key:
        return {"status": "error", "message": "KIWOOM_APP_KEY 설정 안됨"}

    # 1) 종목 검색
    query_clean = query.strip().lower().replace(" ", "")
    stock_code = query if query.isdigit() else None
    corp_code = None
    found_name = None

    exact_match = None
    partial_matches = []

    for row in CORP_LIST:
        if stock_code and row["stock_code"] == stock_code:
            corp_code = row["corp_code"]
            found_name = row["corp_name"]
            break

        if not stock_code:
            if query_clean == row["corp_name_clean"]:
                exact_match = row
                break
            if query_clean in row["corp_name_clean"]:
                partial_matches.append(row)

    if not stock_code:
        if exact_match:
            stock_code = exact_match["stock_code"]
            corp_code = exact_match["corp_code"]
            found_name = exact_match["corp_name"]
        elif len(partial_matches) == 1:
            stock_code = partial_matches[0]["stock_code"]
            corp_code = partial_matches[0]["corp_code"]
            found_name = partial_matches[0]["corp_name"]
        elif len(partial_matches) > 1:
            return {
                "status": "multiple",
                "message": "유사 종목명 검색됨",
                "matches": [
                    {
                        "종목명": x["corp_name"],
                        "stock_code": x["stock_code"],
                        "corp_code": x["corp_code"],
                    }
                    for x in partial_matches[:5]
                ],
            }
        else:
            return {"status": "error", "message": f"종목 검색 실패: {query}"}

    if not corp_code and stock_code in CORP_BY_STOCK_CODE:
        corp_code = CORP_BY_STOCK_CODE[stock_code]["corp_code"]
        found_name = CORP_BY_STOCK_CODE[stock_code]["corp_name"]

    if not stock_code or not corp_code:
        return {"status": "error", "message": "종목코드 식별 불가"}

    # 2) DART 재무 분석
    sales = op = net = margin = None
    reasons = []
    fundamental_ok = False

    try:
        dart_response = requests.get(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": dart_api_key,
                "corp_code": corp_code,
                "bsns_year": "2024",
                "reprt_code": "11011",
                "fs_div": "CFS",
            },
            timeout=20,
        )
        dart_response.raise_for_status()
        dart_data = dart_response.json()

        for item in dart_data.get("list", []):
            name = (item.get("account_nm") or "").strip()
            amount = int(item.get("thstrm_amount") or 0)

            if sales is None and name in ["매출액", "수익(매출액)", "영업수익", "매출", "Revenue"]:
                sales = amount
            elif op is None and ("영업이익" in name or name in ["영업이익(손실)", "영업손익"]):
                op = amount
            elif net is None and (
                "당기순이익" in name
                or "연결당기순이익" in name
                or "지배기업 소유주지분 순이익" in name
                or "계속영업당기순이익" in name
                or name in ["당기순이익(손실)", "분기순이익", "반기순이익", "연결순이익"]
                or "순이익" in name
            ):
                net = amount

        if sales and sales != 0 and op is not None and net is not None:
            margin = float(op / sales)
            if op > 0:
                reasons.append("영업이익 흑자")
            if net > 0:
                reasons.append("순이익 흑자")
            if margin > 0.15:
                reasons.append("고수익 구조")
            if len(reasons) >= 2:
                fundamental_ok = True

    except Exception as e:
        return {"status": "error", "message": f"재무 데이터 로드 에러: {str(e)}"}

    # 3) 키움 데이터 분석
    try:
        access_token = get_kiwoom_token()
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "api-id": "ka10001",
        }

        price_response = requests.post(
            "https://api.kiwoom.com/api/dostk/stkinfo",
            headers=headers,
            json={"stk_cd": stock_code},
            timeout=20,
        )
        price_response.raise_for_status()
        price = price_response.json()

        current_price = clean_number(price.get("cur_prc"))
        high_250 = clean_number(price.get("250hgst"))
        volume_today = clean_number(price.get("trde_qty"))

        chart_headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "api-id": "ka10081",
        }

        chart_response = requests.post(
            "https://api.kiwoom.com/api/dostk/chart",
            headers=chart_headers,
            json={
                "stk_cd": stock_code,
                "base_dt": datetime.now().strftime("%Y%m%d"),
                "upd_stkpc_tp": "1",
            },
            timeout=20,
        )
        chart_response.raise_for_status()
        chart = chart_response.json()

        closes = [
            clean_number(x.get("cur_prc"))
            for x in chart.get("stk_dt_pole_chart_qry", [])
            if clean_number(x.get("cur_prc")) is not None
        ]
        volumes = [
            clean_number(x.get("trde_qty"))
            for x in chart.get("stk_dt_pole_chart_qry", [])
            if clean_number(x.get("trde_qty")) is not None
        ]

    except Exception as e:
        return {"status": "error", "message": f"키움 통신 에러: {str(e)}"}

    if len(closes) < 200:
        return {"status": "error", "message": "데이터 부족 (최소 200거래일 필요)"}

    if len(volumes) < 20:
        return {"status": "error", "message": "거래량 데이터 부족 (최소 20거래일 필요)"}

    # 4) 지표 계산
    breakout_ratio = float(current_price / high_250) if current_price and high_250 and high_250 != 0 else 0

    df_price = pd.DataFrame({"c": closes})
    df_vol = pd.DataFrame({"v": volumes})

    ma20 = float(df_price["c"].head(20).mean())
    ma60 = float(df_price["c"].head(60).mean())
    ma150 = float(df_price["c"].head(150).mean())
    ma200 = float(df_price["c"].head(200).mean())
    vol_avg20 = float(df_vol["v"].head(20).mean())

    volume_up = bool(volume_today and vol_avg20 and volume_today > vol_avg20)
    chart_ok = bool(
        current_price
        and current_price > ma150
        and current_price > ma200
        and ma150 > ma200
        and ma20 > ma60
    )
    overheat = bool(current_price and current_price > ma20 * 1.10)
    pullback = bool(current_price and ma20 * 0.97 <= current_price <= ma20 * 1.03)
    trend_break = bool(current_price and current_price < ma60)

    # 5) 최종 판정
    final = "관망"
    action = "대기"

    if trend_break:
        final = "추세훼손 주의"
        action = "60일선 이탈, 신규 진입 보류"
    elif chart_ok and fundamental_ok:
        if overheat:
            final = "단기 과열"
            action = "매수 금지 (조정 대기)"
        elif pullback:
            final = "매수 타점"
            action = "20일선 눌림목 매수 접근"
        else:
            final = "상승 추세"
            action = "보유자 영역"
    elif fundamental_ok and breakout_ratio > 0.90:
        final = "신고가 준비"
        action = "돌파 여부 관찰"

    return {
        "status": "ok",
        "종목명": found_name,
        "종목코드": stock_code,
        "분석결과": {
            "최종판단": final,
            "대응전략": action,
        },
        "재무": {
            "판정": "적격" if fundamental_ok else "부적격",
            "매출액": sales,
            "영업이익": op,
            "당기순이익": net,
            "영업이익률": f"{round(margin * 100, 1)}%" if margin is not None else "계산불가",
            "근거": reasons,
        },
        "차트": {
            "현재가": current_price,
            "250일최고가": high_250,
            "신고가대비비율": f"{round(breakout_ratio * 100, 1)}%",
            "차트추세": "정배열/우상향" if chart_ok else "역배열/혼조",
            "과열여부": overheat,
            "20일선눌림": pullback,
            "거래량증가": volume_up,
            "이평선": {
                "ma20": round(ma20, 0),
                "ma60": round(ma60, 0),
                "ma150": round(ma150, 0),
                "ma200": round(ma200, 0),
            },
        },
    }


@app.get("/run-stock-analysis")
def run_stock_analysis(query: str):
    return _run_stock_analysis_internal(query)


# 추천안 1 핵심: 기존 연결 경로 유지용 alias
@app.get("/analyze-stock")
def analyze_stock(query: str):
    return _run_stock_analysis_internal(query)
