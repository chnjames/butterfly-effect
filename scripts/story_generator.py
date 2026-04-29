#!/usr/bin/env python3
"""DeepSeek 剧情生成模块"""
import os, json, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

def generate_story(system_prompt: str, user_message: str) -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {
            "scene": "",
            "narrative": "（未配置 DEEPSEEK_API_KEY，请稍后再试。）",
            "mood": "",
            "choices": ["发送 帮助 查看指令"],
        }
    url = os.getenv("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.85,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"}
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        out = json.loads(data["choices"][0]["message"]["content"])
        if not isinstance(out, dict):
            raise ValueError("LLM returned non-object JSON")
        out.setdefault("scene", "")
        out.setdefault("narrative", "（剧情暂时空白。）")
        out.setdefault("mood", "")
        if not isinstance(out.get("choices"), list):
            out["choices"] = ["继续探索", "观察周围"]
        return out
    except Exception as e:
        print(f"[WARN] generate_story: {e}")
        return {
            "scene": "",
            "narrative": "（剧情生成失败，请稍后再试。）",
            "mood": "",
            "choices": ["继续尝试", "发送 帮助 查看指令"],
        }