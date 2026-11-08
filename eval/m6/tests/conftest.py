import sys
from pathlib import Path

# Add eval/m6/ to sys.path so `import run_eval` etc. resolve, regardless
# of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))
