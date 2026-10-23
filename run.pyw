"""映录启动器（无控制台窗口）。"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from yinglu.ui.app import App  # noqa: E402


def main() -> None:
    app = App()
    app.root.mainloop()


if __name__ == "__main__":
    main()
