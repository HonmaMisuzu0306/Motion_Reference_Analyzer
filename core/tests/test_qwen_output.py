"""Qwen request/response regressions; transport fixtures never load a model."""

import json

import httpx
import pytest
from PIL import Image

from schemas.typography import TypographyAnalysis
from schemas.vision import VisionAnalysis
from vision.provider import ShotContext
from vision.qwen import QwenVisionProvider


@pytest.mark.parametrize("typography", [False, True])
def test_json_generation_closes_thinking_and_constrains_output(tmp_path, typography):
    image = tmp_path / "frame.jpg"
    Image.new("RGB", (40, 40)).save(image)
    requests = []
    expected = TypographyAnalysis(role="title", confidence=.9) if typography else VisionAnalysis()

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": expected.model_dump_json()},
            "done": True, "done_reason": "stop", "eval_count": 100,
        })

    provider = QwenVisionProvider()
    provider._client.close()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider._client = client
        if typography:
            result = provider.analyze_text_region(image, (.1, .1, .5, .5), "TITLE", {})
        else:
            result = provider.analyze_shot([image], ShotContext(
                shot_id="shot", start_time=0, end_time=1, frame_count=1,
            ))
    assert not result.analysis_error
    payload = requests[0]
    assert payload["messages"][-1] == {"role": "assistant", "content": "<think>\n\n</think>\n\n"}
    assert payload["format"]["type"] == "object"
    assert payload["format"]["required"]
    assert payload["messages"][-2]["images"]
    assert payload["options"]["num_ctx"] == 16384


@pytest.mark.parametrize("typography", [False, True])
def test_truncated_generation_is_explicit_even_with_parseable_json(tmp_path, typography):
    image = tmp_path / "frame.jpg"
    Image.new("RGB", (40, 40)).save(image)

    def respond(request):
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": "{}", "thinking": "unfinished reasoning"},
            "done": True, "done_reason": "length", "eval_count": 8192,
        })

    provider = QwenVisionProvider()
    provider._client.close()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider._client = client
        if typography:
            result = provider.analyze_text_region(image, (.1, .1, .5, .5), "TITLE", {})
        else:
            result = provider.analyze_shot([image], ShotContext(
                shot_id="shot", start_time=0, end_time=1, frame_count=1,
            ))
    assert result.analysis_error and "length" in result.analysis_error
