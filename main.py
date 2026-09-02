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

def save_and_get_previous_scores(email: str, current_scores: dict):
    """
    1. 搜尋 Email 是否有歷史紀錄
    2. 若有舊紀錄，先取出舊分數，再用新分數覆蓋
    3. 若無舊紀錄，直接新增一列
    4. 回傳舊分數字典 (若無舊資料則回傳 None)
    """
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
            current_scores.get("SOCIAL", 0),
            current_scores.get("PHYSICAL", 0),
            current_scores.get("FINANCIAL", 0),
            current_scores.get("INTELLECTUAL", 0),
            current_scores.get("SPIRITUAL", 0),
            current_scores.get("OCCUPATIONAL", 0),
            current_scores.get("ENVIRONMENTAL", 0),
            current_scores.get("EMOTIONAL", 0)
        ]

        previous_scores = None

        # 如果有提供 Email，搜尋是否已存在於第二欄 (B欄)
        if email and email != "未提供":
            cell = sheet.find(email, in_column=2)
            if cell:
                # 讀取該列舊數據（欄位 3 到 10 對應 C 欄至 J 欄的八大維度分數）
                existing_row = sheet.row_values(cell.row)
                if len(existing_row) >= 10:
                    previous_scores = {
                        "SOCIAL": float(existing_row[2]),
                        "PHYSICAL": float(existing_row[3]),
                        "FINANCIAL": float(existing_row[4]),
                        "INTELLECTUAL": float(existing_row[5]),
                        "SPIRITUAL": float(existing_row[6]),
                        "OCCUPATIONAL": float(existing_row[7]),
                        "ENVIRONMENTAL": float(existing_row[8]),
                        "EMOTIONAL": float(existing_row[9]),
                    }
                
                # 抓完舊分數後，將該列覆蓋更新為最新資料
                sheet.update(f"A{cell.row}:J{cell.row}", [row_data])
                print(f"🔄 已找到舊紀錄！已更新 {email} 的資料（第 {cell.row} 行）")
                return previous_scores

        # 若找不到舊資料或未提供 Email，追加新列
        sheet.append_row(row_data)
        print(f"✅ 新學員！已成功將 {email} 的資料寫入 Google Sheets！")
        return None

    except Exception as e:
        print(f"⚠️ 讀寫 Google Sheets 發生錯誤: {e}")
        return None

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
@limiter.limit("1/hour")  # 防刷機制
async def process_survey(request: Request, data: DirectScoreInput):
    """
    主要端點：接收前端 5 分制維度分數，寫入/覆蓋 Google Sheet 並調用 Claude API 生成諮詢報告
    """
    scaled_scores = {}
    ratings = {}
    
    # 算分與評級換算 (1-5分 轉為 百分制)
    for cat in CATEGORIES:
        avg_5 = data.category_scores.get(cat, 0.0)
        score_100 = (avg_5 / 5.0) * 100
        scaled_scores[cat] = round(score_100, 1)
        ratings[cat] = get_rating(score_100)

    # 1. 抓取歷史數據並更新 Google Sheet
    previous_scores = save_and_get_previous_scores(data.email, scaled_scores)

    # 2. 根據是否有歷史資料，動態構建 Prompt 歷史 context
    history_context = ""
    if previous_scores:
        history_context = "\n【學員歷史數據對比（上次測驗得分）】\n"
        for cat in CATEGORIES:
            old_s = previous_scores.get(cat, 0.0)
            new_s = scaled_scores.get(cat, 0.0)
            diff = round(new_s - old_s, 1)
            sign = "+" if diff > 0 else ""
            history_context += f"- {cat}: 上次 {old_s} 分 ➡️ 本次 {new_s} 分 (變化: {sign}{diff}分)\n"
        
        history_context += "\n⚠️ 注意：這是一位『再次前來測驗』的學員。請在報告中額外加入【📈 成長與轉變覺察】區塊，具體指出進步最多的維度並給予鼓勵，若有分數下降的維度也請給予溫柔關懷與實用建議。"

    # 3. 構建 Claude Prompt 提示詞
    prompt = f"""
你是一位專屬 Ness Wellness 的身心靈健康分析顧問。請根據學員在 Wellness Wheel 測驗中的得分與評級生成一份溫暖、專業且精鍊的報告：

【本次八大維度得分與評級】
- 社交關係 (Social): {scaled_scores.get('SOCIAL', 0)}分 (等級: {ratings.get('SOCIAL')})
- 身體健康 (Physical): {scaled_scores.get('PHYSICAL', 0)}分 (等級: {ratings.get('PHYSICAL')})
- 財務理財 (Financial): {scaled_scores.get('FINANCIAL', 0)}分 (等級: {ratings.get('FINANCIAL')})
- 心智成長 (Intellectual): {scaled_scores.get('INTELLECTUAL', 0)}分 (等級: {ratings.get('INTELLECTUAL')})
- 心靈信仰 (Spiritual): {scaled_scores.get('SPIRITUAL', 0)}分 (等級: {ratings.get('SPIRITUAL')})
- 職場職涯 (Occupational): {scaled_scores.get('OCCUPATIONAL', 0)}分 (等級: {ratings.get('OCCUPATIONAL')})
- 環境感知 (Environmental): {scaled_scores.get('ENVIRONMENTAL', 0)}分 (等級: {ratings.get('ENVIRONMENTAL')})
- 情緒管理 (Emotional): {scaled_scores.get('EMOTIONAL', 0)}分 (等級: {ratings.get('EMOTIONAL')})
{history_context}

【輸出要求】
請使用繁體中文，並嚴格按照以下區塊輸出（語氣溫暖真誠、切忌過度誇大吹捧）：

### 🌟 **整體現況覺察**
（用 2-3 句話簡要點出學員目前的整體身心靈平衡狀態。）

{"### 📈 **成長與轉變覺察**\n（具體對比上次與本次的數據變化，給予有感且溫暖的回饋。）\n" if previous_scores else ""}
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
