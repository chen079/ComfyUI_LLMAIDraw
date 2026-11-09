import json
from pathlib import Path


CONFIG_FILE = Path(__file__).with_name("config.json")
EXAMPLE_FILE = Path(__file__).with_name("config.example.json")


def load_config():
    path = CONFIG_FILE if CONFIG_FILE.exists() else EXAMPLE_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def _write(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_section(name, values):
    config = load_config()
    config.setdefault(name, {}).update(values)
    _write(config)


def save_profile_models(section, name, models):
    config = load_config()
    config[section][name]["models"] = models
    _write(config)


def profile_names(section):
    return list(load_config().get(section, {})) or ["official"]


def model_names(section, defaults):
    names = list(defaults)
    for profile in load_config().get(section, {}).values():
        names += [model for model in profile.get("models", []) if model not in names]
    return names


def get_profile(section, name):
    profile = load_config().get(section, {}).get(name)
    if not profile or not profile.get("api_key") or not profile.get("base_url"):
        raise RuntimeError(f"Set base_url and api_key for {section}.{name} in {CONFIG_FILE}.")
    return profile["base_url"].rstrip("/"), profile["api_key"]
