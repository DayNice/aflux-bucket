from pathlib import Path
from typing import Annotated

from cyclopts import Parameter, validators

InputFile = Annotated[
    Path,
    Parameter(validator=validators.Path(exists=True, dir_okay=False)),
]

OutputFile = Annotated[
    Path,
    Parameter(validator=validators.Path(dir_okay=False)),
]
