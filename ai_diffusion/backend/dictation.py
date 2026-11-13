from __future__ import annotations

import asyncio
import ctypes as c
import hashlib
import io
import os
import platform
import time
import wave
import zipfile
from ctypes import wintypes as w
from pathlib import Path

from PyQt5.QtCore import QObject, QProcess, QTimer, QUrl, pyqtSignal
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import eventloop, media_storage
from ..localization import translate as _
from ..settings import settings
from ..util import client_logger as log
from ..util import user_data_dir

supported = (
    platform.system() == "Windows"
    and platform.machine().lower() in ("amd64", "x86_64")
    and c.sizeof(c.c_void_p) == 8
)
sample_rate = 16000
model_name = "ggml-base-q5_1.bin"
runtime_url = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.3/whisper-bin-x64.zip"
runtime_hash = "d824b1e37599f882b396e73f1ee0bfd5d0529f700314c48311dcbd00b803321d"
model_url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{model_name}"
model_hash = "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898"


class WaveFormat(c.Structure):
    _pack_ = 1
    _fields_ = [
        ("tag", w.WORD),
        ("channels", w.WORD),
        ("rate", w.DWORD),
        ("byte_rate", w.DWORD),
        ("alignment", w.WORD),
        ("bits", w.WORD),
        ("extra", w.WORD),
    ]


class WaveHeader(c.Structure):
    _fields_ = [
        ("data", c.c_void_p),
        ("size", w.DWORD),
        ("recorded", w.DWORD),
        ("user", c.c_size_t),
        ("flags", w.DWORD),
        ("loops", w.DWORD),
        ("next", c.c_void_p),
        ("reserved", c.c_size_t),
    ]


class Microphone:
    def __init__(self, seconds: int):
        self._api = c.WinDLL("winmm")
        self._handle = w.HANDLE()
        self._prepared = False
        self._buffer = c.create_string_buffer(seconds * sample_rate * 2)
        self._header = WaveHeader(c.addressof(self._buffer), len(self._buffer))
        fmt = WaveFormat(1, 1, sample_rate, sample_rate * 2, 2, 16, 0)
        self._check(
            self._api.waveInOpen(
                c.byref(self._handle),
                c.c_size_t(0xFFFFFFFF),
                c.byref(fmt),
                c.c_size_t(0),
                c.c_size_t(0),
                w.DWORD(0),
            )
        )
        try:
            self._header_call("waveInPrepareHeader")
            self._prepared = True
            self._header_call("waveInAddBuffer")
            self._check(self._api.waveInStart(self._handle))
        except Exception:
            self.stop()
            raise

    def _check(self, result: int):
        if result:
            message = c.create_unicode_buffer(256)
            self._api.waveInGetErrorTextW(result, message, len(message))
            raise RuntimeError(message.value or f"winmm: {result}")

    def _header_call(self, name: str):
        self._check(
            getattr(self._api, name)(self._handle, c.byref(self._header), c.sizeof(self._header))
        )

    def stop(self):
        self._check(self._api.waveInReset(self._handle))
        if self._prepared:
            self._header_call("waveInUnprepareHeader")
            self._prepared = False
        self._check(self._api.waveInClose(self._handle))
        return c.string_at(self._buffer, self._header.recorded)


def write_wav(path: Path, pcm: bytes):
    with wave.open(str(path), "wb") as file:
        file.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
        file.writeframes(pcm)


class Dictation(QObject):
    changed = pyqtSignal()
    recognized = pyqtSignal(object, str)

    def __init__(self):
        super().__init__()
        self.target: object | None = None
        self.status = ""
        self.ready = False
        self.install_failed = False
        self._prompt_jobs = 0
        self._closing = False
        self._mic: Microphone | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.finish)
        self._install_task: asyncio.Task | None = None
        self._transcription: asyncio.Task | None = None
        self._process: QProcess | None = None
        settings.changed.connect(self._setting_changed)

    @property
    def recording(self):
        return self._mic is not None

    @property
    def available(self):
        return (
            self.ready
            and self.target is None
            and self._transcription is None
            and not self._prompt_jobs
        )

    def prompt_started(self):
        self._prompt_jobs += 1
        self.cancel()
        self.changed.emit()

    def prompt_finished(self):
        self._prompt_jobs -= 1
        self.changed.emit()

    @property
    def directory(self):
        return user_data_dir / "dictation"

    def _setting_changed(self, key: str, value):
        if key == "dictation_enabled":
            self.configure()

    def configure(self):
        self.install_failed = False
        if not settings.dictation_enabled or not supported:
            self.cancel()
            if self._install_task is not None:
                self._install_task.cancel()
            self._status("" if supported else _("Dictation requires Windows x64."))
        elif self._install_task is None:
            self.ready = (self.directory / "v1.8.3" / "whisper-cli.exe").is_file() and (
                self.directory / model_name
            ).is_file()
            if self.ready:
                self._status(_("Ready"))
            else:
                self._install_task = eventloop.run(self._install())
                self._install_task.add_done_callback(self._installation_done)

    def _installation_done(self, task: asyncio.Task):
        self._install_task = None
        if task.cancelled() and settings.dictation_enabled and not self._closing:
            self.configure()
        self.changed.emit()

    def _status(self, text: str):
        self.status = text
        self.changed.emit()

    async def _install(self):
        self._status(_("Downloading Whisper runtime and model…"))
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            runtime = self.directory / "v1.8.3"
            if not (runtime / "whisper-cli.exe").is_file():
                payload = await self._download(runtime_url, runtime_hash, 8 * 1024**2)
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    runtime.mkdir(exist_ok=True)
                    files = {
                        Path(name).name: name
                        for name in archive.namelist()
                        if Path(name).suffix.lower() == ".dll"
                        or Path(name).name == "whisper-cli.exe"
                    }
                    # Publish the executable last so a partial install is retried.
                    exe = files.pop("whisper-cli.exe")
                    for name, member in files.items():
                        (runtime / name).write_bytes(archive.read(member))
                    partial = runtime / "whisper-cli.part"
                    try:
                        partial.write_bytes(archive.read(exe))
                        partial.replace(runtime / "whisper-cli.exe")
                    finally:
                        partial.unlink(missing_ok=True)
            model = self.directory / model_name
            if not model.is_file():
                payload = await self._download(model_url, model_hash, 70 * 1024**2)
                partial = model.with_suffix(".part")
                try:
                    partial.write_bytes(payload)
                    partial.replace(model)
                finally:
                    partial.unlink(missing_ok=True)
            self.ready = True
            self._status(_("Ready"))
        except Exception as e:
            log.warning(f"Dictation setup: {e}")
            self.install_failed = True
            self._status(_("Whisper setup failed: {error}", error=e))

    async def _download(self, url: str, checksum: str, max_bytes: int):
        net = QNetworkAccessManager()
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setTransferTimeout(30_000)
        reply = net.get(request)
        assert reply is not None
        payload = bytearray()

        def read():
            payload.extend(reply.readAll().data())
            if len(payload) > max_bytes:
                reply.abort()

        reply.readyRead.connect(read)
        try:
            deadline = time.monotonic() + 600
            while not reply.isFinished():
                if time.monotonic() >= deadline:
                    raise TimeoutError(_("Whisper download timed out."))
                await asyncio.sleep(0.05)
            read()
            if reply.error() != QNetworkReply.NetworkError.NoError:  # type: ignore (PyQt5 stubs)
                raise RuntimeError(reply.errorString())
            if hashlib.sha256(payload).hexdigest() != checksum:
                raise RuntimeError(_("Whisper download failed its checksum check."))
            return payload
        finally:
            reply.abort()

    def start(self, target: object):
        if not (supported and settings.dictation_enabled and self.available):
            return
        seconds = max(15, min(settings.dictation_record_limit, 120))
        try:
            self._mic = Microphone(seconds)
        except Exception as e:
            self._status(_("Could not open the microphone: {error}", error=e))
            return
        self.target = target
        self._timer.start(seconds * 1000)
        self._status(_("Recording… Click the microphone to stop."))

    def finish(self):
        if self._mic is None:
            return
        self._timer.stop()
        try:
            pcm = self._mic.stop()
        except Exception as e:
            self.target = None
            self._mic = None
            self._status(_("Could not stop the microphone: {error}", error=e))
            return
        finally:
            self._mic = None
        if len(pcm) < sample_rate // 2:
            self.target = None
            self._status(_("Recording was too short."))
            return
        self._transcription = eventloop.run(self._transcribe(self.target, pcm))
        self._status(_("Transcribing…"))

    async def _transcribe(self, target: object, pcm: bytes):
        try:
            if self.target is not target:
                return
            with media_storage.temporary_directory("dictation-") as folder:
                audio = Path(folder) / "recording.wav"
                output = Path(folder) / "transcript"
                write_wav(audio, pcm)
                process = QProcess()
                self._process = process
                process.setWorkingDirectory(folder)
                process.setStandardOutputFile(QProcess.nullDevice())
                process.setStandardErrorFile(QProcess.nullDevice())
                try:
                    process.start(
                        str(self.directory / "v1.8.3" / "whisper-cli.exe"),
                        [
                            "-m",
                            os.path.relpath(self.directory / model_name, folder),
                            "-f",
                            audio.name,
                            "-l",
                            settings.dictation_language.strip().lower() or "auto",
                            "-ng",
                            "-t",
                            str(min(4, os.cpu_count() or 1)),
                            "-nt",
                            "-sns",
                            "-otxt",
                            "-of",
                            output.name,
                        ],
                    )
                    deadline = time.monotonic() + 180
                    while process.state() != QProcess.ProcessState.NotRunning:
                        if time.monotonic() >= deadline:
                            raise TimeoutError()
                        await asyncio.sleep(0.05)
                    if self.target is not target:
                        return
                    if (
                        process.exitStatus() != QProcess.ExitStatus.NormalExit
                        or process.exitCode() != 0
                        or not output.with_suffix(".txt").is_file()
                    ):
                        raise RuntimeError(_("Whisper could not transcribe this recording."))
                    text = " ".join(output.with_suffix(".txt").read_text(encoding="utf-8").split())
                    if self.target is target and text:
                        self.recognized.emit(target, text)
                    self._status(_("Ready") if text else _("No speech recognized."))
                finally:
                    self._kill_process()
        except TimeoutError:
            self._status(_("Dictation timed out."))
        except Exception as e:
            self._status(_("Dictation failed: {error}", error=e))
        finally:
            self.target = None
            self._transcription = None
            self.changed.emit()

    def _kill_process(self):
        if self._process is not None:
            if self._process.state() != QProcess.ProcessState.NotRunning:
                self._process.kill()
                self._process.waitForFinished(2000)
            self._process = None

    def cancel(self, target: object | None = None):
        if self.target is None or (target is not None and self.target is not target):
            return
        self.target = None
        self._timer.stop()
        if self._mic is not None:
            try:
                self._mic.stop()
            except Exception:
                log.exception("Could not release the microphone")
            self._mic = None
        self._kill_process()
        self._status(_("Ready"))

    def shutdown(self):
        self._closing = True
        self.cancel()
        if self._transcription is not None:
            self._transcription.cancel()
        if self._install_task is not None:
            self._install_task.cancel()


dictation = Dictation()
