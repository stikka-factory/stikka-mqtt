
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
                   
    def render_image(self) -> Image: 
        img = Image.new('RGB', (int(self.width * 3.78), int(self.height * 3.78)), color='white')
        draw = ImageDraw.Draw(img)
        for e in self.elements:
            if isinstance(e, TextElement):
                try:
                    font = ImageFont.truetype(e.font, int(e.char_height * 10))
                except IOError:
                    font = ImageFont.load_default()
                draw.text((e.x, e.y), e.text, font=font, fill='black')
            elif isinstance(e, ImageElement):
                img.paste(e.image.resize((e.width, e.height)), (e.x, e.y))
            elif isinstance(e, BarcodeElement):
                # Barcode rendering can be complex; this is a placeholder
                draw.rectangle([e.x, e.y, e.x + e.width * e.magnification, e.y + e.height], outline='black')
        return img


if __name__ == "__main__":
    # Create a label of size 100mm x 60mm
    label = StikkaLabel(100, 60)

    # Add text to the label
    label.add_text("Hello, World!", x=0, y=10, char_height=1.5, char_width=1.0, line_width=50, justification='L', font='arial.ttf')
    label.add_text("Centered Text", x=0, y=10, char_height=1.5, char_width=1.0, line_width=50, justification='C', font='B')
    label.add_text("Right Aligned", x=0, y=10, char_height=1.5, char_width=1.0, line_width=50, justification='R', font='C')
    label.add_barcode("1234567890", x=10, y=40, barcode_type='U', height=30, width=2, justification='L', magnification=2, check_digit='Y')  
    label.add_barcode("1234567890", x=30, y=40, barcode_type='Q', height=30, width=2, justification='L', magnification=4, check_digit='Y')  

    # Generate ZPL code
    print(label.render_zpl(preview=True))

    rendered_image = label.render_image()
    rendered_image.show()