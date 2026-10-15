"""Convert downloaded test attachments to reviewable PDFs without a cloud service."""
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf

MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_PDF_BYTES = 50 * 1024 * 1024
OFFICE_EXTENSIONS = {'.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp'}


def _check_pdf(data):
    if not data.startswith(b'%PDF-') or len(data) > MAX_PDF_BYTES:
        raise ValueError('The converted PDF is invalid or exceeds 50 MB.')
    try:
        with pymupdf.open(stream=data, filetype='pdf') as pdf:
            if pdf.needs_pass or not len(pdf):
                raise ValueError('The converted PDF is locked or empty.')
    except pymupdf.FileDataError:
        raise ValueError('The converted PDF could not be read.') from None
    return data


def _image_pdf(data):
    with pymupdf.open(stream=data, filetype='jpg' if data.startswith(b'\xff\xd8') else None) as image:
        return image.convert_to_pdf()


def _text_pdf(data):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('cp1252')
    pdf = pymupdf.open()
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    while lines:
        page = pdf.new_page(width=612, height=792)
        y = 48
        used = 0
        for line in lines:
            chunks = [line[i:i+80] for i in range(0, len(line), 80)] or ['']
            if y + 13 * len(chunks) > 748:
                break
            for chunk in chunks:
                page.insert_text((48, y), chunk, fontsize=10, fontname='cour')
                y += 13
            used += 1
        if used == 0:
            used = 1
        lines = lines[used:]
    if not pdf.page_count:
        pdf.new_page(width=612, height=792)
    result = pdf.tobytes()
    pdf.close()
    return result


def _office_pdf(name, data):
    with tempfile.TemporaryDirectory(prefix='test-exchange-convert-') as folder:
        root = Path(folder)
        source = root / ('source' + Path(name).suffix.lower())
        output = root / 'source.pdf'
        source.write_bytes(data)
        soffice = shutil.which('soffice') or shutil.which('libreoffice')
        if soffice:
            profile = (root / 'lo-profile').as_uri()
            command = [soffice, '-env:UserInstallation=' + profile, '--headless', '--convert-to', 'pdf',
                       '--outdir', str(root), str(source)]
            try:
                subprocess.run(command, capture_output=True, timeout=120, check=False)
            except subprocess.TimeoutExpired:
                pass
            if output.is_file():
                return output.read_bytes()
        if os.name == 'nt':
            # Office is optional. The source path is passed via environment variables,
            # never interpolated into PowerShell code.
            ext = source.suffix
            if ext in ('.doc', '.docx'):
                script = """$app=New-Object -ComObject Word.Application
$app.Visible=$false
$app.DisplayAlerts=0
$app.AutomationSecurity=3
try {
  $doc=$app.Documents.Open($env:CONVERTER_INPUT,$false,$true,$false)
  try { $doc.ExportAsFixedFormat($env:CONVERTER_OUTPUT,17) }
  finally { $doc.Close($false) }
} finally { $app.Quit() }
"""
            elif ext in ('.ppt', '.pptx'):
                script = """$app=New-Object -ComObject PowerPoint.Application
$app.AutomationSecurity=3
try {
  $doc=$app.Presentations.Open($env:CONVERTER_INPUT,$true,$true,$false)
  try { $doc.SaveAs($env:CONVERTER_OUTPUT,32) }
  finally { $doc.Close() }
} finally { $app.Quit() }
"""
            else:
                script = """$app=New-Object -ComObject Excel.Application
$app.Visible=$false
$app.DisplayAlerts=$false
$app.AutomationSecurity=3
try {
  $doc=$app.Workbooks.Open($env:CONVERTER_INPUT,0,$true)
  try { $doc.ExportAsFixedFormat(0,$env:CONVERTER_OUTPUT) }
  finally { $doc.Close($false) }
} finally { $app.Quit() }
"""
            environment = dict(os.environ, CONVERTER_INPUT=str(source), CONVERTER_OUTPUT=str(output))
            try:
                subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                               capture_output=True, timeout=120, check=False, env=environment)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if output.is_file():
                return output.read_bytes()
    raise ValueError('Could not convert this Office document. Install LibreOffice or Microsoft Office, then retry.')


def convert_to_pdf(name, data):
    """Return (validated PDF bytes, converted); never mislabel arbitrary bytes as PDF."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_SOURCE_BYTES:
        raise ValueError('The downloaded file is empty or exceeds 50 MB.')
    if data.startswith(b'%PDF-'):
        return _check_pdf(data), False
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        result = _image_pdf(data)
    elif suffix == '.txt':
        result = _text_pdf(data)
    elif suffix in OFFICE_EXTENSIONS:
        result = _office_pdf(name, data)
    else:
        raise ValueError(f'Unsupported attachment type: {suffix or "unknown"}. The original was not attached.')
    return _check_pdf(result), True
