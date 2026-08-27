from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import json
import urllib.request
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔑 請在下面替換成你的 Google Sheet ID (網址中 /d/ 與 /edit 中間的那串字串)
SPREADSHEET_ID = "1zEAssGnfDwk5tZtZ-9KQSZEWwWfdAyXoq9epyltqnCg"

def save_to_google_sheets(email: str, scores: dict):
    """將學員 Email 與分數自動寫入 Google Sheets"""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # 讀取 Render 環境變數中的 Google Credentials JSON
        google_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
        if google_json_str:
            creds_dict = json.loads(google_json_str)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        else:
            # 本地測試時備用：如果找不到環境變數，讀取本地 json
            creds = Credentials.from_service_account_file("google_key.json", scopes=scopes)

        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1

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
        
        # 追加到試算表最新一行
        sheet.append_row(row_data)
        print(f"✅ 已成功將 {email} 的資料寫入 Google Sheets！")
    except Exception as e:
        print(f"⚠️ 寫入 Google Sheets 失敗: {e}")

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

    # 1. 自動同步學員資料到 Google Sheets
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
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            report_text = res_data['content'][0]['text']
    except urllib.error.HTTPError as e:
        err_detail = e.read().decode('utf-8')
        report_text = f"【API 拒絕】HTTP {e.code} | 原因: {err_detail}"
    except Exception as e:
        report_text = f"【系統錯誤】{str(e)}"

    return {
        "scores": scaled_scores,
        "ratings": ratings,
        "report": report_text
    }
