import sys
from pathlib import Path

# Add eval/seeded/ to sys.path so `import make_variants` etc. resolve,
# regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))
