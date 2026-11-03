"""Entry point for the packaged desktop app (Augur.exe / Augur.app)."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from augur.desktop import run
    run()
