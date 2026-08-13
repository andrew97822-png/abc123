import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import resend
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# 允許前端 index.html 跨域呼叫 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 定義前端傳進來的資料格式
class QuizRequest(BaseModel):
    name: str
    email: str
    scores: dict  # {"sleep": 8, "stress": 6, "emotion": 7, "mind": 5, "inner": 9}

@app.post("/api/analyze")
async def analyze_quiz(data: QuizRequest):
    try:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="未設定 ANTHROPIC_API_KEY")

        client = anthropic.Anthropic(api_key=api_key)

        # 1. 組合 Prompt 給 Claude
        prompt = f"""
        你是一位非常資深的專業身心靈導師。請根據使用者的五維度得分（滿分 10 分）進行深度的分析與引導。

        使用者姓名：{data.name}
        得分狀況：
        - 睡眠修復：{data.scores.get('sleep', 0)}/10
        - 壓力抗性：{data.scores.get('stress', 0)}/10
        - 情緒覺察：{data.scores.get('emotion', 0)}/10
        - 心智清晰：{data.scores.get('mind', 0)}/10
        - 內在連結：{data.scores.get('inner', 0)}/10

        請按以下格式提供專業、溫暖且具建設性的分析：
        1. 【睡眠與身體修復】：分析其狀況並給予一項生活建議。
        2. 【壓力抗性與復原力】：分析其狀況並給予一項放鬆建議。
        3. 【情緒覺察與調節】：分析其狀況並給予情緒安撫建議。
        4. 【心智專注與清晰度】：分析其狀況並給予專注力建議。
        5. 【內在連結與靈性】：分析其狀況並給予內在練習建議。
        6. 【總結與專屬建議】：給予整體鼓勵與適合他的身心靈練習（如頌缽、冥想或呼吸法）。
        """

        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}]
        )

        ai_comment = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        print("=" * 50)
        print(f"【DEBUG】Claude 回傳總字數：{len(ai_comment)}")
        print(ai_comment)
        print("=" * 50)

        # 2. 寄送 Email (如果設定了 RESEND_API_KEY)
        resend_key = os.getenv("RESEND_API_KEY")
        if resend_key:
            resend.api_key = resend_key
            resend.Emails.send({
                "from": "Ness Wellness <onboarding@resend.dev>",
                "to": data.email,
                "subject": f"🌿 {data.name} 的身心靈深度檢測報告",
                "html": f"<div style='font-family: sans-serif; line-height: 1.6;'><h3>親愛的 {data.name} 您好：</h3><p>感謝參與檢測！以下是您的個人化身心靈分析報告：</p><hr><pre style='white-space: pre-wrap;'>{ai_comment}</pre></div>"
            })

        return {"status": "success", "ai_comment": ai_comment}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
