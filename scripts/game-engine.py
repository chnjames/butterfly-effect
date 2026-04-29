#!/usr/bin/env python3
"""
蝴蝶效应 —— 游戏引擎主脚本（Ark API 图片生成版）
监听飞书群聊事件，驱动互动叙事游戏
"""

import argparse, json, os, re, time, subprocess, shutil
import datetime
import unicodedata
import requests
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from dotenv import load_dotenv

try:
    import yaml
except ImportError:
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# lark-cli --image 要求：相对路径，且相对于进程 cwd
IMAGE_SEND_CACHE = PROJECT_ROOT / ".butterfly-effect" / "image-cache"
IMAGE_SEND_CACHE.mkdir(parents=True, exist_ok=True)


def _lark_cli() -> str:
    """Windows 上需使用 shutil.which，否则 subprocess 找不到 lark-cli.CMD。"""
    return shutil.which("lark-cli") or "lark-cli"


# ============================================================
# 图片生成 (Ark API)
# ============================================================
from openai import OpenAI

def generate_image(prompt: str) -> Optional[str]:
    api_key = os.getenv("ARK_API_KEY")
    model = os.getenv("ARK_MODEL", "doubao-seedream-4-5-251128")
    if not api_key:
        print("[WARN] ARK_API_KEY 未配置，跳过图片生成")
        return None
    client = OpenAI(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key=api_key,
    )
    try:
        response = client.images.generate(
            model=model,
            prompt=f"数字绘画，电影级，16:9宽屏。{prompt}",
            size="1792x1024",
            response_format="url",
            extra_body={"watermark": False}
        )
        return response.data[0].url
    except Exception as e:
        print(f"[ERROR] Ark 图片生成失败: {e}")
        return None

# ============================================================
# 剧情生成 (DeepSeek)
# ============================================================
def _fallback_story(nudge: str) -> dict:
    return {
        "scene": "",
        "narrative": f"（{nudge}，请稍后再试。）",
        "mood": "",
        "choices": ["继续尝试", "发送 帮助 查看指令"],
    }


def _clean_choices(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        s = str(item or "").strip()
        if s:
            out.append(s)
    return out[:4]


def _normalize_story_result(raw: Any, fallback_nudge: str = "模型返回格式异常") -> dict:
    """把 LLM 返回统一成引擎可安全消费的结构，避免 choices/narrative 缺失导致空回复。"""
    if not isinstance(raw, dict):
        return _fallback_story(fallback_nudge)
    narrative = str(raw.get("narrative") or "").strip()
    if not narrative:
        narrative = f"（{fallback_nudge}，请稍后再试。）"
    choices = _clean_choices(raw.get("choices"))
    if not choices:
        choices = ["继续探索", "观察周围", "发送 帮助 查看指令"]
    return {
        "scene": str(raw.get("scene") or "").strip(),
        "narrative": narrative,
        "mood": str(raw.get("mood") or "").strip(),
        "choices": choices,
    }


def generate_story(system_prompt: str, user_message: str) -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return _fallback_story("未配置 DEEPSEEK_API_KEY")
    url = os.getenv("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            return _fallback_story(f"剧情服务 HTTP {resp.status_code}")
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        out = json.loads(raw)
        return _normalize_story_result(out)
    except (KeyError, json.JSONDecodeError) as e:
        print(f"[WARN] generate_story 解析失败: {e}", flush=True)
        return _fallback_story("剧情解析失败")
    except Exception as e:
        print(f"[WARN] generate_story: {e}", flush=True)
        return _fallback_story("网络或服务异常")


OUTLINE_SYSTEM = (
    "你是编辑。将用户给出的互动小说节点压缩为 Markdown 无序列表（5～12 条），"
    "每条不超过 90 字，中文，不编造新情节，不输出代码块以外的前言。"
)


def _generate_llm_outline(blob: str) -> str:
    """非 JSON 模式，用于梗概摘要。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key or not (blob or "").strip():
        return ""
    url = os.getenv("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": OUTLINE_SYSTEM},
            {"role": "user", "content": (blob or "")[:14000]},
        ],
        "temperature": 0.35,
        "max_tokens": min(1200, int(config.LLM_MAX_TOKENS)),
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=90)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        print(f"[WARN] _generate_llm_outline: {e}", flush=True)
        return ""


def build_compact_story_blob(state: "GameState") -> str:
    lines: List[str] = []
    for n in state.nodes:
        d = n.get("decision", "")
        nv = (n.get("narrative") or "")[:800]
        lines.append(f"第 {n['index']} 幕\n决策：{d}\n剧情：{nv}")
    return "\n\n".join(lines)


def build_rule_based_outline(state: "GameState") -> str:
    items: List[str] = []
    for n in state.nodes:
        dec = n.get("decision", "")
        nv = (n.get("narrative") or "").strip().replace("\n", " ")
        if len(nv) > 120:
            nv = nv[:120] + "…"
        items.append(f"- **第 {n['index']} 幕**（{dec}）：{nv}")
    return "## 梗概（节选）\n\n" + "\n".join(items)


def _preset_match_key(raw: str) -> Optional[str]:
    """在 PRESETS 中查找键，支持大小写不敏感。"""
    if raw in PRESETS:
        return raw
    low = raw.lower()
    for k in PRESETS:
        if k.lower() == low:
            return k
    return None


def _resolve_story_seed(story: str) -> tuple[str, str, Optional[str]]:
    """
    返回 (传给 LLM 的种子文案, 建议标题短名, 预设键或 None)。
    未识别 preset: / # 时整段 story 作为自定义开局。
    """
    s = (story or "").strip()
    sl = s.lower()
    if sl.startswith("preset:"):
        pid = s.split(":", 1)[1].strip()
        key = _preset_match_key(pid)
        if not key:
            return "", "", "__missing__"
        pr = PRESETS[key]
        op = (pr.get("opening") or "").strip()
        if not op:
            return "", "", "__missing__"
        return op, pr.get("title") or key, key
    if s.startswith("#") and len(s) > 1:
        rest = s[1:].strip()
        pid = rest.split()[0] if rest else ""
        key = _preset_match_key(pid)
        if key:
            pr = PRESETS[key]
            op = (pr.get("opening") or "").strip()
            if op:
                return op, pr.get("title") or key, key
    return s, (s[:40] + "…") if len(s) > 40 else s, None

# ============================================================
# 飞书文档存档
# ============================================================
def build_markdown(state) -> str:
    lines = []
    title = state.story_title or f"蝴蝶效应 - {datetime.datetime.now().strftime('%Y-%m-%d')}"
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

def _parse_docs_create_url(stdout: str) -> str:
    """兼容 v1（data.doc_url）与 v2（data.document.url）响应格式。"""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return ""
    if data.get("ok") is False:
        return ""
    d = data.get("data") or {}
    # v2 格式
    doc = d.get("document")
    if isinstance(doc, dict) and doc.get("url"):
        return str(doc["url"])
    # v1 格式
    if d.get("doc_url"):
        return str(d["doc_url"])
    if d.get("url"):
        return str(d["url"])
    return str(data.get("url") or "")


def export_to_feishu_doc(title: str, markdown_content: str) -> str:
    """
    创建飞书云文档，返回 URL；失败返回空字符串。
    使用 v1 API（--title 明确设置标题，避免 v2 无 title 参数导致文档显示 Untitled）。
    正文里的 # H1 已包含完整内容，v1 --markdown 可正确渲染。
    """
    safe_title = (title or f"蝴蝶效应-{datetime.datetime.now().strftime('%Y%m%d-%H%M')}").strip()
    body = (markdown_content or "").strip()
    export_dir = PROJECT_ROOT / ".butterfly-effect" / "export-temp"
    export_dir.mkdir(parents=True, exist_ok=True)
    tmp = export_dir / f"story_{int(time.time() * 1000)}.md"
    tmp.write_text(body, encoding="utf-8")
    rel_content = "./" + tmp.relative_to(PROJECT_ROOT).as_posix()
    cmd = [
        "docs",
        "+create",
        "--as",
        "bot",
        "--title",
        safe_title,
        "--markdown",
        f"@{rel_content}",
    ]
    result = run_lark_cli(cmd)
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode == 0 and out:
        url = _parse_docs_create_url(out)
        if url:
            return url
    detail = err or out or "(无输出)"
    print(f"[ERROR] 创建飞书文档失败: {detail}", flush=True)
    return ""

# ============================================================
# 游戏状态管理
# ============================================================
SAVE_DIR = Path.home() / ".butterfly-effect" / "saves"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
FINISHED_DIR = Path.home() / ".butterfly-effect" / "finished-runs"
FINISHED_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (name or "").strip())
    s = re.sub(r"\s+", "_", s).strip("._")
    return (s or "butterfly-effect")[:80]


def _cleanup_temp_files(max_age_hours: int = 24) -> None:
    """清理 export-temp 和 image-cache 中超过 max_age_hours 的旧临时文件，防止磁盘积累。"""
    cutoff = time.time() - max_age_hours * 3600
    for folder in (
        PROJECT_ROOT / ".butterfly-effect" / "export-temp",
        PROJECT_ROOT / ".butterfly-effect" / "image-cache",
    ):
        if not folder.exists():
            continue
        for f in folder.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass


def save_finished_markdown(state: "GameState", markdown_content: str) -> str:
    title = state.story_title or "butterfly-effect"
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = FINISHED_DIR / f"{ts}_{_safe_filename(state.chat_id)}_{_safe_filename(title)}.md"
    path.write_text(markdown_content or "", encoding="utf-8")
    return str(path)


def _load_yaml_config() -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "INACTIVITY_TIMEOUT": 600,
        "IMAGE_GEN_INTERVAL": 3,
        "MAX_STORY_NODES": 50,
        "CONTEXT_WINDOW_NODES": 5,
        "MAX_DECISIONS_PER_MINUTE": 10,
        "LLM_TEMPERATURE": 0.85,
        "LLM_MAX_TOKENS": 2048,
    }
    p = PROJECT_ROOT / "config.yaml"
    if not p.exists() or yaml is None:
        return d
    try:
        with open(p, encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        g, llm, safety = y.get("game") or {}, y.get("llm") or {}, y.get("safety") or {}
        if g.get("inactivity_timeout") is not None:
            d["INACTIVITY_TIMEOUT"] = int(g["inactivity_timeout"])
        if g.get("image_gen_interval") is not None:
            d["IMAGE_GEN_INTERVAL"] = int(g["image_gen_interval"])
        if g.get("max_story_nodes") is not None:
            d["MAX_STORY_NODES"] = int(g["max_story_nodes"])
        if g.get("context_window_nodes") is not None:
            d["CONTEXT_WINDOW_NODES"] = int(g["context_window_nodes"])
        if llm.get("temperature") is not None:
            d["LLM_TEMPERATURE"] = float(llm["temperature"])
        if llm.get("max_tokens") is not None:
            d["LLM_MAX_TOKENS"] = int(llm["max_tokens"])
        if safety.get("max_decisions_per_minute") is not None:
            d["MAX_DECISIONS_PER_MINUTE"] = int(safety["max_decisions_per_minute"])
    except Exception as e:
        print(f"[WARN] 读取 config.yaml 失败，使用内置默认: {e}", flush=True)
    return d


def _load_presets() -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    p = PROJECT_ROOT / "config.yaml"
    if not p.exists() or yaml is None:
        return out
    try:
        with open(p, encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        raw = y.get("presets") or {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if not isinstance(v, dict):
                    continue
                kid = str(k).strip()
                if not kid:
                    continue
                out[kid] = {
                    "title": str(v.get("title") or kid),
                    "opening": str(v.get("opening") or "").strip(),
                }
    except Exception as e:
        print(f"[WARN] 读取 presets 失败: {e}", flush=True)
    return out


_cfg = _load_yaml_config()
PRESETS: Dict[str, Dict[str, str]] = _load_presets()


class Config:
    INACTIVITY_TIMEOUT = _cfg["INACTIVITY_TIMEOUT"]
    IMAGE_GEN_INTERVAL = _cfg["IMAGE_GEN_INTERVAL"]
    MAX_STORY_NODES = _cfg["MAX_STORY_NODES"]
    CONTEXT_WINDOW_NODES = _cfg["CONTEXT_WINDOW_NODES"]
    MAX_DECISIONS_PER_MINUTE = _cfg["MAX_DECISIONS_PER_MINUTE"]
    LLM_TEMPERATURE = _cfg["LLM_TEMPERATURE"]
    LLM_MAX_TOKENS = _cfg["LLM_MAX_TOKENS"]


config = Config()

# 每分钟决策次数（防刷），按 chat_id 滑动窗口
_rate_log: Dict[str, List[float]] = {}

class GameState:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.active = False
        self.story_opening = ""
        self.story_title = ""
        self.nodes = []
        self.last_activity = datetime.datetime.now()
        self.participants = set()
        self.runs_completed = 0
        self.last_ended_at = ""
        self.warned_no_ark_key = False
        self.warned_image_fail = False
        self.image_skips_this_run = 0
        self.save_path = SAVE_DIR / f"{chat_id}.json"

    def to_dict(self):
        return {
            "chat_id": self.chat_id,
            "active": self.active,
            "story_opening": self.story_opening,
            "story_title": self.story_title,
            "nodes": self.nodes,
            "last_activity": self.last_activity.isoformat(),
            "participants": list(self.participants),
            "runs_completed": int(self.runs_completed),
            "last_ended_at": str(self.last_ended_at or ""),
            "warned_no_ark_key": bool(self.warned_no_ark_key),
            "warned_image_fail": bool(self.warned_image_fail),
            "image_skips_this_run": int(self.image_skips_this_run),
        }

    @classmethod
    def from_dict(cls, data):
        s = cls(data["chat_id"])
        s.active = data.get("active", False)
        s.story_opening = data.get("story_opening", "")
        s.story_title = data.get("story_title", "")
        s.nodes = data.get("nodes", [])
        s.last_activity = datetime.datetime.fromisoformat(
            data.get("last_activity", datetime.datetime.now().isoformat())
        )
        s.participants = set(data.get("participants", []))
        s.runs_completed = int(data.get("runs_completed", 0))
        s.last_ended_at = str(data.get("last_ended_at", "") or "")
        s.warned_no_ark_key = bool(data.get("warned_no_ark_key", False))
        s.warned_image_fail = bool(data.get("warned_image_fail", False))
        s.image_skips_this_run = int(data.get("image_skips_this_run", 0))
        return s

    def save(self):
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def add_node(self, player_id, decision, narrative, scene="", image_url=""):
        self.nodes.append({
            "index": len(self.nodes) + 1,
            "player_id": player_id,
            "decision": decision,
            "narrative": narrative,
            "scene": scene,
            "image_url": image_url,
            "timestamp": datetime.datetime.now().isoformat(),
        })
        self.participants.add(player_id)
        self.last_activity = datetime.datetime.now()
        self.save()

games: Dict[str, GameState] = {}

def load_game(chat_id):
    if chat_id not in games:
        path = SAVE_DIR / f"{chat_id}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                games[chat_id] = GameState.from_dict(json.load(f))
        else:
            games[chat_id] = GameState(chat_id)
    return games[chat_id]

# ============================================================
# 飞书消息发送
# ============================================================
def run_lark_cli(args: List[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [_lark_cli(), *args],
        cwd=str(PROJECT_ROOT),
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "(无输出)"
        print(f"[ERROR] lark-cli {' '.join(args[:2])} 失败: {detail}", flush=True)
    return result


def send_text(chat_id, text) -> bool:
    """
    发送文本消息。
    用 --content JSON + --msg-type text：json.dumps 将 \\n 编码为两字符转义序列，
    命令行传参不含真实换行符，完全规避 Windows 下多行文本被截断的问题。
    """
    if DEBUG_EVENTS:
        preview = text[:120].replace("\n", "↵")
        print(f"[DEBUG] → send_text chat={chat_id} | {preview}", flush=True)
    content_json = json.dumps({"text": text or ""}, ensure_ascii=False)
    result = run_lark_cli(
        ["im", "+messages-send", "--as", "bot", "--chat-id", chat_id,
         "--content", content_json, "--msg-type", "text"],
    )
    if DEBUG_EVENTS:
        print(f"[DEBUG] ← send_text rc={result.returncode}", flush=True)
    return result.returncode == 0

def send_image(chat_id, image_url):
    try:
        resp = requests.get(image_url, timeout=120)
        resp.raise_for_status()
        name = f"send_{int(time.time() * 1000)}.png"
        local_path = IMAGE_SEND_CACHE / name
        local_path.write_bytes(resp.content)
        rel = "./" + local_path.relative_to(PROJECT_ROOT).as_posix()
        result = run_lark_cli(
            [
                "im",
                "+messages-send",
                "--as",
                "bot",
                "--chat-id",
                chat_id,
                "--image",
                rel,
            ],
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[WARN] 发送图片失败: {e}")
        return False

# ============================================================
# 游戏逻辑
# ============================================================
SYSTEM_PROMPT = (
    "你是一个互动叙事游戏的主持人（Game Master）。"
    "基于玩家输入生成下一段剧情（200-400字），使用中文，有画面感。"
    "每次输出 JSON：scene（场景）、narrative（剧情）、mood（氛围英文词）、choices（2-4个选项）。"
)

OPTIONS_ONLY_PROMPT = (
    SYSTEM_PROMPT
    + " 当前为「仅列选项」模式：不要推进剧情、不要写新的故事段落，narrative 用一句简短引导即可；"
    "重点给出 choices 数组（2-4 条可执行行动）。"
)


def _normalize_cmd_text(text: str) -> str:
    """统一飞书侧可能出现的兼容字符、零宽字符，避免指令正则漏匹配。"""
    s = unicodedata.normalize("NFKC", (text or "").strip())
    for ch in ("\ufeff", "\u200b", "\u200c", "\u200d", "\u2060"):
        s = s.replace(ch, "")
    return s.strip()


def _spaced_cmd(phrase: str) -> str:
    """指令词各字之间允许 IME 插入空白（如「导 出 故 事」「结 束游 戏」）。"""
    return r"\s*".join(re.escape(c) for c in phrase)


def _flex_marker_regex(mk: str) -> str:
    """@ 后切分用：英文短语用 \\s+；中文用 spaced。"""
    mk = mk.strip()
    if mk.lower() == "butterfly effect":
        return r"butterfly\s+effect"
    return _spaced_cmd(mk)


_POLITE_PREFIX = r"^[\s请帮麻烦祝，,。]*"
_COMMAND_TAIL = r"(\s*吧)?(\s*谢谢)?[\s\?？!！。，,…]*$"


def _match_command_phrase(text: str, phrase: str) -> Optional[re.Match]:
    return re.match(rf"{_POLITE_PREFIX}{_spaced_cmd(phrase)}", text)


def _is_fixed_command(text: str, phrase: str) -> bool:
    return bool(re.match(rf"{_POLITE_PREFIX}{_spaced_cmd(phrase)}{_COMMAND_TAIL}", text))


def _parse_incoming_command(text: str) -> Tuple[str, str]:
    """
    返回 (command, argument)。command 为空表示剧情决策。
    固定口令必须整行匹配；如「导出故事：这是一段剧情」会落入剧情决策。
    """
    t = _normalize_cmd_text(text)
    if re.match(r"^(帮助|指令|菜单|help|\?|／\?)$", t, re.I):
        return "help", ""
    if re.match(r"^(蝴蝶效应|butterfly\s*effect)[\s\?？!！。…]*$", t, re.I):
        return "help", ""

    m = _match_command_phrase(t, "开始游戏")
    if m:
        story = t[m.end() :].strip() or "一群冒险者踏上了旅途"
        return "start", story

    m = _match_command_phrase(t, "新游戏")
    if m:
        story = re.sub(_COMMAND_TAIL, "", t[m.end() :].strip()).strip()
        return "start", story or "一群冒险者踏上了旅途"

    fixed = {
        "结束游戏": "end",
        "导出故事": "export",
        "导出梗概": "outline",
        "游戏状态": "status",
        "重新开始": "restart",
        "回溯": "undo",
    }
    for phrase, cmd in fixed.items():
        if _is_fixed_command(t, phrase):
            return cmd, ""

    for phrase in ("行动选项", "看选项", "选项"):
        if _is_fixed_command(t, phrase):
            return "options", ""

    return "", t


# ============================================================
# AI 指令分类器（DeepSeek fallback）
# ============================================================
_CMD_CLASSIFY_PROMPT = (
    "你是飞书群游戏「蝴蝶效应」的指令分类器。\n"
    "玩家发来一段文本，返回 JSON：{\"command\": \"<cmd>\", \"argument\": \"<arg>\"}\n\n"
    "command 只能取以下之一：\n"
    "  help     — 帮助/指令菜单（如「帮我」「菜单」「help」「?」）\n"
    "  start    — 开始/新游戏（如「新局」「开局」「重新来过」）argument=故事开场（可为空）\n"
    "  end      — 结束游戏（如「结束」「结束本局」「game over」）\n"
    "  export   — 导出全文（如「导出」「存档」「保存故事」）\n"
    "  outline  — 导出梗概（如「梗概」「摘要」「outline」）\n"
    "  status   — 游戏状态（如「进度」「状态」「status」）\n"
    "  restart  — 重新开始（如「清空」「重来」「重置」）\n"
    "  undo     — 回溯上一幕（如「撤销」「undo」「返回」）\n"
    "  options  — 查看行动选项（如「选项」「有什么选择」「options」）\n"
    "  decision — 剧情决策，argument=玩家行动原文（非以上任何指令时）\n\n"
    "规则：只返回 JSON，不要多余文字。"
)

_VALID_CMDS = frozenset(("help", "start", "end", "export", "outline", "status", "restart", "undo", "options", "decision"))


def _ai_classify_command(text: str) -> Tuple[str, str]:
    """用 DeepSeek 对指令进行语义分类，作为 regex 的 fallback。返回 (command, argument)。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "", text
    url = os.getenv("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": _CMD_CLASSIFY_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "max_tokens": 80,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        obj = json.loads(raw)
        cmd = str(obj.get("command") or "").strip().lower()
        arg = str(obj.get("argument") or "").strip()
        if cmd not in _VALID_CMDS:
            return "", text
        if cmd == "decision":
            return "", arg or text
        return cmd, arg
    except Exception as e:
        print(f"[WARN] AI 指令分类失败: {e}", flush=True)
    return "", text


# @机器人新游戏（中间无空格）时，^@\S+\s+ 无法匹配；用「指令词」在 @ 后定位切口（最长优先减少误切）
_AT_CUT_MARKERS: tuple[str, ...] = tuple(
    sorted(
        (
            "开始游戏",
            "导出故事",
            "导出梗概",
            "结束游戏",
            "游戏状态",
            "重新开始",
            "行动选项",
            "看选项",
            "蝴蝶效应",
            "butterfly effect",
            "新游戏",
            "选项",
            "回溯",
            "帮助",
            "菜单",
            "指令",
        ),
        key=len,
        reverse=True,
    )
)


def _strip_at_mentions(text: str) -> str:
    """
    去掉飞书群聊里常见的 @机器人 / @用户 前缀，避免指令匹配失败。
    支持以下格式：
      - @nickname command         （有空格）
      - @nickname command          （无空格，如 @傻妞新游戏）
      - <at id="ou_xxx">name</at> command  （富文本 XML 标签）
      - @_user_1 command           （compact 内部占位符）
    """
    t = (text or "").strip()
    # 1. 先去掉 Feishu 富文本 <at ...>...</at> 标签（出现在消息内容原始字符串里）
    t = re.sub(r"<at[^>]*>[^<]*</at>", "", t).strip()
    while True:
        if t.startswith("@"):
            tl = t.casefold()
            # 优先：找已知指令词在 @ 后的位置，精确切口（防止把指令首字吃掉）
            best: Optional[int] = None
            for mk in _AT_CUT_MARKERS:
                pat = _flex_marker_regex(mk)
                mloc = re.search(pat, tl, re.I if mk.isascii() else 0)
                idx = mloc.start() if mloc else -1
                if idx > 1:
                    if best is None or idx < best:
                        best = idx
            if best is not None:
                t = t[best:].strip()
                continue
            # 后备：直接按 @word<space> 剥离
            n = re.sub(r"^@\S+\s+", "", t).strip()
            if n != t:
                t = n
                continue
            # @word 后紧跟指令（无空格且指令不在上面的 markers 中）——整体剥离 @ 前缀词
            n = re.sub(r"^@\S+", "", t).strip()
            if n != t:
                t = n
                continue
        break
    return t


def _rate_allow(chat_id: str) -> bool:
    lim = max(1, int(config.MAX_DECISIONS_PER_MINUTE))
    now = time.time()
    log = _rate_log.setdefault(chat_id, [])
    log[:] = [x for x in log if now - x < 60.0]
    if len(log) >= lim:
        return False
    log.append(now)
    return True


def _maybe_auto_pause(chat_id: str, state: "GameState") -> bool:
    """超时无操作则暂停并提示。返回 True 表示已暂停，调用方应停止处理本条。"""
    if not state.active or not state.nodes:
        return False
    idle = (datetime.datetime.now() - state.last_activity).total_seconds()
    if idle <= float(config.INACTIVITY_TIMEOUT):
        return False
    state.active = False
    state.save()
    send_text(
        chat_id,
        f"已超过 {config.INACTIVITY_TIMEOUT // 60} 分钟无操作，本局已自动暂停。"
        "发送「开始游戏 …」开新局，或「重新开始」清空后再开局。",
    )
    return True


HELP_TEXT = (
    "【蝴蝶效应 · 指令】\n"
    "• 开始游戏 … ｜ 新游戏 … — 开局（可用 preset:键名 或 #键名 载入 config 预设）\n"
    "• 任意描述 — 推进剧情（需本局进行中）\n"
    "• 游戏状态 — 当前进度摘要\n"
    "• 选项 — 只看 2～4 个行动方向\n"
    "• 回溯 — 回到上一幕\n"
    "• 重新开始 — 清空本局剧情（累计通关局数保留）\n"
    "• 导出故事 — 导出全文飞书文档（不结束）\n"
    "• 导出梗概 — 导出压缩梗概文档（不结束，可能调用 LLM）\n"
    "• 结束游戏 — 结束并导出全文\n"
    "• 帮助 — 显示本说明"
)


def send_help(chat_id: str) -> None:
    extra = ""
    if PRESETS:
        keys = "、".join(sorted(PRESETS.keys())[:16])
        more = " …" if len(PRESETS) > 16 else ""
        extra = f"\n\n当前预设键：{keys}{more}"
    send_text(chat_id, HELP_TEXT + extra)


def _player_plot_turns(state: "GameState") -> int:
    """玩家推进剧情的次数（不含开局幕「[开始]」），用于配图间隔，避免把开局算进 N 幕一张图。"""
    return sum(1 for n in state.nodes if n.get("decision") != "[开始]")


def _route_incoming_message(chat_id: str, sender_id: str, text: str) -> None:
    """
    指令路由：
    1. 先用 regex 快速匹配（零延迟）
    2. regex 未识别（剧情决策）时，若文本较短（<= 20 字）则尝试 AI 分类
       避免对长文剧情段落走 AI（必定是决策，加 AI 反而慢）
    """
    command, arg = _parse_incoming_command(text)

    # regex 未命中，且文本足够短（可能是指令变体），用 AI 再判断
    if not command and len(text) <= 20:
        ai_cmd, ai_arg = _ai_classify_command(text)
        if ai_cmd:
            command, arg = ai_cmd, ai_arg
            if DEBUG_EVENTS:
                print(f"[DEBUG] AI 分类: {repr(text)} → {command!r} arg={arg!r}", flush=True)

    if command == "help":
        send_help(chat_id)
        return
    if command == "start":
        handle_start(chat_id, sender_id, arg)
        return
    if command == "end":
        handle_end(chat_id)
        return
    if command == "export":
        handle_export_only(chat_id)
        return
    if command == "outline":
        handle_export_outline(chat_id)
        return
    if command == "status":
        handle_status(chat_id)
        return
    if command == "restart":
        handle_restart(chat_id)
        return
    if command == "undo":
        handle_undo(chat_id)
        return
    if command == "options":
        handle_options(chat_id)
        return
    handle_decision(chat_id, sender_id, arg)


def handle_start(chat_id, player_id, story):
    state = load_game(chat_id)
    if state.active:
        send_text(chat_id, "已有进行中的游戏")
        return
    seed, title_hint, preset_key = _resolve_story_seed(story)
    if preset_key == "__missing__":
        send_text(
            chat_id,
            "未找到该预设。请发送「帮助」查看 config.yaml 中的预设键（preset:键名 或 #键名）。",
        )
        return
    if not seed:
        send_text(chat_id, "开局内容为空，请补充故事开头或使用预设。")
        return
    result = generate_story(SYSTEM_PROMPT, f"新故事：{seed}")
    narrative = (result.get("narrative") or "").strip()
    if not narrative or narrative.startswith("（"):
        send_text(chat_id, narrative or "开局失败，请稍后再试。")
        return
    # 「结束游戏」只置 inactive，不删节点；新开局必须清空，否则导出会把上一局与当前局拼在同一文档
    state.nodes = []
    state.participants = set()
    state.active = True
    state.story_opening = seed
    state.story_title = title_hint or ((seed[:40] + "…") if len(seed) > 40 else seed)
    state.warned_no_ark_key = False
    state.warned_image_fail = False
    state.image_skips_this_run = 0
    state.save()
    state.add_node(player_id, "[开始]", narrative, result.get("scene", ""))
    choices = "\n".join(f"- {c}" for c in result.get("choices", []))
    send_text(chat_id, f"{narrative}\n\n你可以：\n{choices}")

def handle_decision(chat_id, player_id, decision):
    state = load_game(chat_id)
    if not state.active:
        send_text(chat_id, "当前无进行中的游戏。发送「开始游戏 …」或「帮助」。")
        return
    if _maybe_auto_pause(chat_id, state):
        return
    if not _rate_allow(chat_id):
        send_text(chat_id, "操作太频繁，请稍等一分钟再试。")
        return
    if state.nodes:
        last_nv = (state.nodes[-1].get("narrative") or "").strip()
        if last_nv and last_nv == (decision or "").strip():
            print("[INFO] 跳过与上一段剧情相同的内容（多为机器人消息被误收）", flush=True)
            return
    n_hist = max(1, int(config.CONTEXT_WINDOW_NODES))
    history = "\n".join(
        f"决策：{n['decision']}\n剧情：{n['narrative']}" for n in state.nodes[-n_hist:]
    )
    result = generate_story(SYSTEM_PROMPT, f"历史：{history}\n新决策：{decision}")
    narrative = (result.get("narrative") or "").strip() or "（剧情暂时空白）"
    state.add_node(player_id, decision, narrative, result.get("scene", ""))
    choices = result.get("choices") or []
    if choices:
        choices_text = "\n".join(f"- {c}" for c in choices)
        send_text(chat_id, f"{narrative}\n\n你可以：\n{choices_text}")
    else:
        send_text(chat_id, narrative)
    # 仅按「玩家剧情决策次数」配图：开局幕不计入；管理指令不会进此分支
    turns = _player_plot_turns(state)
    if turns > 0 and turns % config.IMAGE_GEN_INTERVAL == 0:
        img_prompt = f"{result.get('scene', '')} {result.get('mood', '')}"
        if not (os.getenv("ARK_API_KEY") or "").strip():
            state.image_skips_this_run = int(getattr(state, "image_skips_this_run", 0)) + 1
            if not state.warned_no_ark_key:
                n = state.image_skips_this_run
                send_text(
                    chat_id,
                    f"（已到配图节点：未配置 ARK_API_KEY，本局已累计跳过 {n} 次配图。"
                    "后续跳过不再逐条刷屏，可发「游戏状态」查看累计。）",
                )
                state.warned_no_ark_key = True
            state.save()
        else:
            url = generate_image(img_prompt)
            if url:
                send_image(chat_id, url)
                state.nodes[-1]["image_url"] = url
                state.save()
            else:
                state.image_skips_this_run = int(getattr(state, "image_skips_this_run", 0)) + 1
                if not state.warned_image_fail:
                    n = state.image_skips_this_run
                    send_text(
                        chat_id,
                        f"（配图生成未成功，本局已累计跳过 {n} 次配图。"
                        "可检查 Ark 配额与网络；后续见「游戏状态」。）",
                    )
                    state.warned_image_fail = True
                state.save()
    if len(state.nodes) >= config.MAX_STORY_NODES:
        handle_end(chat_id)

def handle_end(chat_id):
    state = load_game(chat_id)
    if state.active:
        state.active = False
        md = build_markdown(state)
        local_archive = save_finished_markdown(state, md)
        url = export_to_feishu_doc(state.story_title, md)
        state.runs_completed = int(getattr(state, "runs_completed", 0)) + 1
        state.last_ended_at = datetime.datetime.now().replace(microsecond=0).isoformat()
        sk = int(getattr(state, "image_skips_this_run", 0))
        skip_line = f"\n本局跳过配图 {sk} 次。" if sk else ""
        export_line = (
            f"飞书文档：{url}"
            if url
            else "飞书导出失败（请检查 lark-cli 与 docs 权限），已保留本地 Markdown 快照。"
        )
        send_text(
            chat_id,
            f"游戏结束，{export_line}"
            f"\n本地快照：{local_archive}"
            f"\n累计完成 {state.runs_completed} 局。{skip_line}".rstrip(),
        )
        state.save()
    else:
        send_text(chat_id, "当前没有进行中的游戏。若要导出已有进度，请发送「导出故事」。")


def handle_status(chat_id):
    state = load_game(chat_id)
    if state.active and state.nodes and _maybe_auto_pause(chat_id, state):
        return
    rc = int(getattr(state, "runs_completed", 0))
    if not state.active:
        ended = str(getattr(state, "last_ended_at", "") or "").strip()
        end_hint = f" 上次结束：{ended}。" if ended else ""
        if rc:
            send_text(
                chat_id,
                f"当前没有进行中的游戏。本群累计通关 {rc} 局。{end_hint.strip()} 发送「开始游戏 …」开局。",
            )
        elif ended:
            send_text(
                chat_id,
                f"当前没有进行中的游戏。上次结束：{ended}。发送「开始游戏 …」开局。",
            )
        else:
            send_text(chat_id, "当前没有进行中的游戏。发送「开始游戏 …」开局。")
        return
    n = len(state.nodes)
    last = state.nodes[-1]
    participants = "、".join(sorted(state.participants)[:8])
    more = f"等共 {len(state.participants)} 人" if len(state.participants) > 8 else ""
    rc_line = f" | 累计通关 {rc} 局" if rc else ""
    sk = int(getattr(state, "image_skips_this_run", 0))
    skip_line = f"\n本局已跳过配图 {sk} 次（无 Ark 或生成失败）。" if sk else ""
    send_text(
        chat_id,
        f"【游戏状态】第 {n} 幕{rc_line} | 参与者：{participants}{more}{skip_line}\n"
        f"最近决策：{last.get('decision', '')}\n\n{last.get('narrative', '')}",
    )


def handle_restart(chat_id):
    state = load_game(chat_id)
    state.active = False
    state.story_opening = ""
    state.story_title = ""
    state.nodes = []
    state.participants = set()
    state.warned_no_ark_key = False
    state.warned_image_fail = False
    state.image_skips_this_run = 0
    state.save()
    send_text(chat_id, "已清空本局进度。发送「开始游戏 …」重新开局。")


def handle_options(chat_id):
    state = load_game(chat_id)
    if not state.active or not state.nodes:
        send_text(chat_id, "请先「开始游戏」后再要选项。")
        return
    if _maybe_auto_pause(chat_id, state):
        return
    if not _rate_allow(chat_id):
        send_text(chat_id, "操作太频繁，请稍等一分钟再试。")
        return
    last = state.nodes[-1].get("narrative", "")
    result = generate_story(
        OPTIONS_ONLY_PROMPT,
        f"当前停在如下剧情，请只输出行动选项，不要推进故事：\n{last}",
    )
    choices = "\n".join(f"- {c}" for c in result.get("choices", []))
    send_text(chat_id, f"可参考的方向：\n{choices}")


def handle_undo(chat_id):
    state = load_game(chat_id)
    if state.active and state.nodes and _maybe_auto_pause(chat_id, state):
        return
    if not state.active:
        send_text(chat_id, "没有进行中的游戏。")
        return
    if len(state.nodes) <= 1:
        send_text(chat_id, "已是第一幕，无法继续回溯。")
        return
    state.nodes.pop()
    state.save()
    if state.nodes:
        prev = state.nodes[-1]
        send_text(
            chat_id,
            f"已回溯到第 {prev['index']} 幕。\n\n{prev.get('narrative', '')}",
        )
    else:
        send_text(chat_id, "已清空节点（异常状态）。")


def handle_export_only(chat_id):
    state = load_game(chat_id)
    if not state.nodes:
        send_text(chat_id, "还没有剧情可导出。")
        return
    md = build_markdown(state)
    title = state.story_title or f"蝴蝶效应-{datetime.datetime.now().strftime('%Y%m%d-%H%M')}"
    local_archive = save_finished_markdown(state, md)
    url = export_to_feishu_doc(title, md)
    send_text(
        chat_id,
        f"已导出飞书文档（游戏未结束）：{url or '（失败，请检查 lark-cli）'}"
        f"\n本地快照：{local_archive}",
    )


def handle_export_outline(chat_id):
    state = load_game(chat_id)
    if not state.nodes:
        send_text(chat_id, "还没有剧情可导出。")
        return
    if not _rate_allow(chat_id):
        send_text(chat_id, "操作太频繁，请稍等一分钟再试。")
        return
    blob = build_compact_story_blob(state)
    summary = _generate_llm_outline(blob) if (os.getenv("DEEPSEEK_API_KEY") or "").strip() else ""
    if summary.strip():
        md = f"## 梗概\n\n{summary.strip()}"
    else:
        md = build_rule_based_outline(state)
    base = state.story_title or f"蝴蝶效应-{datetime.datetime.now().strftime('%Y%m%d-%H%M')}"
    url = export_to_feishu_doc(f"{base}-梗概", md)
    send_text(
        chat_id,
        f"已导出飞书文档（梗概，游戏未结束）：{url or '（失败，请检查 lark-cli）'}",
    )


# ============================================================
# 事件监听主循环
# ============================================================
DEBUG_EVENTS = (os.getenv("BUTTERFLY_DEBUG") or "").strip().lower() in ("1", "true", "yes")


def _extract_text_content(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or "").strip()
    return str(value or "").strip()


def _extract_message_event(raw: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """
    从 compact 或原始 envelope 中提取 (chat_id, sender_id, text)。返回 None 表示应忽略。
    compact 格式字段：type / event_type / message_type / chat_id / sender_id / sender_type / content
    envelope 格式字段：event.sender.* / event.message.*
    """
    # compact 格式——lark-cli event +subscribe --compact 输出
    ev_type = raw.get("type") or raw.get("event_type") or ""
    if ev_type == "im.message.receive_v1":
        msg_type = raw.get("message_type") or raw.get("msg_type") or ""
        if msg_type and msg_type != "text":
            return None
        sender_type = (raw.get("sender_type") or "").lower()
        if sender_type == "app":
            return None
        bot_id = (os.getenv("FEISHU_BOT_OPEN_ID") or "").strip()
        sender_id = str(raw.get("sender_id") or raw.get("open_id") or "").strip()
        if bot_id and sender_id == bot_id:
            return None
        chat_id = str(raw.get("chat_id") or "").strip()
        text = _extract_text_content(raw.get("content") or raw.get("text") or "")
        return chat_id, sender_id, text

    # envelope 格式（未加 --compact 时的原始结构）
    event = raw.get("event") or {}
    if not event:
        return None
    sender = event.get("sender") or {}
    sender_type = (sender.get("sender_type") or "").lower()
    if sender_type == "app":
        return None
    msg = event.get("message") or {}
    content_raw = msg.get("content", "{}")
    try:
        content = json.loads(content_raw) if isinstance(content_raw, str) else (content_raw or {})
    except json.JSONDecodeError:
        content = {}
    return (
        str(msg.get("chat_id") or "").strip(),
        str((sender.get("sender_id") or {}).get("open_id") or "").strip(),
        _extract_text_content(content),
    )


def _process_event_line(line: str) -> None:
    line = line.strip()
    if not line:
        return
    # lark-cli 进度行（如 "[1] im.message.receive_v1"）不是 JSON，直接跳过
    if not line.startswith("{"):
        return
    try:
        raw = json.loads(line)
        if DEBUG_EVENTS:
            print(f"[DEBUG] event keys={list(raw.keys())} | {line[:400]}", flush=True)
        if raw.get("ok") is False:
            err = raw.get("error") or {}
            msg = err.get("message", str(raw))
            print(f"[ERROR] lark-cli: {msg}")
            if "another event +subscribe" in msg or "Only one subscriber" in msg:
                print(
                    "提示：请先结束其它正在运行的 `lark-cli event +subscribe`（或其它终端里的本引擎），"
                    "或确认无旧进程后再启动。若你清楚风险，可用: python scripts/game-engine.py --force-subscribe"
                )
            return

        extracted = _extract_message_event(raw)
        if not extracted:
            return
        chat_id, sender_id, text = extracted

        if not chat_id:
            print("[DEBUG] 忽略：chat_id 为空", flush=True) if DEBUG_EVENTS else None
            return
        if not text:
            print("[DEBUG] 忽略：text 为空", flush=True) if DEBUG_EVENTS else None
            return

        text = _strip_at_mentions(text)
        if not text:
            return
        if DEBUG_EVENTS:
            print(f"[DEBUG] routing: chat={chat_id} text={repr(text)}", flush=True)

        _route_incoming_message(chat_id, sender_id, text)
    except Exception as e:
        print(f"[WARN] 解析事件错误: {e}", flush=True)


def watch_events(force_subscribe: bool = False):
    cmd = [
        _lark_cli(),
        "event",
        "+subscribe",
        "--as",
        "bot",
        "--compact",
        "--event-types",
        "im.message.receive_v1",
    ]
    if force_subscribe:
        cmd.append("--force")
    _cleanup_temp_files()
    print(
        "蝴蝶效应引擎：正在启动 lark-cli 订阅（连接日志在下方；无群消息时几乎无新输出）。Ctrl+C 退出。\n",
        flush=True,
    )
    listener = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=None,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert listener.stdout is not None
    try:
        for line in listener.stdout:
            _process_event_line(line)
    except KeyboardInterrupt:
        listener.terminate()
        print("游戏引擎已停止。")
        return
    listener.wait()
    if listener.returncode != 0:
        print(
            "\n[提示] 若上方提示「another event +subscribe」：\n"
            "  • 等待约 30 秒后重新运行（旧连接会自动超时）\n"
            "  • 或加 --force-subscribe 参数强制启动",
            flush=True,
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="蝴蝶效应 — 飞书群聊叙事游戏引擎")
    parser.add_argument(
        "--force-subscribe",
        action="store_true",
        help="将 --force 传给 lark-cli（已有订阅进程时仍启动；可能导致多实例分片收事件，非必要勿用）",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="打印每条原始事件 JSON 及路由决策，用于排查指令识别问题",
    )
    args = parser.parse_args()
    if args.debug:
        globals()["DEBUG_EVENTS"] = True
        print("[DEBUG 模式已启用] 每条事件将打印原始 JSON 及路由信息\n", flush=True)
    watch_events(force_subscribe=args.force_subscribe)