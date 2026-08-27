from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import json
import time
import base64
import urllib.request
import urllib.parse
from datetime import datetime

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

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def get_google_access_token(creds_dict: dict) -> str:
    """使用純 Python 內建庫 (urllib + struct/math) 解析 RSA 私鑰並取得 Google OAuth Token"""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        has_crypto = True
    except ImportError:
        has_crypto = False

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claim_set = {
        "iss": creds_dict["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now
    }
    
    encoded_header = base64url_encode(json.dumps(header).encode('utf-8'))
    encoded_claim = base64url_encode(json.dumps(claim_set).encode('utf-8'))
    signing_input = f"{encoded_header}.{encoded_claim}".encode('utf-8')

    private_key_pem = creds_dict["private_key"].encode('utf-8')

    if has_crypto:
        key = load_pem_private_key(private_key_pem, password=None)
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    else:
        # 備用純 Python PKCS1v15 簽署
        import re
        pem_body = re.sub(r'-----.*?-----|\s', '', creds_dict["private_key"])
        key_bytes = base64.b64decode(pem_body)
        
        # 簡易解析 DER 格式 RSA 私鑰中的 n 與 d
        def parse_der_integers(der):
            idx = 2  # skip sequence header
            ints = []
            while idx < len(der):
                if der[idx] == 0x02:  # INTEGER
                    length = der[idx+1]
                    idx_start = idx + 2
                    if length & 0x80:
                        num_bytes = length & 0x7f
                        length = int.from_bytes(der[idx_start:idx_start+num_bytes], 'big')
                        idx_start += num_bytes
                    val = int.from_bytes(der[idx_start:idx_start+length], 'big')
                    ints.append(val)
                    idx = idx_start + length
                else:
                    idx += 1
            return ints

        ints = parse_der_integers(key_bytes)
        n, d = ints[1], ints[3]

        # SHA256 DigestInfo Prefix
        sha256_prefix = bytes.fromhex("3031300d060960864801650304020105000420")
        import hashlib
        hashed = hashlib.sha256(signing_input).digest()
        t = sha256_prefix + hashed
        
        k = (n.bit_length() + 7) // 8
        ps = b'\xff' * (k - len(t) - 3)
        em = b'\x00\x01' + ps + b'\x00' + t
        em_int = int.from_bytes(em, 'big')
        sig_int = pow(em_int, d, n)
        signature = sig_int.to_bytes(k, 'big')

    jwt_token = f"{encoded_header}.{encoded_claim}.{base64url_encode(signature)}"

    # 發送請求取得 Access Token
    token_url = "https://oauth2.googleapis.com/token"
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt_token
    }).encode('utf-8')

    req = urllib.request.Request(token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        return res["access_token"]

def save_to_google_sheets(email: str, scores: dict):
    """使用原生 Google Sheets REST API 寫入資料（無額外第三方套件）"""
    try:
        google_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
        if not google_json_str:
            print("⚠️ 找不到 GOOGLE_CREDENTIALS_JSON 環境變數")
            return

        creds_dict = json.loads(google_json_str)
        access_token = get_google_access_token(creds_dict)

        # 寫入列的內容
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
        payload = {
            "values": [row_data]
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
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

    # 1. 自動同步資料至 Google Sheets
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
