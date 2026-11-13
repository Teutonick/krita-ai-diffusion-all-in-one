import asyncio
import wave

from ai_diffusion.backend import dictation as speech
from ai_diffusion.settings import settings


def test_recording_limit_stops_and_routes_to_original_field(monkeypatch, qtapp):
    stopped = []

    class Microphone:
        def __init__(self, seconds):
            assert seconds == 120

        def stop(self):
            stopped.append(True)
            return bytes(speech.sample_rate)

    monkeypatch.setattr(speech, "Microphone", Microphone)
    monkeypatch.setattr(speech, "supported", True)
    monkeypatch.setitem(settings._values, "dictation_enabled", True)
    monkeypatch.setitem(settings._values, "dictation_record_limit", 999)
    controller = speech.Dictation()
    controller.ready = True
    first, second = object(), object()
    delivered = []

    async def transcribe(target, pcm):
        delivered.append((target, pcm))

    monkeypatch.setattr(controller, "_transcribe", transcribe)

    async def run():
        controller.start(first)
        controller.start(second)
        assert controller.target is first
        assert controller._timer.interval() == 120_000
        controller._timer.timeout.emit()
        assert controller._transcription is not None
        await controller._transcription

    qtapp.run(run())
    assert stopped == [True]
    assert delivered == [(first, bytes(speech.sample_rate))]


def test_cancel_before_transcription_prevents_late_delivery(qtapp):
    controller = speech.Dictation()
    controller.ready = True
    target = object()
    delivered = []
    controller.recognized.connect(lambda *args: delivered.append(args))

    async def run():
        controller.target = target
        controller._transcription = asyncio.create_task(controller._transcribe(target, b""))
        task = controller._transcription
        controller.prompt_started()
        assert not controller.available
        await task
        assert not controller.available
        controller.prompt_finished()
        assert controller.available

    qtapp.run(run())
    assert delivered == []


def test_whisper_wav_format(tmp_path):
    audio = tmp_path / "sample.wav"
    samples = b"\x01\x00\xff\xff"
    speech.write_wav(audio, samples)
    with wave.open(str(audio), "rb") as file:
        assert (file.getnchannels(), file.getsampwidth(), file.getframerate()) == (1, 2, 16000)
        assert file.readframes(2) == samples
