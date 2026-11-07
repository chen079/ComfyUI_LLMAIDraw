import base64
import hashlib
import http.server
import json
import secrets
import time
import urllib.parse
import webbrowser

import requests

from ..config import load_config, save_section
from ..http_errors import raise_for_status


# Same public OAuth client and endpoints as the "Sign in with ChatGPT" flow of the Codex CLI.
AUTH_URL = "https://auth.openai.com"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_PORT = 1455
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/auth/callback"
RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
LOGIN_TIMEOUT = 300


def _account_id(id_token):
    payload = id_token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return claims["https://api.openai.com/auth"]["chatgpt_account_id"]


def _save_tokens(tokens):
    values = {"access_token": tokens["access_token"], "expires_at": int(time.time()) + int(tokens.get("expires_in", 3600))}
    if tokens.get("refresh_token"):
        values["refresh_token"] = tokens["refresh_token"]
    if tokens.get("id_token"):
        values["account_id"] = _account_id(tokens["id_token"])
    save_section("chatgpt_account", values)


def _wait_for_code(state):
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path == "/auth/callback" and query.get("state") == [state] and "code" in query:
                result["code"] = query["code"][0]
                body = "Login succeeded. You can close this tab and return to ComfyUI."
            else:
                result["error"] = query.get("error_description", query.get("error", ["invalid callback"]))[0]
                body = f"Login failed: {result['error']}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    deadline = time.time() + LOGIN_TIMEOUT
    with http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler) as server:
        server.timeout = 1
        while not result and time.time() < deadline:
            server.handle_request()
    if "code" not in result:
        raise RuntimeError(f"ChatGPT login failed: {result.get('error', 'timed out')}")
    return result["code"]


def login():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile email offline_access",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": "codex_cli_rs",
    })
    url = f"{AUTH_URL}/oauth/authorize?{query}"
    print(f"LLMAIDraw: open this URL to sign in with ChatGPT:\n{url}")
    webbrowser.open(url)
    code = _wait_for_code(state)
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI, "client_id": CLIENT_ID, "code_verifier": verifier}
    response = requests.post(f"{AUTH_URL}/oauth/token", data=form, timeout=60)
    raise_for_status(response, code, "ChatGPT login")
    _save_tokens(response.json())


def _refresh(refresh_token):
    body = {"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": refresh_token, "scope": "openid profile email"}
    response = requests.post(f"{AUTH_URL}/oauth/token", json=body, timeout=60)
    raise_for_status(response, refresh_token, "ChatGPT login")
    _save_tokens(response.json())


def credentials(force_login):
    account = load_config().get("chatgpt_account", {})
    if force_login or not account.get("refresh_token"):
        login()
    elif account.get("expires_at", 0) < time.time() + 60:
        _refresh(account["refresh_token"])
    return load_config()["chatgpt_account"]


def _data_url(png):
    return f"data:image/png;base64,{base64.b64encode(png).decode()}"


def generate(prompt, tool, images, mask_png, force_login, timeout):
    account = credentials(force_login)
    content = [{"type": "input_text", "text": prompt}] + [{"type": "input_image", "image_url": _data_url(png)} for png in images]
    if mask_png is not None:
        tool = {**tool, "input_image_mask": {"image_url": _data_url(mask_png)}}
    body = {
        "model": account.get("model", "gpt-6.1-sol"),
        "instructions": "Generate the requested image with the image_generation tool.",
        "input": [{"type": "message", "role": "user", "content": content}],
        "tools": [{"type": "image_generation", **tool}],
        "tool_choice": {"type": "image_generation"},
        "parallel_tool_calls": False,
        "stream": True,
        "store": False,
    }
    headers = {
        "Authorization": f"Bearer {account['access_token']}",
        "chatgpt-account-id": account.get("account_id", ""),
        "OpenAI-Beta": "responses=experimental",
        "originator": "codex_cli_rs",
        "Accept": "text/event-stream",
    }
    with requests.post(RESPONSES_URL, json=body, headers=headers, stream=True, timeout=timeout) as response:
        raise_for_status(response, account["access_token"], "ChatGPT")
        response.encoding = "utf-8"
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            if event.get("type") == "response.output_item.done" and event["item"].get("type") == "image_generation_call" and event["item"].get("result"):
                return base64.b64decode(event["item"]["result"])
            if event.get("type") in ("response.failed", "error"):
                raise RuntimeError(f"ChatGPT image generation failed: {json.dumps(event)[:500]}")
    raise RuntimeError("ChatGPT response did not contain an image.")
