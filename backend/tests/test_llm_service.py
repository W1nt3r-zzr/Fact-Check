import unittest
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.llm_service import extract_structured_info_from_reasoning, sanitize_model_preamble


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


if __name__ == "__main__":
    unittest.main()
