"""Deterministic package icons; no remote assets."""
from pathlib import Path
from PIL import Image, ImageDraw

def create(folder):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    for name, size in (('StoreLogo',50), ('Square150x150Logo',150), ('Square44x44Logo',44)):
        image = Image.new('RGB', (size,size), '#236548')
        draw = ImageDraw.Draw(image)
        draw.text((size*.32,size*.24), 'P', fill='white', font_size=int(size*.55))
        image.save(folder / (name+'.png'))

if __name__ == '__main__':
    import sys
    create(sys.argv[1])
