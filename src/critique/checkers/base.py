from abc import ABC, abstractmethod
from typing import List, NamedTuple, Optional
from enum import Enum

class Severity(Enum):
    FATAL = "FATAL"     # Blocks push (Red)
    WARNING = "WARNING" # Allows push with confirmation (Yellow)
    INFO = "INFO"       # Just for info (Blue)

class Issue(NamedTuple):
    file_path: str
    line: int
    column: int
    message: str
    code: str  # Error code e.g. E501
    severity: Severity
    reasoning: Optional[str] = None

class BaseChecker(ABC):
    name: str = "Base"
    description: str = "Base Checker"
    
    @abstractmethod
    def run(self, files: List[str]) -> List[Issue]:
        """
        Run the checker on the given list of files.
        Return a list of Issues found.
        """
        pass
