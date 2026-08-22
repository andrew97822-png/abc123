from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import google.generativeai as genai

app = FastAPI()

# 設定 Gemini API Key
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY"))

# 分數換算等級 (根據 Excel 標準)[cite: 1]
def get_rating(score_100):
    if score_100 >= 95:
        return "S"
    elif score_100 >= 80:
        return "A+"
    elif score_100 >= 70:
        return "A"
    elif score_100 >= 60:
        return "B"
    else:
        return "Room for improvement"

class SurveyData(BaseModel):
    category_scores: dict # 接收前端 1~5 分的平均值

@app.post("/api/submit-survey")
async def process_survey(data: SurveyData):
    scaled_scores = {}
    ratings = {}
    
    # 轉換 0~100 分與等級[cite: 1]
    for cat, avg_5 in data.category_scores.items():
        score_100 = (avg_5 / 5.0) * 100
        scaled_scores[cat] = round(score_100, 1)
        ratings[cat] = get_rating(score_100)

    # 組裝 AI Prompt[cite: 1]
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

    請輸出繁體中文，並包含以下三大架構：
    1. 🌟 **整體現況覺察**：肯定學員完成測驗，並給予整體身心靈狀態的簡要總結。
    2. 💪 **優勢維度亮點**：點出表現優異 (S 或 A+) 的項目並給予具體鼓勵。
    3. 🌱 **微小改變指引**：針對得分較低的領域，提供 2 個能在日常生活中輕鬆執行的改善小練習。
    """

    model = genai.GenerativeModel('gemini-2.5-flash')
    response = model.generate_content(prompt)

    return {
        "scores": scaled_scores,
        "ratings": ratings,
        "report": response.text
    }

# 靜態檔案掛載
app.mount("/", StaticFiles(directory=".", html=True), name="static")
