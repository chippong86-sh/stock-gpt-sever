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
        "종목명": query,
        "stock_code": "042700" if query == "한미반도체" else None,
        "메시지": "1단계 테스트 성공"
    }