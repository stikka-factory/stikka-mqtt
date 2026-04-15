import os
import binascii
import socket
import zlib
import base64
from typing import Optional

def font_to_zpl(dir_path: str, font_name: str) -> str:
    """
    Convert a font file to a ZPL command string with Z64 encoding.
    
    Args:
        dir_path (str): Directory path where the font file is located
        font_name (str): Name of the font file (e.g., 'comic.ttf')
    
    Returns:
        str: ZPL command string containing the font data
    """
    # Construct the full file path
    file_path = os.path.join(dir_path, font_name)
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Font file '{font_name}' not found in '{dir_path}'")

    with open(file_path, 'rb') as file:
        font_bytes = file.read()
    
    # Compress the data using zlib's DEFLATE (LZ77) algorithm
    compressed_data = zlib.compress(font_bytes)

    # Encode the compressed data in Base64
    base64_encoded_data = base64.b64encode(compressed_data).decode('utf-8')

    # Calculate CRC32 of the Base64-encoded data
    crc_value = zlib.crc32(base64_encoded_data.encode('utf-8')) & 0xFFFF
    crc_hex = f"{crc_value:04X}".lower()  # Format as 4 lowercase hex digits

    # Create the Z64-encoded font data string with CRC
    encoded_data_with_crc = f":Z64:{base64_encoded_data}:{crc_hex}"

    # Get the original font size (in bytes) for the `~DY` command
    original_size = len(font_bytes)

    # Construct the ZPL command to send to the printer
    zpl = (
        f"^XA\n"
        f"~DUR:{font_name.upper()},{original_size},{encoded_data_with_crc}\n"
        f"^FB300,1,,C,"
        f"^CW1,R:{font_name.upper()}\n"
        f"^FO0,20"
        f"^A@N,40,,R:{font_name.upper()}\n"
        f"^FDThis is {font_name}!^FS\n"
        f"^XZ"
    )
    
    return zpl

def send_to_device(host: str, port: int, data: str, timeout: Optional[float] = 5.0) -> bool:
    """
    Send data to a device over TCP.
    
    Args:
        host (str): The IP address or hostname of the device
        port (int): The port number (typically 9100 for printers)
        data (str): The data to send
        timeout (float, optional): Socket timeout in seconds. Defaults to 5.0
    
    Returns:
        bool: True if successful, False if failed
    """
    try:
        # Create a TCP socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # Set timeout
            sock.settimeout(timeout)
            
            # Connect to the device
            sock.connect((host, port))
            
            # Send the data
            sock.sendall(data.encode('utf-8'))
            
            return True
            
    except socket.timeout:
        print(f"Error: Connection to {host}:{port} timed out")
        return False
    except ConnectionRefusedError:
        print(f"Error: Connection to {host}:{port} was refused")
        return False
    except Exception as e:
        print(f"Error sending data to {host}:{port}: {str(e)}")
        return False

def main():
    # Configuration
    dir_path = r"fonts/"  # Replace with your directory path
    font_name = "TurboType.ttf"
    device_ip = "192.168.0.142"  # Replace with your device's IP address
    device_port = 9100
    
    try:
        # Generate ZPL command
        zpl_command = font_to_zpl(dir_path, font_name)
        
        # Print the command (for debugging)
        print("Generated ZPL command:")
        print(zpl_command)
        
        print("\nSending to device...")
        # Send to device
        if send_to_device(device_ip, device_port, zpl_command):
            print(f"Successfully sent to {device_ip}:{device_port}")
        else:
            print("Failed to send data to device")
            
    except FileNotFoundError as e:
        print(e)
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main()