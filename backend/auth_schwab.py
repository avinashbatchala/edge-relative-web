"""Run once in an interactive terminal to authorize Schwab; repeat on refresh expiry."""
import os
from pathlib import Path
from dotenv import load_dotenv
from schwabdev import Client

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
os.chdir(root)
path = Path(os.getenv("SCHWAB_TOKENS_DB", "data/schwab/tokens.db")).expanduser()
path.parent.mkdir(parents=True, exist_ok=True)
if __name__ == "__main__":
    client = Client(os.environ["SCHWAB_APP_KEY"], os.environ["SCHWAB_APP_SECRET"],
        os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1"), tokens_db=str(path))
    if not client.tokens.access_token:
        client.close()
        raise SystemExit("Authorization did not complete. Run this command again.")
    client.close()
    print("Schwab authorization saved. Restart the backend.")
