from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import re

app = FastAPI()

# CORS (GPT 연결 필수)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 기본 확인용
@app.get("/")
def root():
    return {"status": "ok"}

# 주식 분석 (1단계: 현재가)
@app.get("/analyze-stock")
def analyze_stock(query: str):

    # 👉 테스트용 (한미반도체 고정)
    # 이후 종목검색 로직 붙일 예정
    stock_code = "042700"
    stock_name = query

    try:
        url = f"https://finance.naver.com/item/main.nhn?code={stock_code}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        html = res.text

        # 현재가 추출
        price = re.search(r"현재가.*?<span.*?>([\d,]+)</span>", html)
        price = price.group(1) if price else None

        return {
            "status": "ok",
            "종목명": stock_name,
            "stock_code": stock_code,
            "현재가": price
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }