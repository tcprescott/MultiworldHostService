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

    parser_close = subparsers.add_parser('close')
    parser_close.add_argument("token")

    parser_msg = subparsers.add_parser('msg')
    parser_msg.add_argument("token")
    parser_msg.add_argument("msg")

    args = parser.parse_args()
    
    if args.command == 'update':
        if args.value == 'true':
            value = True
        elif args.value == 'false':
            value = False

        try:
            value = int(args.value)
        except ValueError:
            pass
        resp = requests.put(
            url=f'http://localhost:5000/game/{args.token}/{args.parameter}',
            json={
                'value': value
            }
        )
    elif args.command == 'close':
        resp = requests.delete(
            url=f'http://localhost:5000/game/{args.token}'
        )
    elif args.command == 'msg':
        resp = requests.put(
            url=f'http://localhost:5000/game/{args.token}/msg',
            json={
                'msg': args.msg
            }
        )

    print(resp.json())
