import sys

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        from tracker.sync.agent import main as sync_main
        return sync_main()
    else:
        from tracker.main import main as tracker_main
        return tracker_main()

if __name__ == "__main__":
    sys.exit(main())
