from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
import os
import json
import urllib.request
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# 🆕 1. 引入 Slowapi 防刷套件
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# 🆕 2. 初始化 Limiter (依 IP 辨識)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Ness Wellness Wheel API",
    description="身心靈八大維度測驗分析與 Google Sheets 同步後端服務",
    version="2.0.0"
)

# 🆕 3. 註冊防刷限制處理器
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 🔑 Google Sheet 配置
SPREADSHEET_ID = "1zEAssGnfDwk5tZtZ-9KQSZEWwWfdAyXoq9epyltqnCg"

# ────────────── 1. 身心靈八大維度測驗題目與維度對照庫 ──────────────
# 定義 8 大維度：SOCIAL, PHYSICAL, FINANCIAL, INTELLECTUAL, SPIRITUAL, OCCUPATIONAL, ENVIRONMENTAL, EMOTIONAL
CATEGORIES = [
    "SOCIAL", "PHYSICAL", "FINANCIAL", "INTELLECTUAL",
    "SPIRITUAL", "OCCUPATIONAL", "ENVIRONMENTAL", "EMOTIONAL"
]

def save_to_google_sheets(email: str, scores: dict):
    """將學員 Email 與八大維度分數自動寫入 Google Sheets"""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        google_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
        if google_json_str:
            creds_dict = json.loads(google_json_str)
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        else:
            creds = Credentials.from_service_account_file("google_key.json", scopes=scopes)

        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1

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
        
        sheet.append_row(row_data)
        print(f"✅ 已成功將 {email} 的資料寫入 Google Sheets！")
    except Exception as e:
        print(f"⚠️ 寫入 Google Sheets 失敗: {e}")

def get_rating(score_100: float) -> str:
    """評分等級換算算法"""
    if score_100 >= 95: return "S"
    elif score_100 >= 80: return "A+"
    elif score_100 >= 70: return "A"
    elif score_100 >= 60: return "B"
    else: return "Room for improvement"

# ────────────── 2. 資料結構定義 (Pydantic Models) ──────────────
class DirectScoreInput(BaseModel):
    email: Optional[str] = None
    category_scores: Dict[str, float] = Field(
        ..., 
        example={
            "SOCIAL": 4.2, "PHYSICAL": 3.8, "FINANCIAL": 3.5, "INTELLECTUAL": 4.5,
            "SPIRITUAL": 4.0, "OCCUPATIONAL": 3.9, "ENVIRONMENTAL": 4.1, "EMOTIONAL": 3.6
        }
    )

class DetailedAnswersInput(BaseModel):
    email: Optional[str] = None
    answers: Dict[str, int]  # key: 題目維度名稱或題號, value: 1-5 分

# ────────────── 3. API Endpoints ──────────────
@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Ness Wellness Wheel Backend API",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/submit-survey")
@limiter.limit("1/hour")  # 🆕 加在函數正上方
async def process_survey(request: Request, data: DirectScoreInput):  # 🆕 括號內一定要加上 request: Request
    """
    主要端點：接收前端計算好的 5 分制維度分數或原始分數，寫入 Google Sheet 並調用 Claude API 生成諮詢報告
    """
    scaled_scores = {}
    ratings = {}
    
    # 算分與評級換算 (1-5分 轉為 百分制)
    for cat in CATEGORIES:
        avg_5 = data.category_scores.get(cat, 0.0)
        score_100 = (avg_5 / 5.0) * 100
        scaled_scores[cat] = round(score_100, 1)
        ratings[cat] = get_rating(score_100)

    # 1. 非同步備份到 Google Sheets
    save_to_google_sheets(data.email, scaled_scores)

    # 2. 構建 Claude Prompt 提示詞
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
        return {
            "scores": scaled_scores,
            "ratings": ratings,
            "report": "⚠️ 錯誤：系統找不到 ANTHROPIC_API_KEY 環境變數，無法生成 AI 分析報告。"
        }

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
        report_text = f"【API 請求失敗】HTTP {e.code} | 詳細原因: {err_detail}"
    except Exception as e:
        report_text = f"【系統發生錯誤】{str(e)}"

    return {
        "status": "success",
        "scores": scaled_scores,
        "ratings": ratings,
        "report": report_text
    }
