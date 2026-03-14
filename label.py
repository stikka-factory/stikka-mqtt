
from PIL import Image, ImageDraw, ImageFont
import zpl
from dataclasses import dataclass  


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
    justification: str = 'L'
    magnification: int = 1
    check_digit: str = 'Y'

class StikkaLabel:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.height_pos = 0
        self.elements = []

    def add_text(self, text, x, y, char_height=1.0, char_width=1.0, line_width=None, justification='L', font='A'):
        self.elements.append(TextElement(text, x, y, char_height, char_width, line_width, justification, font))
        
    def add_image(self, image: Image, x, y, width=None, height=None,justification='C'):
        self.elements.append(ImageElement(image, x, y, width, height, justification))
        
    def add_barcode(self, data, x, y, barcode_type='U', height=10, width=1, justification='L',magnification=1,check_digit='Y'):
        self.elements.append(BarcodeElement(data, x, y, barcode_type, height, width, justification, magnification, check_digit))
    
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
                if e.justification == 'C':
                    x = (l.width - e.width * e.magnification) / 2 - e.x
                elif e.justification == 'R':
                    x = l.width - e.width * e.magnification - e.x
                else:
                    x = e.x
                l.origin(x, e.y)
                l.barcode(
                    e.barcode_type,
                    e.data,
                    height=e.height,
                    magnification=e.magnification,
                    check_digit=e.check_digit)
                l.endorigin()
        if preview:
            l.preview()
        return l.dumpZPL()
                   
    def render_image(self,dpi=150,framing=False) -> Image: 
        mm_to_dpi_scale = dpi / 25.4  # Convert mm to inches for DPI scaling
        w = int(self.width * mm_to_dpi_scale)
        h = int(self.height * mm_to_dpi_scale)
        img = Image.new('RGB', [w, h], color='white')
        draw = ImageDraw.Draw(img)
        if framing:
            draw.rectangle([0,0,w-0.2*mm_to_dpi_scale,h-0.2*mm_to_dpi_scale],outline ="black")
        for e in self.elements:
            if isinstance(e, TextElement):
                print(e.font)
                try:
                    font = ImageFont.truetype(e.font, int(e.char_height*mm_to_dpi_scale))
                    print("Font found")
                except IOError:
                    font = ImageFont.load_default( size=int(e.char_height*mm_to_dpi_scale))

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
                # Barcode rendering can be complex; this is a placeholder
                draw.rectangle([e.x*mm_to_dpi_scale, e.y*mm_to_dpi_scale, e.x*mm_to_dpi_scale + e.width * e.magnification*mm_to_dpi_scale, e.y*mm_to_dpi_scale + e.height*mm_to_dpi_scale], outline='black')
        return img


if __name__ == "__main__":
    # Create a label of size 100mm x 60mm
    label = StikkaLabel(100, 60)

    # Add text to the label
    label.add_text("Hello, World!", x=0, y=10, char_height=1.5, char_width=1.0, line_width=50, justification='L', font='/usr/share/fonts/TTF/HeavyDataNerdFontPropo-Regular.ttf') 
    label.add_text("Centered Text", x=0, y=10, char_height=1.5, char_width=1.0, line_width=50, justification='C', font='B')
    label.add_text("Right Aligned", x=0, y=10, char_height=1.5, char_width=1.0, line_width=50, justification='R', font='C')
    label.add_barcode("1234567890", x=10, y=40, barcode_type='U', height=30, width=2, justification='L', magnification=2, check_digit='Y')  
    label.add_barcode("1234567890", x=30, y=40, barcode_type='Q', height=30, width=2, justification='L', magnification=4, check_digit='Y')  

    # Generate ZPL code
    # print(label.render_zpl(preview=True))

    rendered_image = label.render_image()
    rendered_image.show()