import os
import anthropic
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=api_key)

try:
    models = client.models.list()
    print("=== 你目前可使用的模型清單 ===")
    for model in models.data:
        print(f"- {model.id}")
except Exception as e:
    print(f"查詢失敗，錯誤原因：{e}")