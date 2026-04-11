import base64

from app.services.dashscope_client import raise_upstream_error
from app.services.dashscope_http import DASHSCOPE_BASE_URL, dashscope_headers, get_client


async def describe_image(
    image_bytes: bytes,
    prompt: str = "请详细描述这张图片的内容。",
    model: str | None = None,
) -> str:
    """Describe an image using DashScope Vision model.

    Args:
        image_bytes: Raw image data (JPEG, PNG, etc.)
        prompt: Question/instruction about the image
        model: Vision model ID (default: qwen-vl-plus)

    Returns:
        Text description of the image
    """
    model = model or "qwen-vl-plus"

    # Encode image as base64 data URL
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    try:
        client = get_client()
        response = await client.post(
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            headers=dashscope_headers(),
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}",
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
                "max_tokens": 1024,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)


async def chat_with_image(
    image_bytes: bytes,
    messages: list[dict],
    model: str | None = None,
) -> str:
    """Chat completion with an image (for multimodal LLMs like Qwen3.5-Plus).
    Inserts the image into the last user message.

    Args:
        image_bytes: Raw image data
        messages: Standard chat messages list (with system prompt, history, etc.)
        model: Model ID (must support vision, e.g. qwen3.5-plus)

    Returns:
        Assistant's response text
    """
    model = model or "qwen3.5-plus"
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Convert the last user message to multimodal format
    formatted_messages = []
    for msg in messages:
        if msg == messages[-1] and msg["role"] == "user":
            # Make the last user message multimodal
            formatted_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": msg["content"],
                    },
                ],
            })
        else:
            formatted_messages.append(msg)

    try:
        client = get_client()
        response = await client.post(
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            headers=dashscope_headers(),
            json={
                "model": model,
                "messages": formatted_messages,
                "max_tokens": 2048,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise_upstream_error(exc)
