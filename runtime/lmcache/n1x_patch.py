"""Build-time source edits that fail closed on missing or ambiguous anchors."""
from pathlib import Path
import site


def installed_root():
    return Path(site.getsitepackages()[0])


class Patch:
    def __init__(self, relative, patch, *, root=None, text=None):
        self.path = (installed_root() if root is None else Path(root)) / relative
        self.patch = patch
        try:
            self.text = self.path.read_text(encoding='utf-8') if text is None else text
        except OSError as error:
            self.fail(str(error))
        self.original = self.text

    def fail(self, detail):
        raise RuntimeError(f'Unexpected patch target: {self.patch}: {self.path}: {detail}')

    def require(self, needle, count=1):
        """Require an exact count, or at least one occurrence when count is None."""
        actual = self.text.count(needle)
        if (actual < 1 if count is None else actual != count):
            expected = 'at least 1' if count is None else str(count)
            self.fail(f'expected {expected} matches, found {actual}: {needle[:100]!r}')

    def replace(self, old, new):
        self.require(old)
        self.text = self.text.replace(old, new, 1)

    def section(self, start, end=None):
        """Return a guarded slice; replace its original text to merge edits back."""
        self.require(start)
        first = self.text.index(start)
        last = len(self.text)
        if end is not None:
            self.require(end)
            last = self.text.index(end)
            if last <= first:
                self.fail(f'section end precedes start: {start!r}, {end!r}')
        return Patch(self.path, self.patch, text=self.text[first:last])

    def compile(self):
        try:
            compile(self.text, str(self.path), 'exec', dont_inherit=True)
        except SyntaxError as error:
            self.fail(f'invalid Python at line {error.lineno}: {error.msg}')

    def write(self):
        self.compile()
        self.path.write_text(self.text, encoding='utf-8')
