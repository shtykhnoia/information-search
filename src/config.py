import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml


def configure_utf8():
    import sys

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def load_config(path):
    path = Path(path).resolve()
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"Некорректный YAML: {error}") from error
    if not isinstance(config, dict):
        raise ValueError("Конфигурация должна быть YAML-объектом")
    logic = config.setdefault("logic", {})
    if not isinstance(logic, dict):
        raise ValueError("logic должен быть объектом")
    defaults = {
        "delay_seconds": 1,
        "timeout_seconds": 30,
        "retries": 3,
        "max_document_bytes": 10000000,
        "recrawl_seconds": 86400,
    }
    integer_keys = {"retries", "max_document_bytes"}
    for key, default in defaults.items():
        value = logic.setdefault(key, default)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"logic.{key}: требуется конечное неотрицательное число")
        if key in integer_keys and not isinstance(value, int):
            raise ValueError(f"logic.{key}: требуется целое число")
        if (
            key in {"timeout_seconds", "max_document_bytes", "recrawl_seconds"}
            and value == 0
        ):
            raise ValueError(f"logic.{key}: требуется положительное число")
    logic.setdefault("user_agent", "FilmSeriesIR/1.0 (educational corpus research)")
    if not isinstance(logic["user_agent"], str) or not logic["user_agent"].strip():
        raise ValueError("logic.user_agent должен быть непустой строкой")
    for key in ("continuous", "crawl_categories"):
        logic.setdefault(key, False)
        if not isinstance(logic[key], bool):
            raise ValueError(f"logic.{key} должен быть true или false")
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources должен быть непустым списком")
    names = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Источник должен быть объектом")
        name = source.get("name")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]*", name)
            or name in names
        ):
            raise ValueError(
                "Источник должен иметь уникальное имя из латинских букв, цифр, _ и -"
            )
        names.add(name)
        base = source.get("base_url")
        if not isinstance(base, str):
            raise ValueError("base_url должен быть строкой")
        parts = urlsplit(base)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                "base_url должен быть HTTP(S)-origin без пути и параметров"
            )
        port = parts.port
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        suffix = (
            f":{port}"
            if port and (parts.scheme, port) not in (("http", 80), ("https", 443))
            else ""
        )
        source["base_url"] = f"{parts.scheme}://{host}{suffix}"
        for key in ("titles", "categories"):
            values = source.setdefault(key, [])
            if not isinstance(values, list) or any(
                not isinstance(v, str) or not v.strip() for v in values
            ):
                raise ValueError(f"{key} должен быть списком непустых строк")
        if not source["titles"] and not source["categories"]:
            raise ValueError("У источника должны быть titles или categories")
    return config
