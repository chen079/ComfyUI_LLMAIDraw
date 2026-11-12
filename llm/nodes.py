from . import chatgpt_account
from ..config import get_profile, model_names, profile_names
from .image_apis import gemini_generate, gemini_list_models, openai_generate, openai_list_models, wavespeed_generate, xai_generate
from ..image_codec import edit_mask_to_png, image_to_png, images_to_batch


CATEGORY = "LLMAIDraw"
ACCOUNT_PROFILE = "chatgpt_account"
MODEL_TOOLTIP = "Use the refresh models button to load the models of the selected profile into this list."
CUSTOM_MODEL = ("STRING", {"default": "", "tooltip": "Model name to use instead of model when not empty."})
GEMINI_ASPECT_RATIOS = ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "1:4", "4:1", "1:8", "8:1"]
GPT_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536", "2048x2048", "2048x1152", "1152x2048", "3840x2160", "2160x3840"]
GROK_ASPECT_RATIOS = ["auto", "1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2", "9:19.5", "19.5:9", "9:20", "20:9", "1:2", "2:1", "21:9", "5:2"]


def _prompt():
    return ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False})


def _references(image, extra_images):
    # The frontend adds image_2, image_3, ... as references are connected.
    images = [image] + [extra_images[name] for name in sorted(extra_images, key=lambda name: int(name.removeprefix("image_")))]
    return [image_to_png(pixels) for batch in images if batch is not None for pixels in batch]


class LLMAIDrawGPTImage:
    CONFIG_SECTION = "gpt_image"
    MODELS = ["gpt-image-2.6-sunburst", "gpt-image-2.6-flare", "gpt-image-2.5-sunburst", "gpt-image-2.5-flare"]
    list_models = staticmethod(openai_list_models)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "profile": (profile_names(cls.CONFIG_SECTION) + [ACCOUNT_PROFILE], {"tooltip": f"Profiles come from the gpt_image section of config.json; {ACCOUNT_PROFILE} signs in with a ChatGPT account."}),
                "prompt": _prompt(),
                "model": (model_names(cls.CONFIG_SECTION, cls.MODELS), {"tooltip": f"Image model for API profiles. {ACCOUNT_PROFILE} ignores it: ChatGPT picks the image model. {MODEL_TOOLTIP}"}),
                "size": (GPT_SIZES, {"default": "auto", "tooltip": "Sizes above 2560x1440 are experimental and need a GPT Image 2 or newer model."}),
                "quality": (["auto", "low", "medium", "high", "xhigh", "max"], {"default": "auto", "tooltip": "xhigh and max need GPT Image 2.5 or newer."}),
                "background": (["auto", "transparent", "opaque"], {"default": "auto"}),
                "output_format": (["png", "jpeg", "webp"], {"default": "png"}),
                "output_compression": ("INT", {"default": 100, "min": 0, "max": 100, "step": 1, "tooltip": "Used only for jpeg and webp."}),
                "moderation": (["auto", "low"], {"default": "auto"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 10, "step": 1}),
                "timeout_sec": ("INT", {"default": 300, "min": 30, "max": 3000, "step": 1}),
                "force_login": ("BOOLEAN", {"default": False, "tooltip": f"Sign in with ChatGPT again even when {ACCOUNT_PROFILE} already has a saved login."}),
            },
            "optional": {"custom_model": CUSTOM_MODEL, "image": ("IMAGE",), "mask": ("MASK", {"tooltip": "White marks the area to edit. Applies to the first image."})},
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, profile, prompt, model, size, quality, background, output_format, output_compression, moderation, n, timeout_sec, force_login, custom_model="", image=None, mask=None, **extra_images):
        if mask is not None and image is None:
            raise ValueError("Connect an image to edit with the mask.")
        references = _references(image, extra_images)
        mask_png = None if mask is None else edit_mask_to_png(mask, (image.shape[2], image.shape[1]))
        options = {"size": size, "quality": quality, "background": background, "output_format": output_format, "moderation": moderation}
        if output_format != "png":
            options["output_compression"] = output_compression
        if profile == ACCOUNT_PROFILE:
            results = [chatgpt_account.generate(prompt, options, references, mask_png, force_login and index == 0, timeout_sec) for index in range(n)]
        else:
            base_url, api_key = get_profile(self.CONFIG_SECTION, profile)
            results = openai_generate(base_url, api_key, prompt, {"model": custom_model.strip() or model, "n": n, **options}, references, mask_png, timeout_sec)
        return (images_to_batch(results, background == "transparent"),)


class LLMAIDrawNanoBanana2:
    CONFIG_SECTION = "nano_banana"
    MODELS = ["gemini-3.1-flash-image"]
    list_models = staticmethod(gemini_list_models)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "profile": (profile_names(cls.CONFIG_SECTION), {"tooltip": "Profiles come from the nano_banana section of config.json."}),
                "prompt": _prompt(),
                "model": (model_names(cls.CONFIG_SECTION, cls.MODELS), {"tooltip": MODEL_TOOLTIP}),
                "aspect_ratio": (GEMINI_ASPECT_RATIOS, {"default": "auto"}),
                "image_size": (["auto", "1K", "2K", "4K"], {"default": "auto"}),
                "temperature": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
                "timeout_sec": ("INT", {"default": 300, "min": 30, "max": 3000, "step": 1}),
            },
            "optional": {"custom_model": CUSTOM_MODEL, "image": ("IMAGE", {"tooltip": "Reference images; every image in the batch is sent."})},
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, profile, prompt, model, aspect_ratio, image_size, temperature, timeout_sec, custom_model="", image=None, **extra_images):
        base_url, api_key = get_profile(self.CONFIG_SECTION, profile)
        image_config = {}
        if aspect_ratio != "auto":
            image_config["aspectRatio"] = aspect_ratio
        if image_size != "auto":
            image_config["imageSize"] = image_size
        generation_config = {"responseModalities": ["IMAGE"], "temperature": temperature}
        if image_config:
            generation_config["imageConfig"] = image_config
        results = gemini_generate(base_url, api_key, custom_model.strip() or model, prompt, _references(image, extra_images), generation_config, timeout_sec)
        return (images_to_batch(results),)


class LLMAIDrawGrokImage:
    CONFIG_SECTION = "grok_image"
    MODELS = ["grok-imagine-image-2.0"]
    list_models = staticmethod(openai_list_models)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "profile": (profile_names(cls.CONFIG_SECTION), {"tooltip": "Profiles come from the grok_image section of config.json."}),
            "prompt": _prompt(),
            "model": (model_names(cls.CONFIG_SECTION, cls.MODELS), {"tooltip": MODEL_TOOLTIP}),
            "aspect_ratio": (GROK_ASPECT_RATIOS, {"default": "auto", "tooltip": "auto leaves the aspect ratio to the server default."}),
            "resolution": (["1k", "2k"], {"default": "1k"}),
            "quality": (["low", "medium"], {"default": "medium", "tooltip": "Supported by grok-imagine-image-2.0."}),
            "n": ("INT", {"default": 1, "min": 1, "max": 10, "step": 1}),
            "timeout_sec": ("INT", {"default": 300, "min": 30, "max": 3000, "step": 1}),
        }, "optional": {"custom_model": CUSTOM_MODEL}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, profile, prompt, model, aspect_ratio, resolution, quality, n, timeout_sec, custom_model=""):
        base_url, api_key = get_profile(self.CONFIG_SECTION, profile)
        params = {"model": custom_model.strip() or model, "resolution": resolution, "quality": quality, "n": n}
        if aspect_ratio != "auto":
            params["aspect_ratio"] = aspect_ratio
        return (images_to_batch(xai_generate(base_url, api_key, prompt, params, timeout_sec)),)


SEEDREAM_ASPECT_RATIOS = ["1:1", "1:2", "2:1", "1:3", "3:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "9:21", "21:9"]


class LLMAIDrawSeadream55:
    CONFIG_SECTION = "seedream"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "profile": (profile_names(cls.CONFIG_SECTION), {"tooltip": "Profiles come from the seedream section of config.json."}),
            "prompt": _prompt(),
            "aspect_ratio": (SEEDREAM_ASPECT_RATIOS, {"default": "1:1"}),
            "resolution": (["1k", "1.5k", "2k"], {"default": "1k"}),
            "background": (["auto", "transparent", "opaque"], {"default": "auto"}),
            "output_format": (["png", "jpeg"], {"default": "png"}),
            "timeout_sec": ("INT", {"default": 300, "min": 30, "max": 3000, "step": 1}),
        }}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, profile, prompt, aspect_ratio, resolution, background, output_format, timeout_sec):
        base_url, api_key = get_profile(self.CONFIG_SECTION, profile)
        params = {"aspect_ratio": aspect_ratio, "resolution": resolution, "background": background, "output_format": output_format}
        results = wavespeed_generate(base_url, api_key, prompt, params, timeout_sec)
        return (images_to_batch(results, background == "transparent"),)


NODE_CLASS_MAPPINGS = {
    "LLMAIDrawGPTImage": LLMAIDrawGPTImage,
    "LLMAIDrawNanoBanana2": LLMAIDrawNanoBanana2,
    "LLMAIDrawGrokImage": LLMAIDrawGrokImage,
    "LLMAIDrawSeadream55": LLMAIDrawSeadream55,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMAIDrawGPTImage": "LLMAIDraw · GPT Image",
    "LLMAIDrawNanoBanana2": "LLMAIDraw · Nano Banana 2",
    "LLMAIDrawGrokImage": "LLMAIDraw · Grok Image",
    "LLMAIDrawSeadream55": "LLMAIDraw · Seedream 5.5",
}
