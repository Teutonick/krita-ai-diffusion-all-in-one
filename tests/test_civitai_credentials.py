from unittest.mock import AsyncMock

import pytest

from ai_diffusion.backend import civitai
from ai_diffusion.backend.lora_manager import start_download
from ai_diffusion.settings import ServerMode, settings

from .conftest import qtapp


@pytest.mark.parametrize("key", ["  example-test-key  ", ""])
@qtapp
async def test_civitai_syncs_current_credentials_before_transfer(monkeypatch, key):
    monkeypatch.setattr(settings, "server_mode", ServerMode.managed)
    monkeypatch.setattr(settings, "civitai_api_key", key)
    monkeypatch.setattr(settings, "civitai_host", "civitai.red")
    requests = AsyncMock()
    requests.post.side_effect = [{"success": True}, {"success": True}]
    assert (await start_download(requests, "http://localhost:8188", 123))["success"]
    calls = requests.post.await_args_list
    assert calls[0].args == (
        "http://localhost:8188/api/lm/settings",
        {"civitai_api_key": key.strip(), "civitai_host": "civitai.red"},
    )
    assert calls[1].args[0].endswith("/api/lm/download-model")
    assert "civitai_api_key" not in calls[1].args[1]


@qtapp
async def test_settings_failure_prevents_unauthenticated_download(monkeypatch):
    monkeypatch.setattr(settings, "server_mode", ServerMode.managed)
    requests = AsyncMock()
    requests.post.return_value = {"success": False}
    result = await start_download(requests, "http://localhost:8188", 123)
    assert result["success"] is False
    assert requests.post.await_count == 1


def test_civitai_architecture_filter_uses_all_versions():
    model = civitai.CivitaiModel.from_api({
        "id": 1862761,
        "modelVersions": [
            {"id": 3448140, "baseModel": "Krea 2"},
            {"id": 3410486, "baseModel": "MOSS Image"},
            {"id": 3352079, "baseModel": "Qwen 2.1"},
            {"id": 3075498, "baseModel": "Krea 2"},
            {"id": 5, "baseModel": "NoobAI"},
        ],
    })
    assert [v.id for v in civitai.matching_versions(model, "moss")] == [3410486]
    assert [v.id for v in civitai.matching_versions(model, "krea2")] == [3448140, 3075498]
    assert [v.id for v in civitai.matching_versions(model, "qwen")] == [3352079]
    assert [v.id for v in civitai.matching_versions(model, "illu")] == [5]
    assert civitai.matching_versions(model, None) == model.versions
