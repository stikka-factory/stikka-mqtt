#!/usr/bin/env python

from label import StikkaLabel
from printer_ql import BrotherPrintJob, BrotherPrinter
import time


printers = BrotherPrinter.find("pyusb")
time.sleep(2)

for serial, printer in printers.items():
    for i in range(1):
        label = StikkaLabel(printer.status.media_width, 15)
        label.add_text("L x0,y0,h3", x=0, y=0, char_height=3, char_width=1.0, line_width=printer.status.media_width, justification='L', font='/usr/share/fonts/TTF/HeavyDataNerdFontPropo-Regular.ttf') 
        label.add_text("C x0,y7,h3", x=0, y=7, char_height=3, char_width=1.0, line_width=printer.status.media_width, justification='C', font='/usr/share/fonts/OTF/OpenDyslexicNerdFontPropo-Regular.otf') 
        label.add_text("R x0,y1,h5", x=0, y=1, char_height=5, char_width=0.5, line_width=printer.status.media_width, justification='R', font='/usr/share/fonts/Adwaita/AdwaitaMono-Bold.ttf') 

        l = label.render_image(framing=True)
        print_job= BrotherPrintJob(l)
        printer.add_to_queue(print_job)
    printer.handle_queue()