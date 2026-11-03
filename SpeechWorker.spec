# Optional Windows-x64 runtime, separate from the lightweight main application.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
ROOT = os.path.abspath('.')
binaries, datas = [], []
for package in ('sounddevice', 'sherpa_onnx', 'sherpa_onnx_core', 'soxr', 'ctranslate2', 'tokenizers'):
    binaries += collect_dynamic_libs(package)
for package in ('sherpa_onnx', 'faster_whisper', 'ctranslate2', 'tokenizers', 'huggingface_hub'):
    datas += collect_data_files(package, include_py_files=False)
a = Analysis(['speech_worker.py'], pathex=[ROOT], binaries=binaries, datas=datas,
    hiddenimports=['numpy', 'sounddevice', 'sherpa_onnx', 'soxr', 'faster_whisper',
                   'ctranslate2', 'tokenizers', 'huggingface_hub', 'core.speech_recognizer',
                   'core.speech_session', 'core.speech_service'],
    excludes=['PySide6', 'tkinter', 'torch', 'transformers', 'scipy', 'sympy', 'numba', 'pytest'],
    noarchive=False)
pyz = PYZ(a.pure)
# Console bootloader enables stdin/stdout pipes. The caller always launches it
# with CREATE_NO_WINDOW; no visible or uncloseable terminal is created.
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MouserSpeech',
          console=True, debug=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='MouserSpeech', strip=False, upx=False)
