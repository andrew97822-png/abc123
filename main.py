from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import json
import requests
from datetime import datetime
from google.oauth2 import service_account
from google.auth.transport.requests import Request

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔑 請替換成你的 Google Sheet ID (網址 /d/ 與 /edit 中間那一串)
SPREADSHEET_ID = "1zEAssGnfDwk5tZtZ-9KQSZEWwWfdAyXoq9epyltqnCg"

def save_to_google_sheets(email: str, scores: dict):
    """使用 google-auth 取得官方 Access Token 並寫入 Google Sheets"""
    try:
        google_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
        if not google_json_str:
            print("⚠️ 找不到 GOOGLE_CREDENTIALS_JSON 環境變數")
            return

        # 解析環境變數中的 JSON 金鑰
        creds_dict = json.loads(google_json_str)
        
        # 修正 JSON 內 private_key 的換行字元格式
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        credentials = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
        
        # 刷新取得 Access Token
        credentials.refresh(Request())
        access_token = credentials.token

        # 整理要寫入試算表的一列資料
        row_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            email or "未提供",
            scores.get("SOCIAL", 0),
            scores.get("PHYSICAL", 0),
            scores.get("FINANCIAL", 0),
            scores.get("INTELLECTUAL", 0),
            scores.get("SPIRITUAL", 0),
            scores.get("OCCUPATIONAL", 0),
            scores.get("ENVIRONMENTAL", 0),
            scores.get("EMOTIONAL", 0)
        ]

        url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/Sheet1!A1:append?valueInputOption=USER_ENTERED"
        payload = {"values": [row_data]}
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            print(f"✅ 已成功將 {email} 的資料寫入 Google Sheets！")
        else:
            print(f"⚠️ 寫入 Google Sheets 失敗 [HTTP {response.status_code}]: {response.text}")

    except Exception as e:
        print(f"⚠️ 寫入 Google Sheets 發生例外錯誤: {e}")

def get_rating(score_100):
    if score_100 >= 95: return "S"
    elif score_100 >= 80: return "A+"
    elif score_100 >= 70: return "A"
    elif score_100 >= 60: return "B"
    else: return "Room for improvement"

class SurveyData(BaseModel):
    email: Optional[str] = None
    category_scores: dict

@app.post("/api/submit-survey")
async def process_survey(data: SurveyData):
    scaled_scores = {}
    ratings = {}
    
    for cat, avg_5 in data.category_scores.items():
        score_100 = (avg_5 / 5.0) * 100
        scaled_scores[cat] = round(score_100, 1)
        ratings[cat] = get_rating(score_100)

    # 1. 自動同步學員資料至 Google Sheets
    save_to_google_sheets(data.email, scaled_scores)

    # 2. 構建 Claude prompt
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
    
    try:
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            res_data = res.json()
            report_text = res_data['content'][0]['text']
        else:
            report_text = f"【API 拒絕】HTTP {res.status_code} | 原因: {res.text}"
    except Exception as e:
        report_text = f"【系統錯誤】{str(e)}"

    return {
        "scores": scaled_scores,
        "ratings": ratings,
        "report": report_text
    }
