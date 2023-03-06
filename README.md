# MultiworldHostService
A simple hosting service for the door rando implementations of ALTTPR Multiworld.  Port 5002 is unauthenticated and not designed to be accessed remotely.

Ensure that the directory containing the MultiServer.py and MultiClient.py is included in the PYTHONPATH.

`PYTHONPATH=$PYTHONPATH:/opt/ALttPDoorRandomizer`

## To do

1. Refactor MultiServer so all of the functions that are called are just within the Context
2. Subclass the class noted in #1
3. Let an authorized user in the server create a thread for the multiworld, and have messages from the multiserver be posted in that thread.
