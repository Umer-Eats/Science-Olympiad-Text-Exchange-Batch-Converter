import io
import unittest

import pymupdf
from PIL import Image

from converter.file_conversion import convert_to_pdf


class FileConversionTests(unittest.TestCase):
    def test_image_becomes_readable_pdf(self):
        image = Image.new('RGB', (120, 80), 'white')
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        data, converted = convert_to_pdf('diagram.png', stream.getvalue())
        self.assertTrue(converted)
        with pymupdf.open(stream=data, filetype='pdf') as pdf:
            self.assertEqual(len(pdf), 1)

    def test_text_becomes_searchable_pdf(self):
        data, converted = convert_to_pdf('instructions.txt', b'First line\nSecond line')
        self.assertTrue(converted)
        with pymupdf.open(stream=data, filetype='pdf') as pdf:
            self.assertIn('Second line', pdf[0].get_text())

    def test_unsupported_bytes_are_not_disguised_as_pdf(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported attachment type'):
            convert_to_pdf('archive.zip', b'PK\x03\x04not a paper')
