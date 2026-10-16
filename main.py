import sys

if __name__ == "__main__":
    if "--backup" in sys.argv:
        # Headless mode for Task Scheduler on the database PC: no GUI.
        from backup.backup_job import main as backup_main

        sys.exit(backup_main([a for a in sys.argv[1:] if a != "--backup"]))

    from gui.app import run

    sys.exit(run())