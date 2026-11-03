# Mouser optional local speech runtime

Original Mouser project: https://github.com/TomBadash/Mouser
G502 fork: https://github.com/meiyoutou/Mouser-G502

This is a separate, optional Windows x64 speech process, not a mouse driver.
It runs locally, stores no recordings or transcripts, and contains no personal
configuration, shortcuts, vocabulary, device backups or logs.

The executable is built with PyInstaller (GPL with bootloader exception),
using CPython and these open-source projects. Included dependency license
files are under `_internal/third_party_licenses` and package license folders.

- CPython: https://github.com/python/cpython
- NumPy: https://github.com/numpy/numpy
- sounddevice / PortAudio: https://github.com/spatialaudio/python-sounddevice
- sherpa-onnx / ONNX Runtime: https://github.com/k2-fsa/sherpa-onnx
- soxr / libsoxr: https://github.com/dofuuz/python-soxr
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- CTranslate2: https://github.com/OpenNMT/CTranslate2
- tokenizers: https://github.com/huggingface/tokenizers
- huggingface_hub: https://github.com/huggingface/huggingface_hub
- PyAV / FFmpeg: https://github.com/PyAV-Org/PyAV

Models are separate downloads with their own notices. Whisper is imported
only when selected, not when using SenseVoice or Zipformer.
