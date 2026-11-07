# Domain context

## Config file

`config.json` holds every credential: the NovelAI token, named `base_url`/`api_key` profiles per image service (`gpt_image`, `nano_banana`, `grok_image`), and the saved ChatGPT account login. Nodes pick a profile by name; `base_url` and `api_key` are only edited in the file.

## Image APIs

`llm/image_apis.py` owns the HTTP formats of OpenAI-compatible image generation/edits, Gemini `generateContent`, and xAI image generation. `llm/chatgpt_account.py` owns the ChatGPT OAuth login, token refresh, and the ChatGPT image tool request.

## NovelAI client

`nai/client.py` owns authentication and HTTP request formats for image generation, Vibe encoding, and Director tools. Nodes do not construct HTTP requests.

## Generation request

A generation request combines the Generate node inputs with an optional `NAI_NEO_OPTION` chain. It owns model selection, generation action, resolution limits, sampler adjustments, image inputs, masks, and Vibe references.

## Image codec

The image codec converts between ComfyUI image tensors, PNG data, NovelAI masks, ZIP responses, and supported resolutions.

## Prompt syntax

Prompt syntax converts ComfyUI parenthesis weights into NovelAI brace or numeric weights.

## Workflow identity

The `NAINeo...` class identifiers and `NAI_NEO_...` socket types define this project's workflow format. Legacy identifiers are intentionally not registered; workflows from the original project need their nodes replaced once with the Neo equivalents. The `LLMAIDraw...` identifiers belong to the GPT Image, Nano Banana 2, and Grok Image nodes.
