"""Prepare local gallery files and package completed photos; never calls an AI API."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import zipfile

try:
    from PIL import Image, ImageOps
except ImportError:
    raise SystemExit('Нужен Pillow. Используйте Python с Pillow или установите зависимость из requirements.txt.')

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.tiff', '.tif', '.bmp', '.avif'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.m4v'}
MAX_PIXELS = 40_000_000
MAX_ARCHIVE_BYTES = 2_000_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def read_photo(path):
    with Image.open(path) as source:
        if source.width * source.height > MAX_PIXELS:
            raise ValueError('Фото превышает допустимый размер 40 мегапикселей.')
        return ImageOps.exif_transpose(source).copy()


def safe_job_path(root, value):
    relative = PurePosixPath(value)
    if relative.is_absolute() or '..' in relative.parts or '\\' in value or ':' in value:
        raise ValueError('Недопустимый путь в задании.')
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Файл выходит за пределы папки задания.')
    return path


def inspect_entries(archive):
    entries = []
    total = 0
    members = archive.infolist()
    if len(members) > 1000:
        raise ValueError('В архиве больше 1000 файлов.')
    for item in members:
        name = item.filename.replace('\\', '/')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or ':' in name or ((item.external_attr >> 16) & 0o170000) == 0o120000:
            raise ValueError(f'Недопустимое имя файла в архиве: {name}')
        total += item.file_size
        if total > MAX_ARCHIVE_BYTES:
            raise ValueError('Распакованный архив превышает 2 ГБ.')
        if item.is_dir() or any(part.startswith('.') or part == '__MACOSX' for part in path.parts):
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            entries.append(item)
    # Extension archives already have a meaningful gallery order. Keep it.
    return entries


def prepare(args):
    source = Path(args.source).resolve()
    destination = Path(args.job_dir).resolve()
    if destination.exists():
        raise ValueError('Папка задания уже существует. Выберите новую папку.')
    if not re.fullmatch(r'[0-9]{1,30}', args.article):
        raise ValueError('Укажите числовой артикул маркетплейса, до 30 цифр.')
    subject = None
    if args.mode == '3':
        if not args.subject:
            raise ValueError('Для режима 3 нужно приложить фото своего товара (--subject).')
        subject = Path(args.subject).resolve()
        read_photo(subject)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        entries = inspect_entries(archive)
        if not any(Path(item.filename).suffix.lower() in IMAGE_EXTENSIONS for item in entries):
            raise ValueError('В архиве не найдены поддерживаемые фото.')
        with tempfile.TemporaryDirectory(prefix='.prostojpg-', dir=destination.parent) as temporary:
            staging = Path(temporary).resolve() / 'job'
            staging.mkdir()
            (staging / 'originals').mkdir()
            (staging / 'generated').mkdir()
            job = {'version': 1, 'mode': args.mode, 'marketplace': args.marketplace,
                   'article': args.article, 'images': [], 'videos': [], 'subject': None}
            for gallery_index, item in enumerate(entries, 1):
                extension = Path(item.filename).suffix.lower()
                is_image = extension in IMAGE_EXTENSIONS
                collection = job['images' if is_image else 'videos']
                index = len(collection) + 1
                relative = f'originals/{"photo" if is_image else "video"}-{index:04}{extension}'
                target = staging / relative
                with archive.open(item) as incoming, target.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                record = {'source': relative, 'original_name': item.filename}
                if is_image:
                    image = read_photo(target)
                    record.update({'width': image.width, 'height': image.height,
                                   'generated': f'generated/{index:04}.png',
                                   'output': f'photos/{args.marketplace}_{args.article}_{gallery_index:02}-photo.jpg'})
                else:
                    record['output'] = f'videos/{args.marketplace}_{args.article}_{gallery_index:02}-video{extension}'
                collection.append(record)
            if subject:
                (staging / 'reference').mkdir()
                relative = f'reference/subject{subject.suffix.lower() or ".png"}'
                shutil.copyfile(subject, staging / relative)
                job['subject'] = relative
            (staging / 'job.json').write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
            if not staging.is_relative_to(Path(temporary).resolve()):
                raise ValueError('Некорректная временная папка.')
            staging.rename(destination)
    return {'job_dir': str(destination), 'mode': args.mode, 'image_count': len(job['images']),
            'video_count': len(job['videos']), 'job_manifest': str(destination / 'job.json')}


def target_size(width, height):
    if width <= 0 or height <= 0:
        raise ValueError('Некорректные размеры исходного фото.')
    divisor = math.gcd(width, height)
    unit_width, unit_height = width // divisor, height // divisor
    multiplier = max(divisor, math.ceil(1200 / min(unit_width, unit_height)))
    size = unit_width * multiplier, unit_height * multiplier
    if size[0] * size[1] > MAX_PIXELS:
        raise ValueError('Фото с такими пропорциями превышает 40 мегапикселей при увеличении.')
    return size


def export_photo(image, size, target):
    rgba = image.convert('RGBA')
    rgb = Image.new('RGB', rgba.size, 'white')
    rgb.paste(rgba, mask=rgba.getchannel('A'))
    fitted = ImageOps.contain(rgb, size, Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', size, 'white')
    canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    canvas.save(target, 'JPEG', quality=95, subsampling=0)
    return fitted.size != size, fitted.width > image.width or fitted.height > image.height


def build(args):
    root = Path(args.job_dir).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError('Итоговый файл уже существует. Выберите новое имя; перезапись запрещена.')
    job = json.loads((root / 'job.json').read_text(encoding='utf-8'))
    if job.get('version') != 1 or job.get('mode') not in {'1', '2', '3'} or not job.get('images'):
        raise ValueError('Некорректное или пустое задание.')
    if job['mode'] == '3' and not job.get('subject'):
        raise ValueError('В задании режима 3 отсутствует фото товара.')
    inputs = []
    for record in job['images']:
        path = safe_job_path(root, record['source'] if job['mode'] == '1' else record['generated'])
        if not path.is_file():
            raise ValueError(f'Не обработано фото: {record.get("original_name", "")} — отсутствует {path.name}')
        inputs.append((record, path))
    for record in job.get('videos', []):
        if not safe_job_path(root, record['source']).is_file():
            raise ValueError('Исходный видеофайл отсутствует. Архив не собран.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prostojpg-', dir=output.parent) as temporary:
        staging = Path(temporary).resolve()
        report = {'product': f'{job["marketplace"]}_{job["article"]}', 'mode': job['mode'],
                  'created_at': datetime.now(timezone.utc).isoformat(), 'min_short_side': 1200,
                  'image_count': len(inputs), 'video_count': len(job.get('videos', [])), 'photos': []}
        archive_path = staging / 'result.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for index, (record, path) in enumerate(inputs):
                size = target_size(int(record['width']), int(record['height']))
                image = read_photo(path)
                target = staging / f'{index:04}.jpg'
                padded, upscaled = export_photo(image, size, target)
                # Confirm the actual exported file, rather than trusting generation metadata.
                with Image.open(target) as verified:
                    if verified.size != size or min(verified.size) < 1200:
                        raise ValueError('Экспортированное фото не прошло проверку размеров.')
                name = str(PurePosixPath(record['output']))
                if not name.startswith('photos/') or '..' in PurePosixPath(name).parts or '\\' in name or ':' in name:
                    raise ValueError('Недопустимое имя результата.')
                archive.write(target, name)
                report['photos'].append({'file': name, 'width': size[0], 'height': size[1],
                                         'original_width': record['width'], 'original_height': record['height'],
                                         'padded': padded, 'upscaled': upscaled})
            for record in job.get('videos', []):
                name = str(PurePosixPath(record['output']))
                if not name.startswith('videos/') or '..' in PurePosixPath(name).parts or '\\' in name or ':' in name:
                    raise ValueError('Недопустимое имя видео.')
                archive.write(safe_job_path(root, record['source']), name)
            archive.writestr('manifest.json', json.dumps(report, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(archive_path) as verified:
            if verified.testzip() is not None:
                raise ValueError('Архив не прошёл проверку целостности.')
        with output.open('xb') as final, archive_path.open('rb') as source:
            shutil.copyfileobj(source, final)
    return {'archive': str(output), 'image_count': len(inputs), 'video_count': report['video_count']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('--source', required=True)
    preparation.add_argument('--job-dir', required=True)
    preparation.add_argument('--mode', choices=['1', '2', '3'], required=True)
    preparation.add_argument('--marketplace', choices=['WB', 'OZON'], required=True)
    preparation.add_argument('--article', required=True)
    preparation.add_argument('--subject')
    assembly = commands.add_parser('build')
    assembly.add_argument('--job-dir', required=True)
    assembly.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args) if args.command == 'prepare' else build(args), ensure_ascii=False))
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        print(f'Ошибка: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    sys.exit(main())
