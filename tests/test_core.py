import base64
import importlib
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

import requests
import torch
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
# Load the plugin as a package without running its ComfyUI-facing __init__.py.
package = types.ModuleType("llmaidraw_test")
package.__path__ = [str(ROOT)]
comfy = types.ModuleType("comfy")
comfy.utils = types.ModuleType("comfy.utils")
comfy.utils.common_upscale = lambda samples, width, height, method, crop: torch.nn.functional.interpolate(samples, size=(height, width), mode=method, align_corners=False)

server = types.ModuleType("server")
server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=types.SimpleNamespace(post=lambda path: lambda handler: handler)))
aiohttp = types.ModuleType("aiohttp")
aiohttp.web = types.ModuleType("aiohttp.web")

with patch.dict(sys.modules, {"llmaidraw_test": package, "comfy": comfy, "comfy.utils": comfy.utils, "server": server, "aiohttp": aiohttp, "aiohttp.web": aiohttp.web}):
    config = importlib.import_module("llmaidraw_test.config")
    image_codec = importlib.import_module("llmaidraw_test.image_codec")
    nai_client = importlib.import_module("llmaidraw_test.nai.client")
    generation = importlib.import_module("llmaidraw_test.nai.generation")
    nodes = importlib.import_module("llmaidraw_test.nai.nodes")
    prompt_syntax = importlib.import_module("llmaidraw_test.nai.prompt_syntax")
    chatgpt_account = importlib.import_module("llmaidraw_test.llm.chatgpt_account")
    llm_nodes = importlib.import_module("llmaidraw_test.llm.nodes")
    image_apis = importlib.import_module("llmaidraw_test.llm.image_apis")
    routes = importlib.import_module("llmaidraw_test.llm.routes")

ALL_NODES = {**nodes.NODE_CLASS_MAPPINGS, **llm_nodes.NODE_CLASS_MAPPINGS}
PROFILE_CONFIG = {
    "gpt_image": {"official": {"base_url": "https://api.openai.com/v1/", "api_key": "sk-test"}},
    "nano_banana": {"official": {"base_url": "https://gemini.test/v1beta", "api_key": "g-test"}},
    "grok_image": {"official": {"base_url": "https://api.x.ai/v1", "api_key": "x-test"}},
}


def png_bytes(size=(64, 64)):
    output = io.BytesIO()
    Image.new("RGB", size).save(output, format="PNG")
    return output.getvalue()


def json_response(data):
    return Mock(status_code=200, json=Mock(return_value=data), raise_for_status=Mock())


def image_zip(mode="RGB"):
    image = io.BytesIO()
    Image.new(mode, (64, 64)).save(image, format="PNG")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("image.png", image.getvalue())
    return archive.getvalue()


class ClientTests(unittest.TestCase):
    def test_vibe_encoding_uses_multipart(self):
        response = Mock(content=b"encoded-vibe")
        with patch.object(requests, "post", return_value=response) as post:
            encoded = nai_client.NovelAIClient("token").encode_vibe(image_codec.image_to_base64(torch.zeros((1, 32, 48, 3))), "nai-diffusion-4-5-full", 0.7, 180)
        self.assertEqual(base64.b64decode(encoded), b"encoded-vibe")
        request = post.call_args.kwargs
        payload = json.loads(request["files"]["request"][1])
        self.assertEqual(payload, {"image": "image", "model": "nai-diffusion-4-5-full", "information_extracted": 0.7})
        self.assertEqual(request["timeout"], 180)

    def test_vibe_encoding_exposes_bounded_server_error(self):
        response = requests.Response()
        response.status_code = 500
        response._content = b'{"statusCode":500,"message":"Invalid reference image"}'
        response.headers["x-correlation-id"] = "abc123"
        with patch.object(requests, "post", return_value=response):
            with self.assertRaisesRegex(requests.HTTPError, "Invalid reference image") as raised:
                nai_client.NovelAIClient("token").encode_vibe(image_codec.image_to_base64(torch.zeros((1, 8, 8, 3))), "nai-diffusion-4-5-full", 0.7)
        self.assertIn("abc123", str(raised.exception))

    def test_token_is_required(self):
        with patch.object(nai_client, "load_config", return_value={"novelai": {"access_token": ""}}):
            with self.assertRaisesRegex(RuntimeError, "novelai.access_token"):
                nai_client.NovelAIClient.from_config()
        with patch.object(nai_client, "load_config", return_value={"novelai": {"access_token": "pst-x"}}):
            self.assertEqual(nai_client.NovelAIClient.from_config().access_token, "pst-x")
        self.assertEqual(config.CONFIG_FILE, ROOT / "config.json")

    def test_example_config_has_every_profile_section(self):
        example = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        for section in ("gpt_image", "nano_banana", "grok_image"):
            self.assertEqual(set(example[section]["official"]), {"base_url", "api_key"})


class LLMNodeTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(config, "load_config", return_value=PROFILE_CONFIG)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_gpt_image_generation_and_edit(self):
        data = {"data": [{"b64_json": base64.b64encode(png_bytes()).decode()}] * 2}
        node = llm_nodes.LLMAIDrawGPTImage()
        args = ("official", "a fox girl", "gpt-image-2.5-sunburst", "1024x1024", "high", "auto", "png", 100, "auto", 2, 0, 60, False)
        with patch.object(requests, "post", return_value=json_response(data)) as post:
            image, = node.generate(*args)
        self.assertEqual(tuple(image.shape), (2, 64, 64, 3))
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/images/generations")
        self.assertEqual(post.call_args.kwargs["json"]["n"], 2)
        self.assertNotIn("output_compression", post.call_args.kwargs["json"])
        with patch.object(requests, "post", return_value=json_response(data)) as post:
            node.generate(*args, image=torch.zeros((2, 32, 32, 3)), mask=torch.ones((1, 16, 16)))
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/images/edits")
        fields = [name for name, _ in post.call_args.kwargs["files"]]
        self.assertEqual(fields, ["image[]", "image[]", "mask"])
        mask = Image.open(io.BytesIO(post.call_args.kwargs["files"][2][1][1]))
        self.assertEqual((mask.size, mask.getpixel((0, 0))[3]), ((32, 32), 0))

    def test_gpt_image_chatgpt_account(self):
        event = {"type": "response.output_item.done", "item": {"type": "image_generation_call", "result": base64.b64encode(png_bytes()).decode()}}
        response = Mock(raise_for_status=Mock(), iter_lines=Mock(return_value=["event: x", "data: " + json.dumps(event)]))
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        account = {"access_token": "at", "account_id": "acc", "model": "gpt-5"}
        with patch.object(chatgpt_account, "credentials", return_value=account), patch.object(requests, "post", return_value=response) as post:
            image, = llm_nodes.LLMAIDrawGPTImage().generate("chatgpt_account", "p", "gpt-image-2.5-sunburst", "auto", "auto", "auto", "webp", 80, "auto", 1, 0, 60, False)
        self.assertEqual(tuple(image.shape), (1, 64, 64, 3))
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["tools"][0], {"type": "image_generation", "size": "auto", "quality": "auto", "background": "auto", "output_format": "webp", "moderation": "auto", "output_compression": 80})
        self.assertEqual(post.call_args.kwargs["headers"]["chatgpt-account-id"], "acc")

    def test_chatgpt_tokens_are_saved_with_account_id(self):
        claims = base64.urlsafe_b64encode(json.dumps({"https://api.openai.com/auth": {"chatgpt_account_id": "acc"}}).encode()).decode().rstrip("=")
        with patch.object(chatgpt_account, "save_section") as save:
            chatgpt_account._save_tokens({"access_token": "at", "refresh_token": "rt", "id_token": f"h.{claims}.s", "expires_in": 10})
        name, values = save.call_args.args
        self.assertEqual((name, values["account_id"], values["refresh_token"]), ("chatgpt_account", "acc", "rt"))

    def test_nano_banana_request(self):
        data = {"candidates": [{"content": {"parts": [{"text": "ok"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png_bytes()).decode()}}]}}]}
        with patch.object(requests, "post", return_value=json_response(data)) as post:
            image, = llm_nodes.LLMAIDrawNanoBanana2().generate("official", "p", "gemini-3.1-flash-image", "16:9", "auto", 1.0, 5, 60, torch.zeros((1, 8, 8, 3)), image_10=torch.zeros((2, 8, 8, 3)), image_2=torch.ones((1, 8, 8, 3)), image_3=None)
        self.assertEqual(tuple(image.shape), (1, 64, 64, 3))
        self.assertEqual(post.call_args.args[0], "https://gemini.test/v1beta/models/gemini-3.1-flash-image:generateContent")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["generationConfig"]["imageConfig"], {"aspectRatio": "16:9"})
        self.assertEqual(len(body["contents"][0]["parts"]), 5)

    def test_grok_request_and_missing_key(self):
        data = {"data": [{"b64_json": base64.b64encode(png_bytes()).decode()}]}
        with patch.object(requests, "post", return_value=json_response(data)) as post:
            llm_nodes.LLMAIDrawGrokImage().generate("official", "p", "grok-imagine-image-2.0", "16:9", "2k", "medium", 1, 0, 60)
        self.assertEqual(post.call_args.kwargs["json"], {"prompt": "p", "model": "grok-imagine-image-2.0", "resolution": "2k", "quality": "medium", "n": 1, "aspect_ratio": "16:9", "response_format": "b64_json"})
        with self.assertRaisesRegex(RuntimeError, "grok_image.missing"):
            llm_nodes.LLMAIDrawGrokImage().generate("missing", "p", "grok-imagine-image-2.0", "auto", "1k", "low", 1, 0, 60)

    def test_refresh_models_filters_image_models_and_saves_them(self):
        data = {"data": [{"id": "gpt-6.1-sol"}, {"id": "gpt-image-2.5-flare"}, {"id": "gpt-image-2.5-sunburst"}]}
        response = json_response(data)
        with patch.object(requests, "get", return_value=response) as get, patch.object(routes, "save_profile_models") as save:
            models = routes.refresh_models("LLMAIDrawGPTImage", "official")
        self.assertEqual(models, ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst"])
        self.assertEqual(get.call_args.args[0], "https://api.openai.com/v1/models")
        save.assert_called_once_with("gpt_image", "official", models)

    def test_gemini_model_list_and_proxy_fallback(self):
        data = {"models": [
            {"name": "models/gemini-3.1-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-005", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/gemini-6-pro", "supportedGenerationMethods": ["generateContent"]},
        ]}
        with patch.object(requests, "get", return_value=json_response(data)):
            self.assertEqual(image_apis.gemini_list_models("https://g.test", "k", 60), ["gemini-3.1-flash-image"])
        with patch.object(requests, "get", return_value=json_response({"data": [{"id": "draw-b"}, {"id": "draw-a"}]})):
            self.assertEqual(image_apis.openai_list_models("https://proxy.test", "k", 60), ["draw-a", "draw-b"])

    def test_saved_models_extend_model_choices(self):
        saved = {"gpt_image": {"official": {**PROFILE_CONFIG["gpt_image"]["official"], "models": ["gpt-image-2.5-flare"]}, "proxy": {"models": ["gpt-image-2.5-sunburst", "draw-x"]}}}
        with patch.object(config, "load_config", return_value=saved):
            choices = llm_nodes.LLMAIDrawGPTImage.INPUT_TYPES()["required"]["model"][0]
        self.assertEqual(choices, llm_nodes.LLMAIDrawGPTImage.MODELS + ["draw-x"])


class GenerationTests(unittest.TestCase):
    def build(self, option=None):
        return generation.build_generation_request(832, 1216, "positive", "negative", 28, 5.0, False, False, "none", "k_euler", "native", 123, 1.0, 0.0, True, option)

    def test_encoded_vibes_select_model_and_preserve_order(self):
        vibe = {"model": "nai-diffusion-4-5-full", "encoding": "encoded"}
        model, action, params = self.build({"model": vibe["model"], "encoded_vibe": [(vibe, 0.6), (vibe, 0.2)]})
        self.assertEqual((model, action), (vibe["model"], "generate"))
        self.assertEqual(params["reference_image_multiple"], ["encoded", "encoded"])
        self.assertEqual(params["reference_strength_multiple"], [0.6, 0.2])
        self.assertNotIn("reference_information_extracted_multiple", params)

    def test_raw_vibe_requires_v3(self):
        image = torch.zeros((1, 32, 32, 3))
        with self.assertRaisesRegex(ValueError, "requires EncodeVibe"):
            self.build({"vibe": [(image, 1.0, 0.6)]})
        model, _, params = self.build({"model": "nai-diffusion-3", "vibe": [(image, 0.8, 0.6)]})
        self.assertEqual(model, "nai-diffusion-3")
        self.assertEqual(params["reference_information_extracted_multiple"], [0.8])

    def test_img2img_action_and_free_limits(self):
        image = torch.zeros((1, 32, 32, 3))
        model, action, params = generation.build_generation_request(1600, 1600, "p", "n", 50, 5.0, False, False, "none", "k_euler", "native", 1, 1.0, 0.0, True, {"img2img": (image, 0.7, 0.1)})
        self.assertEqual((model, action), (generation.DEFAULT_MODEL, "img2img"))
        self.assertLessEqual(params["width"] * params["height"], generation.FREE_PIXEL_LIMIT)
        self.assertEqual(params["steps"], 28)


class NodeTests(unittest.TestCase):
    def test_only_neo_node_ids_are_registered(self):
        self.assertTrue(nodes.NODE_CLASS_MAPPINGS)
        self.assertTrue(all(node_id.startswith("NAINeo") for node_id in nodes.NODE_CLASS_MAPPINGS))
        self.assertNotIn("GenerateNAID", nodes.NODE_CLASS_MAPPINGS)
        self.assertEqual(nodes.NAINeoGenerate.RETURN_TYPES, ("IMAGE",))
        self.assertEqual(nodes.NAINeoEncodeVibe.RETURN_TYPES, ("NAI_NEO_VIBE",))

    def test_locales_cover_every_registered_node_and_input(self):
        for language in ("en", "zh"):
            translations = json.loads((ROOT / "locales" / language / "nodeDefs.json").read_text(encoding="utf-8"))
            self.assertEqual(set(translations), set(ALL_NODES))
            for node_id, node_class in ALL_NODES.items():
                node_inputs = node_class.INPUT_TYPES()
                input_names = set(node_inputs.get("required", {})) | set(node_inputs.get("optional", {}))
                self.assertEqual(set(translations[node_id].get("inputs", {})), input_names, f"{language}: {node_id}")

    def test_generate_returns_image_without_writing_files(self):
        client = Mock()
        client.generate_image.return_value = image_zip()
        with patch.object(nodes.NovelAIClient, "from_config", return_value=client):
            node = nodes.NAINeoGenerate()
        image, = node.generate(False, 64, 64, "p", "n", 28, 5.0, False, False, "none", "k_euler", "native", 1, 1.0, 0.0, True)
        self.assertEqual(tuple(image.shape), (1, 64, 64, 3))

    def test_ignore_errors_works_without_masking_original_error(self):
        client = Mock()
        client.generate_image.side_effect = RuntimeError("server failed")
        with patch.object(nodes.NovelAIClient, "from_config", return_value=client):
            node = nodes.NAINeoGenerate()
        with self.assertRaisesRegex(RuntimeError, "server failed"):
            node.generate(False, 64, 64, "p", "n", 28, 5.0, False, False, "none", "k_euler", "native", 1, 1.0, 0.0, True)
        image, = node.generate(False, 64, 64, "p", "n", 28, 5.0, False, False, "none", "k_euler", "native", 1, 1.0, 0.0, True, {"ignore_errors": True})
        self.assertEqual(tuple(image.shape), (1, 1, 1))


class PromptTests(unittest.TestCase):
    def test_brace_and_numeric_conversion(self):
        self.assertEqual(prompt_syntax.prompt_to_nai("a (cat:1.1)", 0.05, "brace"), "a {{cat}}")
        self.assertEqual(prompt_syntax.prompt_to_nai("(cat:1.2)", 0.05, "numeric"), "1.2::cat ::")
        self.assertEqual(prompt_syntax.prompt_to_nai(r"\(literal\)"), "(literal)")


if __name__ == "__main__":
    unittest.main()
