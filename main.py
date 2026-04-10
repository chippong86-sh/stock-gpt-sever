from fastapi import FastAPI

app = FastAPI()

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