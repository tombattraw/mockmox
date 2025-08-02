import os
import shutil

def get_editor():
    editor = os.environ.get('EDITOR')
    if editor: return editor
    editor = os.environ.get('VISUAL')
    if editor: return editor

    for fallback in ['nano', 'vim', 'vi']:
        if shutil.which(fallback):
            return fallback
    raise RuntimeError("No editor found. Set the EDITOR environment variable.")