#!/usr/bin/env python

from label import StikkaLabel
from printer_ql import BrotherPrintJob, find_brother_ql
import time


printers = find_brother_ql("pyusb")
time.sleep(2)


# for serial, printer in printers.items():
#     for i in range(5):
#         label = StikkaLabel(50, 10)
#         label.add_text(f"Hello, World! {i}", x=0, y=10, char_height=4, char_width=4, line_width=50, justification='L', font='arial.ttf')
#         l = label.render_image()
#         print_job= BrotherPrintJob(l)
#         printer.add_to_queue(print_job)
#     printer.handle_queue()