# MAC Toys

***Buttplug.io integration for [MAC](https://github.com/MegaAntiCheat/client-backend)***

## Requirements
- [Intiface Central](https://intiface.com/central/)
- [Python >~3.11](https://www.python.org/)
- [Python Poetry](https://python-poetry.org/)
- A compatible toy (check compatibility [here](https://iostindex.com/?filter0Availability=Available,DIY&filter1Connection=Digital))
- Bluetooth capabilities for your computer
  - if you don't have a bluetooth card built in, any CSR 4.0 bluetooth dongle should work.
  - The TP-Link UB400 is recommended, I use the TP-Link UB500 (It is backwards compatible with Bluetooth 4)
  - See [here](https://docs.intiface.com/docs/intiface-central/hardware/bluetooth) for Intiface docs
- [MAC Client](https://github.com/MegaAntiCheat/client-backend)
  - Just download the release binary from the latest release (under the assets drop down)
- Some minor knowledge of how to use the terminal (Powershell/bash) and git
- Your IGN and SteamID64
  - Your SteamID64 should look something like '76561198071482715' and can be found on any steam profile lookup website
  - Your IGN should be as people will see it in TF2

This app is confirmed working with at least one Satisfyer and at least one Lovense toy.

## Usage

- Clone this repository into a good folder (like your Documents)
- Start the MAC client-backend binary
- Move into the MAC Toys directory in Powershell/bash
- Modify the `config.toml` file!
  - At the very least, you need to fill out the 'in_game_name' and 'steamid_64' fields.
  - Feel free to modify any other values to your hearts desire. 
  - Avoid: setting intensity values above 1 or below 0, as they will do nothing
- Run `poetry install` to install the python dependencies
- Run `poetry shell` to enter the virtual environment
- Run `python main.py` to begin the program.
  - Vibration should start within 5s!

## Rules

There is a background 'ambient' vibration that scales its intensity with your current kill and death streak

There are also the following 'instant' vibrations that occur:
 - There is two sets of 'forbidden' words controlled by the config file. If these words are said by the right people, you will get vibrated
 - If you get a kill, you get vibrated
   - If it's a crit kill, you get vibrated more
 - If you get killed, you get vibrated
   - If it's a crit death, you get vibrated more
 - If you get a (true, i.e. not including assists) domination, you get vibrated more
 - If you get true dominated, you get vibrated more
 - If you lose a domination, you get vibrated more
 - If you get revenge on someone dominating you, you get vibrated more.

## Known issues/missing features

The app tracks 'true' dominations (doms that don't track assists), but currently has no response to changes
in the domination status.

The app cannot track the destruction of buildings or assists.

The app cannot track damage events, only kills, deaths and chat events.