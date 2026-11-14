"""Stage a targeted update with the installed Python 3.10 and unchanged bootloader.

Only existing modules and selected App methods change. The installed startup flow,
dependencies and resources stay intact. Run with run_bundled_python.ps1.
"""
import datetime
import marshal
from pathlib import Path
import struct
import types
import zlib

ROOT = Path(__file__).resolve().parents[1]
MAGIC = b'MEI\014\013\012\013\016'
MODULES = {'common', 'core', 'ui', 'mac_theme', 'collector', 'collector_ui', 'facebook_history', 'facebook_browser', 'facebook_profile', 'instagram_support', 'x_support', 'x_ui'}
MODULES.update({'updater', 'glass_host'})


def read_archive(data):
    cookie = data.rfind(MAGIC)
    assert cookie == len(data) - 88, 'Unexpected executable trailer'
    magic, size, offset, length, version, library = struct.unpack('!8sIIII64s', data[cookie:])
    assert magic == MAGIC and version == 310
    start = cookie + 88 - size
    position = start + offset
    entries = []
    while position < start + offset + length:
        entry_size, entry_offset, packed, raw, flag, kind = struct.unpack('!IIIIBc', data[position:position + 18])
        name = data[position + 18:position + entry_size].rstrip(b'\0').decode()
        entries.append((name, kind, flag, raw, data[start + entry_offset:start + entry_offset + packed]))
        position += entry_size
    assert position == start + offset + length
    return data[:start], entries, library


def update_pyz(payload):
    offset = struct.unpack('!i', payload[8:12])[0]
    toc = dict(marshal.loads(payload[offset:]))
    for name in sorted(MODULES - toc.keys()):
        toc[name] = (0, 0, 0)
    output = bytearray(payload[:12])
    updated_toc = []
    for name, (kind, position, size) in toc.items():
        if name in MODULES:
            source = (ROOT / 'source' / (name + '.py')).read_text('utf-8')
            block = zlib.compress(marshal.dumps(compile(source, name + '.py', 'exec')), 6)
        else:
            block = payload[position:position + size]
        updated_toc.append((name, (kind, len(output), len(block))))
        output.extend(block)
    output[8:12] = struct.pack('!i', len(output))
    output.extend(marshal.dumps(updated_toc))
    # Every module must still decompress into a code object (except namespaces).
    for name, (kind, position, size) in updated_toc:
        if kind != 3:
            assert isinstance(marshal.loads(zlib.decompress(output[position:position + size])), types.CodeType), name
    return bytes(output)


def update_app(payload):
    original = marshal.loads(payload)
    # Earlier updates wrap the original entrypoint in a marshalled-code constant.
    for _ in range(20):
        if any(isinstance(c, types.CodeType) and c.co_name == 'App' for c in original.co_consts):
            break
        if not {'marshal', 'exec', 'loads'} <= set(original.co_names):
            raise ValueError('Cannot locate the original App entrypoint; no update was written.')
        candidates=[]
        for value in original.co_consts:
            if isinstance(value, bytes):
                try:code=marshal.loads(value)
                except (ValueError,TypeError,EOFError):continue
                if isinstance(code, types.CodeType):candidates.append(code)
        if len(candidates)!=1:
            raise ValueError('Ambiguous App wrapper; no update was written.')
        original=candidates[0]
    else:
        raise ValueError('App wrapper nesting limit exceeded; no update was written.')
    source = compile((ROOT / 'source' / 'app.py').read_text('utf-8'), 'app.py', 'exec')
    app_class = next(c for c in source.co_consts if isinstance(c, types.CodeType) and c.co_name == 'App')
    methods = {c.co_name: c for c in app_class.co_consts
               if isinstance(c, types.CodeType) and c.co_name in {'__init__', 'run_job', 'shutdown', 'start_download', 'poll', 'set_busy', 'show_page'}}
    assert len(methods) == 7
    def patch_class(code):
        return code.replace(co_consts=tuple(methods.get(c.co_name, c) if isinstance(c, types.CodeType)
                                           else c for c in code.co_consts))
    patched = original.replace(co_consts=tuple(patch_class(c) if isinstance(c, types.CodeType)
                                               and c.co_name == 'App' else c for c in original.co_consts))
    # Keep original App methods while adopting the local webview startup and CLI modes.
    patched_class = next(c for c in patched.co_consts if isinstance(c, types.CodeType) and c.co_name == 'App')
    patched = source.replace(co_consts=tuple(patched_class if isinstance(c, types.CodeType) and c.co_name == 'App' else c for c in source.co_consts))
    wrapper = compile('import sys, os\nif sys.stdout is None: sys.stdout=open(os.devnull, "w")\nif sys.stderr is None: sys.stderr=open(os.devnull, "w")\nfrom common import load_settings, save_settings\n'
                      'import marshal\nglobals()["__name__"]="__main__"\ntry:\n exec(marshal.loads(' + repr(marshal.dumps(patched)) + '))\nexcept Exception:\n import traceback, pathlib, sys\n pathlib.Path(sys.executable).with_suffix(".startup.log").write_text(traceback.format_exc(), encoding="utf-8")\n raise\n', 'app.py', 'exec')
    return marshal.dumps(wrapper)


def main():
    installed = ROOT / '清影' / '清影.exe'
    prefix, entries, library = read_archive(installed.read_bytes())
    body = bytearray()
    toc = bytearray()
    changed = set()
    for name, kind, flag, raw_size, packed in entries:
        if name in ('app', 'PYZ.pyz'):
            raw = zlib.decompress(packed) if flag else packed
            raw = update_app(raw) if name == 'app' else update_pyz(raw)
            raw_size = len(raw)
            packed = zlib.compress(raw, 9) if flag else raw
            changed.add(name)
        name_bytes = name.encode() + b'\0'
        length = ((18 + len(name_bytes) + 15) // 16) * 16
        toc.extend(struct.pack('!IIIIBc', length, len(body), len(packed), raw_size, flag, kind))
        toc.extend(name_bytes.ljust(length - 18, b'\0'))
        body.extend(packed)
    assert changed == {'app', 'PYZ.pyz'}
    cookie = struct.pack('!8sIIII64s', MAGIC, len(body) + len(toc) + 88,
                         len(body), len(toc), 310, library)
    candidate = installed.with_name('清影-一体窗口.exe')
    candidate.write_bytes(prefix + body + toc + cookie)
    new_prefix, new_entries, _ = read_archive(candidate.read_bytes())
    assert prefix == new_prefix
    for before, after in zip(entries, new_entries):
        if before[0] not in changed:
            assert before == after
    backup = ROOT / 'backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True)
    (backup / installed.name).write_bytes(installed.read_bytes())
    print('PASS: candidate archive validated; original bootloader and other entries unchanged')
    print('Candidate:', candidate)
    print('Backup:', backup / installed.name)


if __name__ == '__main__':
    main()

