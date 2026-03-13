from zpl import Label

# Create a label of size 100mm x 60mm
label = Label(100, 60)

# Add text to the label
for i,font in enumerate(['0', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']):
    label.origin(0,2+i*2)
    label.write_text(f"Font {font}\n", 
                     char_height=1.4, char_width=1, 
                     line_width=60, justification='C', 
                     font=font)
    label.endorigin()

# Generate ZPL code
print(label.dumpZPL())

# Preview the label (requires Pillow)
label.preview()

