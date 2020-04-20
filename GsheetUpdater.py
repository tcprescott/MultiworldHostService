import argparse
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
gsheet_api_oauth = json.loads(os.environ('GSHEET_API_OAUTH'))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("token")
    parser.add_argument("gsheet")

    args = parser.parse_args()


