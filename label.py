
from PIL import Image, ImageDraw, ImageFont
import barcode
import qrcode
import zpl

from dataclasses import asdict, dataclass
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
    font: str = 'A'

    def __repr__(self):
        return f'''\n[yellow]TextElement:[/yellow ]
\ttext:\t{self.text}
\tx:\t{self.x}
\ty:\t{self.y}
'''

@dataclass
class ImageElement:
    image: Image
    x: int
    y: int
    width: int = None
    height: int = None

    def __repr__(self):
        return f'''\n[yellow]ImageElement:[/yellow ]
\tx:\t{self.x}
\ty:\t{self.y}
\twidth:\t{self.width}
\theight:\t{self.height}
'''

@dataclass
class Code128Element:
    data: str
    x: int
    y: int
    orientation: str = 'N'
    height: int = 10
    print_text: str = 'Y'
    text_above: str = 'N'
    check_digit: str = 'Y'
    mode: str = 'N'

    def __repr__(self):
        return f'''\n[yellow]Code128Element:[/yellow ]
\tdata:\t{self.data}
\tx:\t{self.x}
\ty:\t{self.y}'''
        


@dataclass
class QRCodeElement:
    data: str
    x: int
    y: int
    model: int = 2
    magnification: int = 1
    error_correction: str = 'Q'
    mask_value: int = 7

    def __repr__(self):
        return f'''\n[yellow]QRCodeElement:[/yellow ]
\tdata:\t{self.data}
\tx:\t{self.x}
\ty:\t{self.y}'''

class StikkaLabel:
    def __init__(self, width, height, dpi=300):
        self.width = width
        self.height = height
        self.dpi = dpi
        self.height_pos = 0
        self.elements = []

    def __repr__(self):
        return f'''\n[yellow ]StikkaLabel:[/yellow ]
\twidth:\t{self.width}
\theight:\t{self.height}
	dpi:\t{self.dpi}
\telements:\t{[e for e in self.elements]}'''

    def add_text(self, text, x, y, char_height=1.0, char_width=1.0, line_width=None, font='A'):
        log.debug(
            f"Adding text element: '{text}' at ({x}, {y}) with char_height={char_height}, char_width={char_width}, line_width={line_width}, font='{font}'")
        self.elements.append(TextElement(
            text, x, y, char_height, char_width, line_width, font))

    def add_image(self, image: Image, x, y, width=None, height=None):
        log.debug(
            f"Adding image element at ({x}, {y}) with width={width}, height={height}")
        self.elements.append(ImageElement(
            image, x, y, width, height))

    def add_code_128(self, data, x, y, orientation='N', height=10, print_text='Y', text_above='N', check_digit='Y', mode="N"):
        '''
        adds a code 128 BC
        o	Orientation	                            N, R, I, B	        N
        h	Bar code height	From                    1 to 32000 dots	
        f	Print interpretation line	            Y, N	            Y
        g	Print interpretation line above code	Y, N	            N
        e	UCC check digit	                        Y, N	            N
        m	Mode	                                N, U, A, D	        N

        '''
        log.debug(
            f"Adding barcode element with data '{data}' at ({x}, {y}) with height={height}, print_text='{print_text}', text_above='{text_above}', check_digit='{check_digit}', mode='{mode}'")
        self.elements.append(Code128Element(data, x, y, orientation, height,
                             print_text, text_above, check_digit, mode))

    def add_qrcode(self, data, x, y, model=2, magnification=1, error_correction='Q', mask_value=7) :
        '''
        adds a QR code
        a	Orientation	            N	            N
        b	Model	                1, 2	        2
        c	Magnification factor	1 to 10         (1 on 150 dpi printers - 2 on 200 dpi printers - 3 on 300 dpi printers - 6 on 600 dpi printers).	1
        d	Error correction	    H, Q, M, L	    Q
        e	Mask value	            0 to 7.	        7
        '''
        log.debug(
            f"Adding QR code element with data '{data}' at ({x}, {y}) with model={model}, magnification={magnification}, error_correction='{error_correction}', mask_value={mask_value}")
        self.elements.append(QRCodeElement(
            data, x, y, model, magnification, error_correction, mask_value))

    def change_label_size(self, width, height, scale_elements=True, keep_aspect=False):
        """Resize the label canvas.

        When scale_elements=True, existing element positions and relevant sizing
        attributes are scaled to fit the new label size.
        """
        if width <= 0 or height <= 0:
            raise ValueError("Label width and height must be positive")

        old_width = self.width
        old_height = self.height
        if old_width <= 0 or old_height <= 0:
            raise ValueError("Current label width and height must be positive")

        scale_x = width / old_width
        scale_y = height / old_height
        if keep_aspect:
            uniform_scale = min(scale_x, scale_y)
            scale_x = uniform_scale
            scale_y = uniform_scale

        log.info(
            f"Changing label size from ({old_width}, {old_height}) to ({width}, {height}) "
            f"with scale_elements={scale_elements}, keep_aspect={keep_aspect}"
        )

        if scale_elements:
            for e in self.elements:
                e.x = int(round(e.x * scale_x))
                e.y = int(round(e.y * scale_y))

                if isinstance(e, TextElement):
                    e.char_height = max(0.1, e.char_height * scale_y)
                    e.char_width = max(0.1, e.char_width * scale_x)
                    if e.line_width is not None:
                        e.line_width = max(1, int(round(e.line_width * scale_x)))

                elif isinstance(e, ImageElement):
                    if e.width is not None:
                        e.width = max(1, int(round(e.width * scale_x)))
                    if e.height is not None:
                        e.height = max(1, int(round(e.height * scale_y)))

                elif isinstance(e, Code128Element):
                    e.height = max(1, int(round(e.height * scale_y)))

                elif isinstance(e, QRCodeElement):
                    scaled_mag = int(round(e.magnification * min(scale_x, scale_y)))
                    e.magnification = min(10, max(1, scaled_mag))

        self.width = width
        self.height = height

    def render_zpl(
        self,
        preview=False,
        bitmap_font=False,
        save_preview=False,
        vertical_center=True,
        vertical_offset=0,
    ) -> str:
        # The zpl library computes ^GFA metadata from dpmm arithmetic and is most
        # reliable with integer printer-native resolutions (e.g. 8, 12, 24 dpmm).
        dpmm = max(1, int(round(self.dpi / 25.4)))
        l = zpl.Label(
            int(round(self.height)),
            int(round(self.width)),
            dpmm=dpmm,
        )
        center_offset = 0
        if vertical_center:
            total_elements_height = 0
            for e in self.elements:
                if isinstance(e, TextElement):
                    total_elements_height = max(total_elements_height, e.y + e.char_height)
                elif isinstance(e, ImageElement):
                    total_elements_height = max(total_elements_height, e.y + (e.height if e.height else 0))
                    log.info(f"Image element at y={e.y} with height={e.height}, contributing to total_elements_height={total_elements_height}") 
                elif isinstance(e, Code128Element):
                    total_elements_height = max(total_elements_height, e.y + e.height)
                elif isinstance(e, QRCodeElement):
                    qr_size = 21 + (e.model - 1) * 4
                    qr_pixel_size = qr_size * e.magnification
                    total_elements_height = max(total_elements_height, e.y + qr_pixel_size)

            center_offset = max(0, (self.height - total_elements_height) / 2)
            log.info(f"Calculated vertical offset for centering: {center_offset} mm")

        total_vertical_offset = center_offset + float(vertical_offset)
        if vertical_offset:
            log.info(f"Applying configured vertical offset: {vertical_offset} mm")

        for e in self.elements:
            draw_y = e.y + total_vertical_offset
            if isinstance(e, TextElement):
                l.origin(int(round(e.x)), int(round(draw_y)))
                if bitmap_font:
                    # zpl.write_graphic width is in millimeters in this library.
                    text_width = max(1, int(round(e.char_height)))
                    l.write_graphic(self._text2img(e, mm_to_dpi_scale=self.dpi/25.4), text_width)
                else:
                    try:
                        l.write_text(e.text,
                                     char_height=e.char_height,
                                     char_width=e.char_width,
                                     line_width=e.line_width,
                                     font=e.font)
                    except ValueError:
                        l.write_text(e.text,
                                     char_height=e.char_height,
                                     char_width=e.char_width,
                                     line_width=e.line_width,
                                     font='A')
                l.endorigin()
            elif isinstance(e, ImageElement):
                l.origin(int(round(e.x)), int(round(draw_y)))
                image_width = e.width if e.width is not None else self.width
                l.write_graphic(
                    e.image,
                    max(1, int(round(image_width))))
                l.endorigin()
            elif isinstance(e, Code128Element):
                l.origin(int(round(e.x)), int(round(draw_y)))
                l.barcode(
                    barcode_type='C',
                    code=e.data,
                    height=max(1, int(round(e.height * self.dpi / 25.4))),
                    orientation=e.orientation,
                    check_digit=e.check_digit,
                    print_interpretation_line=e.print_text,
                    print_interpretation_line_above=e.text_above,
                    mode=e.mode,
                )
                l.endorigin()
            elif isinstance(e, QRCodeElement):
                l.origin(int(round(e.x)), int(round(draw_y)))
                l.barcode(
                    barcode_type='Q',
                    code=e.data,
                    magnification=e.magnification,
                    errorCorrection=e.error_correction,
                )
                l.endorigin()
        if preview:
            if save_preview: 
                l.preview(outputfile="preview.png")
            else:
                l.preview()
        return l.dumpZPL()

    def _text2img(self, e:TextElement, mm_to_dpi_scale) -> Image:
        # Create a temporary image to calculate text size
        temp_img = Image.new('RGB', (1, 1))
        draw = ImageDraw.Draw(temp_img)
        try:
            font = ImageFont.truetype(
                e.font, int(e.char_height*mm_to_dpi_scale * 2))
            log.debug(f"Loaded font {e.font} for text '{e.text}'")
        except IOError:
            font = ImageFont.load_default(
                size=int(e.char_height*mm_to_dpi_scale * 2))
            log.warning(
                f"Failed to load font {e.font} for text '{e.text}', using default font instead.")
        # Text image should be local to its own origin, not offset by label y.
        bbox = draw.textbbox(
            (0, 0), e.text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Create an image with the calculated size
        img = Image.new('RGB', (round(text_width), round(text_height)), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), e.text, font=font, fill='black')
        return img

    def render_image(self, framing=False, preview=False) -> Image:
        mm_to_dpi_scale = self.dpi / 25.4  # Convert mm to inches for DPI scaling
        w = int(self.width * mm_to_dpi_scale)
        h = int(self.height * mm_to_dpi_scale)
        img = Image.new('RGB', [w, h], color='white')
        draw = ImageDraw.Draw(img)
        if framing:
            draw.rectangle([0, 0, w-0.2*mm_to_dpi_scale, h -
                           0.2*mm_to_dpi_scale], outline="black")
        for e in self.elements:
            if isinstance(e, TextElement):
                img_text = self._text2img(e, mm_to_dpi_scale)

                img.paste(img_text.resize((int(img_text.width * 0.5), int(img_text.height * 0.5))), (int(e.x*mm_to_dpi_scale ), int(e.y*mm_to_dpi_scale)))

            elif isinstance(e, ImageElement):
                img.paste(e.image.resize((int(e.width*mm_to_dpi_scale), int(e.height *
                          mm_to_dpi_scale))), (int(e.x*mm_to_dpi_scale), int(e.y*mm_to_dpi_scale)))

            elif isinstance(e, Code128Element):
                barcode_img = barcode.get('code128', 
                                          e.data, 
                                          writer=ImageWriter()).render(
                                              writer_options={
                                                  'module_height': e.height * mm_to_dpi_scale,
                                                  'module_width': 0.5 * mm_to_dpi_scale,
                                                  'quiet_zone': 3,
                                                  'font_size': 0 if e.print_text == 'N' else int(e.height * mm_to_dpi_scale)})
                scale = barcode_img.height/( mm_to_dpi_scale * e.height)
                log.info(f"Generated barcode image for data '{e.data}' with original size {barcode_img.size}, scaling down by factor {scale} to fit height {e.height}")
                barcode_img = barcode_img.resize((int(barcode_img.width / scale), int(barcode_img.height / scale)))

                if e.orientation == 'R':
                    barcode_img = barcode_img.rotate(270, expand=True)
                elif e.orientation == 'I':
                    barcode_img = barcode_img.rotate(180, expand=True)
                elif e.orientation == 'B':
                    barcode_img = barcode_img.rotate(90, expand=True)

                img.paste(barcode_img, (int(e.x*mm_to_dpi_scale), int(e.y*mm_to_dpi_scale)))

            # elif isinstance(e, QRCodeElement):

        if preview:
            img.show()
        return img
    
    @staticmethod
    def address_label(width=100, height=None,name="John Doe",street="123 Main St",city="Anytown", country="USA", zip_code="12345",font='fonts/Orbitron Black.otf',text_height=5, dpi=300):
        if height is None:
            # top_padding + 4 lines + 3 gaps + bottom_padding
            height = text_height + (4 * text_height) + (3 * 2) + text_height
        label = StikkaLabel(width, height, dpi=dpi)
        label.add_text(name, x=10, y=text_height, char_height=text_height, char_width=1.0, line_width=80, font=font)
        label.add_text(street, x=10, y=2*text_height+2, char_height=text_height, char_width=1.0, line_width=80, font=font)
        label.add_text(f"{zip_code} {city}", x=10, y=3*text_height+4, char_height=text_height, char_width=1.0, line_width=80, font=font)
        label.add_text(country, x=10, y=4*text_height+6, char_height=text_height, char_width=1.0, line_width=80, font=font)
        return label

    @staticmethod
    def test_label(width=100, height=100, dpi=300):
        label = StikkaLabel(width, height, dpi=dpi)
        label.add_text("Test Label", x=10, y=10, char_height=5, char_width=1.0,
                       line_width=50,font='fonts/knewave-outline.otf')
        label.add_code_128("Tillo", x=10, y=30, height=10, orientation='R',
                           print_text='Y', text_above='N', check_digit='N', mode='N')
        label.add_qrcode("https://www.stikka.io", x=10, y=60, model=2,
                         magnification=4, error_correction='Q', mask_value=7)
        return label


if __name__ == "__main__":
    # l = StikkaLabel.test_label()
    # l.render_image(preview=True)
    # print(l.render_zpl(preview=True))
    label = StikkaLabel.address_label(name="Jane Smith", street="456 Elm St", city="Othertown", country="Canada", zip_code="67890", font='fonts/Orbitron Black.otf', text_height=6)
    label.render_image(preview=True)
    print(label.render_zpl(preview=True, bitmap_font=True, save_preview=True))
