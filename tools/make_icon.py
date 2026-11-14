from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]
image=Image.open(root/'source/assets/qingying-icon.png').convert('RGBA')
image.save(root/'source/assets/qingying.ico',format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
with Image.open(root/'source/assets/qingying.ico') as ico:
 assert ico.ico.sizes()=={(s,s) for s in (16,24,32,48,64,128,256)}
print('PASS: seven Windows icon sizes, 16–256px')
