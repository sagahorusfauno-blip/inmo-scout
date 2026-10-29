"""Punto de entrada de InmoScout."""
import logging
import sys

from PySide6.QtWidgets import QApplication

from app.config import Settings, data_dir
from app.db import Database
from app.ui.main_window import MainWindow


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(data_dir() / "inmoscout.log", encoding="utf-8"),
                  logging.StreamHandler()],
    )
    app = QApplication(sys.argv)
    app.setApplicationName("InmoScout")
    app.setQuitOnLastWindowClosed(False)   # sigue en la bandeja del sistema
    settings = Settings.load()
    db = Database(data_dir() / "inmoscout.db")
    win = MainWindow(db, settings)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
