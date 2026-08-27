from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import json
import csv
import urllib.request
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_rating(score_100):
    if score_100 >= 95: return "S"
    elif score_100 >= 80: return "A+"
    elif score_100 >= 70: return "A"
    elif score_100 >= 60: return "B"
    else: return "Room for improvement"

# 1. 擴充資料模型：新增可選的 email 欄位
class SurveyData(BaseModel):
    email: Optional[str] = None
    category_scores: dict

@app.post("/api/submit-survey")
async def process_survey(data: SurveyData):
    # 2. 收集與記錄 Email
    if data.email:
        print(f"✅ 收到新填寫者 Email: {data.email}")
        try:
            # 自動寫入/追加到 user_emails.csv 檔案中
            with open("user_emails.csv", mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data.email])
        except Exception as e:
            print(f"⚠️ CSV 寫入失敗: {e}")

    scaled_scores = {}
    ratings = {}
    
    for cat, avg_5 in data.category_scores.items():
        score_100 = (avg_5 / 5.0) * 100
        scaled_scores[cat] = round(score_100, 1)
        ratings[cat] = get_rating(score_100)

    prompt = f"""
    你是一位專屬 Ness Wellness 的身心靈健康分析顧問。請根據學員在 Wellness Wheel 測驗中的得分與評級生成一份溫暖、專業且精鍊的報告：

    【八大維度得分與評級】
    - 社交關係 (Social): {scaled_scores.get('SOCIAL', 0)}分 (等級: {ratings.get('SOCIAL')})
    - 身體健康 (Physical): {scaled_scores.get('PHYSICAL', 0)}分 (等級: {ratings.get('PHYSICAL')})
    - 財務理財 (Financial): {scaled_scores.get('FINANCIAL', 0)}分 (等級: {ratings.get('FINANCIAL')})
    - 心智成長 (Intellectual): {scaled_scores.get('INTELLECTUAL', 0)}分 (等級: {ratings.get('INTELLECTUAL')})
    - 心靈信仰 (Spiritual): {scaled_scores.get('SPIRITUAL', 0)}分 (等級: {ratings.get('SPIRITUAL')})
    - 職場職涯 (Occupational): {scaled_scores.get('OCCUPATIONAL', 0)}分 (等級: {ratings.get('OCCUPATIONAL')})
    - 環境感知 (Environmental): {scaled_scores.get('ENVIRONMENTAL', 0)}分 (等級: {ratings.get('ENVIRONMENTAL')})
    - 情緒管理 (Emotional): {scaled_scores.get('EMOTIONAL', 0)}分 (等級: {ratings.get('EMOTIONAL')})

    【輸出要求】
    請使用繁體中文，並嚴格按照以下三區塊輸出（語氣溫暖真誠、切忌過度誇大吹捧）：

    ### 🌟 **整體現況覺察**
    （用 2-3 句話簡要點出學員目前的整體身心靈平衡狀態。）

    ### 💪 **優勢維度亮點**
    （挑選得分最高的 2-3 個維度進行具體鼓勵，不要把 8 個維度全部列出來。）

    ### 🌱 **微小改變指引**
    （挑選得分相對較低或最需要滋養的 1-2 個維度，提供 2 個今天就能開始實踐的具體微小練習。）
    """

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    
    if not api_key:
        return {"scores": scaled_scores, "ratings": ratings, "report": "錯誤：Render 環境變數找不到 ANTHROPIC_API_KEY！"}
    
    key_preview = f"{api_key[:7]}...{api_key[-4:]}" if len(api_key) > 10 else "invalid_length"

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    payload = {
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            report_text = res_data['content'][0]['text']
    except urllib.error.HTTPError as e:
        err_detail = e.read().decode('utf-8')
        report_text = f"【API 拒絕】HTTP {e.code} | Key: {key_preview} | 原因: {err_detail}"
    except Exception as e:
        report_text = f"【系統錯誤】{str(e)}"

    return {
        "scores": scaled_scores,
        "ratings": ratings,
        "report": report_text
    }
