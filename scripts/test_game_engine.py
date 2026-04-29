#!/usr/bin/env python3
"""Lightweight regression tests for game-engine.py.

Run from project root:
    python scripts/test_game_engine.py
"""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "scripts" / "game-engine.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("butterfly_game_engine", ENGINE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_command_parser(engine):
    cases = {
        "导出故事": ("export", ""),
        "导 出 故 事": ("export", ""),
        "导出故事：这是剧情": ("", "导出故事:这是剧情"),
        "新 游戏": ("start", "一群冒险者踏上了旅途"),
        "请新 游戏吧": ("start", "一群冒险者踏上了旅途"),
        "开始游戏 沙漠": ("start", "沙漠"),
        "开 始 游 戏 沙漠": ("start", "沙漠"),
        "游戏状态谢谢": ("status", ""),
        "行 动 选 项": ("options", ""),
        "你好": ("", "你好"),
    }
    for text, expected in cases.items():
        assert engine._parse_incoming_command(text) == expected, text


def test_at_mention_strip(engine):
    cases = {
        "@机器人 新游戏": "新游戏",
        "@机器人新游戏": "新游戏",
        "@机器人导 出 故 事": "导 出 故 事",
        "@傻妞 开始游戏 沙漠": "开始游戏 沙漠",
        # 富文本 XML <at> 标签格式
        "<at id=\"ou_xxx\">傻妞</at> 导出故事": "导出故事",
        "<at id=\"ou_xxx\">傻妞</at>导出故事": "导出故事",
        # compact 内部占位符格式
        "@_user_1 新游戏": "新游戏",
        "@_user_1新游戏": "新游戏",
        # event_type 字段别名
    }
    for text, expected in cases.items():
        result = engine._strip_at_mentions(text)
        assert result == expected, f"strip({text!r}) = {result!r}, expected {expected!r}"


def test_event_type_alias(engine):
    """event_type 字段（compact 别名）也能被正确提取。"""
    ev = {
        "event_type": "im.message.receive_v1",
        "message_type": "text",
        "chat_id": "chat3",
        "sender_id": "ou_abc",
        "sender_type": "user",
        "content": "游戏状态",
    }
    result = engine._extract_message_event(ev)
    assert result == ("chat3", "ou_abc", "游戏状态"), repr(result)


def test_story_normalization(engine):
    out = engine._normalize_story_result({"narrative": "正文", "choices": "bad"})
    assert out["narrative"] == "正文"
    assert isinstance(out["choices"], list)
    assert out["choices"]


def test_event_extract(engine):
    compact_string = {
        "type": "im.message.receive_v1",
        "message_type": "text",
        "chat_id": "chat",
        "sender_id": "user",
        "sender_type": "user",
        "content": "帮助",
    }
    assert engine._extract_message_event(compact_string) == ("chat", "user", "帮助")

    compact_dict = dict(compact_string, content={"text": "导出故事"})
    assert engine._extract_message_event(compact_dict) == ("chat", "user", "导出故事")

    envelope = {
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_x"}},
            "message": {
                "chat_id": "chat2",
                "content": json.dumps({"text": "新游戏"}),
            },
        }
    }
    assert engine._extract_message_event(envelope) == ("chat2", "ou_x", "新游戏")

    app = dict(compact_string, sender_type="app")
    assert engine._extract_message_event(app) is None


def main():
    engine = load_engine()
    test_command_parser(engine)
    test_at_mention_strip(engine)
    test_story_normalization(engine)
    test_event_extract(engine)
    test_event_type_alias(engine)
    print("ok")


if __name__ == "__main__":
    main()
