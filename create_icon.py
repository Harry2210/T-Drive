from PIL import Image
import sys

def create_ico(source_path, target_path):
    img = Image.open(source_path)
    # Standard Windows ICO sizes
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (255, 255)]
    img.save(target_path, sizes=icon_sizes)
    print(f"✅ Created {target_path}")

if __name__ == "__main__":
    src = "C:\\Users\\hario\\.gemini\\antigravity\\brain\\c22d1b98-68d8-4ec3-991d-66d947115b8e\\tdrive_app_icon_1776426489608.png"
    create_ico(src, "app.ico")
