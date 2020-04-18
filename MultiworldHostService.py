import argparse
import asyncio
import datetime
import functools
import json
import logging
import random
import socket
import string
import zlib
import aiohttp

import aiofiles
import websockets
from quart import Quart, abort, jsonify, request

import Items
import MultiClient
import MultiServer

# from config import Config as c

APP = Quart(__name__)

MULTIWORLDS = {}

@APP.route('/game', methods=['POST'])
async def create_game():
    global MULTIWORLDS

    data = await request.get_json()
    
    if not 'multidata_url' in data and not 'token' in data:
        abort(400, description=f'Missing multidata_url or token in data')

    port = int(data.get('port', random.randint(30000, 35000)))

    if port < 30000 or port > 35000:
        abort(400, description=f'Port {port} is out of bounds.')
    if is_port_in_use(port):
        abort(400, description=f'Port {port} is in use!')

    if 'token' in data:
        token = data['token']
        if token in MULTIWORLDS:
            abort(400, description=f'Game with token {token} already exists.')

        async with aiofiles.open(f"data/{token}_multidata", "rb") as multidata_file:
            binary = await multidata_file.read()
    else:
        token = random_string(6)

        async with aiohttp.request(method='get', url=data['multidata_url'], headers={'User-Agent': 'SahasrahBot Multiworld Service'}) as resp:
            binary = await resp.read()

        async with aiofiles.open(f"data/{token}_multidata", "wb") as multidata_file:
            await multidata_file.write(binary)

    multidata = json.loads(zlib.decompress(binary).decode("utf-8"))

    ctx = await create_multiserver(port, f"data/{token}_multidata", racemode=data.get('racemode', False))

    MULTIWORLDS[token] = {
        'token': token,
        'server': ctx,
        'port': port,
        'admin': data.get('admin', None),
        'date': datetime.datetime.now(),
        'meta': data.get('meta', None),
        'players': multidata['names'],
    }
    response = APP.response_class(
        response=json.dumps(MULTIWORLDS[token], default=multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response

@APP.route('/game', methods=['GET'])
async def get_all_games():
    global MULTIWORLDS
    response = APP.response_class(
        response=json.dumps(
            {
                'count': len(MULTIWORLDS),
                'games': MULTIWORLDS
            },
            default=multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response

@APP.route('/game/<string:token>', methods=['GET'])
async def get_game(token):
    global MULTIWORLDS

    if not token in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    response = APP.response_class(
        response=json.dumps(MULTIWORLDS[token], default=multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response

@APP.route('/game/<string:token>/msg', methods=['PUT'])
async def update_game(token):
    data = await request.get_json()

    global MULTIWORLDS

    if not token in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    if not 'msg' in data:
        abort(400)

    if data['msg'] == '/exit':
        close_game(data['token'])
        return jsonify(resp='Game closed.', success=True)

    resp = MULTIWORLDS[token]['server'].commandprocessor(data['msg'])
    return jsonify(resp=resp, success=True)

@APP.route('/game/<string:token>', methods=['DELETE'])
async def delete_game(token):
    global MULTIWORLDS

    if not token in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    close_game(token)
    return jsonify(success=True)

@APP.route('/jobs/cleanup/<int:minutes>', methods=['POST'])
async def cleanup(minutes):
    global MULTIWORLDS
    tokens_to_clean = []
    for token in MULTIWORLDS:
        if MULTIWORLDS[token]['date'] < datetime.datetime.now()-datetime.timedelta(minutes=minutes):
            tokens_to_clean.append(token)
    for token in tokens_to_clean:
        close_game(token)
    return jsonify(success=True, count=len(tokens_to_clean), cleaned_tokens=tokens_to_clean)

@APP.errorhandler(400)
def bad_request(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.status_code)

@APP.errorhandler(404)
def game_not_found(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.status_code)

@APP.errorhandler(500)
def something_bad_happened(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.status_code)

def close_game(token):
    server = MULTIWORLDS[token]['server']
    server.server.ws_server.close()
    del MULTIWORLDS[token]

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('0.0.0.0', port)) == 0

def random_string(length=6):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for i in range(length))

def multiworld_converter(o):
    if isinstance(o, MultiServer.Client):
        return {
            'auth': o.auth,
            'name': o.name,
            'team': o.team,
            'slot': o.slot,
            'send_index': o.send_index
        }
    if isinstance(o, MultiServer.Context):
        received_items = []
        print(o.player_names.keys())
        for team in list(set(team for team, slot in o.player_names.keys())):
            received_items.append({key[1]:len(value) for (key, value) in o.received_items.items() if key[0] == team})
        return {
            'data_filename': o.data_filename,
            'save_filename': o.save_filename,
            'clients': {
                'count': len(o.clients),
                'connected': o.clients
            },
            'received_items': received_items
        }
    if isinstance(o, tuple):
        return list([list(row) for row in o])
    if isinstance(o, datetime.datetime):
        return o.__str__()
    if isinstance(o, asyncio.subprocess.Process):
        return o.pid

async def create_multiserver(port, multidatafile, racemode=False):
    args = argparse.Namespace(
        host='0.0.0.0',
        port=port,
        password=None,
        location_check_points=1,
        hint_cost=1000 if racemode else 25,
        disable_item_cheat=racemode,
        disable_client_forfeit=racemode,
        multidata=multidatafile,
        disable_save=False,
        loglevel="info"
    )

    logging.basicConfig(format='[%(asctime)s] %(message)s', level=getattr(logging, args.loglevel.upper(), logging.INFO))

    ctx = MultiServer.Context(args.host, args.port, args.password, args.location_check_points, args.hint_cost,
                  not args.disable_item_cheat, not args.disable_client_forfeit)

    ctx.data_filename = args.multidata

    try:
        with open(ctx.data_filename, 'rb') as f:
            jsonobj = json.loads(zlib.decompress(f.read()).decode("utf-8"))
            for team, names in enumerate(jsonobj['names']):
                for player, name in enumerate(names, 1):
                    ctx.player_names[(team, player)] = name
            ctx.rom_names = {tuple(rom): (team, slot) for slot, team, rom in jsonobj['roms']}
            ctx.remote_items = set(jsonobj['remote_items'])
            ctx.locations = {tuple(k): tuple(v) for k, v in jsonobj['locations']}
    except Exception as e:
        logging.error('Failed to read multiworld data (%s)' % e)
        return

    ctx.disable_save = args.disable_save
    if not ctx.disable_save:
        if not ctx.save_filename:
            ctx.save_filename = (ctx.data_filename[:-9] if ctx.data_filename[-9:] == 'multidata' else (
                    ctx.data_filename + '_')) + 'multisave'
        try:
            with open(ctx.save_filename, 'rb') as f:
                jsonobj = json.loads(zlib.decompress(f.read()).decode("utf-8"))
                ctx.set_save(jsonobj)
        except FileNotFoundError:
            logging.error('No save data found, starting a new game')
        except Exception as e:
            logging.exception(e)
    ctx.server = websockets.serve(functools.partial(MultiServer.server, ctx=ctx), ctx.host, ctx.port, ping_timeout=None,
                                  ping_interval=None)
    await ctx.server
    return ctx

if __name__ == '__main__':
    APP.run(host='127.0.0.1', port=5000, use_reloader=False)
