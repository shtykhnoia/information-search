import hashlib
import json
import sys
from pathlib import Path

import requests
from pymongo import MongoClient

with MongoClient('mongodb://127.0.0.1:27017', serverSelectionTimeoutMS=5000) as client:
    assert client.admin.command('buildInfo')['buildEnvironment']['target_os'] == 'linux'
    db = client.film_lab2
    documents = list(db.documents.find().sort('_id', 1))
    for document in documents:
        assert hashlib.sha256(document['html'].encode()).hexdigest() == document['sha256']
        assert not {'words', 'raw_bytes', 'text_bytes'} & document.keys()
    state = {'documents': documents, 'progress': list(db.progress.find().sort('_id', 1))}
    snapshot = Path(__file__).with_name('container-snapshot.json')
    if sys.argv[1] == 'save':
        assert len(documents) == 12
        snapshot.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    elif sys.argv[1] == 'compare':
        assert state == json.loads(snapshot.read_text(encoding='utf-8'))
    print('Container MongoDB:', len(documents), 'documents;', len(state['progress']), 'checkpoints')

with requests.Session() as session:
    session.trust_env = False
    response = session.get('http://127.0.0.1:8081/', timeout=10)
    response.raise_for_status()
    assert 'mongo' in response.text.lower()
    print('mongo-express HTTP', response.status_code)
