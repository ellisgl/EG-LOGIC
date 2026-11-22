#!/usr/bin/env python3
"""tile the per-cell previews into docs/gallery_<pdk>.png"""
import os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.image as im
from cells import ORDER
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
os.makedirs(os.path.join(root, 'docs'), exist_ok=True)
for pdk in sys.argv[1:] or ['gf180mcuD', 'sky130A']:
    fig, axs = plt.subplots(2, 4, figsize=(20, 9))
    for a, c in zip(axs.flat, ORDER):
        a.imshow(im.imread(os.path.join(root, pdk, f'{c}_preview.png')))
        a.axis('off')
    plt.tight_layout()
    plt.savefig(os.path.join(root, 'docs', f'gallery_{pdk}.png'), dpi=80)
