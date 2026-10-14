"""Build on each target OS. The resulting folder includes Python and OCR models."""
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parent
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir',
    '--windowed','--name','Test Exchange Converter','--add-data',str(root/'web')+':web',
    '--add-data',str(root/'events.json')+':.',
    '--collect-all','rapidocr_onnxruntime','--collect-all','onnxruntime',
    '--collect-all','pymupdf','--collect-all','pyclipper','--collect-all','shapely',
    '--collect-all','cv2','--collect-all','numpy',str(root/'app.py')],cwd=root,check=True)
