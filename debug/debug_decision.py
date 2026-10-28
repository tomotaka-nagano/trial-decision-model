import json
from pathlib import Path

from exmgai import Client
from typesafe_sdk import Noul

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    print('Connecting to Decision-1 using env.toml (this request may incur charges)...', flush=True)
    client = Client('decision', env=ROOT / 'env.toml')
    response = client.decision.system_one(
        state='2 is an even number.',
        questions={'approve': Noul(instructions='Is this statement correct?')},
    )
    print('Connection successful.')
    print(json.dumps(response.model_dump(mode='json'), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
