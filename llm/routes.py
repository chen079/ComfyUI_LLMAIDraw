import asyncio

from aiohttp import web
from server import PromptServer

from ..config import get_profile, save_profile_models
from .nodes import NODE_CLASS_MAPPINGS


def refresh_models(node_type, profile):
    node_class = NODE_CLASS_MAPPINGS[node_type]
    base_url, api_key = get_profile(node_class.CONFIG_SECTION, profile)
    models = node_class.list_models(base_url, api_key, 60)
    save_profile_models(node_class.CONFIG_SECTION, profile, models)
    return models


@PromptServer.instance.routes.post("/llmaidraw/models")
async def models_route(request):
    body = await request.json()
    try:
        models = await asyncio.to_thread(refresh_models, body["node_type"], body["profile"])
    except Exception as error:
        return web.json_response({"error": str(error)}, status=400)
    return web.json_response({"models": models})
