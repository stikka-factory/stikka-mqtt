import logging
import PIL
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler

FORMAT = "%(message)s"
logging.basicConfig(
    level="DEBUG", 
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