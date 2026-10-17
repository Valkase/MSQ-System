import sys

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--setup" in args:
        from setup_tool import main as setup_main  # installer helper, no GUI

        sys.exit(setup_main([a for a in args if a != "--setup"]))
    if "--mark-drive" in args:
        from gui.drive_tool import run as mark_drive

        sys.exit(mark_drive())
    if "--backup" in args:
        # Headless mode for Task Scheduler: no GUI.
        from backup.backup_job import main as backup_main

        sys.exit(backup_main([a for a in args if a != "--backup"]))

    from gui.app import run

    sys.exit(run())