"""Download a browser-observed product gallery directly to a new local ZIP.

No extension download API, authentication tokens or browser download folder needed.
The agent supplies URLs observed in the matching product's gallery, not guessed URLs.
"""
import argparse
from http.client import IncompleteRead
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

from PIL import Image

DOMAINS = {'WB': ('wbbasket.ru', 'wbstatic.net', 'wbstatic.ru', 'geobasket.ru', 'wbcontent.net', 'wb.ru'),
           'OZON': ('ozone.ru', 'ozon.ru', 'ozonusercontent.com')}
MAX_ITEM = {'image': 100 * 1024 * 1024, 'video': 500 * 1024 * 1024}
MAX_TOTAL = 2 * 1024 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000


def check_url(url, marketplace, article, media_type=None):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Media URL must be HTTPS without credentials or a custom port.')
    if not any(host == domain or host.endswith('.' + domain) for domain in DOMAINS[marketplace]):
        raise ValueError(f'Unrecognized {marketplace} media host: {host}')
    path = parsed.path.lower()
    if re.search(r'\.(m3u8|mpd)(?:$|/)', path):
        raise ValueError('Streaming video cannot be saved as a single video file; gallery is not complete.')
    if re.search(r'/(?:icons?|sprite|logo|avatar|cms|marketing-api|badge|rating|stars?)/', path) or dict(parse_qsl(parsed.query)).get('type') == 'review':
        raise ValueError('UI/review media is not a product gallery asset.')
    if media_type == 'image' and marketplace == 'WB' and (f'/{article}/' not in path or '/images/' not in path):
        raise ValueError('WB photo does not belong to the requested article.')
    if media_type == 'image' and marketplace == 'OZON' and 'multimedia' not in path:
        raise ValueError('Ozon photo is not a product media URL.')
    return parsed


def normalize_url(url, marketplace):
    parsed = urlsplit(url)
    path = parsed.path
    if marketplace == 'WB':
        path = re.sub(r'/(?:c\d+x\d+|tm|small)/', '/big/', path, flags=re.I)
    else:
        path = re.sub(r'/(?:wc\d+|c\d+)/', '/wc1200/', path, flags=re.I)
    # Same high-resolution paths as the extension, with valid query separators.
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                       if k.lower() not in ('width', 'height', 'w', 'h')]) if marketplace == 'OZON' else parsed.query
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ''))


class SafeRedirect(HTTPRedirectHandler):
    def __init__(self, marketplace, article, media_type=None):
        self.marketplace, self.article, self.media_type = marketplace, article, media_type

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.marketplace, self.article, self.media_type)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(request, marketplace, article, media_type):
    return build_opener(SafeRedirect(marketplace, article, media_type)).open(request, timeout=45)


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError('Gallery manifest must be a JSON object.')
    marketplace = manifest.get('marketplace')
    article = str(manifest.get('article', ''))
    if marketplace not in DOMAINS or not re.fullmatch(r'[0-9]{1,30}', article):
        raise ValueError('Expected WB/OZON and a numeric marketplace article.')
    page = urlsplit(manifest.get('page_url', ''))
    valid_host = ((page.hostname == 'wildberries.ru' or (page.hostname or '').endswith('.wildberries.ru')) if marketplace == 'WB'
                  else (page.hostname == 'ozon.ru' or (page.hostname or '').endswith('.ozon.ru')))
    match = re.fullmatch(r'/catalog/([0-9]+)/detail\.aspx', page.path) if marketplace == 'WB' else re.fullmatch(r'/product/(?:[^/]*-)?([0-9]+)/?', page.path)
    if page.scheme != 'https' or page.username or page.password or page.port not in (None, 443) or not valid_host or not match or match[1] != article:
        raise ValueError('Page URL does not match the requested marketplace/article.')
    if manifest.get('complete') is not True:
        raise ValueError('Visit every gallery item before declaring the gallery complete.')
    media = manifest.get('media')
    if not isinstance(media, list) or not 1 <= len(media) <= 1000:
        raise ValueError('Expected 1..1000 observed gallery items.')
    items, seen = [], set()
    for item in media:
        if not isinstance(item, dict):
            raise ValueError('Every gallery item must be a JSON object.')
        kind, url = item.get('type'), item.get('url')
        if kind not in MAX_ITEM or not isinstance(url, str):
            raise ValueError('Every gallery item needs type image/video and its observed URL.')
        check_url(url, marketplace, article, kind)
        improved = normalize_url(url, marketplace) if kind == 'image' else url
        check_url(improved, marketplace, article, kind)
        if (kind, improved) not in seen:
            seen.add((kind, improved))
            items.append(dict(type=kind, url=improved, source_url=url, local_path=item.get('local_path')))
    expected = manifest.get('expected_count')
    if type(expected) is not int or expected != len(items) or not any(item['type'] == 'image' for item in items):
        raise ValueError('Unique media count must match the verified gallery count and contain photos.')
    return marketplace, article, items


def fetch_file(item, destination, marketplace, article, page_url):
    url = item['url']
    for attempt in range(3):
        try:
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0 ProstoJPG/1.0.2', 'Referer': page_url, 'Accept': '*/*', 'Accept-Encoding': 'identity'})
            with open_url(request, marketplace, article, item['type']) as response, destination.open('wb') as output:
                count = 0
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > MAX_ITEM[item['type']]:
                        raise ValueError('Media exceeds the size limit.')
                    output.write(chunk)
                declared = response.headers.get('Content-Length') if hasattr(response, 'headers') else None
                if declared and int(declared) != count:
                    raise ValueError('Incomplete HTTP response: content length does not match.')
            if count == 0:
                raise ValueError('Empty media response.')
            return url
        except HTTPError as error:
            # An observed preview is a safe fallback only if the high-res variant is absent.
            if error.code == 404 and url != item['source_url']:
                url = item['source_url']
                continue
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError, ConnectionError, IncompleteRead):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)
    raise ValueError('Download attempts exhausted.')


def media_extension(path, kind):
    if kind == 'image':
        with Image.open(path) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('Image exceeds 40 megapixels.')
            suffix = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif', 'AVIF': '.avif'}.get(image.format)
            if not suffix:
                raise ValueError('Unsupported image format.')
            image.verify()
        return suffix
    with path.open('rb') as source:
        header = source.read(64)
    if len(header) >= 12 and header[4:8] == b'ftyp':
        return '.mov' if header[8:12] == b'qt  ' else '.mp4'
    if header.startswith(b'\x1a\x45\xdf\xa3'):
        return '.webm'
    raise ValueError('Video response is not an MP4/MOV/WebM container (possibly a stream or access challenge).')


def download(manifest, output, from_local=False):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Choose a new ZIP name: {output}')
    marketplace, article, items = validate_manifest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prostojpg-', dir=output.parent) as temporary:
        root = Path(temporary)
        total, images, videos = 0, 0, 0
        records = []
        archive_path = root / 'complete.zip'
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for index, item in enumerate(items, 1):
                local = root / f'{index}.media'
                if from_local:
                    observed_path = item.get('local_path')
                    if not isinstance(observed_path, str) or not Path(observed_path).is_absolute():
                        raise ValueError('External-browser download must supply an absolute local_path for every item.')
                    source = Path(observed_path).resolve(strict=True)
                    if not source.is_file() or not 0 < source.stat().st_size <= MAX_ITEM[item['type']]:
                        raise ValueError('Local media is missing, empty or exceeds its size limit.')
                    shutil.copyfile(source, local)
                    actual_url = item['source_url']
                else:
                    actual_url = fetch_file(item, local, marketplace, article, manifest['page_url'])
                try:
                    suffix = media_extension(local, item['type'])
                except (OSError, Image.DecompressionBombError) as error:
                    raise ValueError(f'Invalid gallery item {index}: {error}') from error
                total += local.stat().st_size
                if total > MAX_TOTAL:
                    raise ValueError('Gallery exceeds the total size limit of 2 GB.')
                filename = f'{marketplace}_{article}_{index:04d}{suffix}'
                archive.write(local, filename)
                records.append(dict(index=index, type=item['type'], file=filename, url=actual_url))
                images += item['type'] == 'image'
                videos += item['type'] == 'video'
                local.unlink()
            archive.writestr('download-manifest.json', json.dumps(dict(marketplace=marketplace, article=article, page_url=manifest['page_url'], complete=True,
                                                                     image_count=images, video_count=videos, media=records), ensure_ascii=False, indent=2))
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip():
                raise ValueError('ZIP verification failed.')
        # Exclusive create: an existing archive is never replaced, including a racing creator.
        created = False
        try:
            with output.open('xb') as target, archive_path.open('rb') as source:
                created = True
                shutil.copyfileobj(source, target)
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
    return dict(archive=str(output), image_count=images, video_count=videos, complete=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--from-local', action='store_true', help='Pack verified files downloaded by the external browser without HTTP requests.')
    args = parser.parse_args()
    try:
        if args.manifest.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Gallery manifest is too large.')
        result = download(json.loads(args.manifest.read_text(encoding='utf-8-sig')), args.output, args.from_local)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, HTTPError, URLError, Image.DecompressionBombError) as error:
        import sys
        print(json.dumps(dict(error=str(error), complete=False), ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
