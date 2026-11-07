import requests


def raise_for_status(response, secret, service, image=None):
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        detail = response.text.replace(secret, "[redacted]")
        if image:
            detail = detail.replace(image, "[image]")
        detail = detail.strip()[:500]
        request_id = response.headers.get("x-correlation-id") or response.headers.get("x-request-id", "unavailable")
        error.args = (f"{error}\n{service} response: {detail or '(empty body)'}\nRequest ID: {request_id}",)
        raise
