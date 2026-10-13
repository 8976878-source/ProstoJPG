"""Prepare uploaded photos or an extension ZIP without requesting an article."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile
from cards import IMAGE_EXTENSIONS, inspect_entries, read_photo, MAX_ARCHIVE_BYTES


def prepare_upload(args):
    if args.mode not in {'1', '2', '3'}:
        raise ValueError('Выберите режим ProstoJpg-1, ProstoJpg-2 или ProstoJpg-3.')
    destination = Path(args.job_dir).resolve()
    if destination.exists():
        raise ValueError('Папка задания уже существует. Выберите новую папку.')
    subject = Path(args.subject).resolve(strict=True) if args.subject else None
    if args.mode in {'2', '3'} and subject is None:
        raise ValueError(f'Для ProstoJpg-{args.mode} нужно фото вашего товара (--subject).')
    if args.mode == '1' and subject is not None:
        raise ValueError('Фото замены товара используется только в ProstoJpg-2 и ProstoJpg-3.')
    if subject:
        read_photo(subject)
    photos = [Path(p).resolve(strict=True) for p in (args.photos or [])]
    if subject in photos:
        raise ValueError('Фото вашего товара не должно входить в исходные карточки.')
    if len(photos) > 1000 or sum(p.stat().st_size for p in photos) > MAX_ARCHIVE_BYTES:
        raise ValueError('Слишком много исходных фото: максимум 1000 файлов и 2 ГБ.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prostojpg-', dir=destination.parent) as temporary:
        staging = Path(temporary) / 'job'
        (staging / 'originals').mkdir(parents=True)
        (staging / 'generated').mkdir()
        job = dict(version=2, mode=args.mode, product='ProstoJPG', images=[], videos=[], subject=None)

        def add_photo(stream, name):
            extension = Path(name).suffix.lower()
            if extension not in IMAGE_EXTENSIONS:
                raise ValueError('Неподдерживаемое фото: ' + name)
            index = len(job['images']) + 1
            relative = f'originals/photo-{index:04}{extension}'
            target = staging / relative
            with target.open('xb') as outgoing:
                shutil.copyfileobj(stream, outgoing)
            image = read_photo(target)
            job['images'].append(dict(source=relative, original_name=name, width=image.width,
                height=image.height, generated=f'generated/{index:04}.png',
                output=f'photos/ProstoJPG_{index:02}-photo.jpg'))

        if args.archive:
            with zipfile.ZipFile(Path(args.archive).resolve(strict=True)) as archive:
                for entry in inspect_entries(archive):
                    if Path(entry.filename).suffix.lower() in IMAGE_EXTENSIONS:
                        with archive.open(entry) as incoming:
                            add_photo(incoming, entry.filename)
        else:
            for photo in photos:
                with photo.open('rb') as incoming:
                    add_photo(incoming, photo.name)
        if not job['images']:
            raise ValueError('Загрузите хотя бы одно исходное фото.')
        if subject:
            (staging / 'reference').mkdir()
            relative = 'reference/subject' + (subject.suffix.lower() or '.png')
            shutil.copyfile(subject, staging / relative)
            job['subject'] = relative
        (staging / 'job.json').write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        staging.rename(destination)
    return dict(job_dir=str(destination), image_count=len(job['images']), mode=args.mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-dir', required=True)
    parser.add_argument('--mode', choices=['1', '2', '3'], required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--photos', nargs='+')
    sources.add_argument('--archive')
    parser.add_argument('--subject')
    try:
        print(json.dumps(prepare_upload(parser.parse_args()), ensure_ascii=False))
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        print('Ошибка: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    sys.exit(main())
