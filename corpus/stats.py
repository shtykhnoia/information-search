import argparse

import yaml
from pymongo import MongoClient

if __package__:
    from .text import extract_document
else:
    from text import extract_document

SAMPLE_SIZE = 20

def kilobytes(size):
    return f"{size / 1024:.1f} КБ"


def main():
    parser = argparse.ArgumentParser(description="Статистика корпуса по выборке документов")
    parser.add_argument("config", help="путь до yaml-конфига робота")
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as file:
        config = yaml.safe_load(file)

    with MongoClient(config["db"]["uri"]) as mongo:
        db = mongo[config["db"]["name"]]
        for source in config["sources"]:
            name = source["name"]
            sample = list(db.documents.aggregate([{"$match": {"source": name}}, {"$sample": {"size": SAMPLE_SIZE}}]))
            html_sizes = [len(document["html"].encode()) for document in sample]
            texts = [extract_document(document["html"])[1] for document in sample]
            text_sizes = [len(text.encode()) for text in texts]
            words = [len(text.split()) for text in texts]

            print(f"== {name}")
            print("документов в корпусе:", db.frontier.count_documents({"source": name}))
            print("документов в выборке:", len(sample))
            print("сырые данные выборки:", kilobytes(sum(html_sizes)))
            print("текст выборки:", kilobytes(sum(text_sizes)))
            print("средний размер документа:", kilobytes(sum(html_sizes) / len(sample)))
            print("средний объём текста:", kilobytes(sum(text_sizes) / len(sample)), f"({sum(words) // len(sample)} слов)")
            print(f"доля текста: {sum(text_sizes) / sum(html_sizes):.1%}")


if __name__ == "__main__":
    main()
