"""Deterministic packaging around real imageGeneration results returned by Codex."""
from argparse import Namespace
from pathlib import Path
import shutil
import threading
import zipfile
from cards import prepare, build, read_photo

PROMPTS = {
    2: 'Make a similar photo. Change the angle and details of the photo a bit, but keep it recognizable. Improve the quality.',
    3: 'Take a similar photo. Change the angle and some details of the photo slightly, but keep it recognizable. Improve the quality. Replace the main subject with the one shown in the attached photo.'
}


def run_design(config, client, progress, cancel=None):
    cancel = cancel or threading.Event()
    root = Path(config['root'])
    source_zip = root / 'originals.zip'
    sources = [item for item in config['files'] if item['role'] == 'source']
    subject = next((item['path'] for item in config['files'] if item['role'] == 'subject'), None)
    with zipfile.ZipFile(source_zip, 'x', zipfile.ZIP_DEFLATED) as archive:
        for index, item in enumerate(sources, 1):
            archive.write(item['path'], f'{config["marketplace"]}_{config["article"]}_{index:04}.png')
    job = root / 'work'
    prepare(Namespace(source=source_zip, job_dir=job, mode=str(config['mode']),marketplace=config['marketplace'],article=config['article'],subject=subject))
    import json
    data = json.loads((job / 'job.json').read_text(encoding='utf-8'))
    for index, image in enumerate(data['images'],1):
        if cancel.is_set(): raise RuntimeError('Остановлено; исходники сохранены.')
        progress(dict(status='generating',current=index,total=len(data['images']),message=f'Codex создаёт фото {index} из {len(data["images"])}'))
        references = [job / image['source']]
        if subject: references.append(Path(subject))
        actual = Path(client.generate(references, PROMPTS[config['mode']], root, cancel)).resolve(strict=True)
        read_photo(actual)
        shutil.copyfile(actual, job / image['generated'])
    if cancel.is_set(): raise RuntimeError('Остановлено; исходники сохранены.')
    progress(dict(status='packing',message='Собираем готовые карточки в ZIP'))
    result = build(Namespace(job_dir=job, output=root / f'{config["marketplace"]}_{config["article"]}_ready.zip'))
    with zipfile.ZipFile(result['archive']) as archive:
        report = json.loads(archive.read('manifest.json'))
    padded = sum(bool(item.get('padded')) for item in report['photos'])
    message = f'Готово: {result["image_count"]} карточек, архив создан на компьютере.'
    if padded: message += f' Для {padded} фото добавлены белые поля для сохранения пропорций.'
    return dict(**result,status='done',message=message,padded_count=padded)
