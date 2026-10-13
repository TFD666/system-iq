import sys
from pathlib import Path

# Add cli/ to the front of sys.path so that `from systemiq import load_input`
# resolves to cli/systemiq.py regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))
