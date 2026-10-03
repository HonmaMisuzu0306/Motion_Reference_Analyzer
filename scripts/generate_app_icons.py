"""Generate Windows bitmap variants of the original vector MRA mark."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]

def main():
    size = 1024
    image = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(image)
    scale = size / 48
    draw.rounded_rectangle(tuple(int(v*scale) for v in (2, 2, 46, 46)), radius=int(9*scale), fill='#232323')
    for pts in [[(11,20),(11,11),(20,11)],[(28,11),(37,11),(37,20)],[(37,28),(37,37),(28,37)],[(20,37),(11,37),(11,28)]]:
        draw.line([(int(x*scale),int(y*scale)) for x,y in pts], fill='#67A9E8', width=int(3*scale), joint='curve')
    draw.line([(int(x*scale),int(y*scale)) for x,y in [(13,29),(21,20),(27,27),(35,18)]], fill='#D5E8FC', width=int(3*scale), joint='curve')
    dest=ROOT/'apps/desktop/src-tauri/icons'
    dest.mkdir(parents=True, exist_ok=True)
    for name, n in [('32x32',32),('128x128',128),('128x128@2x',256)]:
        image.resize((n,n),Image.Resampling.LANCZOS).save(dest/f'{name}.png')
    image.save(dest/'icon.ico',sizes=[(n,n) for n in (16,24,32,48,64,128,256)])
    public=ROOT/'apps/desktop/public'
    public.mkdir(exist_ok=True)
    image.resize((64,64),Image.Resampling.LANCZOS).save(public/'favicon.png')
    (public/'mra-mark.svg').write_bytes((ROOT/'apps/desktop/src/design/mra-mark.svg').read_bytes())

if __name__ == '__main__':
    main()
