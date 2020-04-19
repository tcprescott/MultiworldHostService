#!env/bin/python

import argparse
import requests
import json

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest='command')

    parser_update = subparsers.add_parser('update')

    parser_update.add_argument("token", help="server token")
    parser_update.add_argument("parameter", help="parameter to update")
    parser_update.add_argument("value", help="value to set")

    args = parser.parse_args()
    
    if args.value == 'true':
        value = True
    elif args.value == 'false':
        value = False

    try:
        value = int(args.value)
    except ValueError:
        pass

    if args.command == 'update':
        resp = requests.put(
            url=f'http://localhost:5000/game/{args.token}/{args.parameter}',
            json={
                'value': value
            }
        )

        print(resp.json())