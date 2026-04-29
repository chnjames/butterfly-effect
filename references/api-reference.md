# API 调用参考

## DeepSeek API
POST https://api.deepseek.com/v1/chat/completions
Authorization: Bearer {API_KEY}
Content-Type: application/json

{
  "model": "deepseek-chat",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.85,
  "max_tokens": 2048,
  "response_format": {"type": "json_object"}
}

### 费用
- 每次生成约 ¥0.001-0.005，完整游戏约 ¥0.02-0.15

## 火山方舟 Ark 图片生成（OpenAI 兼容）

Base URL: `https://ark.cn-beijing.volces.com/api/v3`

```python
client.images.generate(
    model=os.getenv("ARK_MODEL", "doubao-seedream-4-5-251128"),
    prompt="数字绘画，电影级，16:9宽屏。火星基地...",
    size="1792x1024",
    response_format="url",
    extra_body={"watermark": False},
)
```

注意：返回的 TOS URL 通常是临时签名 URL，长期归档应上传到飞书或保存本地快照。

## 飞书 CLI 常用命令
发送文本: `lark-cli im +messages-send --as bot --chat-id "xxx" --text "消息"`
发送图片: `lark-cli im +messages-send --as bot --chat-id "xxx" --image ./相对路径.png`
创建文档: `lark-cli docs +create --as bot --api-version v2 --doc-format markdown --content @./file.md`
事件订阅: `lark-cli event +subscribe --as bot --compact --event-types im.message.receive_v1`

## 单次游戏成本（20节点）
| 项目 | 单价 | 数量 | 小计 |
| DeepSeek | ¥0.003 | 20 | ¥0.06 |
| 火山图片 | ¥0.15  | 6  | ¥0.90 |
| 总计     |        |    | ¥0.96 |