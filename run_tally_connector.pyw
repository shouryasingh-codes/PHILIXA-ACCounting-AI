import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from helper.connect import Connect

if __name__ == "__main__":
    c = Connect()
    c.root.mainloop()
