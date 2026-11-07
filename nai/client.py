import base64
import json

import requests
from requests.adapters import HTTPAdapter, Retry

from ..config import CONFIG_FILE, load_config
from ..http_errors import raise_for_status


IMAGE_URL = "https://image.novelai.net"


def _request_target(retry):
    if retry is None or retry <= 1:
        return requests
    retries = Retry(total=retry, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["POST"])
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


class NovelAIClient:
    def __init__(self, access_token):
        self.access_token = access_token

    @classmethod
    def from_config(cls):
        token = load_config().get("novelai", {}).get("access_token")
        if not token:
            raise RuntimeError(f"Set novelai.access_token in {CONFIG_FILE}.")
        return cls(token)

    def encode_vibe(self, image, model, information_extracted, timeout=120):
        request = {"image": "image", "model": model, "information_extracted": information_extracted}
        files = {
            "image": ("blob", base64.b64decode(image), "image/png"),
            "request": ("blob", json.dumps(request), "application/json"),
        }
        response = requests.post(f"{IMAGE_URL}/ai/encode-vibe", files=files, headers=self._headers(), timeout=timeout)
        raise_for_status(response, self.access_token, "NovelAI", image)
        if not response.content:
            raise RuntimeError("NovelAI returned an empty vibe encoding.")
        return base64.b64encode(response.content).decode()

    def generate_image(self, prompt, model, action, parameters, timeout=None, retry=None):
        data = {"input": prompt, "model": model, "action": action, "parameters": parameters}
        request = _request_target(retry)
        try:
            response = request.post(f"{IMAGE_URL}/ai/generate-image", json=data, headers=self._headers(), timeout=timeout)
            raise_for_status(response, self.access_token, "NovelAI")
            return response.content
        finally:
            if isinstance(request, requests.Session):
                request.close()

    def augment_image(self, req_type, width, height, image, options=None, timeout=None, retry=None):
        data = {"req_type": req_type, "width": width, "height": height, "image": image}
        if options:
            data.update(options)
        request = _request_target(retry)
        try:
            response = request.post(f"{IMAGE_URL}/ai/augment-image", json=data, headers=self._headers(), timeout=timeout)
            raise_for_status(response, self.access_token, "NovelAI", image)
            return response.content
        finally:
            if isinstance(request, requests.Session):
                request.close()

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}
