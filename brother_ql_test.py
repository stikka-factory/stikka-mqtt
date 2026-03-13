from label import StikkaLabel
from printer_ql import BrotherPrintJob, find_brother_ql
import time


printers = find_brother_ql("pyusb")
time.sleep(2)


    for serial, printer in printers.items():
        label = StikkaLabel(50, 20)
        label.add_text("Hello, World!", x=0, y=10, char_height=4, char_width=4, line_width=50, justification='L', font='arial.ttf')
        label.add_text("Hello, World!", x=10, y=30, char_height=10, char_width=4, line_width=50, justification='C', font='arial.ttf')
        printer.print_image(label.render_image())