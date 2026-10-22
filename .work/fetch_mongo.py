import io
import zipfile
from pathlib import Path

import requests


class RemoteZip(io.RawIOBase):
    def __init__(self, url):
        self.session = requests.Session()
        self.url = url
        self.size = int(self.session.head(url, timeout=20).headers['Content-Length'])
        self.position = 0

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        return self.position

    def tell(self):
        return self.position

    def read(self, size=-1):
        if size < 0:
            size = self.size - self.position
        if not size:
            return b''
        end = min(self.size, self.position + size) - 1
        response = self.session.get(self.url, headers={'Range': f'bytes={self.position}-{end}'}, timeout=60)
        response.raise_for_status()
        if response.status_code != 206:
            raise ValueError('Range is required')
        data = response.content
        if len(data) != end - self.position + 1:
            raise ValueError(f'Wrong range size: {len(data)}')
        self.position += len(data)
        return data


directory = Path(__file__).resolve().parent / 'runtime' / 'mongodb'
directory.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(RemoteZip('https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-8.0.28.zip')) as archive:
    entries = [entry for entry in archive.infolist() if entry.filename.endswith('/bin/mongod.exe') or ('/bin/' in entry.filename and entry.filename.endswith('.dll'))]
    for entry in entries:
        print(entry.filename, entry.compress_size, flush=True)
        (directory / Path(entry.filename).name).write_bytes(archive.read(entry))
        print('Saved', entry.filename, flush=True)
