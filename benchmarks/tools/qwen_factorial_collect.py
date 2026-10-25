"""Missing-only factorial collection. No model lifecycle, scoring, or retry authority.

This standalone tool deliberately uses curl rather than BakeoffClient._timed_chat:
the latter does not carry the qualified native response_format constraint.
Builders and acceptance still come from the pinned genuine producer/service.
See docs/assessments/qwen-factorial-collector-20261025.md for the input contract.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import copy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit


BAKEOFF_SHA = "87c58a41cb0a9421605dd9adf80aaee91bdde7eb5b6e54c39cde540f97e3ca66"
PRODUCER_SHA = "5c89754916884fc3448e00067e40afab4fd0f850bb430200a7a74c82bafc1838"
LOADER_SHA = "4ac52b4f22fb426eb10067a6cb465f310c9240989166fd395b11b0a491079f68"
DEPICTION_SHA = "765a46f1633332e8c8b58cb6875b623e495df933828ba43790fdc05432ca4fb8"
SCHEMA = "qwen-factorial-collector/v1"
RESPONSE_LIMIT = 8 * 1024**2
FILE_LIMIT = 64 * 1024**2
SURFACES = {"title", "alt", "caption"}
REQUIRED_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {key: {"type": "string", "minLength": 1} for key in sorted(SURFACES)},
    "required": ["title", "alt", "caption"],
}


class Invalid(ValueError):
    """A binding, immutable artifact, or acceptance check failed."""


class WrongModel(Invalid):
    """Quarantine this output and stop its entire model stream."""


def need(condition, message):
    if not condition:
        raise Invalid(message)


def sha(raw):
    return hashlib.sha256(raw.encode() if isinstance(raw, str) else raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            need(key not in out, "duplicate JSON key")
            out[key] = value
        return out

    def constant(_):
        raise Invalid("nonfinite JSON")

    def number(text):
        value = float(text)
        need(math.isfinite(value), "nonfinite JSON")
        return value

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


def read(path, limit=FILE_LIMIT):
    # Evidence and input leaves cannot be symlinks. The evidence root is caller-owned.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(limit + 1)
    need(len(raw) <= limit, "file exceeds bounded read")
    return raw


def pin(path, digest):
    need(isinstance(digest, str) and re.fullmatch("[0-9a-f]{64}", digest), "invalid SHA256")
    raw = read(path)
    need(sha(raw) == digest, "file digest mismatch")
    return raw


def pinned_file(spec):
    need(set(spec) == {"path", "sha256"} and Path(spec["path"]).is_absolute(),
         "absolute path and SHA256 required")
    return pin(spec["path"], spec["sha256"])


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdir(path):
    need(all(not part.is_symlink() for part in (path, *path.parents)),
         "evidence directory ancestors must not be symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    need(path.is_dir() and not path.is_symlink(), "evidence directory must not be a symlink")
    sync_dir(path.parent)


def new_file(path):
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)


def write_new(path, raw):
    """No replacement, even after a crash; a torn artifact fails closed on resume."""
    if not isinstance(raw, bytes):
        raw = canonical(raw) + b"\n"
    fd = new_file(path)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(path.parent)
    return sha(raw)


def load_module(path, name, digest):
    pin(path, digest)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Genuine:
    """Offline-only facade over actual, digest-checked frozen code."""

    def __init__(self, cfg):
        self.cfg = cfg
        service = Path(cfg["service_dir"]).resolve()
        bakeoff = service / "scripts/eval_harness/bakeoff.py"
        pin(bakeoff, BAKEOFF_SHA)
        pin(cfg["loader_override"], LOADER_SHA)
        pin(Path(cfg["canon_root"]) / "lexicons/depiction.md", DEPICTION_SHA)
        # Do not produce bytecode in the read-only frozen resources.
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(service))
        self.producer = load_module(cfg["original_producer"], "_qwen_original_producer", PRODUCER_SHA)
        resource_cfg = dict(cfg, loader_sha256=LOADER_SHA, canon_sha256=DEPICTION_SHA)
        self.b, self.lex = self.producer.load_resources(resource_cfg)
        need(Path(self.b.__file__).resolve() == bakeoff, "genuine service import origin mismatch")
        need(self.lex.version == "canon v0.26.2" and len(self.lex.rules) == 17,
             "depiction lexicon identity mismatch")

    def client(self, model, writing):
        return self.b.BakeoffClient(
            model["endpoint"], model_id=model["request_model"], seed=0, no_think=True,
            timeout_s=300, eval_mode="name_ablation", entry_traits={}, roster=[],
            prompt_variant="v3", caption_length="standard", two_pass=True,
            depiction_lexicon=self.lex if writing else None,
        )

    def extraction_messages(self, client, enabled, image):
        return self.producer.extraction_messages(self.b, client, self.lex, bool(enabled), image)

    def accept(self, raw, model, writing):
        envelope = strict_json(raw)
        # This check is mandatory even if parsing the text would subsequently fail.
        if envelope.get("model") != model["expected_response_model"]:
            raise WrongModel("missing or wrong actual response model")
        choices = envelope.get("choices")
        need(type(choices) is list and len(choices) == 1, "exactly one completion required")
        choice = choices[0]
        need(choice.get("finish_reason") == "stop", "completion did not stop normally")
        text = choice.get("message", {}).get("content")
        need(type(text) is str and bool(text.strip()), "missing generated text")
        if writing:
            value = strict_json(text)
            need(type(value) is dict and set(value) == SURFACES and
                 all(type(v) is str and v.strip() for v in value.values()),
                 "writer must be strict raw three-surface JSON")
            self.b._parse_three_surface_json(text)
        else:
            self.b._parse_pass1_json(text)
        # A received response without trustworthy usage is not an inference receipt.
        usage = envelope.get("usage", {})
        measured = all(type(usage.get(k)) is int and usage[k] >= 0
                       for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
        measured = measured and usage["completion_tokens"] > 0 and (
            usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"])
        return {"text": text, "text_sha256": sha(text), "inference_receipt": measured,
                "usage": usage if measured else None}


def endpoint(value):
    url = urlsplit(value)
    need(url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password
         and url.path in {"", "/"} and not url.query and not url.fragment,
         "endpoint must be a root HTTP URL without credentials")
    need(url.port is None or 1 <= url.port <= 65535, "invalid endpoint port")


def finite(value, name, minimum=0):
    need(type(value) in (int, float) and math.isfinite(value) and value > minimum,
         "invalid " + name)


def slug(value):
    need(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value)
         and value not in {".", ".."}, "invalid stage identifier")
    return value


def decoder(payload, tokens):
    need(type(payload) is dict and type(payload.get("seed")) is int and payload["seed"] == 0
         and type(payload.get("temperature")) in (int, float) and payload["temperature"] == 0
         and type(payload.get("top_p")) in (int, float) and payload["top_p"] == 1
         and type(payload.get("max_tokens")) is int and payload["max_tokens"] == tokens,
         "qualified greedy decoder/token limits required")
    need(payload.get("stream", False) is False and payload.get("n", 1) == 1,
         "streaming/multiple completions forbidden")
    for where in (payload, payload.get("chat_template_kwargs", {}),
                  payload.get("extra_body", {}).get("chat_template_kwargs", {})):
        need(where.get("enable_thinking", False) is False, "thinking must be disabled")


def writer_template(raw):
    payload = strict_json(raw)
    decoder(payload, 512)
    rf = payload.get("response_format", {})
    schema = rf.get("schema", {})
    need(rf.get("type") == "json_object", "native json_object response_format required")
    need(all(schema.get(k) == REQUIRED_SCHEMA[k]
             for k in ("type", "additionalProperties", "properties"))
         and set(schema.get("required", [])) == SURFACES,
         "qualified native three-surface schema required")
    return payload


def image_part(payload, digest):
    messages = payload.get("messages", [])
    parts = [part for msg in messages if isinstance(msg.get("content"), list)
             for part in msg["content"] if part.get("type") == "image_url"]
    need(len(parts) == 1, "exactly one original image part required")
    url = parts[0].get("image_url", {}).get("url", "")
    need(re.fullmatch(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\r\n]+", url),
         "opaque base64 image data URL required")
    data = base64.b64decode(url.split(",", 1)[1], validate=True)
    need(sha(data) == digest, "actual data URL image digest mismatch")
    return parts[0]


class Children:
    """Bounded process supervisor; only children spawned here can be terminated."""

    def __init__(self, stop):
        self.stop = stop
        self.lock = threading.Lock()
        self.children = set()

    @staticmethod
    def kill(child):
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        child.wait()

    def run(self, argv, *, timeout, **kwargs):
        need(not self.stop.is_set(), "supervisor stopped before spawn")
        child = subprocess.Popen(argv, start_new_session=True, **kwargs)
        with self.lock:
            self.children.add(child)
        end = time.monotonic() + timeout
        try:
            while child.poll() is None:
                if self.stop.is_set() or time.monotonic() >= end:
                    self.kill(child)
                    return {"returncode": child.returncode, "spawned": True, "interrupted": True}
                self.stop.wait(min(0.05, max(0, end - time.monotonic())))
            return {"returncode": child.returncode, "spawned": True, "interrupted": False}
        finally:
            self.kill(child)
            with self.lock:
                self.children.discard(child)

    def close(self):
        self.stop.set()
        with self.lock:
            children = list(self.children)
        for child in children:
            self.kill(child)


class Curl:
    def __init__(self, children):
        self.children = children

    def __call__(self, model, header_file, directory, *, timeout, cleanup):
        files = {}
        try:
            for name in ("response.json", "metrics.json", "headers.txt"):
                files[name] = os.fdopen(new_file(directory / name), "wb")
            response_fd = files["response.json"].fileno()
            headers_fd = files["headers.txt"].fileno()
            argv = ["/usr/bin/curl", "-q", "--silent", "--request", "POST",
                    "--proto", "=http,https", "--noproxy", "*", "--retry", "0",
                    "--connect-timeout", "5", "--max-time", str(timeout),
                    "--max-filesize", str(RESPONSE_LIMIT), "--max-redirs", "0",
                    "--header", "@" + str(header_file), "--header", "Content-Type: application/json",
                    "--data-binary", "@" + str(directory / "request.json"),
                    "--output", f"/proc/self/fd/{response_fd}",
                    "--dump-header", f"/proc/self/fd/{headers_fd}", "--write-out", "%{json}",
                    model["endpoint"].rstrip("/") + "/v1/chat/completions"]
            # Reserve cleanup for sealing results instead of spending it waiting on curl.
            return self.children.run(argv, timeout=timeout,
                                     stdout=files["metrics.json"], stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL, pass_fds=(response_fd, headers_fd))
        finally:
            for stream in files.values():
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
            sync_dir(directory)


def http_received(metrics):
    code = metrics.get("http_code", metrics.get("response_code"))
    need(type(code) is int and 100 <= code <= 599, "no received native HTTP response")
    return code


def pointer(value, path):
    need(isinstance(path, str) and path.startswith("/"), "JSON pointer required")
    for token in path[1:].split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


class Collector:
    def __init__(self, cfg, evidence, deadline, *, genuine=None, boundary=None, clock=time.time):
        self.cfg = copy.deepcopy(cfg)
        self.evidence = Path(evidence).absolute()
        finite(deadline, "absolute deadline")
        self.deadline = deadline
        self.clock = clock
        self.stop = threading.Event()
        self.heartbeat_error = None
        self.children = Children(self.stop)
        self.boundary = boundary if boundary is not None else Curl(self.children)
        self.genuine = genuine if genuine is not None else Genuine(strict_json(pinned_file(cfg["resources"])))
        self.validate()

    def validate(self):
        cfg = self.cfg
        self.template_raw = pinned_file(cfg["writer_template"])
        self.template = writer_template(self.template_raw)
        # No opening, statting or logging the credential file contents.
        need(Path(cfg["header_file"]).is_absolute() and "\n" not in cfg["header_file"],
             "absolute header FILE locator required")
        self.timeout = cfg.get("timeout_s", 300)
        need(type(self.timeout) is int and 5 <= self.timeout <= 300, "timeout must be integer 5..300")
        self.cleanup = cfg.get("cleanup_margin_s", 5)
        finite(self.cleanup, "cleanup margin")
        self.parallel = cfg.get("max_parallel_models", 2)
        need(type(self.parallel) is int and 1 <= self.parallel <= 8, "invalid parallel model limit")
        need(type(cfg["models"]) is list and 1 <= len(cfg["models"]) <= 8, "bounded models required")
        ids = set()
        response_models = set()
        endpoints = set()
        self.prepared = {}
        for model in cfg["models"]:
            mid = slug(model["id"])
            need(mid not in ids, "duplicate model stream")
            ids.add(mid)
            endpoint(model["endpoint"])
            for key in ("expected_response_model", "request_model", "precision", "native_epoch"):
                need(type(model[key]) is str and model[key] and model[key] == model[key].strip(),
                     "explicit model/precision/native epoch binding required")
            need(model["expected_response_model"] not in response_models and
                 model["endpoint"].rstrip("/") not in endpoints, "duplicate serving model/endpoint stream")
            response_models.add(model["expected_response_model"])
            endpoints.add(model["endpoint"].rstrip("/"))
            pinned_file(model["profile"])
            finite(model["deadline_unix"], "model absolute deadline")
            need(type(model["extractions"]) is list and len(model["extractions"]) <= 1000,
                 "bounded extraction entries required")
            client = self.genuine.client(model, False)
            seen = set()
            try:
                for entry in model["extractions"]:
                    slug(entry["image_id"])
                    need(type(entry["E"]) is int and entry["E"] in (0, 1), "E must be 0 or 1")
                    key = (entry["image_id"], entry["E"])
                    need(key not in seen, "duplicate extraction")
                    seen.add(key)
                    raw = pinned_file(entry["request"])
                    payload = strict_json(raw)
                    decoder(payload, 1536)
                    need(payload.get("model") == model["request_model"], "extraction request model mismatch")
                    part = image_part(payload, entry["input_sha256"])
                    need(payload["messages"] == self.genuine.extraction_messages(client, entry["E"], part),
                         "extraction differs from genuine builder")
                    self.prepared[(mid, *key)] = (raw, part)
            finally:
                client.close()
        self.adoptions = {}
        for source in cfg.get("adopt", []):
            key = (source["model_id"], source["image_id"], source["E"], source.get("W"))
            need(key not in self.adoptions and key[:3] in self.prepared, "unknown/duplicate legacy stage")
            need(key[3] is None or type(key[3]) is int and key[3] in (0, 1), "invalid legacy W")
            need(set(source["sha256"]) == {"request.json", "intent.json", "response.json",
                                           "metrics.json", "result.json"}, "five pinned legacy artifacts required")
            need(Path(source["directory"]).is_absolute(), "absolute legacy directory required")
            self.adoptions[key] = source
        hb = cfg.get("heartbeat")
        need(hb is None or type(hb) is dict and bool(hb), "heartbeat must be a nonempty object")
        if hb:
            need(type(hb["argv"]) is list and hb["argv"] and
                 all(type(v) is str and v and "\x00" not in v for v in hb["argv"])
                 and Path(hb["argv"][0]).is_absolute(), "absolute heartbeat argv required; no shell")
            for name in ("deadline_unix", "interval_s", "timeout_s"):
                finite(hb[name], "heartbeat " + name)
            need(hb["timeout_s"] <= 300 and hb["interval_s"] <= 300,
                 "heartbeat command/interval must be bounded by 300s")
            need(type(hb["max_count"]) is int and 1 <= hb["max_count"] <= 10000,
                 "finite heartbeat count required")

    def stage_key(self, model, entry, writing):
        return (model["id"], entry["image_id"], entry["E"], writing)

    def binding(self, model, entry, writing, raw, parent):
        return dict(model_id=model["id"], precision=model["precision"],
                    expected_response_model=model["expected_response_model"], request_model=model["request_model"],
                    endpoint=model["endpoint"], profile_sha256=model["profile"]["sha256"],
                    native_epoch=model["native_epoch"], image_id=entry["image_id"],
                    image_sha256=entry["input_sha256"], E=entry["E"], W=writing,
                    request_sha256=sha(raw) if raw is not None else None,
                    facts_sha256=parent["text_sha256"] if parent else None,
                    parent_response_sha256=parent["response_sha256"] if parent else None)

    def directory(self, model, entry, writing):
        leaf = f"{entry['image_id']}-E{entry['E']}" + (f"-W{writing}" if writing is not None else "")
        return self.evidence / model["id"] / leaf

    def validate_response(self, directory, model, writing, process, raws=None):
        # Adopt exactly the bytes whose pins were checked, without a second source read.
        metrics_raw = raws["metrics.json"] if raws is not None else read(directory / "metrics.json", RESPONSE_LIMIT)
        response_raw = raws["response.json"] if raws is not None else read(directory / "response.json", RESPONSE_LIMIT)
        need(len(metrics_raw) <= RESPONSE_LIMIT and len(response_raw) <= RESPONSE_LIMIT, "response too large")
        metrics = strict_json(metrics_raw)
        code = http_received(metrics)
        need(process["spawned"] is True and type(process["returncode"]) is int
             and process["returncode"] == 0 and process["interrupted"] is False,
             "native subprocess failed or interrupted")
        need(code == 200, "native HTTP status is not 200")
        accepted = self.genuine.accept(response_raw, model, writing is not None)
        accepted["response_sha256"] = sha(response_raw)
        return accepted

    def resume(self, directory, binding, model, writing):
        result = strict_json(read(directory / "result.json"))
        need(result["binding"] == binding, "resume result binding mismatch")
        if result["status"] == "dependency_skip":
            return result
        need(sha(read(directory / "request.json")) == binding["request_sha256"], "resume request mismatch")
        intent_raw = read(directory / "intent.json")
        need(sha(intent_raw) == result["intent_sha256"] and strict_json(intent_raw)["binding"] == binding,
             "resume intent binding mismatch")
        if result["status"] == "accepted":
            need({"response.json", "metrics.json", "headers.txt"} <= set(result["files"]),
                 "accepted evidence is incomplete")
        for name, digest in result["files"].items():
            need(name in {"response.json", "metrics.json", "headers.txt", "legacy-intent.json", "legacy-result.json"},
                 "unexpected evidence filename")
            pin(directory / name, digest)
        if result["status"] == "accepted":
            accepted = self.validate_response(directory, model, writing, result["process"])
            need({key: value for key, value in accepted.items() if key != "text"} == result["accepted"],
                 "resume acceptance lineage mismatch")
            result = dict(result, facts=accepted)
        return result

    def adopt(self, source, directory, binding, model, writing):
        """Explicit adoption, never directory scanning or status-only reuse.

        Selectors allow an operator to identify fields in an older intent/result
        without editing it. Every binding must be evidenced in both records.
        """
        old = Path(source["directory"])
        raws = {name: pin(old / name, digest) for name, digest in source["sha256"].items()}
        need(sha(raws["request.json"]) == binding["request_sha256"], "legacy request mismatch")
        intent, result = (strict_json(raws[n]) for n in ("intent.json", "result.json"))
        for label, value in (("intent", intent), ("result", result)):
            selectors = source.get(label + "_fields", {})
            for key, expected in binding.items():
                need(pointer(value, selectors.get(key, "/binding/" + key)) == expected,
                     "legacy " + label + " binding mismatch")
        accepted_value = source.get("accepted_value", "accepted")
        need(accepted_value is True or accepted_value in {"accepted", "success", "ok", "completed"},
             "legacy accepted status value required")
        actual_status = pointer(result, source.get("status_field", "/status"))
        need(type(actual_status) is type(accepted_value) and actual_status == accepted_value,
             "legacy stage was not accepted; no retry authority")
        need(pointer(result, source.get("response_sha256_field", "/files/response.json")) ==
             sha(raws["response.json"]), "legacy response receipt mismatch")
        need(pointer(result, source.get("metrics_sha256_field", "/files/metrics.json")) ==
             sha(raws["metrics.json"]), "legacy metrics receipt mismatch")
        process = pointer(result, source.get("process_field", "/process"))
        # Validate in the source before any destination mutation.
        accepted = self.validate_response(old, model, writing, process, raws)
        mkdir(directory)
        for name in ("request.json", "response.json", "metrics.json"):
            write_new(directory / name, raws[name])
        write_new(directory / "headers.txt", b"")
        write_new(directory / "legacy-intent.json", raws["intent.json"])
        write_new(directory / "legacy-result.json", raws["result.json"])
        intent_sha = write_new(directory / "intent.json", {
            "binding": binding, "kind": "legacy_adoption", "source": source,
            "source_intent_sha256": sha(raws["intent.json"]),
            "source_result_sha256": sha(raws["result.json"]),
        })
        return self.result(directory, binding, intent_sha, "accepted", process, accepted,
                           adopted=True)

    def result(self, directory, binding, intent_sha, status, process, accepted=None,
               *, adopted=False, error=None):
        files = {name: sha(read(directory / name)) for name in
                 ("response.json", "metrics.json", "headers.txt", "legacy-intent.json", "legacy-result.json")
                 if (directory / name).exists()}
        received = False
        try:
            received = bool(http_received(strict_json(read(directory / "metrics.json"))))
        except (OSError, ValueError, TypeError, KeyError):
            pass
        value = dict(binding=binding, intent_sha256=intent_sha, status=status, process=process,
                     files=files, native_http_attempt=bool(process["spawned"]) and not adopted,
                     received_response=received and not adopted,
                     verified_inference_receipt=bool(accepted and accepted["inference_receipt"]) and not adopted,
                     adopted=adopted, error=error,
                     accepted={k: v for k, v in accepted.items() if k != "text"} if accepted else None)
        write_new(directory / "result.json", value)
        return dict(value, facts=accepted) if accepted else value

    def stage(self, model, entry, writing, raw, parent=None):
        directory = self.directory(model, entry, writing)
        source = self.adoptions.get(self.stage_key(model, entry, writing))
        if source and raw is not None:
            # Legacy request serialization is evidence too. Require whole-payload
            # equivalence, then preserve its raw hash instead of rewriting it.
            if (directory / "result.json").exists():
                legacy_raw = read(directory / "request.json")
            else:
                legacy_raw = pin(Path(source["directory"]) / "request.json", source["sha256"]["request.json"])
            need(strict_json(legacy_raw) == strict_json(raw), "legacy request payload differs from genuine request")
            raw = legacy_raw
        binding = self.binding(model, entry, writing, raw, parent)
        if (directory / "result.json").exists():
            return self.resume(directory, binding, model, writing)
        # Any incomplete prior claim is uncertain, never permission to repeat POST.
        if directory.exists():
            raise Invalid("incomplete stage evidence; no automatic retry")
        if source:
            return self.adopt(source, directory, binding, model, writing)
        mkdir(directory)
        if raw is None:
            value = {"binding": binding, "status": "dependency_skip", "native_http_attempt": False,
                     "received_response": False, "verified_inference_receipt": False}
            write_new(directory / "result.json", value)
            return value
        write_new(directory / "request.json", raw)
        bound = min(self.deadline, model["deadline_unix"],
                    (self.cfg.get("heartbeat") or {}).get("deadline_unix", self.deadline))
        remaining = bound - self.clock()
        allowed = not self.stop.is_set() and remaining > self.timeout + self.cleanup
        intent_sha = write_new(directory / "intent.json", {
            "binding": binding, "kind": "native_http" if allowed else "unsubmitted_skip",
            "deadline_unix": bound,
            "submitted_at_unix": self.clock() if allowed else None,
        })
        process = {"spawned": False, "returncode": None, "interrupted": False}
        if not allowed:
            return self.result(directory, binding, intent_sha, "deadline_or_stop_skip", process)
        try:
            # Recheck after the evidence fsyncs and immediately before the boundary.
            need(not self.stop.is_set() and bound - self.clock()
                 > self.timeout + self.cleanup, "deadline expired before native boundary")
            process = self.boundary(model, Path(self.cfg["header_file"]), directory,
                                    timeout=self.timeout, cleanup=self.cleanup)
            accepted = self.validate_response(directory, model, writing, process)
            return self.result(directory, binding, intent_sha, "accepted", process, accepted)
        except WrongModel:
            return self.result(directory, binding, intent_sha, "quarantined_wrong_model", process,
                               error="WrongModel")
        except Exception as exc:
            # Error class only: parser/subprocess diagnostics can contain private text.
            return self.result(directory, binding, intent_sha, "failed", process, error=type(exc).__name__)

    def stream(self, model):
        clients = {writing: self.genuine.client(model, writing) for writing in (0, 1)}
        counts = {"native_http_attempts": 0, "received_responses": 0, "verified_inference_receipts": 0,
                  "accepted": 0, "reused": 0, "adopted": 0, "failed_or_skipped": 0}
        def count(result, existing):
            counts["reused"] += existing
            counts["adopted"] += bool(result.get("adopted")) and not existing
            counts["accepted"] += result["status"] == "accepted"
            counts["failed_or_skipped"] += result["status"] != "accepted"
            if not existing:
                for out, key in (("native_http_attempts", "native_http_attempt"),
                                 ("received_responses", "received_response"),
                                 ("verified_inference_receipts", "verified_inference_receipt")):
                    counts[out] += bool(result.get(key))
        try:
            for entry in model["extractions"]:
                if self.stop.is_set():
                    break
                raw, part = self.prepared[(model["id"], entry["image_id"], entry["E"])]
                existing = (self.directory(model, entry, None) / "result.json").exists()
                extraction = self.stage(model, entry, None, raw)
                count(extraction, existing)
                if extraction["status"] == "quarantined_wrong_model":
                    return dict(counts, stopped="wrong_model")
                parent = extraction.get("facts")
                order = (0, 1) if int(entry["input_sha256"][-1], 16) % 2 == 0 else (1, 0)
                for writing in order:
                    payload_raw = None
                    if parent:
                        payload = copy.deepcopy(self.template)
                        payload["model"] = model["request_model"]
                        payload["messages"] = clients[writing]._weave_messages(parent["text"], {}, image_part=part)
                        payload_raw = canonical(payload) + b"\n"
                    existing = (self.directory(model, entry, writing) / "result.json").exists()
                    result = self.stage(model, entry, writing, payload_raw, parent)
                    count(result, existing)
                    if result["status"] == "quarantined_wrong_model":
                        return dict(counts, stopped="wrong_model")
            return dict(counts, stopped="supervisor" if self.stop.is_set() else None)
        except Exception as exc:
            return dict(counts, stopped=type(exc).__name__)
        finally:
            for client in clients.values():
                client.close()

    def heartbeat(self, first):
        hb = self.cfg["heartbeat"]
        end = min(self.deadline, hb["deadline_unix"])
        try:
            for index in range(hb["max_count"]):
                if self.stop.is_set():
                    return
                need(self.clock() + hb["timeout_s"] + self.cleanup < end,
                     "heartbeat deadline cannot admit full command")
                process = self.children.run(hb["argv"], timeout=hb["timeout_s"],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL)
                write_new(self.heartbeat_evidence / f"heartbeat-{index:05d}.json", {"process": process})
                need(process["returncode"] == 0 and not process["interrupted"], "heartbeat failed")
                first.set()
                wait_s = min(hb["interval_s"], max(0, end - self.clock() - hb["timeout_s"] - self.cleanup))
                if self.stop.wait(wait_s):
                    return
            # A depleted heartbeat budget cannot silently leave collection running.
            self.stop.set()
            self.heartbeat_error = "count_exhausted"
        except Exception:
            self.heartbeat_error = "command_or_deadline_failure"
            self.stop.set()
        finally:
            first.set()

    def run(self):
        mkdir(self.evidence)
        lock_fd = os.open(self.evidence / ".collector.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        heartbeat_thread = None
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            manifest = dict(schema=SCHEMA, config=self.cfg, deadline_unix=self.deadline,
                            bakeoff_sha256=BAKEOFF_SHA, producer_sha256=PRODUCER_SHA,
                            loader_sha256=LOADER_SHA, depiction_sha256=DEPICTION_SHA,
                            collector_sha256=sha(read(Path(__file__))))
            raw = canonical(manifest) + b"\n"
            path = self.evidence / "run.json"
            if path.exists():
                need(read(path) == raw, "run binding/deadline changed; no reset authority")
            else:
                write_new(path, raw)
            # Each invocation gets its own immutable summary/heartbeat namespace.
            index = 0
            while (self.evidence / f"invocation-{index:05d}").exists():
                index += 1
            invocation = self.evidence / f"invocation-{index:05d}"
            mkdir(invocation)
            if self.cfg.get("heartbeat"):
                first = threading.Event()
                # Heartbeat receipts belong to this invocation, not the stage tree.
                def heartbeat_target():
                    # Pass the destination explicitly without changing stage paths.
                    self.heartbeat_evidence = invocation
                    self.heartbeat(first)
                heartbeat_thread = threading.Thread(target=heartbeat_target, daemon=False)
                heartbeat_thread.start()
                first.wait(self.cfg["heartbeat"]["timeout_s"] + self.cleanup)
                if not first.is_set():
                    self.stop.set()
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel) as pool:
                futures = {model["id"]: pool.submit(self.stream, model) for model in self.cfg["models"]}
                streams = {mid: future.result() for mid, future in futures.items()}
            self.stop.set()
            if heartbeat_thread:
                heartbeat_thread.join(self.cfg["heartbeat"]["timeout_s"] + self.cleanup)
                need(not heartbeat_thread.is_alive(), "heartbeat did not stop")
            report = {"schema": SCHEMA, "models": streams, "human_review": "unreviewed",
                      "supervision_failure": self.heartbeat_error}
            write_new(invocation / "summary.json", report)
            return report
        finally:
            self.children.close()
            if heartbeat_thread:
                heartbeat_thread.join(self.cfg["heartbeat"]["timeout_s"] + self.cleanup)
            os.close(lock_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--deadline-unix", required=True, type=float)
    args = parser.parse_args(argv)
    collector = None
    previous = {}
    try:
        collector = Collector(strict_json(read(args.config)), args.evidence, args.deadline_unix)
        def stop(_signum, _frame):
            collector.stop.set()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        report = collector.run()
        print(canonical(report).decode())
        return int(bool(report["supervision_failure"]) or
                   any(v["stopped"] or v["failed_or_skipped"] for v in report["models"].values()))
    except Exception as exc:
        # Never print config values, credentials, generated content or server diagnostics.
        print("collector stopped: " + type(exc).__name__, file=sys.stderr)
        return 2
    finally:
        if collector:
            collector.children.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
