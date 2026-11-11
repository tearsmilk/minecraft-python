"""The program inside Honoka.app (and later Honoka.exe): the window.

HONOKA_SMOKE=1 is the build's check that the bundle works: HTTPS reaches Mojang (certificates found),
the window opens and closes, and it prints "smoke ok".
"""

import os

if __name__ == "__main__":
    if os.environ.get("HONOKA_SMOKE"):
        import tkinter as tk

        from honoka import gui, net

        manifest = net.get_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
        assert manifest["versions"], "no versions"
        root = tk.Tk()
        gui.App(root)
        root.after(1500, root.destroy)
        root.mainloop()
        print("smoke ok")
    else:
        from honoka.gui import main

        main()
