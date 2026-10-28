import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import yaml
from pymongo import MongoClient


ROOT = Path(__file__).resolve().parents[2]
HTML = '<h1 id="firstHeading">Фильм</h1><div class="mw-parser-output"><p>Ёлки &amp; кино.</p></div>'


class ExportTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / 'data' / 'tests'
        directory.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / 'export'
        uri = os.environ.get('TEST_MONGO_URI', 'mongodb://127.0.0.1:27017')
        self.client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        self.addCleanup(self.client.close)
        self.client.admin.command('ping')
        self.db = self.client['test_export_' + uuid.uuid4().hex]
        self.addCleanup(self.client.drop_database, self.db.name)
        self.config = self.directory / 'config.yaml'
        self.config.write_text(yaml.safe_dump({
            'db': {'uri': uri, 'name': self.db.name},
            'sources': [{'name': 'wikipedia'}, {'name': 'wikiquote'}],
        }), encoding='utf-8')

    def add_document(self, source='wikipedia', html=HTML):
        return self.db.documents.insert_one({
            'url': 'https://example.org/' + uuid.uuid4().hex,
            'source': source, 'html': html, 'crawled_at': 123,
        }).inserted_id

    def run_export(self, *args):
        return subprocess.run([
            sys.executable, '-B', '-X', 'utf8', str(ROOT / 'corpus/export.py'),
            str(self.config), str(self.output), *args,
        ], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)

    def records(self):
        return [json.loads(line) for line in (self.output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_files_metadata_limit_and_database_unchanged(self):
        first = self.add_document()
        self.add_document()
        other = self.add_document('wikiquote')
        self.add_document('unconfigured')
        before = list(self.db.documents.find())
        result = self.run_export('--limit-per-source', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        records = self.records()
        self.assertEqual([r['id'] for r in records], [str(first), str(other)])
        for record in records:
            original = self.db.documents.find_one({'_id': first if record['source'] == 'wikipedia' else other})
            self.assertEqual(record['url'], original['url'])
            self.assertEqual(record['title'], 'Фильм')
            self.assertEqual(record['crawled_at'], 123)
            self.assertEqual((self.output / record['file']).read_bytes(), 'Фильм\n\nЁлки & кино.\n'.encode())
        self.assertEqual(list(self.db.documents.find()), before)

    def test_all_documents_and_empty_output_directory(self):
        self.output.mkdir()
        for _ in range(3):
            self.add_document()
        result = self.run_export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.records()), 3)

    def test_nonempty_directory_is_preserved(self):
        self.output.mkdir()
        marker = self.output / 'keep.txt'
        marker.write_text('keep', encoding='utf-8')
        result = self.run_export()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.output.iterdir()), [marker])
        self.assertEqual(marker.read_text(), 'keep')

    def test_bad_html_is_reported_and_next_document_saved(self):
        self.add_document(html='<p>no article</p>')
        good = self.add_document()
        result = self.run_export()
        self.assertEqual(result.returncode, 1)
        self.assertIn('https://example.org/', result.stderr)
        self.assertIn('ошибок: 1', result.stdout)
        self.assertEqual([r['id'] for r in self.records()], [str(good)])

    def test_invalid_limit(self):
        result = self.run_export('--limit-per-source', '0')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_output_is_file(self):
        self.output.write_text('keep', encoding='utf-8')
        result = self.run_export()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.output.read_text(), 'keep')

    def test_limit_counts_selected_documents_including_bad_html(self):
        self.add_document(html='<p>no article</p>')
        self.add_document()
        result = self.run_export('--limit-per-source', '1')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.records(), [])

    def test_unavailable_database(self):
        config = yaml.safe_load(self.config.read_text())
        config['db']['uri'] = 'mongodb://127.0.0.1:1'
        self.config.write_text(yaml.safe_dump(config), encoding='utf-8')
        result = self.run_export()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Ошибка экспорта', result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
