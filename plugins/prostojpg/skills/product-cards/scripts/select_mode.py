"""Resolve a ProstoJPG message command without downloading or generating files."""
import json
import re
import sys


def select_mode(text):
    message = text.strip()
    if not re.match(r'^[/\$]prostojpg-', message, re.IGNORECASE):
        return {'mode': None, 'arguments': message, 'requires_subject': False}
    match = re.match(r'^[/\$]prostojpg-([123])(?:\s+(.*))?$', message, re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError('Use /ProstoJpg-1, /ProstoJpg-2 or /ProstoJpg-3.')
    arguments = (match.group(2) or '').strip()
    if re.search(r'(?:^|\s)[/\$]prostojpg-', arguments, re.IGNORECASE):
        raise ValueError('Choose one ProstoJPG mode per request.')
    mode = int(match.group(1))
    return {'mode': mode, 'arguments': arguments, 'requires_subject': mode == 3}


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('Pass the user message as one argument.')
        print(json.dumps(select_mode(sys.argv[1]), ensure_ascii=False))
    except ValueError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
