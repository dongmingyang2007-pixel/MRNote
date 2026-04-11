import pytest

from app.services.dashscope_client import UpstreamServiceError
from app.services.dashscope_responses import _build_responses_payload, _parse_responses_result
from app.services.llm_tools import get_response_function_tools


def test_response_function_tools_use_openai_compatible_object_schema() -> None:
    tools_by_name = {tool["name"]: tool for tool in get_response_function_tools()}

    datetime_schema = tools_by_name["get_current_datetime"]["parameters"]
    assert datetime_schema["type"] == "object"
    assert datetime_schema["required"] == []
    assert datetime_schema["additionalProperties"] is False

    knowledge_schema = tools_by_name["search_project_knowledge"]["parameters"]
    assert knowledge_schema["required"] == ["query"]
    assert knowledge_schema["additionalProperties"] is False


def test_build_responses_payload_omits_tool_choice_without_tools() -> None:
    payload = _build_responses_payload(
        input_items=[{"role": "user", "content": "hello"}],
        model="qwen3-max",
        enable_thinking=False,
        tools=None,
        tool_choice="auto",
        stream=False,
    )

    assert "tool_choice" not in payload
    assert "tools" not in payload


def test_parse_responses_result_raises_for_failed_payload() -> None:
    with pytest.raises(
        UpstreamServiceError,
        match="server_error: <400> InternalError.Algo.InvalidParameter",
    ):
        _parse_responses_result(
            {
                "status": "failed",
                "error": {
                    "code": "server_error",
                    "message": (
                        "<400> InternalError.Algo.InvalidParameter: "
                        "The parameters, when provided as a dict, must confirm "
                        "to a valid openai-compatible JSON schema."
                    ),
                },
                "output": [],
            }
        )


def test_parse_responses_result_extracts_image_and_extractor_sources() -> None:
    result = _parse_responses_result(
        {
            "status": "completed",
            "output": [
                {
                    "type": "web_search_image_call",
                    "results": [
                        {
                            "title": "Blue Topology Background",
                            "source_url": "https://images.example.com/topology",
                            "image_url": "https://cdn.example.com/topology.jpg",
                            "thumbnail_url": "https://cdn.example.com/topology-thumb.jpg",
                            "summary": "Abstract blue topology background.",
                        }
                    ],
                },
                {
                    "type": "web_extractor_call",
                    "action": {
                        "results": [
                            {
                                "title": "Aliyun Tool Docs",
                                "url": "https://help.aliyun.com/zh/model-studio/web-search-image",
                                "summary": "Web search image documentation.",
                            }
                        ]
                    },
                },
            ],
        }
    )

    assert len(result.search_sources) == 2
    image_source = next(source for source in result.search_sources if source.image_url)
    assert image_source.tool_type == "web_search_image"
    assert image_source.image_url == "https://cdn.example.com/topology.jpg"
    assert image_source.thumbnail_url == "https://cdn.example.com/topology-thumb.jpg"
    assert image_source.url == "https://images.example.com/topology"

    extractor_source = next(
        source
        for source in result.search_sources
        if source.url == "https://help.aliyun.com/zh/model-studio/web-search-image"
    )
    assert extractor_source.tool_type == "web_extractor"
