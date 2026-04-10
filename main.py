from stock_map import STOCK_MAP
from fastapi import FastAPI, Header, HTTPException
from dotenv import load_dotenv
import os
import requests
import io
import zipfile
import xml.etree.ElementTree as ET

load_dotenv()

app = FastAPI(title="Stock GPT Server")

CORP_LIST = []
CORP_BY_STOCK_CODE = {}

@app.on_event("startup")
def load_corp_data():
    global CORP_LIST, CORP_BY_STOCK_CODE

    dart_api_key = os.getenv("DART_API_KEY")
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

    CORP_LIST = corp_list
    CORP_BY_STOCK_CODE = corp_by_stock_code

def verify_api_key(x_api_key: str | None):
    if x_api_key != "my-secret-key":
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "서버 정상 작동 중"
    }

@app.post("/resolve-stock")
def resolve_stock(
    query: str,
    x_api_key: str | None = Header(default=None)
):
    verify_api_key(x_api_key)

    if query in ["한미반도체", "042700"]:
        return {
            "stock_code": "042700",
            "company_name": "한미반도체",
            "market": "KOSPI",
            "status": "ok"
        }

    return {
        "status": "not_found",
        "query": query
    }

@app.get("/dart-test")
def dart_test():
    api_key = os.getenv("DART_API_KEY")

    url = "https://opendart.fss.or.kr/api/company.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": "00126380"
    }

    response = requests.get(url, params=params, timeout=20)
    return response.json()

@app.get("/dart-find-corp")
def dart_find_corp(stock_code: str):
    api_key = os.getenv("DART_API_KEY")

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {
        "crtfc_key": api_key
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    xml_name = zf.namelist()[0]
    xml_data = zf.read(xml_name)

    root = ET.fromstring(xml_data)

    for item in root.findall("list"):
        current_stock_code = (item.findtext("stock_code") or "").strip()
        if current_stock_code == stock_code:
            return {
                "status": "ok",
                "stock_code": stock_code,
                "corp_code": (item.findtext("corp_code") or "").strip(),
                "corp_name": (item.findtext("corp_name") or "").strip()
            }

    return {
        "status": "not_found",
        "stock_code": stock_code
    }

@app.get("/dart-company")
def dart_company(corp_code: str):
    api_key = os.getenv("DART_API_KEY")

    url = "https://opendart.fss.or.kr/api/company.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code
    }

    response = requests.get(url, params=params, timeout=20)
    return response.json()


@app.get("/dart-financial")
def dart_financial(corp_code: str, bsns_year: str = "2024", reprt_code: str = "11011"):
    api_key = os.getenv("DART_API_KEY")

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": "CFS"
    }

    response = requests.get(url, params=params, timeout=20)
    return response.json()


@app.get("/dart-financial-simple")
def dart_financial_simple(corp_code: str):
    api_key = os.getenv("DART_API_KEY")

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": "2024",
        "reprt_code": "11011",
        "fs_div": "CFS"
    }

    response = requests.get(url, params=params, timeout=20)
    data = response.json()

    result = {
        "status": data.get("status"),
        "corp_code": corp_code,
        "매출액": None,
        "영업이익": None,
        "당기순이익": None
    }

    if data.get("status") != "000":
        return result

    for item in data.get("list", []):
        name = item.get("account_nm")

        if name in ["매출액", "수익(매출액)", "영업수익", "매출", "Revenue"]:
            result["매출액"] = item.get("thstrm_amount")

        elif "영업이익" in name:
            result["영업이익"] = item.get("thstrm_amount")

        elif "당기순이익" in name:
            result["당기순이익"] = item.get("thstrm_amount")

    return result


@app.get("/analysis-fundamental")
def analysis_fundamental(corp_code: str):
    api_key = os.getenv("DART_API_KEY")

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": "2024",
        "reprt_code": "11011",
        "fs_div": "CFS"
    }

    response = requests.get(url, params=params, timeout=20)
    data = response.json()

    sales = None
    op = None
    net = None

    for item in data.get("list", []):
        name = item.get("account_nm")

        if name in ["매출액", "수익(매출액)", "영업수익", "매출"]:
            sales = int(item.get("thstrm_amount") or 0)

        elif "영업이익" in name:
            op = int(item.get("thstrm_amount") or 0)

        elif "당기순이익" in name:
            net = int(item.get("thstrm_amount") or 0)

    # 판정 로직
    result = "부적격"
    reason = []

    if sales and op and net:
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
        else:
            result = "부적격"

    return {
        "status": "ok",
        "판정": result,
        "근거": reason,
        "매출액": sales,
        "영업이익": op,
        "순이익": net,
        "영업이익률": round(op / sales, 2) if sales else None
    }


@app.get("/analysis-chart-sample")
def analysis_chart_sample(
    current_price: float,
    ma20: float,
    ma60: float,
    ma150: float,
    ma200: float,
    high_52w: float
):
    reasons = []

    # 대세 상승 구조
    major_ok = (
        current_price > ma150 and
        current_price > ma200 and
        ma150 > ma200
    )

    if major_ok:
        reasons.append("대세 상승 구조")

    # 단기 추세
    timing_ok = (
        ma20 > ma60 and
        current_price > ma20 and
        current_price > ma60
    )

    if timing_ok:
        reasons.append("단기 상승 추세")

    # 신고가
    breakout_ratio = current_price / high_52w

    if breakout_ratio >= 0.95:
        reasons.append("신고가 근접")

    # 과열 판단
    overheat = current_price > ma20 * 1.10

    if overheat:
        reasons.append("단기 과열 (20일선 대비 +10%)")

    # 최종 판정
    if major_ok and timing_ok and breakout_ratio >= 0.95:
        if overheat:
            result = "과열주의"
        else:
            result = "적격"

    elif major_ok and (timing_ok or breakout_ratio >= 0.95):
        result = "조건부"

    else:
        result = "부적격"

    return {
        "status": "ok",
        "판정": result,
        "근거": reasons,
        "과열여부": overheat,
        "신고가비율": round(breakout_ratio, 2),
        "입력값": {
            "current_price": current_price,
            "ma20": ma20,
            "ma60": ma60,
            "ma150": ma150,
            "ma200": ma200,
            "high_52w": high_52w
        }
    }


@app.get("/kiwoom-key-test")
def kiwoom_key_test():
    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")

    return {
        "app_key_exists": app_key is not None,
        "app_key_length": len(app_key) if app_key else 0,
        "app_key_preview": app_key[:6] + "..." if app_key else "NONE",
        "secret_key_exists": secret_key is not None,
        "secret_key_length": len(secret_key) if secret_key else 0,
        "secret_key_preview": secret_key[:6] + "..." if secret_key else "NONE"
    }



@app.get("/env-debug")
def env_debug():
    return {
        "cwd": os.getcwd(),
        "env_file_exists": os.path.exists(".env"),
        "files_in_folder": os.listdir(".")
    }


from dotenv import dotenv_values

@app.get("/env-key-check")
def env_key_check():
    env_values = dotenv_values(".env")

    return {
        "dart_exists_in_file": env_values.get("DART_API_KEY") is not None,
        "kiwoom_app_exists_in_file": env_values.get("KIWOOM_APP_KEY") is not None,
        "kiwoom_secret_exists_in_file": env_values.get("KIWOOM_SECRET_KEY") is not None,
        "dart_length_in_file": len(env_values.get("DART_API_KEY") or ""),
        "kiwoom_app_length_in_file": len(env_values.get("KIWOOM_APP_KEY") or ""),
        "kiwoom_secret_length_in_file": len(env_values.get("KIWOOM_SECRET_KEY") or "")
    }


@app.get("/kiwoom-token-test")
def kiwoom_token_test():
    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")

    url = "https://api.kiwoom.com/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }

    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        timeout=20
    )

    return response.json()


@app.get("/kiwoom-price-test")
def kiwoom_price_test(stock_code: str):
    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")

    # 1) 토큰 발급
    token_url = "https://api.kiwoom.com/oauth2/token"
    token_payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }

    token_response = requests.post(
        token_url,
        json=token_payload,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        timeout=20
    )
    token_data = token_response.json()
    access_token = token_data.get("token")

    # 2) 주식기본정보요청
    price_url = "https://api.kiwoom.com/api/dostk/stkinfo"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10001"
    }
    body = {
        "stk_cd": stock_code
    }

    price_response = requests.post(
        price_url,
        headers=headers,
        json=body,
        timeout=20
    )

    return price_response.json()



@app.get("/kiwoom-price-simple")
def kiwoom_price_simple(stock_code: str):
    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")

    # 숫자 정리 함수
    def clean_number(value, keep_sign=False):
        if value is None:
            return None

        value = str(value).strip().replace(",", "")
        if value == "":
            return None

        if keep_sign:
            try:
                return float(value)
            except:
                return value

        # 가격/재무/거래량 등 → 부호 제거
        if value.startswith("+") or value.startswith("-"):
            value = value[1:]

        try:
            return int(value)
        except:
            try:
                return float(value)
            except:
                return value

    # 1) 토큰 발급
    token_url = "https://api.kiwoom.com/oauth2/token"
    token_payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }

    token_response = requests.post(
        token_url,
        json=token_payload,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        timeout=20
    )
    token_data = token_response.json()
    access_token = token_data.get("token")

    # 2) 주식기본정보요청 (POST + body)
    price_url = "https://api.kiwoom.com/api/dostk/stkinfo"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10001"
    }
    body = {
        "stk_cd": stock_code
    }

    price_response = requests.post(
        price_url,
        headers=headers,
        json=body,
        timeout=20
    )
    data = price_response.json()

    return {
        "status": "ok",
        "종목코드": data.get("stk_cd"),
        "종목명": data.get("stk_nm"),

        # 가격
        "현재가": clean_number(data.get("cur_prc")),
        "250일최고가": clean_number(data.get("250hgst")),
        "250일최저가": clean_number(data.get("250lwst")),

        # 재무
        "매출액": clean_number(data.get("sale_amt")),
        "영업이익": clean_number(data.get("bus_pro")),
        "당기순이익": clean_number(data.get("cup_nga")),

        # 밸류
        "PER": clean_number(data.get("per"), keep_sign=True),
        "PBR": clean_number(data.get("pbr"), keep_sign=True),

        # 수급/흐름
        "거래량": clean_number(data.get("trde_qty")),
        "등락률": clean_number(data.get("flu_rt"), keep_sign=True)
    }




@app.get("/analysis-breakout-basic")
def analysis_breakout_basic(stock_code: str):
    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")

    def clean_number(value, keep_sign=False):
        if value is None:
            return None

        value = str(value).strip().replace(",", "")
        if value == "":
            return None

        if keep_sign:
            try:
                return float(value)
            except:
                return value

        if value.startswith("+") or value.startswith("-"):
            value = value[1:]

        try:
            return int(value)
        except:
            try:
                return float(value)
            except:
                return value

    # 1) 토큰 발급
    token_url = "https://api.kiwoom.com/oauth2/token"
    token_payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }

    token_response = requests.post(
        token_url,
        json=token_payload,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        timeout=20
    )
    token_data = token_response.json()
    access_token = token_data.get("token")

    # 2) 주식기본정보요청
    price_url = "https://api.kiwoom.com/api/dostk/stkinfo"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10001"
    }
    body = {
        "stk_cd": stock_code
    }

    price_response = requests.post(
        price_url,
        headers=headers,
        json=body,
        timeout=20
    )
    data = price_response.json()

    current_price = clean_number(data.get("cur_prc"))
    high_250 = clean_number(data.get("250hgst"))

    if not current_price or not high_250:
        return {
            "status": "error",
            "message": "현재가 또는 250일 최고가를 불러오지 못했습니다."
        }

    breakout_ratio = round(current_price / high_250, 4)

    if breakout_ratio >= 0.95:
        result = "신고가 근접"
    elif breakout_ratio >= 0.85:
        result = "추적 관찰"
    else:
        result = "아직 멀다"

    return {
        "status": "ok",
        "종목코드": data.get("stk_cd"),
        "종목명": data.get("stk_nm"),
        "현재가": current_price,
        "250일최고가": high_250,
        "신고가비율": breakout_ratio,
        "판정": result
    }




@app.get("/analysis-stage1")
def analysis_stage1(stock_code: str, corp_code: str):
    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")
    dart_api_key = os.getenv("DART_API_KEY")

    def clean_number(value, keep_sign=False):
        if value is None:
            return None

        value = str(value).strip().replace(",", "")
        if value == "":
            return None

        if keep_sign:
            try:
                return float(value)
            except:
                return value

        if value.startswith("+") or value.startswith("-"):
            value = value[1:]

        try:
            return int(value)
        except:
            try:
                return float(value)
            except:
                return value

    # ----------------------------
    # 1) DART 재무 판정
    # ----------------------------
    dart_url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    dart_params = {
        "crtfc_key": dart_api_key,
        "corp_code": corp_code,
        "bsns_year": "2024",
        "reprt_code": "11011",
        "fs_div": "CFS"
    }

    dart_response = requests.get(dart_url, params=dart_params, timeout=20)
    dart_data = dart_response.json()

    sales = None
    op = None
    net = None

    for item in dart_data.get("list", []):
        name = item.get("account_nm")

        if name in ["매출액", "수익(매출액)", "영업수익", "매출", "Revenue"]:
            sales = int(item.get("thstrm_amount") or 0)

        elif "영업이익" in name:
            op = int(item.get("thstrm_amount") or 0)

        elif "당기순이익" in name:
            net = int(item.get("thstrm_amount") or 0)

    fundamental_ok = False
    fundamental_reasons = []

    if sales and op and net:
        margin = op / sales

        if op > 0:
            fundamental_reasons.append("영업이익 흑자")
        if net > 0:
            fundamental_reasons.append("순이익 흑자")
        if margin > 0.15:
            fundamental_reasons.append("고수익 구조")

        if len(fundamental_reasons) >= 3:
            fundamental_ok = True

    # ----------------------------
    # 2) 키움 신고가 근접 판정
    # ----------------------------
    token_url = "https://api.kiwoom.com/oauth2/token"
    token_payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }

    token_response = requests.post(
        token_url,
        json=token_payload,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        timeout=20
    )
    token_data = token_response.json()
    access_token = token_data.get("token")

    price_url = "https://api.kiwoom.com/api/dostk/stkinfo"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10001"
    }
    body = {
        "stk_cd": stock_code
    }

    price_response = requests.post(
        price_url,
        headers=headers,
        json=body,
        timeout=20
    )
    price_data = price_response.json()

    current_price = clean_number(price_data.get("cur_prc"))
    high_250 = clean_number(price_data.get("250hgst"))

    breakout_ratio = None
    breakout_result = "판단 불가"

    if current_price and high_250:
        breakout_ratio = round(current_price / high_250, 4)

        if breakout_ratio >= 0.95:
            breakout_result = "신고가 근접"
        elif breakout_ratio >= 0.85:
            breakout_result = "추적 관찰"
        else:
            breakout_result = "아직 멀다"

    # ----------------------------
    # 3) 최종 1차 판정
    # ----------------------------
    if fundamental_ok and breakout_ratio is not None and breakout_ratio >= 0.95:
        final_result = "1차 매수후보"
    elif fundamental_ok and breakout_ratio is not None and breakout_ratio >= 0.85:
        final_result = "관찰"
    else:
        final_result = "제외"

    return {
        "status": "ok",
        "종목코드": stock_code,
        "corp_code": corp_code,
        "종목명": price_data.get("stk_nm"),
        "재무판정": "적격" if fundamental_ok else "부적격",
        "재무근거": fundamental_reasons,
        "매출액": sales,
        "영업이익": op,
        "당기순이익": net,
        "현재가": current_price,
        "250일최고가": high_250,
        "신고가비율": breakout_ratio,
        "신고가판정": breakout_result,
        "최종판정": final_result
    }



@app.get("/kiwoom-ma-test")
def kiwoom_ma_test(stock_code: str):
    import pandas as pd

    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")

    def clean_number(value):
        if value is None:
            return None
        value = str(value).strip().replace(",", "")
        if value == "":
            return None
        if value.startswith("+") or value.startswith("-"):
            value = value[1:]
        try:
            return int(value)
        except:
            try:
                return float(value)
            except:
                return None

    # 1) 토큰 발급
    token_url = "https://api.kiwoom.com/oauth2/token"
    token_payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }

    token_response = requests.post(
        token_url,
        json=token_payload,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        timeout=20
    )
    token_data = token_response.json()
    access_token = token_data.get("token")

    # 2) 일봉 차트 조회
    chart_url = "https://api.kiwoom.com/api/dostk/chart"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10081"
    }
    body = {
        "stk_cd": stock_code,
        "base_dt": "20260410",
        "upd_stkpc_tp": "1"
    }

    chart_response = requests.post(
        chart_url,
        headers=headers,
        json=body,
        timeout=20
    )
    data = chart_response.json()

    # 3) 실제 응답 데이터 위치
    rows = data.get("stk_dt_pole_chart_qry", [])
    if not rows:
        return {
            "status": "error",
            "message": "일봉 데이터가 비어 있습니다.",
            "raw": data
        }

    # 4) 종가 리스트 추출
    closes = []
    for row in rows:
        close_value = clean_number(row.get("cur_prc"))
        if close_value is not None:
            closes.append(close_value)

    if len(closes) < 20:
        return {
            "status": "error",
            "message": "이동평균 계산에 필요한 데이터가 부족합니다.",
            "close_count": len(closes),
            "raw": data
        }

    # 5) 이동평균 계산
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
        "ma200": ma200
    }


def run_stock_analysis(query: str):
    import pandas as pd

    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")
    dart_api_key = os.getenv("DART_API_KEY")

    def clean_number(value):
        if value is None:
            return None
        value = str(value).strip().replace(",", "")
        if value == "":
            return None
        if value.startswith("+") or value.startswith("-"):
            value = value[1:]
        try:
            return int(value)
        except:
            try:
                return float(value)
            except:
                return None

    # 1) 종목검색
    query_clean = query.strip().lower().replace(" ", "")
    stock_code = query if query.isdigit() else None
    corp_code = None
    found_name = None

    exact_match = None
    partial_matches = []

    for row in CORP_LIST:
        corp_name = row["corp_name"]
        code = row["stock_code"]
        corp = row["corp_code"]
        name_clean = row["corp_name_clean"]

        if stock_code and code == stock_code:
            corp_code = corp
            found_name = corp_name
            break

        if not stock_code:
            if query_clean == name_clean:
                exact_match = row
                break
            if query_clean in name_clean:
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
                "query": query,
                "message": "유사한 종목명이 여러 개 검색되었습니다.",
                "matches": [
                    {
                        "종목명": x["corp_name"],
                        "stock_code": x["stock_code"],
                        "corp_code": x["corp_code"]
                    }
                    for x in partial_matches[:10]
                ]
            }
        else:
            return {
                "status": "error",
                "message": f"종목 검색 실패: {query}"
            }

    if not corp_code:
        row = CORP_BY_STOCK_CODE.get(stock_code)
        if row:
            corp_code = row["corp_code"]
            found_name = row["corp_name"]

    if not stock_code or not corp_code:
        return {
            "status": "error",
            "message": "종목코드 또는 corp_code 조회 실패"
        }

    # 2) 재무 분석
    sales = op = net = None
    reasons = []
    fundamental_ok = False
    margin = None

    dart_data = requests.get(
        "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
        params={
            "crtfc_key": dart_api_key,
            "corp_code": corp_code,
            "bsns_year": "2024",
            "reprt_code": "11011",
            "fs_div": "CFS"
        },
        timeout=20
    ).json()

    for item in dart_data.get("list", []):
        name = (item.get("account_nm") or "").strip()
        amount = int(item.get("thstrm_amount") or 0)

        if sales is None and name in [
            "매출액", "수익(매출액)", "영업수익", "매출", "Revenue"
        ]:
            sales = amount
        elif op is None and (
            "영업이익" in name or
            name in ["영업이익(손실)", "영업손익"]
        ):
            op = amount
        elif net is None and (
            "당기순이익" in name or
            "연결당기순이익" in name or
            "지배기업 소유주지분 순이익" in name or
            "계속영업당기순이익" in name or
            name in ["당기순이익(손실)", "분기순이익", "반기순이익", "연결순이익"]
        ):
            net = amount

    if sales and op and net:
        margin = float(op / sales)
        if op > 0:
            reasons.append("영업이익 흑자")
        if net > 0:
            reasons.append("순이익 흑자")
        if margin > 0.15:
            reasons.append("고수익 구조")
        if len(reasons) >= 2:
            fundamental_ok = True

    # 3) 키움 토큰
    token = requests.post(
        "https://api.kiwoom.com/oauth2/token",
        json={
            "grant_type": "client_credentials",
            "appkey": app_key,
            "secretkey": secret_key
        },
        timeout=20
    ).json().get("token")

    if not token:
        return {
            "status": "error",
            "message": "키움 토큰 발급 실패"
        }

    # 4) 현재가/거래량
    price = requests.post(
        "https://api.kiwoom.com/api/dostk/stkinfo",
        headers={
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "api-id": "ka10001"
        },
        json={"stk_cd": stock_code},
        timeout=20
    ).json()

    current_price = clean_number(price.get("cur_prc"))
    high_250 = clean_number(price.get("250hgst"))
    volume_today = clean_number(price.get("trde_qty"))

    breakout_ratio = None
    if current_price and high_250:
        breakout_ratio = float(current_price / high_250)

    # 5) 일봉/이평/거래량평균
    chart = requests.post(
        "https://api.kiwoom.com/api/dostk/chart",
        headers={
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "api-id": "ka10081"
        },
        json={
            "stk_cd": stock_code,
            "base_dt": "20260410",
            "upd_stkpc_tp": "1"
        },
        timeout=20
    ).json()

    closes = []
    volumes = []

    for x in chart.get("stk_dt_pole_chart_qry", []):
        c = clean_number(x.get("cur_prc"))
        v = clean_number(x.get("trde_qty"))
        if c is not None:
            closes.append(c)
        if v is not None:
            volumes.append(v)

    if len(closes) < 200 or len(volumes) < 20:
        return {
            "status": "error",
            "message": "이동평균 또는 거래량 평균 계산용 데이터 부족"
        }

    df_price = pd.DataFrame({"c": closes})
    df_vol = pd.DataFrame({"v": volumes})

    ma20 = float(df_price["c"].head(20).mean())
    ma60 = float(df_price["c"].head(60).mean())
    ma150 = float(df_price["c"].head(150).mean())
    ma200 = float(df_price["c"].head(200).mean())
    vol_avg20 = float(df_vol["v"].head(20).mean())

    # 6) 판단
    volume_up = bool(volume_today and vol_avg20 and volume_today > vol_avg20)

    chart_ok = bool(
        current_price > ma150 and
        current_price > ma200 and
        ma150 > ma200 and
        ma20 > ma60
    )

    overheat = bool(current_price > ma20 * 1.10)
    pullback = bool(ma20 * 0.97 <= current_price <= ma20 * 1.03)
    below_ma20 = bool(current_price < ma20)
    below_ma60 = bool(current_price < ma60)
    trend_break = bool(below_ma60)

    final = "관망"
    action = "대기"

    if trend_break:
        final = "추세훼손 주의"
        action = "60일선 이탈, 신규 진입 금지"
    elif overheat:
        final = "과열주의"
        action = "단기 과열, 눌림 대기"
    elif breakout_ratio and breakout_ratio > 0.95 and volume_up and fundamental_ok and chart_ok:
        final = "돌파 진입 가능"
        action = "신고가 돌파 + 거래량 동반, 초기 진입 검토"
    elif pullback and volume_up and fundamental_ok and chart_ok:
        final = "눌림목 대기"
        action = "20일선 지지 + 거래량 회복 시 분할 진입"
    elif chart_ok:
        final = "관망"
        action = "추세 양호, 타이밍 대기"

    stop_loss = int(current_price * 0.92) if current_price else None

    return {
        "status": "ok",
        "종목명": found_name or query,
        "stock_code": stock_code,
        "corp_code": corp_code,
        "재무적격": bool(fundamental_ok),
        "재무근거": reasons,
        "매출액": sales,
        "영업이익": op,
        "당기순이익": net,
        "영업이익률": float(margin) if margin is not None else None,
        "현재가": current_price,
        "250일최고가": high_250,
        "신고가비율": float(breakout_ratio) if breakout_ratio is not None else None,
        "ma20": ma20,
        "ma60": ma60,
        "ma150": ma150,
        "ma200": ma200,
        "거래량": volume_today,
        "거래량20평균": vol_avg20,
        "거래량증가": volume_up,
        "20일선이탈": below_ma20,
        "60일선이탈": below_ma60,
        "추세훼손": trend_break,
        "과열여부": overheat,
        "눌림목": pullback,
        "손절가_8pct": stop_loss,
        "최종판정": final,
        "액션": action
    }


@app.get("/analyze-stock")
def analyze_stock(query: str):
    return run_stock_analysis(query)


@app.get("/find-stock-all")
def find_stock_all(query: str):
    import io
    import zipfile
    import xml.etree.ElementTree as ET

    dart_api_key = os.getenv("DART_API_KEY")
    query_clean = query.strip().lower().replace(" ", "")

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": dart_api_key}

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    xml_data = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_data)

    matches = []

    for item in root.findall("list"):
        corp_name = (item.findtext("corp_name") or "").strip()
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()

        if not stock_code:
            continue

        corp_name_clean = corp_name.lower().replace(" ", "")

        if query_clean == corp_name_clean:
            return {
                "status": "ok",
                "match_type": "exact",
                "query": query,
                "종목명": corp_name,
                "stock_code": stock_code,
                "corp_code": corp_code
            }

        if query_clean in corp_name_clean:
            matches.append({
                "종목명": corp_name,
                "stock_code": stock_code,
                "corp_code": corp_code
            })

    if len(matches) == 1:
        return {
            "status": "ok",
            "match_type": "partial",
            "query": query,
            **matches[0]
        }

    if len(matches) > 1:
        return {
            "status": "multiple",
            "query": query,
            "count": len(matches),
            "matches": matches[:20]
        }

    return {
        "status": "not_found",
        "query": query
    }



@app.get("/scan-stocks-basic")
def scan_stocks_basic(limit: int = 100, offset: int = 0):
    strong_candidates = []
    watch_candidates = []

    stats = {
        "총검사": 0,
        "분석성공": 0,
        "재무미달": 0,
        "추세훼손": 0,
        "신고가비율부족": 0,
        "강추천조건미달": 0,
        "기타탈락": 0
    }

    target_rows = CORP_LIST[offset: offset + limit]

    for row in target_rows:
        stock_code = row["stock_code"]
        corp_name = row["corp_name"]

        if not stock_code:
            continue

        # 스팩/리츠/우선주 제외
        if (
            "스팩" in corp_name or
            "리츠" in corp_name or
            corp_name.endswith("우") or
            corp_name.endswith("1우") or
            corp_name.endswith("2우")
        ):
            continue

        stats["총검사"] += 1

        try:
            # 🔥 핵심: HTTP 제거
            response = run_stock_analysis(stock_code)

            if response.get("status") != "ok":
                stats["기타탈락"] += 1
                continue

            stats["분석성공"] += 1

            final = response.get("최종판정")
            ratio = response.get("신고가비율")
            fundamental_ok = response.get("재무적격")
            trend_break = response.get("추세훼손")
            volume_up = response.get("거래량증가")
            current_price = response.get("현재가")
            ma20 = response.get("ma20")
            ma60 = response.get("ma60")

            row_data = {
                "종목명": response.get("종목명", corp_name),
                "stock_code": stock_code,
                "현재가": current_price,
                "신고가비율": ratio,
                "거래량증가": volume_up,
                "ma20": ma20,
                "ma60": ma60,
                "최종판정": final,
                "액션": response.get("액션")
            }

            # ----------------------------
            # 강추천
            # ----------------------------
            if final in ["눌림목 대기", "돌파 진입 가능"]:
                strong_candidates.append(row_data)
                continue

            # ----------------------------
            # 관찰후보
            # ----------------------------
            if (
                fundamental_ok is True and
                trend_break is False and
                ratio is not None and
                ratio >= 0.75 and
                current_price is not None and
                ma60 is not None and
                current_price > ma60
            ):
                watch_candidates.append(row_data)
                continue

            # ----------------------------
            # 탈락 사유
            # ----------------------------
            if fundamental_ok is not True:
                stats["재무미달"] += 1
            elif trend_break is True:
                stats["추세훼손"] += 1
            elif ratio is None or ratio < 0.75:
                stats["신고가비율부족"] += 1
            else:
                stats["강추천조건미달"] += 1

        except Exception:
            stats["기타탈락"] += 1
            continue

    return {
        "status": "ok",
        "offset": offset,
        "limit": limit,
        "강추천개수": len(strong_candidates),
        "관찰후보개수": len(watch_candidates),
        "강추천": strong_candidates[:10],
        "관찰후보": watch_candidates[:20],
        "통계": stats
    }