"""Inspect the existing PyInstaller archive using its matching Python runtime."""
import marshal
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
data = (ROOT / '清影' / '清影.exe').read_bytes()
cookie = data.rfind(b'MEI\014\013\012\013\016')
magic, size, offset, length, version, library = struct.unpack('!8sIIII64s', data[cookie:cookie + 88])
assert version == 310
start = cookie + 88 - size
position = start + offset
while position < start + offset + length:
    entry_size, entry_offset, compressed, raw, flag, kind = struct.unpack('!IIIIBc', data[position:position + 18])
    name = data[position + 18:position + entry_size].rstrip(b'\0').decode()
    payload = data[start + entry_offset:start + entry_offset + compressed]
    if flag:
        payload = zlib.decompress(payload)
    if name == 'app':
        code = marshal.loads(payload)
        print('app source:', code.co_filename)
        print('app strings:', [c[:100] for c in code.co_consts if isinstance(c, str)][-12:])
        import types
        original = next(c for c in code.co_consts if isinstance(c, types.CodeType) and c.co_name == 'App')
        updated_module = compile((ROOT / 'source' / 'app.py').read_text('utf-8'), 'app.py', 'exec')
        updated = next(c for c in updated_module.co_consts if isinstance(c, types.CodeType) and c.co_name == 'App')
        for name in ('__init__', 'run_job', 'shutdown'):
            old = next(c for c in original.co_consts if isinstance(c, types.CodeType) and c.co_name == name)
            new = next(c for c in updated.co_consts if isinstance(c, types.CodeType) and c.co_name == name)
            print(name, 'new referenced names:', sorted(set(new.co_names) - set(old.co_names)))
    if name == 'PYZ.pyz':
        toc_offset = struct.unpack('!i', payload[8:12])[0]
        toc = dict(marshal.loads(payload[toc_offset:]))
        print('Project modules:', [n for n in toc if (ROOT / 'source' / (n + '.py')).exists()])
        print('Glass module present:', 'glass_host' in toc)
    position += entry_size
