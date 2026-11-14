"""Load standard modules from the installed application's PYZ without installing Python."""
import sys
import marshal
import _struct as struct
sys.modules['struct'] = struct
import zlib
import os
from _frozen_importlib import ModuleSpec

root = __file__ if '__file__' in globals() else sys.argv[0]
# The runner includes the tools directory in sys.path.
root = sys.path[-1].replace('\\', '/').rsplit('/', 1)[0]
with open(root + '/清影/清影.exe', 'rb') as stream:
    archive = stream.read()
cookie = archive.rfind(b'MEI\014\013\012\013\016')
_, size, toc_offset, toc_length, version, _ = struct.unpack('!8sIIII64s', archive[cookie:cookie + 88])
assert version == 310
start = cookie + 88 - size
position = start + toc_offset
while position < start + toc_offset + toc_length:
    length, offset, compressed, _, flag, _ = struct.unpack('!IIIIBc', archive[position:position + 18])
    name = archive[position + 18:position + length].rstrip(b'\0').decode()
    if name == 'PYZ.pyz':
        pyz = archive[start + offset:start + offset + compressed]
        if flag:
            pyz = zlib.decompress(pyz)
        break
    position += length
else:
    raise RuntimeError('PYZ archive not found')
pyz_toc = dict(marshal.loads(pyz[struct.unpack('!i', pyz[8:12])[0]:]))


class BundledModules:
    def get_resource_reader(self, fullname):
        from pathlib import Path
        class Resources:
            def files(self):
                return Path(root) / '清影' / '_internal' / fullname.replace('.', '/')
            def resource_path(self, resource):
                return str(self.files() / resource)
            def open_resource(self, resource):
                return (self.files() / resource).open('rb')
            def is_resource(self, resource):
                return (self.files() / resource).is_file()
            def contents(self):
                return (p.name for p in self.files().iterdir())
        return Resources()

    def find_spec(self, fullname, path=None, target=None):
        if fullname in pyz_toc and not os.path.isfile(root + '/source/' + fullname.replace('.', '/') + '.py'):
            return ModuleSpec(fullname, self, is_package=pyz_toc[fullname][0] in (1, 3))

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        kind, offset, size = pyz_toc[module.__name__]
        filename = root + '/清影/_internal/' + module.__name__.replace('.', '/')
        if kind in (1, 3):
            module.__path__ = [filename]
            filename += '/__init__'
        module.__file__ = filename + '.pyc'
        if kind != 3:
            exec(marshal.loads(zlib.decompress(pyz[offset:offset + size])), module.__dict__)


sys.meta_path.insert(2, BundledModules())
import runpy
runpy.run_path(sys.argv[0], run_name='__main__')
