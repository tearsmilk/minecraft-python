"""Honoka: the launcher of the Hoka server.

Starts Horizon (Minecraft: Java Edition 26.3 rewritten in Rust, https://github.com/horizon-rust/horizon)
straight on the server, through Horizon's Launch API for other launchers (docs/api/launch-guide.md there):

1. sign the player in with Microsoft and check they own Minecraft: Java Edition;
2. download a Horizon build and check its signature;
3. for that owner only, get the game's files from Mojang (or from their own install) and a Java;
4. prepare the resources with the build's ``horizon-prepare``;
5. start ``horizon-client`` on the server.
"""

__version__ = "0.1.0"
