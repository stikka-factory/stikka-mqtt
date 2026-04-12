Reimagination of [https://github.com/5shekel/printit](https://github.com/5shekel/printit) trying to takle some issues that popped up during 39c3

## Installation

### Install uv

It's python using [uv](https://docs.astral.sh/uv/getting-started/installation/), so you may need to install uv first.

With uv installed:

### Install stikka-NG

1. Clone the Repo
2. Copy **default_config.json** to **config.json**
3. Run `uv sync`

### Test run

1. Run `uv run main.py`
2. Check the **hostname:port** given in the logs, to see if it's runing

## Configuration

Go to **hostname:port\config** using the default password **stikka** to configure your installation

### App config

The app's general settings are in the first part of **config.json** and should be pretty straight forward. 

You might want to change `"config_pwd"`

#### Default config

```json
{
    "port": 8000,
    "host": "0.0.0.0",
    "fonts_dir": "fonts",
    "use_system_fonts": false,
    "config_pwd": "stikka",
    "name": "Stikka Factory",
    "subtitle": "Kleben und kleben lassen",
    "debug_level": "DEBUG",
    "dark_mode": true,
    "colours": {
        "primary": "#61e84a",
        "secondary": "#fc12ba",
        "brand": "#7e8ffb",
        "accent": "#B0C4DE",
        "dark_pages": "#fc12ba",
        "positive": "#32CD32",
        "negative": "#FF4500",
        "info": "#1E90FF",
        "warning": "#FFD700"
    },
    ...
}
```

### Printer config

The `"printers":`section is to configure the available printers. In the table below are the default values

| | **Description** | **Debug** | **Brother QL** | **Zebra ZPL** |
|:----------------- |:----------------|:-----------------|:---------------|:---------------|
| **"name"**        |Name for the printer to be shown in the UI, can be anything|  |   |  |
| **"serial"**  |Serial number of the printer, can be anything, and isn't used actually|   |   |  |
|**"type"**| The type of the printer | `"file"` |  `"brother_ql"` |  `"zpl"` |
|**"backend"** | Connection type, can be `"file"`,`"pyusb"`, `"network"`, only defaults are implemented for now| `"file"` | `"pyusb"` | `"network"` |
|**"connection"**|How to connect to the printer. | `"file://debug"` | `USB-ID/serial` <sup>1)</sup> |`IP:port` <sup>2)</sup> |
|**"dpi"** | DPI of the printer, typical values in the columns of the printer types |  | `300` | `203` |
|**"label"**| The parameters for the currently used label, `"cut"` isn´t yet implemented in Zebra printers | | | 


<sup>1)</sup>: Run `uv run brother_ql discover` to scan for connected printer, you should see something like `INFO:brother_ql:Probing device at usb://0x04f9:0x2044/000H6Z733099` (and maybe an error, but you can ignore that)

<sup>2)</sup>: Scan for something with the open ports 21,80,515,6101,9100 and 9200, on port 80 it should have a Zebra setup page

#### Default config

```json
{
    ...
    "printers": [
        {
            "name": "Debug Printer",
            "serial": "000J6Z777993",
            "connection": "file://debug",
            "type": "file",
            "backend": "file",
            "dpi": 150,
            "label": {
                "cut": true,
                "width": 80,
                "length": 80,
                "vertical_offset": 0
            }
        },
        {
            "name": "Brother QL-720NW",
            "serial": "000J6Z777993",
            "connection": "usb://0x04f9:0x2044/000J6Z777993",
            "type": "brother_ql",
            "backend": "pyusb",
            "dpi": 300,
            "label": {
                "cut": true,
                "width": 50,
                "length": 0,
                "vertical_offset": 0
            }
        },
        {
            "name": "Zebra ZD410",
            "serial": "50J195204102",
            "type": "zpl",
            "connection": "192.168.0.142:9100",
            "backend": "network",
            "dpi": 203,
            "label": {
                "cut": false,
                "length": 67,
                "width": 55,
                "vertical_offset": 3.5
            }
        }
    ]
}
```

