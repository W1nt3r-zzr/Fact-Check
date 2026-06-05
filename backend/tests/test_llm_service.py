import unittest
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import SearchResult
from routers.fact_check import _clean_assistant_reply
from services.llm_service import (
    build_assistant_llm_prompt,
    extract_structured_info_from_reasoning,
    sanitize_model_preamble,
)


class LLMServiceTextCleanupTest(unittest.TestCase):
    def test_sanitize_model_preamble_removes_role_chatter(self):
        text = (
            "好的，作为专业信息核查助手，以下是对该说法的可信度分析。\n\n"
            "### 1. 证据立场分析\n"
            "**证据 [1] [央视报道](https://example.com)** - 来源：**央视** - **立场**：**支持** - 分析：报道提及该事件。"
        )

        cleaned = sanitize_model_preamble(text)

        self.assertNotIn("好的，作为专业信息核查助手", cleaned)
        self.assertTrue(cleaned.startswith("### 1. 证据立场分析"))

    def test_extract_structured_reasoning_uses_cleaned_reasoning(self):
        reasoning = (
            "好的，作为专业信息核查助手，以下是对该说法的可信度分析。\n"
            "### 1. 证据立场分析\n"
            "**证据 [1] [央视报道](https://example.com)** - 来源：**央视** - **立场**：**支持** - 分析：报道提及该事件。"
        )

        result = extract_structured_info_from_reasoning(reasoning)

        self.assertNotIn("好的，作为专业信息核查助手", result["reasoning"])
        self.assertTrue(result["reasoning"].startswith("### 1. 证据立场分析"))

    def test_assistant_prompt_requests_plain_non_markdown_reply(self):
        prompt = build_assistant_llm_prompt(
            "6月1日起新规限制网约车司机驾驶时间",
            [
                SearchResult(
                    name="官方回应",
                    url="https://example.com/news",
                    summary="规则适用于道路交通事故调查处理环节。",
                    date_published="2026-06-01",
                    source="example",
                )
            ],
        )

        self.assertIn("普通 AI 助手侧栏展示", prompt)
        self.assertIn("不要使用 Markdown", prompt)
        self.assertIn("不要重复同一段摘要", prompt)
        self.assertIn("不要使用标题、编号、项目符号", prompt)

    def test_clean_assistant_reply_removes_markdown_labels_and_duplicate_summary(self):
        text = (
            "## 部分属实，存在争议\n\n"
            "【开头摘要】\n"
            "**关于该说法，经核查严重失实。** 该规则仅适用于事故调查。\n\n"
            "【开头摘要】\n"
            "**关于该说法，经核查严重失实。** 该规则仅适用于事故调查。\n\n"
            "- **核心事实提取**：官方回应见[报道](https://example.com)。"
        )

        cleaned = _clean_assistant_reply(text)

        self.assertNotIn("##", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("【开头摘要】", cleaned)
        self.assertNotIn("- ", cleaned)
        self.assertNotIn("](https://example.com)", cleaned)
        self.assertEqual(cleaned.count("关于该说法，经核查严重失实。"), 1)


if __name__ == "__main__":
    unittest.main()
