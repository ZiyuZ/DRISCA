"""模拟器子进程入口。"""

import argparse
from pathlib import Path

from drisca.core.config import load_run_config
from drisca.simulator.app import SimulatorApp


def main() -> None:
    parser = argparse.ArgumentParser(description='DRISCA 驾驶模拟器')
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    SimulatorApp(load_run_config(args.config)).run()


if __name__ == '__main__':
    main()
