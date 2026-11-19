"""Read Markdown content, rather than its formatting, through TTS."""
from markdown_it import MarkdownIt
import re

_parser = MarkdownIt('commonmark', {'html': False})


def speech_text(markdown):
    pieces = []
    lists = []
    for token in _parser.parse(markdown):
        if token.type in ('ordered_list_open', 'bullet_list_open'):
            lists.append(int(token.attrGet('start') or 1) if token.type == 'ordered_list_open' else None)
        elif token.type in ('ordered_list_close', 'bullet_list_close'):
            lists.pop()
        elif token.type == 'list_item_open' and lists and lists[-1] is not None:
            pieces.append(f'{lists[-1]}. ')
            lists[-1] += 1
        elif token.type == 'inline':
            for child in token.children or []:
                if child.type in ('text', 'code_inline'):
                    pieces.append(child.content)
                elif child.type == 'image':
                    pieces.append(child.content)
                elif child.type in ('softbreak', 'hardbreak'):
                    pieces.append('\n')
        elif token.type in ('fence', 'code_block'):
            pieces.append(token.content)
        elif token.type in ('paragraph_close', 'heading_close', 'list_item_close'):
            pieces.append('\n')
    return '\n'.join(line.strip() for line in ''.join(pieces).splitlines() if line.strip())


def speech_excerpt(markdown):
    text = speech_text(markdown).strip()
    if len(text) <= 550:
        return text
    sentences = list(re.finditer(r'[.!?](?=\s|$)', text[:550]))
    if sentences:
        return text[:sentences[-1].end()]
    return text[:550].rsplit(maxsplit=1)[0] + '…'
