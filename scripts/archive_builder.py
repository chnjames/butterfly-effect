#!/usr/bin/env python3
"""飞书文档存档生成器"""
import json, shutil, subprocess, tempfile
from datetime import datetime
from pathlib import Path

def build_markdown(state) -> str:
    lines = []
    title = state.story_title or f"蝴蝶效应 - {datetime.now().strftime('%Y-%m-%d')}"
    lines.append(f"# {title}")
    lines.append("")
    for node in state.nodes:
        lines.append(f"## 第 {node['index']} 幕")
        lines.append(f"> 决策：{node['decision']}")
        lines.append("")
        lines.append(node["narrative"])
        lines.append("")
        if node.get("image_url"):
            lines.append(f"![概念图]({node['image_url']})")
        lines.append("---")
    return "\n".join(lines)

def export_to_feishu_doc(title: str, markdown_content: str) -> str:
    """
    用 v1 API（--title + --markdown @file）创建飞书文档。
    v2 API 无 --title 参数，文档标题会显示 Untitled；v1 明确设置标题更可靠。
    """
    import time

    root = Path(__file__).resolve().parent.parent
    lark = shutil.which("lark-cli") or "lark-cli"
    safe_title = (title or f"蝴蝶效应-{datetime.now().strftime('%Y%m%d-%H%M')}").strip()
    body = (markdown_content or "").strip()
    export_dir = root / ".butterfly-effect" / "export-temp"
    export_dir.mkdir(parents=True, exist_ok=True)
    tmp = export_dir / f"export_{int(time.time() * 1000)}.md"
    tmp.write_text(body, encoding="utf-8")
    rel = "./" + tmp.relative_to(root).as_posix()
    cmd = [lark, "docs", "+create", "--as", "bot", "--title", safe_title, "--markdown", f"@{rel}"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root))
    if result.returncode != 0 or not (result.stdout or "").strip():
        return ""
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ""
    if data.get("ok") is False:
        return ""
    d = data.get("data") or {}
    # v1: data.doc_url / v2: data.document.url
    if d.get("doc_url"):
        return str(d["doc_url"])
    doc = d.get("document")
    if isinstance(doc, dict) and doc.get("url"):
        return str(doc["url"])
    return str(d.get("url") or data.get("url") or "")