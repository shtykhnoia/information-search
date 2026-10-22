from pathlib import Path
import yaml

root = Path(__file__).resolve().parents[1]
path = root / 'configs/corpus.yaml'
config = yaml.safe_load(path.read_text(encoding='utf-8'))
config.pop('output', None)
config.pop('queries', None)
path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
path = root / 'tests/test_cli.py'
code = path.read_text(encoding='utf-8')
code = code[:code.index('\n\nclass Lab1Tests')]
start = code.index('            if query.get("list") == ["search"]:')
end = code.index('                if "cmcontinue" in query:', start)
code = code[:start] + '            if query.get("list") == ["categorymembers"]:\n' + code[end:]
start = code.index('            elif query.get("prop") == ["categoryinfo"]:')
end = code.index('            else:', start)
code = code[:start] + code[end:]
code = code.replace('            "output": "sample",\n', '')
start = code.index('            "queries": [')
end = code.index('        }', start)
code = code[:start] + code[end:]
(root / 'tests/support.py').write_text(code, encoding='utf-8')
path.unlink()
path = root / 'tests/test_crawler.py'
code = path.read_text(encoding='utf-8').replace('from test_cli import', 'from support import')
code = code.replace('def config(self, titles=None, categories=None):', 'def config(self, titles=None, categories=None, **logic):')
code = code.replace('super().config(titles=titles, categories=categories)', 'super().config(titles=titles, categories=categories, **logic)')
path.write_text(code, encoding='utf-8')
