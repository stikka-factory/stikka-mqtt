
from PIL import Image, ImageDraw, ImageFont
import barcode, qrcode
from datamatrix import DataMatrix
import zpl

from dataclasses import dataclass  
from io import BytesIO
from barcode import *
from barcode.writer import ImageWriter

import logger
log = logger.log

@dataclass
class TextElement:
    text: str
    x: int
    y: int
    char_height: float = 1.0
    char_width: float = 1.0
    line_width: int = None
    justification: str = 'L'
    font: str = 'A'

@dataclass
class ImageElement:
    image: Image
    x: int
    y: int
    width: int = None
    height: int = None
    justification: str = 'C'

@dataclass
class BarcodeElement:
    data: str
    x: int
    y: int
    barcode_type: str = 'U'
    height: int = 10
    width: int = 1
    magnification: int = 1

class StikkaLabel:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.height_pos = 0
        self.elements = []

    def add_text(self, text, x, y, char_height=1.0, char_width=1.0, line_width=None, justification='L', font='A'):
        log.info(f"Adding text element: '{text}' at ({x}, {y}) with char_height={char_height}, char_width={char_width}, line_width={line_width}, justification='{justification}', font='{font}'")
        self.elements.append(TextElement(text, x, y, char_height, char_width, line_width, justification, font))
        
    def add_image(self, image: Image, x, y, width=None, height=None,justification='C'):
        log.info(f"Adding image element at ({x}, {y}) with width={width}, height={height}, justification='{justification}'")
        self.elements.append(ImageElement(image, x, y, width, height, justification))
        
    def add_barcode(self, data, x, y, barcode_type='U', height=10, width=1,magnification=1):
        log.info(f"Adding barcode element: '{data}' at ({x}, {y}) with barcode_type='{barcode_type}', height={height}, width={width}, magnification={magnification}")
        self.elements.append(BarcodeElement(data, x, y, barcode_type, height, width, magnification))
    
    def change_label_size(self, width, height):
        log.info(f"Changing label size to width={width}, height={height}")
        self.width = width
        self.height = height

    def available_barcode_types(self):
        return barcode.PROVIDED_BARCODES

    def render_zpl(self,preview=False) -> str:

        l = zpl.Label(self.height, self.width)
        
        for e in self.elements:
            if isinstance(e, TextElement):
                l.origin(e.x, e.y)
                try:
                    l.write_text(e.text, 
                                char_height=e.char_height, 
                                char_width=e.char_width, 
                                line_width=e.line_width, 
                                justification=e.justification, 
                                font=e.font)
                except ValueError:
                    l.write_text(e.text, 
                                char_height=e.char_height, 
                                char_width=e.char_width, 
                                line_width=e.line_width, 
                                justification=e.justification, 
                                font='A')
                l.endorigin()
            elif isinstance(e, ImageElement):
                if e.justification == 'C':
                    x = (l.width - e.width) / 2 - e.x
                elif e.justification == 'R':
                    x = l.width - e.width - e.x
                else:
                    x = e.x
                l.origin(x, e.y)
                l.write_graphic(
                    e.image,
                    e.width)
                l.endorigin()
            elif isinstance(e, BarcodeElement):
                # '2A'  : Interleaved 2 of 5 Bar Code
                # '3'   : Code 39 Bar Code
                # 'U'   : UPC-A Bar Code
                # 'E'   : EAN-13 Bar Code
                # 'X'   : Data Matrix Bar Code
                # 'Q'   : QR Code
                # 'C'   : Code 128 Bar Code 
                l.origin(e.x, e.y)
                
                if e.barcode_type == 'ean13-guard':
                    zpl_barcode_type = 'E'
                elif e.barcode_type == 'upca':
                    zpl_barcode_type = 'U'
                elif e.barcode_type == 'code39':
                    zpl_barcode_type = '3'
                elif e.barcode_type == 'qr':
                    zpl_barcode_type = 'Q'
                elif e.barcode_type == 'datamatrix':
                    zpl_barcode_type = 'X'
                else:
                    zpl_barcode_type = 'C'
                l.barcode(
                    zpl_barcode_type,
                    e.data, 
                    height=e.height,
                    magnification=e.magnification,
                    check_digit='Y')
                l.endorigin()
        if preview:
            l.preview()
        return l.dumpZPL()
                   
    def render_image(self,dpi=150,framing=False,preview=False) -> Image: 
        mm_to_dpi_scale = dpi / 25.4  # Convert mm to inches for DPI scaling
        w = int(self.width * mm_to_dpi_scale)
        h = int(self.height * mm_to_dpi_scale)
        img = Image.new('RGB', [w, h], color='white')
        draw = ImageDraw.Draw(img)
        if framing:
            draw.rectangle([0,0,w-0.2*mm_to_dpi_scale,h-0.2*mm_to_dpi_scale],outline ="black")
        for e in self.elements:
            if isinstance(e, TextElement):
                try:
                    font = ImageFont.truetype(e.font, int(e.char_height*mm_to_dpi_scale))
                    log.info(f"Loaded font {e.font} for text '{e.text}'")
                except IOError:
                    font = ImageFont.load_default( size=int(e.char_height*mm_to_dpi_scale))
                    log.warning(f"Failed to load font {e.font} for text '{e.text}', using default font instead.")
                bbox = draw.textbbox((0, e.y*mm_to_dpi_scale), e.text, font=font)
                text_width = bbox[2] - bbox[0]
                if e.justification == 'C':
                    x = (img.width - text_width) / 2 - e.x
                elif e.justification == 'R':  
                    x = img.width - text_width - e.x
                else:
                    x = e.x
                draw.text((x, e.y*mm_to_dpi_scale), e.text, font=font, fill='black')
            elif isinstance(e, ImageElement):
                img.paste(e.image.resize((int(e.width*mm_to_dpi_scale), int(e.height*mm_to_dpi_scale))), (int(e.x*mm_to_dpi_scale), int(e.y*mm_to_dpi_scale)))
            elif isinstance(e, BarcodeElement):
                if e.barcode_type == 'qr' or e.barcode_type == 'datamatrix':
                    # For QR codes, we can use the qrcode library to generate the image
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=int(e.width*mm_to_dpi_scale),
                        border=0,
                    )
                    qr.add_data(e.data)
                    qr.make(fit=True)
                    qr_img = qr.make_image(fill_color="black", back_color="white").resize((int(e.height*mm_to_dpi_scale), int(e.height*mm_to_dpi_scale)))
                    img.paste(qr_img, (int(e.x*mm_to_dpi_scale), int(e.y*mm_to_dpi_scale)))
                # elif e.barcode_type == 'datamatrix':
                #     # For Data Matrix codes, we can use the datamatrix library to generate the image
                #     dm = DataMatrix(e.data)
                #     dm_img = dm.render().resize((int(e.height*mm_to_dpi_scale), int(e.height*mm_to_dpi_scale)))
                #     img.paste(dm_img, (int(e.x*mm_to_dpi_scale), int(e.y*mm_to_dpi_scale)))
                else:
                    rv = BytesIO()
                    writer = ImageWriter()
                    font_size = int(e.height * 0.5)
                    if font_size < 4:
                        font_size = 4
                    if font_size > 10:
                        font_size = 10
                    writer_options ={
                        'module_width': e.width if e.width > 0.2 else 0.2,
                        'module_height': e.height if e.height > 8 else 8,
                        'dpi': dpi,
                        'text_distance': font_size,
                        'font_size': font_size,
                    }

                    log.info(f"Generating barcode with options: {writer_options}")
                    bc_class = barcode.get_barcode_class(e.barcode_type)
                    log.info(f"Generating barcode of type '{e.barcode_type}' with data '{e.data}'")
                    bc = bc_class(str(e.data), writer=writer).write(rv, options=writer_options)
                    img.paste(Image.open(BytesIO(rv.getvalue())), (int(e.x*mm_to_dpi_scale), int(e.y*mm_to_dpi_scale)))
        if preview:
            img.show()
        return img
    
    @staticmethod
    def test_label(width=100, height=100) :
        label = StikkaLabel(width, height)
        log.info(f"Available barcode types: {label.available_barcode_types()}")
        label.add_text("Test Label", x=10, y=10, char_height=5, char_width=1.0, line_width=50, justification='C', font='fonts/knewave-outline.otf')
        label.add_barcode("12345678903432", x=10, y=20, barcode_type='ean13-guard', height=20, width=0.2, magnification=1)  
        label.add_barcode("979117892430", x=30, y=20, barcode_type='qr', height=20, width=0.4, magnification=3)
        #label.add_barcode("800304196942164842172605538560", x=10, y=40, barcode_type='datamatrix', height=20, width=0.1, magnification=1)
        return label
        

if __name__ == "__main__":
    l = StikkaLabel.test_label()
    l.render_image(preview=True)
    print(l.render_zpl(preview=True))