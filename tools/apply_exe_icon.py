"""Replace Windows icon resources without altering the bundled Python archive."""
from pathlib import Path
import ctypes, hashlib, os, struct
from ctypes import wintypes
from update_bundle import read_archive
root=Path(__file__).resolve().parents[1]
exe=root/'清影/清影.exe'
ico=(root/'source/assets/qingying.ico').read_bytes()
reserved,kind,count=struct.unpack_from('<HHH',ico)
assert (reserved,kind)==(0,1) and count==7
original=exe.read_bytes()
prefix,entries,_=read_archive(original)
overlay=original[len(prefix):]
stage=exe.with_name('qingying-icon-staging.exe')
stage.write_bytes(prefix)
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.LoadLibraryExW.argtypes=[wintypes.LPCWSTR,wintypes.HANDLE,wintypes.DWORD];k.LoadLibraryExW.restype=wintypes.HMODULE
k.FreeLibrary.argtypes=[wintypes.HMODULE]
k.BeginUpdateResourceW.argtypes=[wintypes.LPCWSTR,wintypes.BOOL];k.BeginUpdateResourceW.restype=wintypes.HANDLE
k.UpdateResourceW.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_void_p,wintypes.DWORD];k.UpdateResourceW.restype=wintypes.BOOL
k.EndUpdateResourceW.argtypes=[wintypes.HANDLE,wintypes.BOOL];k.EndUpdateResourceW.restype=wintypes.BOOL
NameCallback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ssize_t)
LangCallback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_ssize_t)
k.EnumResourceNamesW.argtypes=[wintypes.HMODULE,ctypes.c_void_p,NameCallback,ctypes.c_ssize_t]
k.EnumResourceLanguagesW.argtypes=[wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,LangCallback,ctypes.c_ssize_t]
def nameptr(name):return name if isinstance(name,int) else ctypes.cast(ctypes.c_wchar_p(name),ctypes.c_void_p)
def resources(path):
 module=k.LoadLibraryExW(str(path),None,2)
 if not module:raise ctypes.WinError(ctypes.get_last_error())
 found=[]
 try:
  for rtype in (3,14):
   @NameCallback
   def names(mod,typ,name,param):
    identifier=name if name<=65535 else ctypes.wstring_at(name)
    @LangCallback
    def langs(mod,typ,n,lang,param):found.append((rtype,identifier,lang));return True
    k.EnumResourceLanguagesW(mod,typ,name,langs,0)
    return True
   k.EnumResourceNamesW(module,rtype,names,0)
 finally:k.FreeLibrary(module)
 return found
old=resources(stage)
handle=k.BeginUpdateResourceW(str(stage),False)
if not handle:raise ctypes.WinError(ctypes.get_last_error())
def update(typ,name,lang,data):
 buf=ctypes.create_string_buffer(data) if data else None
 if not k.UpdateResourceW(handle,typ,nameptr(name),lang,buf,len(data) if data else 0):raise ctypes.WinError(ctypes.get_last_error())
try:
 for typ,name,lang in old:update(typ,name,lang,None)
 group=bytearray(struct.pack('<HHH',0,1,count))
 for i in range(count):
  width,height,colors,res,planes,bits,size,offset=struct.unpack_from('<BBBBHHII',ico,6+16*i)
  data=ico[offset:offset+size]
  update(3,i+1,0,data)
  group.extend(struct.pack('<BBBBHHIH',width,height,colors,res,planes,bits,size,i+1))
 for name,lang in {(name,lang) for typ,name,lang in old if typ==14} or {(1,0)}:update(14,name,lang,bytes(group))
 if not k.EndUpdateResourceW(handle,False):raise ctypes.WinError(ctypes.get_last_error())
 handle=None
except:
 if handle:k.EndUpdateResourceW(handle,True)
 raise
with stage.open('ab') as stream:stream.write(overlay)
new=stage.read_bytes()
new_prefix,new_entries,_=read_archive(new)
assert entries==new_entries and new[len(new_prefix):]==overlay
assert len([r for r in resources(stage) if r[0]==3])==7
# Verify the complete icon bitmaps embedded in the PE, not merely their names.
k.FindResourceW.argtypes=[wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p];k.FindResourceW.restype=wintypes.HANDLE
k.LoadResource.argtypes=[wintypes.HMODULE,wintypes.HANDLE];k.LoadResource.restype=wintypes.HANDLE
k.LockResource.argtypes=[wintypes.HANDLE];k.LockResource.restype=ctypes.c_void_p
k.SizeofResource.argtypes=[wintypes.HMODULE,wintypes.HANDLE];k.SizeofResource.restype=wintypes.DWORD
mod=k.LoadLibraryExW(str(stage),None,2)
try:
 for i in range(count):
  size,offset=struct.unpack_from('<II',ico,6+16*i+8)
  resource=k.FindResourceW(mod,i+1,3)
  actual=ctypes.string_at(k.LockResource(k.LoadResource(mod,resource)),k.SizeofResource(mod,resource))
  assert actual==ico[offset:offset+size]
finally:k.FreeLibrary(mod)
os.replace(stage,exe)
print('PASS: seven icon bitmaps embedded and verified; Python archive byte-for-byte unchanged')
print('EXE SHA256:',hashlib.sha256(exe.read_bytes()).hexdigest())
