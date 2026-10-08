import os
import subprocess
import sys
from pathlib import Path

from pymongo import MongoClient
from pymongo.errors import PyMongoError


def main():
    root = Path(__file__).resolve().parents[1]
    uri = os.environ.get("TEST_MONGO_URI", "mongodb://127.0.0.1:27017")
    try:
        with MongoClient(uri, serverSelectionTimeoutMS=3000) as client:
            client.admin.command("ping")
    except PyMongoError:
        print("MongoDB недоступна. Запустите mongod или задайте TEST_MONGO_URI.")
        return 1
    return subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root,
        env=dict(os.environ, PYTHONUTF8="1"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
