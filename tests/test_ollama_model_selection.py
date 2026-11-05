from ai_diffusion.backend import ollama
from ai_diffusion.settings import settings


def test_profile_cannot_override_selected_model(monkeypatch):
    monkeypatch.setattr(settings, "ollama_model", "selected-vision-model")
    profiles = ollama.Profiles({
        "profiles": {
            "test": {
                "model": "old-text-model",
                "describe_model": "old-vision-model",
                "describe": "caption",
            }
        }
    })
    profile = profiles.get("test")
    assert profile is not None
    assert profile.system_for(ollama.EnhanceTask.describe) == "caption"
    for images in (None, ["encoded-image"]):
        body = ollama._request_body(
            "prompt", profile.system_for(ollama.EnhanceTask.describe), "", None, True, images=images
        )
        assert body["model"] == "selected-vision-model"
        if images:
            assert body["images"] == images
