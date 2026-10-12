"""Render uploaded cards using installed Codex and ChatGPT; no Images API key."""
import argparse
from argparse import Namespace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
from cards import export, read_photo, safe_job_path
from codex_rpc import CodexClient

PROMPTS = {
    '2': 'Create a similar photo. Slightly change the camera angle and some visual details while keeping the product recognizable. Improve the image quality. If the source photo contains text blocks, slightly adjust their colors and shapes while preserving the wording and readability. If a person is present in the source photo, change their face and hairstyle so they look like a different person, while keeping the overall look and style recognizable.',
    '3': 'Create a similar photo. Slightly change the camera angle and some visual details while keeping the overall image recognizable. Improve the image quality. Replace the main subject with the product shown in the attached reference photo. If the source photo contains text blocks, slightly adjust their colors and shapes while preserving the wording and readability. If a person is present in the source photo, change their face and hairstyle so they look like a different person, while keeping the overall look and style recognizable.'
}


def find_codex(override=None):
    if override:
        return Path(override).expanduser().resolve(strict=True)
    command = shutil.which('codex')
    if command and (os.name != 'nt' or Path(command).suffix.lower() == '.exe'):
        return Path(command)
    local = os.environ.get('LOCALAPPDATA')
    if local:
        candidates = list((Path(local) / 'OpenAI/Codex/bin').glob('*/codex.exe'))
        if candidates:
            return max(candidates, key=lambda p: p.stat().st_mtime)
    if command:
        return Path(command)
    raise RuntimeError('Установите Codex и войдите в него через ChatGPT. Генератор не требует отдельного плагина или API-ключа.')


def digest(path):
    with path.open('rb') as incoming:
        return hashlib.file_digest(incoming, 'sha256').digest()


def render_job(job_dir, output, client, progress=None):
    root = Path(job_dir).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Папка результата уже существует. Выберите новую папку.')
    if output.suffix.lower() == '.zip':
        raise ValueError('Укажите папку для отдельных фото, а не ZIP.')
    job = json.loads((root / 'job.json').read_text(encoding='utf-8'))
    if job.get('version') != 1 or job.get('mode') not in PROMPTS or not job.get('images'):
        raise ValueError('Нужен подготовленный набор фото ProstoJpg-2 или ProstoJpg-3.')
    subject = safe_job_path(root, job['subject']) if job.get('subject') else None
    if job['mode'] == '3' and subject is None:
        raise ValueError('В задании отсутствует фото вашего товара.')
    if subject:
        read_photo(subject)
    inputs = []
    for record in job['images']:
        source = safe_job_path(root, record['source'])
        target = safe_job_path(root, record['generated'])
        if source == target or not target.is_relative_to(root / 'generated'):
            raise ValueError('Результат должен находиться в generated отдельно от исходников.')
        read_photo(source)
        inputs.append((source, target))
    cancel = threading.Event()
    for index, (source, target) in enumerate(inputs, 1):
        if progress:
            progress(dict(status='generating', current=index, total=len(inputs)))
        references = [source] + ([subject] if subject else [])
        actual = Path(client.generate(references, PROMPTS[job['mode']], root, cancel)).resolve(strict=True)
        read_photo(actual)
        if any(actual == p or digest(actual) == digest(p) for p in references):
            raise ValueError('Генератор вернул исходное фото; оно не выдается за новую карточку.')
        target.parent.mkdir(parents=True, exist_ok=True)
        if actual != target:
            shutil.copyfile(actual, target)
    return export(Namespace(job_dir=root, output_dir=output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-dir')
    parser.add_argument('--output-dir', '--output', dest='output_dir')
    parser.add_argument('--codex-path')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not args.check and (not args.job_dir or not args.output_dir):
        parser.error('--job-dir and --output-dir are required unless --check is used')
    client = None
    try:
        executable = find_codex(args.codex_path)
        client = CodexClient(executable)
        status = client.ready()
        if not status.get('ready'):
            raise RuntimeError('Вход в Codex через ChatGPT не выполнен. Выполните codex login и повторите запрос.')
        if args.check:
            result = dict(**status, codex=str(executable))
        else:
            result = render_job(args.job_dir, args.output_dir, client,
                lambda item: print(json.dumps(item, ensure_ascii=False), file=sys.stderr, flush=True))
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError, TimeoutError, KeyError) as error:
        print('Ошибка: ' + str(error), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    sys.exit(main())
