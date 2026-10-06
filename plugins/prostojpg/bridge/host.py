"""Restricted native-messaging host: accepts photo bytes, talks to Codex, saves ZIP.

No localhost listener, arbitrary process commands, cookie/token reading or remote URLs.
"""
import base64
import json
import os
from pathlib import Path
import re
import struct
import sys
import threading
import uuid

sys.path.insert(0, str(Path(__file__).parent / 'vendor'))
from PIL import Image, ImageOps
from codex_rpc import CodexClient
from runner import run_design

MAX_MESSAGE = 1024 * 1024
MAX_CHUNK = 256 * 1024
MAX_PHOTO = 100 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk: raise EOFError()
        data.extend(chunk)
    return bytes(data)


def read_message(stream):
    header = stream.read(4)
    if not header: return None
    if len(header) != 4: raise EOFError()
    size = struct.unpack('<I',header)[0]
    if not 0 < size <= MAX_MESSAGE: raise ValueError('Native message exceeds the limit.')
    message = json.loads(read_exact(stream,size))
    if not isinstance(message,dict): raise ValueError('Expected a JSON object.')
    return message


def write_message(stream, message):
    data = json.dumps(message,ensure_ascii=False).encode('utf-8')
    if len(data) > MAX_MESSAGE: raise ValueError('Native response exceeds the limit.')
    stream.write(struct.pack('<I',len(data)) + data)
    stream.flush()


class DesignJob:
    def __init__(self, jobs):
        self.jobs = Path(jobs).resolve()
        self.root, self.files, self.config = None, [], None
        self.committed = False

    def begin(self, message):
        if self.root: raise ValueError('This connection already has a job.')
        mode, marketplace, article = message.get('mode'), message.get('marketplace'), str(message.get('article',''))
        files = message.get('files')
        if type(mode) is not int or mode not in (2,3) or marketplace not in ('WB','OZON') or not re.fullmatch(r'\d{1,30}',article):
            raise ValueError('Выберите режим, WB/OZON и числовой артикул.')
        if not isinstance(files,list) or not 1 <= len(files) <= 101: raise ValueError('Expected 1..100 source photos and optional product photo.')
        roles, total = [], 0
        for item in files:
            if not isinstance(item,dict) or item.get('role') not in ('source','subject') or type(item.get('size')) is not int or not 0 < item['size'] <= MAX_PHOTO:
                raise ValueError('Invalid photo metadata.')
            roles.append(item['role']); total += item['size']
        if not 1 <= roles.count('source') <= 100 or roles.count('subject') != (1 if mode == 3 else 0) or total > MAX_TOTAL:
            raise ValueError('Mode 3 requires exactly one product photo; the source set must be complete.')
        self.root = self.jobs / str(uuid.uuid4())
        self.root.mkdir(parents=True)
        self.files = [dict(role=item['role'],size=item['size'],path=str(self.root / f'{index:04}.image'),received=0) for index,item in enumerate(files)]
        for item in self.files: Path(item['path']).touch(exist_ok=False)
        self.config = dict(mode=mode,marketplace=marketplace,article=article,root=str(self.root),files=self.files)
        return dict(job_id=self.root.name)

    def chunk(self, message):
        if not self.root or self.committed: raise ValueError('No writable upload session.')
        index, offset = message.get('file_index'), message.get('offset')
        if type(index) is not int or not 0 <= index < len(self.files) or type(offset) is not int:
            raise ValueError('Invalid file index or offset.')
        item = self.files[index]
        encoded = message.get('data')
        if not isinstance(encoded,str) or len(encoded) > (MAX_CHUNK + 2) // 3 * 4: raise ValueError('Invalid chunk size.')
        data = base64.b64decode(encoded,validate=True)
        if not 0 < len(data) <= MAX_CHUNK or offset != item['received'] or offset + len(data) > item['size']:
            raise ValueError('Chunk offset or declared file size does not match.')
        with Path(item['path']).open('ab') as target: target.write(data)
        item['received'] += len(data)
        return dict(received=item['received'])

    def commit(self):
        if not self.root or self.committed: raise ValueError('No uncommitted upload.')
        for item in self.files:
            if item['received'] != item['size']: raise ValueError('Not all source photos were transferred.')
            try:
                with Image.open(item['path']) as image:
                    if image.width * image.height > 40_000_000: raise ValueError('Photo exceeds 40 megapixels.')
                    image.verify()
            except (OSError, Image.DecompressionBombError) as error: raise ValueError('Invalid source photo.') from error
        # Native Codex localImage inputs need a real image suffix. Normalize losslessly
        # to PNG while preserving the transferred original bytes beside each file.
        for index, item in enumerate(self.files):
            raw_path = item['path']
            normalized = self.root / f'{index:04}.png'
            with Image.open(raw_path) as image:
                ImageOps.exif_transpose(image).convert('RGB').save(normalized, 'PNG')
            item['original_path'], item['path'] = raw_path, str(normalized)
        self.committed = True
        (self.root / 'request.json').write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')
        return self.config


def main():
    root = Path(__file__).parent
    config = json.loads((root / 'config.json').read_text(encoding='utf-8-sig'))
    origin = 'chrome-extension://' + config['extensionId'] + '/'
    if len(sys.argv) < 2 or sys.argv[1] != origin: raise ValueError('Caller extension is not allowed.')
    if os.name == 'nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(),os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(),os.O_BINARY)
    output_lock, cancel = threading.Lock(), threading.Event()
    job, client, worker = DesignJob(config['jobsRoot']), None, None
    result = {}
    def emit(message):
        with output_lock: write_message(sys.stdout.buffer,message)
    def generate(config):
        try:
            result.update(run_design(config,client,lambda event: emit(dict(event='progress',**event)),cancel))
            emit(dict(event='progress',**result))
        except Exception as error: emit(dict(event='progress',status='error',message=str(error),job_id=job.root.name))
        finally:
            client.close()
    try:
        while (message := read_message(sys.stdin.buffer)) is not None:
            try:
                action = message.get('action')
                if action == 'ping':
                    if client is None: client = CodexClient(config['codexPath'])
                    response = client.ready()
                elif action == 'login' and client is not None:
                    response = client.login()
                elif action == 'begin': response = job.begin(message)
                elif action == 'chunk': response = job.chunk(message)
                elif action == 'commit':
                    if client is None: raise ValueError('Check the Codex connection before uploading.')
                    data = job.commit()
                    worker = threading.Thread(target=generate,args=(data,),daemon=True)
                    worker.start(); response = dict(started=True,job_id=job.root.name)
                elif action == 'cancel': cancel.set(); response = dict(stopping=True)
                elif action == 'open_result' and result.get('archive') and Path(result['archive']).is_file():
                    if os.name != 'nt': raise ValueError('Откройте папку по указанному пути.')
                    os.startfile(str(Path(result['archive']).parent)); response = dict(opened=True)
                else: raise ValueError('Unsupported bridge action.')
                emit(dict(id=message.get('id'),ok=True,**response))
            except Exception as error: emit(dict(id=message.get('id'),ok=False,error=str(error)))
    finally:
        cancel.set()
        if client: client.close()


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(str(error),file=sys.stderr)
        raise SystemExit(1)
