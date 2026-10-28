import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from pymongo import MongoClient
from pymongo.errors import PyMongoError

if __package__:
    from .text import extract_document
else:
    from text import extract_document


def export_documents(database, sources, output, limit):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Каталог назначения должен быть новым или пустым")
    output.mkdir(parents=True, exist_ok=True)
    saved = 0
    failed = 0
    with (output / "manifest.jsonl").open("x", encoding="utf-8", newline="\n") as manifest:
        for source in sources:
            with database.documents.find({"source": source}).sort("_id", 1).limit(limit) as cursor:
                for document in cursor:
                    try:
                        identity = str(document["_id"])
                        if not re.fullmatch(r"[0-9a-f]{24}", identity):
                            raise ValueError("Ожидался MongoDB ObjectId")
                        title, text = extract_document(document["html"])
                        metadata = {
                            "id": identity,
                            "file": identity + ".txt",
                            "url": document["url"],
                            "source": document["source"],
                            "title": title,
                            "crawled_at": document["crawled_at"],
                        }
                        record = json.dumps(metadata, ensure_ascii=False)
                    except (ValueError, TypeError, KeyError) as error:
                        failed += 1
                        print(f"{document.get('url', document['_id'])}: {error}", file=sys.stderr)
                        continue
                    with (output / metadata["file"]).open("x", encoding="utf-8", newline="\n") as file:
                        file.write((title + "\n\n" if title else "") + text + "\n")
                    manifest.write(record + "\n")
                    saved += 1
    print(f"Сохранено: {saved}; ошибок: {failed}; каталог: {output.resolve()}")
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description="Выгрузка текста статей из MongoDB")
    parser.add_argument("config", type=Path, help="YAML-конфигурация робота")
    parser.add_argument("output", type=Path, help="Новый или пустой каталог для текстов")
    parser.add_argument("--limit-per-source", type=int, help="Число выбранных документов на источник")
    args = parser.parse_args()
    if args.limit_per_source is not None and args.limit_per_source <= 0:
        parser.error("--limit-per-source должен быть положительным")
    try:
        with args.config.open(encoding="utf-8") as file:
            config = yaml.safe_load(file)
        sources = list(dict.fromkeys(source["name"] for source in config["sources"]))
        if not sources:
            raise ValueError("Не указаны источники")
        with MongoClient(config["db"]["uri"], serverSelectionTimeoutMS=5000) as client:
            client.admin.command("ping")
            return export_documents(client[config["db"]["name"]], sources, args.output, args.limit_per_source or 0)
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError, PyMongoError) as error:
        print(f"Ошибка экспорта: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Экспорт прерван; в каталоге остались частичные результаты", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
