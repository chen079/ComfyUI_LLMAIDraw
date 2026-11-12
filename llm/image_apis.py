import base64
import time

import requests

from ..http_errors import raise_for_status


def _post(url, api_key, service, timeout, **kwargs):
    response = requests.post(url, timeout=timeout, **kwargs)
    raise_for_status(response, api_key, service)
    return response.json()


def _get(url, api_key, service, timeout, **kwargs):
    response = requests.get(url, timeout=timeout, **kwargs)
    raise_for_status(response, api_key, service)
    return response.json()


def openai_list_models(base_url, api_key, timeout):
    data = _get(f"{base_url}/models", api_key, "OpenAI", timeout, headers={"Authorization": f"Bearer {api_key}"})
    return sorted(model["id"] for model in data.get("data", []))


def gemini_list_models(base_url, api_key, timeout):
    data = _get(f"{base_url}/models", api_key, "Gemini", timeout, headers={"x-goog-api-key": api_key}, params={"pageSize": 1000})
    names = [model["name"].removeprefix("models/") for model in data.get("models", []) if "generateContent" in model.get("supportedGenerationMethods", ["generateContent"])]
    return sorted(names)


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


def wavespeed_generate(base_url, api_key, prompt, params, timeout):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"prompt": prompt, **params}
    submit = _post(f"{base_url}/bytedance/seedream-v5.5", api_key, "Wavespeed", timeout, headers=headers, json=body)
    prediction_id = submit.get("data", {}).get("id")
    if not prediction_id:
        raise RuntimeError(f"Wavespeed submit did not return a prediction id: {submit}")
    result_url = f"{base_url}/predictions/{prediction_id}/result"
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Wavespeed prediction timed out.")
        data = _get(result_url, api_key, "Wavespeed", remaining, headers=headers)
        status = data.get("data", {}).get("status")
        if status == "completed":
            outputs = data.get("data", {}).get("outputs", [])
            if not outputs:
                raise RuntimeError("Wavespeed response did not contain any outputs.")
            images = []
            for url in outputs:
                r = requests.get(url, timeout=60)
                r.raise_for_status()
                images.append(r.content)
            return images
        if status in ("failed", "cancelled", "timeout", "deleted"):
            raise RuntimeError(f"Wavespeed prediction {status}: {data.get('data', {})}")
        time.sleep(2)
