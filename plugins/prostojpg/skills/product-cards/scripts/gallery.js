/* Read-only DOM collector. Read this file, then pass the function expression to
 * the available browser tool's documented DOM-evaluation API. Never inject the
 * extension's collector: it registers handlers and performs clicks. UI gallery
 * navigation belongs to the browser tool, outside this function.
 */
function collectProductGallery({marketplace, article, selector}) {
  const page = new URL(location.href);
  const match = marketplace === 'WB'
    ? page.pathname.match(/^\/catalog\/(\d+)\/detail\.aspx$/)
    : page.pathname.match(/^\/product\/(?:[^/]*-)?(\d+)\/?$/);
  const pageDomain = marketplace === 'WB' ? 'wildberries.ru' : 'ozon.ru';
  if (!['WB', 'OZON'].includes(marketplace) || !match || match[1] !== String(article) ||
      !(page.hostname === pageDomain || page.hostname.endsWith('.' + pageDomain))) {
    throw new Error('Open the exact requested product before collecting its gallery.');
  }
  // The agent selects this root from observed DOM, after checking that it belongs
  // to the product gallery. Never scan recommendation/review scripts globally.
  if (!selector) throw new Error('A browser-observed gallery selector is required.');
  const roots = document.querySelectorAll(selector);
  if (roots.length !== 1) throw new Error('Gallery selector must identify exactly one root.');
  const root = roots[0];
  const domains = marketplace === 'WB'
    ? ['wbbasket.ru', 'wbstatic.net', 'wbstatic.ru', 'geobasket.ru', 'wbcontent.net', 'wb.ru']
    : ['ozone.ru', 'ozon.ru', 'ozonusercontent.com'];
  const found = new Map();
  function add(value, type) {
    if (!value || /^(?:blob|data):/i.test(value)) return;
    let url;
    try { url = new URL(String(value).replaceAll('\\/', '/').replaceAll('&amp;', '&'), page); } catch { return; }
    if (url.protocol !== 'https:' || url.username || url.password ||
        !domains.some(domain => url.hostname === domain || url.hostname.endsWith('.' + domain))) return;
    const path = url.pathname;
    if (/\/(?:icons?|sprite|logo|avatar|cms|marketing-api|badge|rating|stars?)\//i.test(path) || url.searchParams.get('type') === 'review') return;
    if (type === 'image' && (!/\.(?:jpe?g|png|webp|gif|avif)$/i.test(path) ||
        (marketplace === 'WB' && (!path.includes('/' + article + '/') || !path.includes('/images/'))) ||
        (marketplace === 'OZON' && !/multimedia/i.test(path)))) return;
    if (type === 'video' && !/\.(?:mp4|webm|mov|m3u8|mpd)$/i.test(path) && !/\/(?:video|videos|ugc-video|vod)\//i.test(path)) return;
    const key = new URL(url);
    if (type === 'image') {
      key.pathname = marketplace === 'WB'
        ? path.replace(/\/(?:c\d+x\d+|tm|small)\//gi, '/big/')
        : path.replace(/\/(?:wc\d+|c\d+)\//gi, '/wc1200/');
      if (marketplace === 'OZON') for (const name of ['width', 'height', 'w', 'h']) key.searchParams.delete(name);
    }
    key.hash = '';
    if (!found.has(type + key.href)) found.set(type + key.href, {type, url: url.href});
  }
  for (const image of root.querySelectorAll('img, picture source[srcset]')) {
    add(image.currentSrc || image.getAttribute('src') || image.getAttribute('data-src') || image.getAttribute('data-original'), 'image');
    for (const part of String(image.getAttribute('srcset') || '').split(',')) add(part.trim().split(/\s+/)[0], 'image');
  }
  for (const element of root.querySelectorAll('video, source[src], [data-video], [data-video-src], [data-mp4], [data-video-url], [data-state], [style]')) {
    for (const attribute of ['src', 'data-src', 'data-video', 'data-video-src', 'data-mp4', 'data-video-url']) add(element.getAttribute(attribute), 'video');
    if (element.currentSrc) add(element.currentSrc, 'video');
    const text = (element.getAttribute('data-state') || '').replaceAll('\\/', '/').replace(/\\u002F/gi, '/').replace(/\\u0026/gi, '&');
    for (const match of text.matchAll(/https:\/\/[^\s"'<>]+?\.(?:mp4|webm|mov|m3u8|mpd)(?:\?[^\s"'<>]*)?/gi)) add(match[0], 'video');
    for (const match of String(element.getAttribute('style') || '').matchAll(/url\(['"]?(.*?)['"]?\)/gi)) add(match[1], 'image');
  }
  return {marketplace, article: String(article), page_url: page.href, complete: false,
          expected_count: null, media: [...found.values()]};
}

if (typeof module !== 'undefined') module.exports = {collectProductGallery};
