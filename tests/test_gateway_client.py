#!/usr/bin/env python3
"""网关响应解析的确定性回归测试，不发真实网络请求。"""

import json
import unittest

from scripts.gateway_client import _stream_content, _stream_parts


class GatewayResponseParsing(unittest.TestCase):
    def test_sse_ignores_reasoning_and_keeps_final_content(self):
        body = "\n".join([
            'data: ' + json.dumps({"choices": [{"delta": {"reasoning_content": "先检查"}}]}),
            'data: ' + json.dumps({"choices": [{"delta": {"content": '{"ok":true}'}}]}),
            "data: [DONE]",
        ])
        content, reasoning = _stream_parts(body)
        self.assertEqual(content, '{"ok":true}')
        self.assertEqual(reasoning, "先检查")
        self.assertEqual(_stream_content(body), '{"ok":true}')

    def test_reasoning_only_is_distinguishable_from_empty_response(self):
        body = 'data: ' + json.dumps({"choices": [{"delta": {"reasoning_content": "仍在推理"}}]})
        self.assertEqual(_stream_parts(body), ("", "仍在推理"))

    def test_plain_json_message_content_is_supported(self):
        body = json.dumps({"choices": [{"message": {"content": "done", "reasoning_content": "thought"}}]})
        self.assertEqual(_stream_parts(body), ("done", "thought"))


if __name__ == "__main__":
    unittest.main()
