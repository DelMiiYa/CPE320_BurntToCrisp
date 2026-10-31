"""Start the private local Agent Office."""
import argparse
from pathlib import Path
import uvicorn
from dotenv import load_dotenv
from .server import create_app


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Burnt Studio · Local Agent Office')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--workspace', type=Path, default=Path('workspace/office'))
    parser.add_argument('--max-rounds', type=int, default=3)
    args = parser.parse_args()
    if args.max_rounds < 1:
        parser.error('--max-rounds must be at least 1')
    print(f'\n  Burnt Studio · Agent Office\n  http://127.0.0.1:{args.port}\n  Project history: {args.workspace.resolve()}\n', flush=True)
    uvicorn.run(create_app(args.workspace, max_rounds=args.max_rounds), host='127.0.0.1', port=args.port,
                log_level='info', timeout_graceful_shutdown=5)


if __name__ == '__main__':
    main()
