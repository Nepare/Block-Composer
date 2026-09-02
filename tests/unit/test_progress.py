import io
import json

from rich.console import Console

from core.progress import FileProgressSink, MultiSink, ProgressEvent, RichConsoleSink


def _console():
    buf = io.StringIO()
    return Console(file=buf, force_terminal=False, width=200), buf


def test_rich_console_sink_prints_narrative_message():
    console, buf = _console()
    sink = RichConsoleSink(console)

    sink(ProgressEvent(kind="plan_done", message="Plan built: 1 step(s)"))

    assert "Plan built: 1 step(s)" in buf.getvalue()


def test_rich_console_sink_skips_llm_call_diagnostic_events():
    console, buf = _console()
    sink = RichConsoleSink(console)

    sink(ProgressEvent(kind="llm_call_start", message="Calling some-model…", model="some-model"))

    assert buf.getvalue().strip() == ""


def test_rich_console_sink_escapes_bracket_markup_in_messages():
    console, buf = _console()
    sink = RichConsoleSink(console)

    sink(ProgressEvent(kind="use", message="use -> police_station [jail]"))

    # a literal bracket in a block id must survive, not be swallowed as Rich markup
    assert "[jail]" in buf.getvalue()


def test_file_progress_sink_appends_one_json_object_per_event(tmp_path):
    path = tmp_path / "logs" / "run.jsonl"
    sink = FileProgressSink(path)

    sink(ProgressEvent(kind="plan_done", message="Plan built: 1 step(s)", step=1, total=1))
    sink(ProgressEvent(kind="llm_call_done", message="model responded", model="m", latency_ms=12.5))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["kind"] == "plan_done"
    assert first["message"] == "Plan built: 1 step(s)"
    assert first["step"] == 1
    second = json.loads(lines[1])
    assert second["kind"] == "llm_call_done"
    assert second["model"] == "m"
    assert second["latency_ms"] == 12.5
    # `at` must be a serialized ISO timestamp, not the raw datetime object
    assert isinstance(first["at"], str)


def test_file_progress_sink_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "run.jsonl"

    FileProgressSink(path)

    assert path.parent.is_dir()


def test_multi_sink_fans_out_to_every_sink():
    received_a = []
    received_b = []
    sink = MultiSink(received_a.append, received_b.append)
    event = ProgressEvent(kind="naming", message="Naming result…")

    sink(event)

    assert received_a == [event]
    assert received_b == [event]
