import base64

import requests

from ..http_errors import raise_for_status


def _post(url, api_key, service, timeout, **kwargs):
    response = requests.post(url, timeout=timeout, **kwargs)
    raise_for_status(response, api_key, service)
    return response.json()


def _decode_b64_items(data, service):
    images = [base64.b64decode(item["b64_json"]) for item in data.get("data", []) if item.get("b64_json")]
    if not images:
        raise RuntimeError(f"{service} response did not contain an image.")
    return images


def openai_generate(base_url, api_key, prompt, params, images, mask_png, timeout):
    headers = {"Authorization": f"Bearer {api_key}"}
    if not images:
        data = _post(f"{base_url}/images/generations", api_key, "OpenAI", timeout, headers=headers, json={"prompt": prompt, **params})
        return _decode_b64_items(data, "OpenAI")
    files = [("image[]", (f"image_{index}.png", png, "image/png")) for index, png in enumerate(images)]
    if mask_png is not None:
        files.append(("mask", ("mask.png", mask_png, "image/png")))
    form = {"prompt": prompt, **{key: str(value) for key, value in params.items()}}
    data = _post(f"{base_url}/images/edits", api_key, "OpenAI", timeout, headers=headers, data=form, files=files)
    return _decode_b64_items(data, "OpenAI")


def gemini_generate(base_url, api_key, model, prompt, images, generation_config, timeout):
    parts = [{"text": prompt}] + [{"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png).decode()}} for png in images]
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": generation_config}
    data = _post(f"{base_url}/models/{model}:generateContent", api_key, "Gemini", timeout, headers={"x-goog-api-key": api_key}, json=body)
    result = []
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline:
                result.append(base64.b64decode(inline["data"]))
    if not result:
        reason = data.get("promptFeedback") or [candidate.get("finishReason") for candidate in data.get("candidates", [])]
        raise RuntimeError(f"Gemini response did not contain an image: {reason}")
    return result


def xai_generate(base_url, api_key, prompt, params, timeout):
    body = {"prompt": prompt, **params, "response_format": "b64_json"}
    data = _post(f"{base_url}/images/generations", api_key, "xAI", timeout, headers={"Authorization": f"Bearer {api_key}"}, json=body)
    return _decode_b64_items(data, "xAI")
