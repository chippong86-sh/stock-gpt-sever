from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/analyze-stock")
def analyze_stock(query: str):
    return {
        "status": "ok",
        "종목": query,
        "메시지": "API 연결 테스트 성공"
    }




import requests

@app.get("/analyze-stock")
def analyze_stock(query: str):
    # 종목코드 찾기 (기존 로직 사용)
    query_clean = query.strip().lower().replace(" ", "")
    stock_code = None
    found_name = None

    for row in CORP_LIST:
        if query_clean in row["corp_name_clean"]:
            stock_code = row["stock_code"]
            found_name = row["corp_name"]
            break

    if not stock_code:
        return {"status": "error", "message": "종목 찾기 실패"}

    # 네이버 금융 간단 크롤링 (가격)
    url = f"https://finance.naver.com/item/main.nhn?code={stock_code}"
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    html = res.text

    import re

    price = re.search(r"현재가.*?<span.*?>([\d,]+)</span>", html)
    price = price.group(1) if price else None

    return {
        "status": "ok",
        "종목명": found_name,
        "stock_code": stock_code,
        "현재가": price
    }