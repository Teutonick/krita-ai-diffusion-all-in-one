import asyncio
import json
import re
from collections.abc import Callable
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from ..localization import translate as _
from ..util import client_logger as log
from .comfy_client import ComfyClient
from .network import NetworkError, RequestManager

_workspace_contexts: dict[str, str] = {}
_missing_workspace_errors = ("This workspace no longer exists.", "Unknown agent_context.")


class WanGPClient:
    def __init__(self, url: str):
        self.url = url.strip()
        endpoint = urlsplit(self.url)
        if endpoint.scheme not in ("http", "https") or not endpoint.hostname:
            raise ValueError(_("Enter a valid WanGP MCP URL in Settings → Integrations."))
        if endpoint.scheme == "http" and endpoint.hostname != "localhost":
            try:
                loopback = ip_address(endpoint.hostname).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                raise ValueError(_("Use HTTPS for WanGP outside this computer."))
        self._requests = RequestManager()
        self._headers: list[tuple[str, str]] = []
        self._id = 0
        self._agent_context: str | None = None

    async def connect(self, timeout: float = 30):
        self._headers = [("Accept", "application/json, text/event-stream")]
        result, headers = await self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "Krita AI Diffusion", "version": "1"},
            },
            timeout=timeout,
        )
        self._headers.append(("MCP-Protocol-Version", result["protocolVersion"]))
        if session := headers.get("mcp-session-id"):
            self._headers.append(("Mcp-Session-Id", session))
        await self._rpc("notifications/initialized", {}, notification=True, timeout=timeout)

    async def _rpc(
        self, method: str, params: dict, notification: bool = False, timeout: float = 30
    ):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self._id += 1
            message["id"] = self._id
        response, headers = await self._requests.http(
            "POST",
            self.url,
            message,
            timeout=timeout,
            headers=self._headers,
            response_headers=True,
            follow_redirects=False,
        )
        if notification:
            return {}, headers
        if isinstance(response, bytes):
            events = response.decode().replace("\r\n", "\n").split("\n\n")
            for event in events:
                data = "\n".join(
                    line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")
                )
                if data and (message := json.loads(data)).get("id") == self._id:
                    response = message
                    break
        if not isinstance(response, dict) or response.get("id") != self._id:
            raise RuntimeError(_("WanGP returned an invalid MCP response."))
        if error := response.get("error"):
            raise RuntimeError(error.get("message", str(error)))
        return response["result"], headers

    async def call(self, tool: str, **arguments):
        if self._agent_context and tool != "wangp_workspace":
            arguments["agent_context"] = self._agent_context
        result, _ = await self._rpc("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(" ".join(i.get("text", "") for i in result.get("content", [])))
        if "structuredContent" in result:
            return result["structuredContent"]
        return json.loads(result["content"][0]["text"])

    async def resolve_workspace(self):
        previous = _workspace_contexts.get(self.url)
        try:
            result = await self.call(
                "wangp_workspace", **({"agent_context": previous} if previous else {})
            )
        except RuntimeError as e:
            if not any(reason in str(e) for reason in _missing_workspace_errors):
                raise
            _workspace_contexts.pop(self.url, None)
            result = {}
        if not result.get("agent_context"):
            listing = await self.call("wangp_workspace", action="list", limit=200)
            manual = [w for w in listing["workspaces"] if w.get("owner_kind") == "manual"]
            if manual:
                # Prefer the default workspace after a deleted shared assignment.
                workspace = next((w for w in manual if w["name"] == "Default"), manual[0])
                result = await self.call(
                    "wangp_workspace", action="attach", workspace_id=workspace["id"]
                )
            else:
                result = await self.call(
                    "wangp_workspace", action="create", name="Krita", storage_mode="shared"
                )
        context: str = result["agent_context"]
        self._agent_context = context
        gallery = await self.call("wangp_list_gallery", media_type="video", selected_only=True)
        viewed = (gallery.get("selection_workspace") or {}).get("workspace_id")
        if viewed and viewed != result.get("workspace_id"):
            result = await self.call(
                "wangp_workspace",
                action="attach",
                workspace_id=viewed,
                agent_context=self._agent_context,
            )
            context = result["agent_context"]
            self._agent_context = context
        _workspace_contexts[self.url] = context

    async def upload_frame(self, png: bytes):
        filename = f"krita-{uuid4().hex}.png"
        grant = await self.call(
            "wangp_session",
            action="create_file_upload",
            arguments={"filename": filename, "size_bytes": len(png)},
        )
        url = urljoin(self.url, grant["upload_url"])
        if urlsplit(url)[:2] != urlsplit(self.url)[:2]:
            raise RuntimeError(_("WanGP returned an upload URL on a different server."))
        try:
            result = await self._requests.http("PUT", url, png, timeout=120, follow_redirects=False)
        except NetworkError:
            # Recover the path if WanGP finalized the upload before the response was lost.
            result = await self.call(
                "wangp_session", action="get_upload", arguments={"token": grant["token"]}
            )
        path = result.get("path", "")
        if not re.fullmatch(r"@documents\d*/uploads/[0-9a-f]{32}/" + re.escape(filename), path):
            raise RuntimeError(_("WanGP did not return an isolated temporary frame path."))
        return path

    async def delete_frame(self, path: str):
        for item in (path, path.rsplit("/", 1)[0]):
            result = await self.call(
                "wangp_io", action="delete", arguments={"path": item, "recursive": False}
            )
            if result.get("deleted") is not True:
                raise RuntimeError(_("WanGP did not confirm temporary frame cleanup."))

    async def wait_for_video(self, job_id: str, status: Callable[[str], None]):
        disconnected = False
        while True:
            try:
                if disconnected:
                    await self.connect()
                result = await self.call(
                    "wangp_session", action="get_job", arguments={"job_id": job_id}
                )
            except NetworkError as e:
                if e.status in (400, 401, 403, 405):
                    raise
                disconnected = True
                status(_("Reconnecting to WanGP to check video status") + f" ({job_id})")
                await asyncio.sleep(5)
                continue
            disconnected = False
            state = result.get("status")
            if state in (
                "done",
                "error",
                "interrupted",
                "cancelled",
                "unknown_after_restart",
            ):
                return result
            # WanGP's running snapshots may only contain done=false and progress.
            if result.get("done") is True:
                details = result.get("result") or {}
                if details.get("success"):
                    state = "done"
                elif details.get("cancelled"):
                    state = "interrupted"
                else:
                    state = "error"
                return {**result, "status": state}
            if state == "running" or result.get("progress"):
                status(_("Generating video in WanGP") + f" ({job_id})")
            else:
                status(_("Video queued in WanGP") + f" ({job_id})")
            await asyncio.sleep(2)


_video_lock = asyncio.Lock()


def read_video_settings(path: Path):
    try:
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ValueError(_("Could not read the selected WanGP settings JSON.")) from e
    if not isinstance(saved, dict):
        raise TypeError(_("Select a WanGP video settings JSON file."))
    model_type = saved.get("model_type")
    if not model_type and path.name.endswith("_settings.json"):
        model_type = path.stem.removesuffix("_settings")
    if not isinstance(model_type, str) or not model_type.strip():
        raise ValueError(_("The WanGP settings file does not identify a model."))
    for key in (
        "template",
        "client_id",
        "prompt",
        "alt_prompt",
        "image_start",
        "image_end",
        "image_refs",
        "image_guide",
        "image_mask",
        "video_guide",
        "video_guide2",
        "video_guide3",
        "video_mask",
        "video_source",
        "audio_guide",
        "audio_guide2",
        "audio_guide3",
        "audio_source",
        "replace_voice_sample",
        "replace_voice_sample2",
        "custom_guide",
        "postprocessing_reference_images",
    ):
        saved.pop(key, None)
    return {
        **saved,
        "model_type": model_type,
        "image_mode": 0,
        "image_prompt_type": "S",
        "prompt_enhancer": "",
    }


async def generate_video(
    client: WanGPClient,
    video_settings: dict,
    prompt: str,
    png: bytes,
    comfy: ComfyClient | None,
    status: Callable[[str], None],
):
    if _video_lock.locked():
        raise RuntimeError(_("A WanGP video request is already in progress."))
    async with _video_lock:
        await client.resolve_workspace()
        image_start = await client.upload_frame(png)
        del png
        settings = {
            **video_settings,
            "prompt": prompt,
            "image_start": image_start,
            "prompt_enhancer": "",
        }
        can_delete = True
        paused = False
        cleanup_failed = False
        try:
            validation = await client.call("wangp_validate", settings=settings)
            if not validation.get("valid"):
                raise RuntimeError(
                    _("WanGP could not validate the saved video settings.")
                    + " "
                    + str(validation.get("diagnostics", ""))
                )
            if comfy is not None:
                comfy.pause_for_video(True)
                paused = True
                status(_("Waiting for ComfyUI to release GPU memory…"))
                await comfy.release_gpu_for_video()
            request_id = uuid4().hex
            # A request without an acknowledgment can still be queued on the server.
            can_delete = False
            try:
                result = await client.call(
                    "wangp_generate", settings=settings, wait=False, request_id=request_id
                )
            except NetworkError as e:
                if e.status is not None and e.status < 500:
                    can_delete = True
                    raise
                # WanGP deduplicates the same request if its acknowledgment was lost.
                await client.connect()
                result = await client.call(
                    "wangp_generate", settings=settings, wait=False, request_id=request_id
                )
            job_id = result["job_id"]
            status(_("Video queued in WanGP") + f" ({job_id})")
            try:
                result = await client.wait_for_video(job_id, status)
            except RuntimeError as e:
                if not any(reason in str(e) for reason in _missing_workspace_errors):
                    raise
                raise RuntimeError(
                    _(
                        "WanGP accepted the video, but its workspace is no longer available. "
                        "Check the WanGP queue for job"
                    )
                    + f" {job_id}"
                ) from e
            can_delete = result["status"] != "unknown_after_restart"
            if result["status"] != "done":
                raise RuntimeError(_("WanGP video ended with status") + f" {result['status']}")
        finally:
            if comfy is not None and paused:
                comfy.pause_for_video(False)
            if can_delete:
                try:
                    await client.delete_frame(image_start)
                except Exception:
                    cleanup_failed = True
                    log.warning("WanGP temporary frame cleanup was not confirmed")
        status(
            _("Video ready in WanGP. Temporary frame cleanup could not be confirmed.")
            if cleanup_failed
            else _("Video ready in WanGP")
        )
