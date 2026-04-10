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
import re

@app.get("/analyze-stock")
def analyze_stock(query: str):
    stock_code = "042700"  # 테스트용

    url = f"https://finance.naver.com/item/main.nhn?code={stock_code}"
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    html = res.text

    price = re.search(r"현재가.*?<span.*?>([\d,]+)</span>", html)
    price = price.group(1) if price else None

    return {
        "status": "ok",
        "종목명": query,
        "현재가": price
    }