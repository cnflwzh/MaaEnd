"""Private browser component launched only by the MaaEnd main application."""

import sys


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "--mxu-host":
        print("This is an internal MaaEnd component. Start MaaEnd.exe.", file=sys.stderr)
        return 2
    from mxu_host import main as run_host
    return run_host(sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
