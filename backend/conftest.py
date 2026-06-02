import sys
from pathlib import Path

# Allow tests to import from scripts/ at the repository root
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
