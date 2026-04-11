from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

import os
import io
import zipfile
import requests
import xml.etree.ElementTree as ET
import pandas as pd

load_dotenv(dotenv_path=".env")

# ==========================================
# 0. 버전 표식
# ==========================================
APP_VERSION = "2026-04-11-main-full-human-readable-v1"

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


def is_kiwoom_enabled():
    """
    로컬 PC에서는 ENABLE_KIWOOM=true
    Render 등 외부 서버에서는 ENABLE_KIWOOM=false 로 운영
    """
    return os.getenv("ENABLE_KIWOOM", "false").strip().lower() == "true"


def label_overheat(overheat: bool):
    return "과열" if overheat else "과열 아님"


def label_pullback(pullback: bool, current_price, ma20):
    if current_price is None or ma20 is None:
        return "판단 불가"

    gap = ((current_price / ma20) - 1) * 100

    if pullback:
        return "20일선 눌림 구간"

    if gap > 10:
        return "20일선 과도한 이격"
    elif gap > 3:
        return "20일선 위 추격 구간"
    elif gap >= -3:
        return "20일선 근처"
    else:
        return "20일선 하회"


def label_volume(volume_up: bool, volume_today, vol_avg20):
    if volume_today is None or vol_avg20 is None:
        return "판단 불가"

    if volume_up:
        return "평균 대비 증가"

    ratio = volume_today / vol_avg20 if vol_avg20 else None
    if ratio is None:
        return "판단 불가"

    if ratio >= 0.9:
        return "평균 수준"
    else:
        return "평균 이하"


# ==========================================
# 3. DART 고유번호 로딩
# ==========================================
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


# ==========================================
# 4. 키움 토큰 및 데이터
# ==========================================
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


def fetch_kiwoom_price(stock_code: str):
    """로컬(키움 ON) 환경에서만 사용"""
    app_key = os.getenv("KIWOOM_APP_KEY")
    if not app_key:
        raise HTTPException(status_code=500, detail="KIWOOM_APP_KEY 설정 안됨")

    access_token = get_kiwoom_token()

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10001",
    }

    response = requests.post(
        "https://api.kiwoom.com/api/dostk/stkinfo",
        headers=headers,
        json={"stk_cd": stock_code},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    return {
        "현재가": clean_number(data.get("cur_prc")),
        "250일최고가": clean_number(data.get("250hgst")),
        "거래량": clean_number(data.get("trde_qty")),
        "등락률": clean_number(data.get("flu_rt"), keep_sign=True),
    }


def fetch_kiwoom_chart(stock_code: str):
    """로컬(키움 ON) 환경에서만 사용"""
    app_key = os.getenv("KIWOOM_APP_KEY")
    if not app_key:
        raise HTTPException(status_code=500, detail="KIWOOM_APP_KEY 설정 안됨")

    access_token = get_kiwoom_token()

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "api-id": "ka10081",
    }

    response = requests.post(
        "https://api.kiwoom.com/api/dostk/chart",
        headers=headers,
        json={
            "stk_cd": stock_code,
            "base_dt": datetime.now().strftime("%Y%m%d"),
            "upd_stkpc_tp": "1",
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    rows = data.get("stk_dt_pole_chart_qry", [])
    closes = [
        clean_number(x.get("cur_prc"))
        for x in rows
        if clean_number(x.get("cur_prc")) is not None
    ]
    volumes = [
        clean_number(x.get("trde_qty"))
        for x in rows
        if clean_number(x.get("trde_qty")) is not None
    ]

    return {
        "closes": closes,
        "volumes": volumes,
    }


# ==========================================
# 5. 외부 대체용 웹 차트 수집
# ==========================================
def fetch_public_naver_chart(stock_code: str, max_pages: int = 25):
    """
    외부(Render 등, 키움 OFF) 환경에서는 네이버 금융 일봉 데이터를 사용
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://finance.naver.com/item/main.nhn?code={stock_code}",
    })

    closes = []
    volumes = []
    dates = []

    for page in range(1, max_pages + 1):
        url = f"https://finance.naver.com/item/sise_day.naver?code={stock_code}&page={page}"
        response = session.get(url, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.select_one("table.type2")
        if not table:
            continue

        for tr in table.select("tr"):
            cols = [td.get_text(strip=True).replace(",", "") for td in tr.select("td")]
            if len(cols) != 7:
                continue
            if not cols[0] or cols[0] == "날짜":
                continue

            try:
                date_text = cols[0]
                close = int(cols[1])
                volume = int(cols[6])
            except Exception:
                continue

            dates.append(date_text)
            closes.append(close)
            volumes.append(volume)

    if not closes:
        raise HTTPException(status_code=500, detail="웹 차트 데이터 수집 실패")

    current_price = closes[0]
    volume_today = volumes[0]
    high_250 = max(closes[:250]) if len(closes) >= 1 else None

    return {
        "현재가": current_price,
        "250일최고가": high_250,
        "거래량": volume_today,
        "등락률": None,
        "closes": closes,
        "volumes": volumes,
        "dates": dates,
    }


# ==========================================
# 6. 종목 검색 및 DART 재무
# ==========================================
def find_stock(query: str):
    """
    종목명/종목코드 검색
    exact match → partial match 순서
    """
    ensure_corp_data_loaded()

    if not query or not str(query).strip():
        return {"status": "error", "message": "query 값이 비어 있습니다."}

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

    return {
        "status": "ok",
        "종목명": found_name,
        "종목코드": stock_code,
        "corp_code": corp_code,
    }


def fetch_dart_fundamentals(corp_code: str):
    """
    DART 재무 데이터 조회
    """
    dart_api_key = os.getenv("DART_API_KEY")
    if not dart_api_key:
        raise HTTPException(status_code=500, detail="DART_API_KEY 설정 안됨")

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": dart_api_key,
        "corp_code": corp_code,
        "bsns_year": "2024",
        "reprt_code": "11011",
        "fs_div": "CFS",
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    sales = op = net = margin = None
    reasons = []
    fundamental_ok = False

    for item in data.get("list", []):
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

    return {
        "매출액": sales,
        "영업이익": op,
        "당기순이익": net,
        "영업이익률": margin,
        "근거": reasons,
        "재무적격": fundamental_ok,
    }


# ==========================================
# 7. 최종 분석 결과 생성
# ==========================================
def build_analysis_result(
    found_name: str,
    stock_code: str,
    financial: dict,
    market_data: dict,
    chart_mode: str,
):
    sales = financial.get("매출액")
    op = financial.get("영업이익")
    net = financial.get("당기순이익")
    margin = financial.get("영업이익률")
    reasons = financial.get("근거", [])
    fundamental_ok = financial.get("재무적격", False)

    current_price = market_data.get("현재가")
    high_250 = market_data.get("250일최고가")
    volume_today = market_data.get("거래량")
    closes = market_data.get("closes", [])
    volumes = market_data.get("volumes", [])

    if len(closes) < 200:
        return {
            "status": "error",
            "message": "차트 데이터 부족 (최소 200거래일 필요)",
            "종목명": found_name,
            "종목코드": stock_code,
            "환경": {
                "kiwoom_enabled": is_kiwoom_enabled(),
                "chart_source": chart_mode,
                "version": APP_VERSION,
            }
        }

    if len(volumes) < 20:
        return {
            "status": "error",
            "message": "거래량 데이터 부족 (최소 20거래일 필요)",
            "종목명": found_name,
            "종목코드": stock_code,
            "환경": {
                "kiwoom_enabled": is_kiwoom_enabled(),
                "chart_source": chart_mode,
                "version": APP_VERSION,
            }
        }

    breakout_ratio = (
        float(current_price / high_250)
        if current_price and high_250 and high_250 != 0
        else 0
    )

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

    overheat_text = label_overheat(overheat)
    pullback_text = label_pullback(pullback, current_price, ma20)
    volume_text = label_volume(volume_up, volume_today, vol_avg20)

    if chart_ok and not overheat and not pullback:
        current_zone = "상승 추세 유지 구간"
    elif pullback:
        current_zone = "눌림목 관찰 구간"
    elif overheat:
        current_zone = "단기 과열 구간"
    elif trend_break:
        current_zone = "추세 훼손 주의 구간"
    else:
        current_zone = "관찰 구간"

    return {
        "status": "ok",
        "version": APP_VERSION,
        "종목명": found_name,
        "종목코드": stock_code,
        "분석결과": {
            "최종판단": final,
            "대응전략": action,
            "현재구간해석": current_zone,
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
            "과열판정": overheat_text,

            "20일선눌림": pullback,
            "진입위치판정": pullback_text,

            "거래량증가": volume_up,
            "거래량판정": volume_text,

            "등락률": market_data.get("등락률"),
            "거래량": volume_today,
            "20일평균거래량": round(vol_avg20, 0),

            "이평선": {
                "ma20": round(ma20, 0),
                "ma60": round(ma60, 0),
                "ma150": round(ma150, 0),
                "ma200": round(ma200, 0),
            },
        },
        "환경": {
            "kiwoom_enabled": is_kiwoom_enabled(),
            "chart_source": chart_mode,
            "version": APP_VERSION,
        }
    }


# ==========================================
# 8. FastAPI 설정
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
# 9. 기본 엔드포인트
# ==========================================
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "서버 정상 작동 중",
        "version": APP_VERSION,
        "startup": STARTUP_STATUS,
        "kiwoom_enabled": is_kiwoom_enabled(),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "startup": STARTUP_STATUS,
        "corp_list_count": len(CORP_LIST),
        "env": {
            "DART_API_KEY": bool(os.getenv("DART_API_KEY")),
            "KIWOOM_APP_KEY": bool(os.getenv("KIWOOM_APP_KEY")),
            "KIWOOM_SECRET_KEY": bool(os.getenv("KIWOOM_SECRET_KEY")),
            "ENABLE_KIWOOM": os.getenv("ENABLE_KIWOOM", "false"),
        },
    }


@app.get("/resolve-stock")
def resolve_stock(query: str):
    return find_stock(query)


@app.get("/dart-financial-simple")
def dart_financial_simple(corp_code: str):
    data = fetch_dart_fundamentals(corp_code)
    return {
        "status": "ok",
        "version": APP_VERSION,
        "corp_code": corp_code,
        "매출액": data.get("매출액"),
        "영업이익": data.get("영업이익"),
        "당기순이익": data.get("당기순이익"),
        "영업이익률": (
            round(data["영업이익률"] * 100, 1)
            if data.get("영업이익률") is not None
            else None
        ),
        "재무적격": data.get("재무적격"),
        "근거": data.get("근거"),
    }


# ==========================================
# 10. 메인 분석 로직
# ==========================================
def _run_stock_analysis_internal(query: str):
    stock = find_stock(query)
    if stock.get("status") != "ok":
        stock["version"] = APP_VERSION
        return stock

    found_name = stock["종목명"]
    stock_code = stock["종목코드"]
    corp_code = stock["corp_code"]

    try:
        financial = fetch_dart_fundamentals(corp_code)
    except Exception as e:
        return {
            "status": "error",
            "version": APP_VERSION,
            "message": f"재무 데이터 로드 에러: {str(e)}"
        }

    # 로컬: 키움 ON이면 키움 우선
    if is_kiwoom_enabled():
        try:
            price_data = fetch_kiwoom_price(stock_code)
            chart_data = fetch_kiwoom_chart(stock_code)

            market_data = {
                "현재가": price_data.get("현재가"),
                "250일최고가": price_data.get("250일최고가"),
                "거래량": price_data.get("거래량"),
                "등락률": price_data.get("등락률"),
                "closes": chart_data.get("closes", []),
                "volumes": chart_data.get("volumes", []),
            }

            return build_analysis_result(
                found_name=found_name,
                stock_code=stock_code,
                financial=financial,
                market_data=market_data,
                chart_mode="kiwoom",
            )

        except Exception:
            # 키움 실패 시 네이버 fallback
            try:
                public_data = fetch_public_naver_chart(stock_code)
                return build_analysis_result(
                    found_name=found_name,
                    stock_code=stock_code,
                    financial=financial,
                    market_data=public_data,
                    chart_mode="naver_fallback",
                )
            except Exception as e2:
                return {
                    "status": "ok",
                    "version": APP_VERSION,
                    "종목명": found_name,
                    "종목코드": stock_code,
                    "분석결과": {
                        "최종판단": "재무 중심 분석만 가능",
                        "대응전략": "키움 및 웹 차트 데이터 수집 실패",
                        "현재구간해석": "차트 판단 불가",
                    },
                    "재무": {
                        "판정": "적격" if financial.get("재무적격") else "부적격",
                        "매출액": financial.get("매출액"),
                        "영업이익": financial.get("영업이익"),
                        "당기순이익": financial.get("당기순이익"),
                        "영업이익률": (
                            f"{round(financial['영업이익률'] * 100, 1)}%"
                            if financial.get("영업이익률") is not None
                            else "계산불가"
                        ),
                        "근거": financial.get("근거"),
                    },
                    "차트": {
                        "현재가": None,
                        "250일최고가": None,
                        "신고가대비비율": None,
                        "차트추세": f"차트 데이터 수집 실패: {str(e2)}",
                        "과열여부": None,
                        "과열판정": "판단 불가",
                        "20일선눌림": None,
                        "진입위치판정": "판단 불가",
                        "거래량증가": None,
                        "거래량판정": "판단 불가",
                        "등락률": None,
                        "거래량": None,
                        "20일평균거래량": None,
                        "이평선": {
                            "ma20": None,
                            "ma60": None,
                            "ma150": None,
                            "ma200": None,
                        },
                    },
                    "환경": {
                        "kiwoom_enabled": True,
                        "chart_source": "none",
                        "version": APP_VERSION,
                    }
                }

    # 외부(Render): 키움 OFF → 네이버 공개 차트만 사용
    try:
        public_data = fetch_public_naver_chart(stock_code)
        return build_analysis_result(
            found_name=found_name,
            stock_code=stock_code,
            financial=financial,
            market_data=public_data,
            chart_mode="naver_public",
        )
    except Exception as e:
        return {
            "status": "ok",
            "version": APP_VERSION,
            "종목명": found_name,
            "종목코드": stock_code,
            "분석결과": {
                "최종판단": "재무 중심 분석만 가능",
                "대응전략": "외부 서버 환경에서는 웹 차트 수집 실패",
                "현재구간해석": "차트 판단 불가",
            },
            "재무": {
                "판정": "적격" if financial.get("재무적격") else "부적격",
                "매출액": financial.get("매출액"),
                "영업이익": financial.get("영업이익"),
                "당기순이익": financial.get("당기순이익"),
                "영업이익률": (
                    f"{round(financial['영업이익률'] * 100, 1)}%"
                    if financial.get("영업이익률") is not None
                    else "계산불가"
                ),
                "근거": financial.get("근거"),
            },
            "차트": {
                "현재가": None,
                "250일최고가": None,
                "신고가대비비율": None,
                "차트추세": f"웹 차트 수집 실패: {str(e)}",
                "과열여부": None,
                "과열판정": "판단 불가",
                "20일선눌림": None,
                "진입위치판정": "판단 불가",
                "거래량증가": None,
                "거래량판정": "판단 불가",
                "등락률": None,
                "거래량": None,
                "20일평균거래량": None,
                "이평선": {
                    "ma20": None,
                    "ma60": None,
                    "ma150": None,
                    "ma200": None,
                },
            },
            "환경": {
                "kiwoom_enabled": False,
                "chart_source": "none",
                "version": APP_VERSION,
            }
        }


@app.get("/run-stock-analysis")
def run_stock_analysis(query: str):
    return _run_stock_analysis_internal(query)


@app.get("/analyze-stock")
def analyze_stock(query: str):
    return _run_stock_analysis_internal(query)