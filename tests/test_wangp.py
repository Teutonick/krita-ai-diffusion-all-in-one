import json
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web

from ai_diffusion.backend import wangp
from ai_diffusion.backend.comfy_client import ComfyClient
from ai_diffusion.backend.wangp import WanGPClient, generate_video, read_video_settings

from .conftest import qtapp


@pytest.mark.parametrize("outcome", ["done", "cancelled", "invalid", "stale_workspace"])
@qtapp
async def test_wangp_submission(outcome):
    events = []
    directory = "@documents/uploads/" + "a" * 32
    video_settings = {"model_type": "minimax_h3_fl2va_pruned_pdd", "num_inference_steps": 2}
    settings = {**video_settings, "prompt": "Orbit the subject", "prompt_enhancer": ""}
    frame = b"start frame PNG"
    comfy = Mock()
    comfy.pause_for_video.side_effect = lambda value: events.append(("pause", value))
    comfy.release_gpu_for_video = AsyncMock(side_effect=lambda: events.append("released"))

    async def upload(request):
        assert await request.read() == frame
        events.append("uploaded")
        return web.json_response({"path": settings["image_start"]})

    async def mcp(request):
        message = await request.json()
        if message["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26"}
        else:
            assert request.headers["Mcp-Session-Id"] == "test-session"
            if message["method"] == "notifications/initialized":
                return web.Response(status=202)
            tool = message["params"]["name"]
            args = message["params"]["arguments"]
            if tool == "wangp_workspace":
                action = args.get("action", "current")
                if outcome == "stale_workspace" and action == "current":
                    result = {
                        "isError": True,
                        "content": [{"text": "This workspace no longer exists."}],
                    }
                elif action == "list":
                    result = {
                        "structuredContent": {
                            "workspaces": [
                                {"id": "other", "name": "Other", "owner_kind": "manual"},
                                {"id": "default", "name": "Default", "owner_kind": "manual"},
                            ]
                        }
                    }
                else:
                    if outcome == "stale_workspace":
                        assert action == "attach" and args["workspace_id"] == "default"
                    result = {"structuredContent": {"agent_context": "test-context"}}
                return web.json_response({"jsonrpc": "2.0", "id": message["id"], "result": result})
            assert args.pop("agent_context") == "test-context"
            if tool == "wangp_session" and args["action"] == "create_file_upload":
                filename = args["arguments"]["filename"]
                assert filename.endswith(".png")
                assert args["arguments"]["size_bytes"] == len(frame)
                settings["image_start"] = f"{directory}/{filename}"
                output = {"upload_url": "/upload"}
            elif tool == "wangp_validate":
                assert args["settings"] == settings
                events.append("validated")
                output = {"valid": outcome != "invalid"}
            elif tool == "wangp_generate":
                assert args["settings"] == settings
                assert args["wait"] is False
                assert args["request_id"]
                events.append("submitted")
                output = {"job_id": "job-1"}
            elif tool == "wangp_io":
                assert args["action"] == "delete"
                item = args["arguments"]["path"]
                assert args["arguments"]["recursive"] is False
                assert item in (settings["image_start"], directory)
                events.append("removed directory" if item == directory else "removed frame")
                output = {"deleted": True}
            else:
                assert tool == "wangp_session" and args["action"] == "get_job"
                assert args["arguments"]["job_id"] == "job-1"
                events.append("finished")
                output = {"status": "done" if outcome == "stale_workspace" else outcome}
            result = {"structuredContent": output}
        return web.json_response(
            {"jsonrpc": "2.0", "id": message["id"], "result": result},
            headers={"Mcp-Session-Id": "test-session"},
        )

    app = web.Application()
    app.router.add_post("/mcp", mcp)
    app.router.add_put("/upload", upload)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = f"http://127.0.0.1:{runner.addresses[0][1]}/mcp"
        if outcome != "invalid":
            if outcome in ("done", "stale_workspace"):
                await generate_video(url, video_settings, settings["prompt"], frame, comfy, Mock())
            else:
                with pytest.raises(RuntimeError, match="cancelled"):
                    await generate_video(
                        url, video_settings, settings["prompt"], frame, comfy, Mock()
                    )
            assert events == [
                "uploaded",
                "validated",
                ("pause", True),
                "released",
                "submitted",
                "finished",
                ("pause", False),
                "removed frame",
                "removed directory",
            ]
        else:
            with pytest.raises(RuntimeError, match="could not validate"):
                await generate_video(url, video_settings, settings["prompt"], frame, comfy, Mock())
            assert events == ["uploaded", "validated", "removed frame", "removed directory"]
    finally:
        await runner.cleanup()


def test_wangp_reads_latest_saved_settings_without_reusing_media(tmp_path):
    source = tmp_path / "minimax_h3_fl2va_pruned_pdd_settings.json"
    saved = {
        "num_inference_steps": 8,
        "image_prompt_type": "",
        "prompt": "Previous prompt",
        "image_start": "old.png",
    }
    source.write_text(json.dumps(saved), encoding="utf-8")
    assert read_video_settings(source)["num_inference_steps"] == 8
    saved.update(num_inference_steps=2, activated_loras=["minimax_h3_pi_2step_lora_bf16"])
    source.write_text(json.dumps(saved), encoding="utf-8")
    assert read_video_settings(source) == {
        "model_type": "minimax_h3_fl2va_pruned_pdd",
        "image_mode": 0,
        "num_inference_steps": 2,
        "image_prompt_type": "S",
        "activated_loras": ["minimax_h3_pi_2step_lora_bf16"],
        "prompt_enhancer": "",
    }


def test_wangp_rejects_cleartext_remote_frames():
    with pytest.raises(ValueError, match="HTTPS"):
        WanGPClient("http://192.0.2.1:8000/mcp")


@qtapp
async def test_wangp_status_without_status_key(monkeypatch):
    client = WanGPClient("http://localhost:8000/mcp")
    call = AsyncMock(
        side_effect=[
            {"job_id": "job-1", "done": False},
            {"job_id": "job-1", "done": False, "progress": {"status": "Denoising"}},
            {"job_id": "job-1", "done": True, "status": "done", "result": {"success": True}},
        ]
    )
    monkeypatch.setattr(client, "call", call)
    monkeypatch.setattr(wangp.asyncio, "sleep", AsyncMock())
    status = Mock()
    result = await client.wait_for_video("job-1", status)
    assert result["status"] == "done"
    assert call.await_count == 3
    assert "queued" in status.call_args_list[0].args[0]
    assert "Generating" in status.call_args_list[1].args[0]


@qtapp
async def test_comfy_drains_queue_and_observes_gpu_release():
    client = Mock()
    client._posting_job = False
    client._get = AsyncMock(
        side_effect=[
            {"queue_running": [[0, "job"]], "queue_pending": []},
            {"queue_running": [], "queue_pending": []},
            {"devices": [{"type": "cuda", "torch_vram_total": 1024}]},
            {"devices": [{"type": "cuda", "torch_vram_total": 0}]},
        ]
    )
    client.free_memory = AsyncMock()
    await ComfyClient.release_gpu_for_video(client)
    assert [call[0] for call in client.mock_calls] == [
        "_get",
        "_get",
        "free_memory",
        "_get",
        "_get",
    ]
