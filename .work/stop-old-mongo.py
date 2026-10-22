from pymongo import MongoClient
from pymongo.errors import AutoReconnect

with MongoClient('mongodb://127.0.0.1:27017', serverSelectionTimeoutMS=3000) as client:
    opts = client.admin.command('getCmdLineOpts')
    path = opts['parsed']['storage']['dbPath'].replace('\\', '/').lower()
    if path != 'd:/ir/data/mongodb':
        raise RuntimeError(f'Unexpected MongoDB path: {path}')
    print('Stopping Windows MongoDB; preserving', path)
    try:
        client.admin.command('shutdown')
    except AutoReconnect:
        pass
