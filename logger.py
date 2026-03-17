import logging
import PIL
from rich.highlighter import JSONHighlighter, NullHighlighter, RegexHighlighter
from rich.logging import RichHandler
from rich import print
from PIL import PngImagePlugin

FORMAT = "%(message)s"
logging.basicConfig(
    level="INFO", 
    format=FORMAT, 
    datefmt="[%X]",
    handlers=[
        RichHandler(
            rich_tracebacks=True, 
            tracebacks_suppress=[PIL],
            markup=True,
            highlighter=NullHighlighter()
        )    
    ]
)


log = logging.getLogger("rich")