# Scrolling capture third-party notices

The verified-registration design in `ui/screenshot_registration.py` was informed
by ScrollSnap's separate translation proposal / appearance verification,
informative-column weighting, and safe recovery approach. Windows implementation
uses OpenCV rather than Apple's Vision/AppKit and is independently integrated.

Reference: https://github.com/Brkgng/ScrollSnap
Commit: `74a613b4cbbfaa689ad3fd80043d5be79b7bc99a`

## ScrollSnap — MIT License

Copyright (c) 2025 Berker Gungor

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Binary dependencies

The optional long-capture engine includes OpenCV (Apache-2.0) and NumPy
(BSD-3-Clause), rather than bundling them in the main app. Their distribution
license and bundled-library notices are included in the component's `licenses/`
directory. OpenCV and NumPy are screenshot dependencies,
not bundled speech recognition engines or AI models.

eSearch and ShareX were inspected for interaction ideas only. No GPL source
from either project is incorporated into this MIT implementation.

## Optional screenshot text selection

The separately installed text-selection component is optional; legacy adjacent
`文字选择组件` folders remain supported. The previous RapidOCR / PP-OCRv6
implementation, installer and result dialog have been removed from this build.
Text selection still uses OCR technology internally; it is not native source text.
No recognizer is loaded into the
main UI, no images leave the computer, and the isolated child exits after each
request. Tesseract recognition can be inaccurate; it is not original source text.

- Tesseract 5.5.3 and tessdata_fast chi_sim / eng: Apache-2.0.
  https://github.com/tesseract-ocr/tesseract
  https://github.com/tesseract-ocr/tessdata_fast
- tesserocr 2.11.0: MIT.
  https://github.com/sirfz/tesserocr
- Windows wheel: community build by simonflueckiger, release
  `tesserocr-v2.11.0-tesseract-5.5.3`, CPython 3.13 x64.
  https://github.com/simonflueckiger/tesserocr-windows_build
- Leptonica and its bundled image codecs: see upstream projects and their
  notices. The optional folder includes the wheel's license, Tesseract,
  tessdata_fast and Leptonica licenses. Keep these notices when redistributing.
