from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import google.generativeai as genai

app = FastAPI()

# 1. 允許跨網域請求 (修復 API 連線失敗關鍵)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 設定 API Key
API_KEY = os.environ.get("GEMINI_API_KEY", "填入你的_GEMINI_API_KEY")
genai.configure(api_key=API_KEY)

def get_rating(score_100):
    if score_100 >= 95: return "S"
    elif score_100 >= 80: return "A+"
    elif score_100 >= 70: return "A"
    elif score_100 >= 60: return "B"
    else: return "Room for improvement"

class SurveyData(BaseModel):
    category_scores: dict

@app.post("/api/submit-survey")
async def process_survey(data: SurveyData):
    try:
        scaled_scores = {}
        ratings = {}
        
        for cat, avg_5 in data.category_scores.items():
            score_100 = (avg_5 / 5.0) * 100
            scaled_scores[cat] = round(score_100, 1)
            ratings[cat] = get_rating(score_100)

        prompt = f"""
        你是一位專屬 Ness Wellness 的身心靈健康分析顧問。請根據學員在 Wellness Wheel 測驗中的得分與評級生成一份溫暖、專業且具實用建議的報告：

        【八大維度得分與評級】
        - 社交關係 (Social): {scaled_scores.get('SOCIAL', 0)}分 (等級: {ratings.get('SOCIAL')})
        - 身體健康 (Physical): {scaled_scores.get('PHYSICAL', 0)}分 (等級: {ratings.get('PHYSICAL')})
        - 財務理財 (Financial): {scaled_scores.get('FINANCIAL', 0)}分 (等級: {ratings.get('FINANCIAL')})
        - 心智成長 (Intellectual): {scaled_scores.get('INTELLECTUAL', 0)}分 (等級: {ratings.get('INTELLECTUAL')})
        - 心靈信仰 (Spiritual): {scaled_scores.get('SPIRITUAL', 0)}分 (等級: {ratings.get('SPIRITUAL')})
        - 職場職涯 (Occupational): {scaled_scores.get('OCCUPATIONAL', 0)}分 (等級: {ratings.get('OCCUPATIONAL')})
        - 環境感知 (Environmental): {scaled_scores.get('ENVIRONMENTAL', 0)}分 (等級: {ratings.get('ENVIRONMENTAL')})
        - 情緒管理 (Emotional): {scaled_scores.get('EMOTIONAL', 0)}分 (等級: {ratings.get('EMOTIONAL')})

        請輸出繁體中文，包含：
        1. 🌟 **整體現況覺察**：簡要總結。
        2. 💪 **優勢維度亮點**：點出高分項目並給予鼓勵。
        3. 🌱 **微小改變指引**：針對較低分項目提供 2 個日常改善小練習。
        """

        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)

        return {
            "scores": scaled_scores,
            "ratings": ratings,
            "report": response.text
        }
    except Exception as e:
        print(f"❌ 後端發生錯誤: {e}")
        return {"report": f"生成失敗，後端錯誤訊息: {str(e)}"}

app.mount("/", StaticFiles(directory=".", html=True), name="static")
