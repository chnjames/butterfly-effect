#!/usr/bin/env python3
"""
图片生成模块 —— 火山方舟 Ark API 封装
使用 Seedream 模型，以简单的 OpenAI 兼容接口生成概念图
"""

import os
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI

# 加载项目根目录下的 .env 文件
load_dotenv(Path(__file__).parent.parent / ".env")


def generate_image(prompt: str) -> str | None:
    """
    调用火山方舟 Ark API 生成图片，返回图片的临时访问 URL。
    
    参数:
        prompt: 图片描述文本（会自动添加风格前缀）
    
    返回:
        成功时返回图片 URL 字符串，失败时返回 None
    """
    api_key = os.getenv("ARK_API_KEY")
    model = os.getenv("ARK_MODEL", "doubao-seedream-4-5-251128")

    if not api_key:
        print("[WARN] ARK_API_KEY 未配置，跳过图片生成")
        return None

    client = OpenAI(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key=api_key,
    )

    # 统一添加画质与风格提示
    full_prompt = (
        f"数字绘画，电影级质感，16:9宽屏比例，细节丰富。{prompt}"
    )

    try:
        response = client.images.generate(
            model=model,
            prompt=full_prompt,
            size="1792x1024",            # 16:9 宽屏
            response_format="url",       # 直接返回可访问的 URL
            extra_body={"watermark": False}  # 关闭水印
        )
        # 返回第一张图片的 URL
        return response.data[0].url

    except Exception as e:
        print(f"[ERROR] Ark 图片生成失败: {e}")
        return None


# 简单测试入口（直接运行此文件时会执行）
if __name__ == "__main__":
    test_prompt = "一艘宇宙飞船在紫色星云中航行，星光点缀，充满探索感"
    print(f"测试提示词: {test_prompt}")
    url = generate_image(test_prompt)
    if url:
        print(f"✅ 图片生成成功: {url}")
    else:
        print("❌ 图片生成失败，请检查 API Key 和网络连接。")