"""Compose only confirmed signs; keep tone placement explicit until labels are supplied."""
import unicodedata


def compose_sign(sentence, label, text):
    text = unicodedata.normalize('NFC', text.strip())
    if not text or label == 'blank' or label.startswith('dau_'):
        # Tone labels need an orthographic policy; users can edit accented text directly.
        return sentence
    if len(text) == 1:
        return sentence + text
    return sentence + (' ' if sentence and not sentence.endswith(' ') else '') + text
