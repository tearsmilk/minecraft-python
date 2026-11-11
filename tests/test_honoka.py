import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

FIXTURES = Path(__file__).parent / "fixtures"


class Home(unittest.TestCase):
    """Every test gets its own HONOKA_HOME."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"HONOKA_HOME": str(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class Ed25519(unittest.TestCase):
    def test_rfc8032_vector_1(self):
        from honoka import ed25519

        pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertTrue(ed25519.verify(pk, b"", sig))
        self.assertFalse(ed25519.verify(pk, b"x", sig))
        self.assertFalse(ed25519.verify(pk, b"", sig[:-1] + b"\x00"))
        self.assertFalse(ed25519.verify(pk[:31], b"", sig))


class Builds(unittest.TestCase):
    def test_asset_for_each_platform(self):
        from honoka.builds import BuildError, asset_name

        self.assertEqual(asset_name("win32", "AMD64"), "horizon-windows-x64.zip")
        self.assertEqual(asset_name("win32", "ARM64"), "horizon-windows-arm64.zip")
        self.assertEqual(asset_name("darwin", "x86_64"), "horizon-macos-x64.zip")  # Intel Macs, macOS 11 too
        self.assertEqual(asset_name("darwin", "arm64"), "horizon-macos-arm64.zip")
        self.assertEqual(asset_name("linux", "x86_64"), "horizon-linux-x86_64.tar.gz")
        with self.assertRaises(BuildError):
            asset_name("linux", "aarch64")

    def test_tags_and_titles(self):
        from honoka.builds import is_game_tag, nightly_version

        self.assertTrue(is_game_tag("v2026.11.10"))
        self.assertFalse(is_game_tag("launcher@0.2.59"))
        self.assertFalse(is_game_tag("nightly"))
        self.assertEqual(nightly_version("Nightly 2026-10-28 · 0c02067"), "nightly-2026-10-28-0c02067")
        self.assertIsNone(nightly_version("Nightly 2026-10-28"))
        self.assertIsNone(nightly_version("Nightly 2026-10-28 · XYZ1234"))

    def test_real_nightly_signature(self):
        # SHA256SUMS and SHA256SUMS.sig of Horizon's Nightly of 2026-11-11, signed for the channel.
        from honoka import builds

        sums = (FIXTURES / "SHA256SUMS").read_bytes()
        sig = (FIXTURES / "SHA256SUMS.sig").read_text()
        builds.check_signature("nightly", sums, sig, builds.trusted_keys())
        with self.assertRaises(builds.BuildError):  # signed for another version
            builds.check_signature("v2026.11.10", sums, sig, builds.trusted_keys())
        with self.assertRaises(builds.BuildError):  # changed list
            builds.check_signature("nightly", sums.replace(b"da05", b"da06"), sig, builds.trusted_keys())
        parsed = builds.parse_sums(sums.decode())
        self.assertEqual(
            parsed["horizon-macos-x64.zip"], "e04185f69c4960c8d8904faac09d8570bbf9a8067cba738c61f6f7347cd0511f"
        )

    def test_unpack_drops_top_folder_and_refuses_escapes(self):
        from honoka.builds import unpack

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "horizon-linux-x86_64.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for name, mode in (("horizon-linux-x86_64/horizon-client", 0o755), ("horizon-linux-x86_64/../evil", 0o644)):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = 2, mode
                    tar.addfile(info, io.BytesIO(b"hi"))
            dest = Path(tmp) / "out"
            unpack(archive, dest)
            self.assertTrue((dest / "horizon-client").is_file())
            self.assertFalse((Path(tmp) / "evil").exists())
            if sys.platform != "win32":
                self.assertTrue((dest / "horizon-client").stat().st_mode & stat.S_IXUSR)


class Mojang(unittest.TestCase):
    def test_rules(self):
        from honoka.mojang import rules_allow

        self.assertTrue(rules_allow(None))
        only_osx = [{"action": "allow", "os": {"name": "osx"}}]
        self.assertTrue(rules_allow(only_osx, "osx"))
        self.assertFalse(rules_allow(only_osx, "windows"))
        not_osx = [{"action": "allow"}, {"action": "disallow", "os": {"name": "osx"}}]
        self.assertFalse(rules_allow(not_osx, "osx"))
        self.assertTrue(rules_allow(not_osx, "linux"))
        self.assertFalse(rules_allow([{"action": "allow", "features": {"is_demo_user": True}}], "linux"))

    def test_libraries_for_this_os(self):
        from honoka.mojang import libraries

        vj = {
            "libraries": [
                {"downloads": {"artifact": {"path": "a/a.jar", "sha1": "1", "url": "u1"}}},
                {
                    "downloads": {"artifact": {"path": "b/b-mac.jar", "sha1": "2", "url": "u2"}},
                    "rules": [{"action": "allow", "os": {"name": "osx"}}],
                },
                {
                    "downloads": {"classifiers": {"natives-osx": {"path": "c/c-natives.jar", "sha1": "3", "url": "u3"}}},
                    "natives": {"osx": "natives-osx"},
                },
            ]
        }
        self.assertEqual([n.url for n in libraries(vj, "osx")], ["u1", "u2", "u3"])
        self.assertEqual([n.url for n in libraries(vj, "windows")], ["u1"])

    def test_java_release_file(self):
        from honoka.mojang import java_major_of

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "release").write_text('IMPLEMENTOR="Eclipse Adoptium"\nJAVA_VERSION="25.0.1"\n')
            self.assertEqual(java_major_of(Path(tmp)), 25)
            (Path(tmp) / "release").write_text('JAVA_VERSION="1.8.0_402"\n')
            self.assertEqual(java_major_of(Path(tmp)), 8)
            self.assertIsNone(java_major_of(Path(tmp) / "missing"))


class Mac(unittest.TestCase):
    def test_macos_versions(self):
        from honoka import system

        with mock.patch.object(sys, "platform", "darwin"):
            for reported, expected in (("10.16", (11, 0)), ("11.7.10", (11, 7)), ("14.5", (14, 5))):
                with mock.patch("platform.mac_ver", return_value=(reported, ("", "", ""), "x86_64")):
                    self.assertEqual(system.macos_version(), expected)
            with mock.patch("platform.mac_ver", return_value=("11.7", ("", "", ""), "x86_64")):
                self.assertTrue(system.supported())
                self.assertIn("macOS 11", system.warnings()[0])
            with mock.patch("platform.mac_ver", return_value=("10.15.7", ("", "", ""), "x86_64")):
                self.assertFalse(system.supported())
            with mock.patch("platform.mac_ver", return_value=("13.0", ("", "", ""), "arm64")):
                self.assertEqual(system.warnings(), [])


class Account(Home):
    def test_session_json(self):
        from honoka.account import Session

        body = json.loads(Session("Alex", "069a79f444e94726a5befca90e38aaf5", "tok", None).game_json())
        self.assertEqual(body, {"name": "Alex", "uuid": "069a79f444e94726a5befca90e38aaf5", "access_token": "tok", "user_type": "msa"})

    @unittest.skipIf(sys.platform == "win32", "DPAPI is covered on Windows itself")
    def test_saved_account_is_private_and_reads_back(self):
        from honoka import account, paths

        account._save({"name": "Alex", "uuid": "u", "owns": True}, {"refresh_token": "r", "minecraft_token": "m"})
        self.assertEqual(paths.account_file().stat().st_mode & 0o777, 0o600)
        self.assertNotIn('"r"', paths.account_file().read_text())
        self.assertEqual(account.load()["secrets"]["refresh_token"], "r")
        self.assertEqual(account.signed_in(), {"name": "Alex", "uuid": "u", "owns": True})

    def test_no_game_no_session(self):
        from honoka import account

        account._save({"name": "", "uuid": "", "owns": False}, {"refresh_token": ""})
        with self.assertRaises(account.AuthError):
            account.session()


@unittest.skipIf(sys.platform == "win32", "uses a shell script as the game")
class Launch(Home):
    def test_game_gets_server_and_session_on_stdin(self):
        from honoka import builds, game, paths

        build = builds.build_dir("v1")
        build.mkdir(parents=True)
        out = self.home / "seen"
        client = build / "horizon-client"
        client.write_text(f'#!/bin/sh\necho "$@" > "{out}.args"\nenv > "{out}.env"\ncat > "{out}.stdin"\n')
        client.chmod(0o755)
        proc = game.start("v1", '{"name":"Alex"}', "mc.hoka.ink")
        self.assertEqual(proc.wait(), 0)
        args = Path(f"{out}.args").read_text()
        self.assertIn("--quickPlayMultiplayer mc.hoka.ink", args)
        self.assertIn("--session-stdin", args)
        self.assertIn(f"--resources {paths.prepared('v1')}", args)
        self.assertNotIn("Alex", args)  # the session never goes on the command line
        self.assertEqual(Path(f"{out}.stdin").read_text(), '{"name":"Alex"}')
        self.assertIn("HORIZON_OLDER_SERVERS=1", Path(f"{out}.env").read_text())
        self.assertIsNone(game.exit_message(0))


@unittest.skipIf(sys.platform == "win32", "uses a shell script as the Horizon launcher")
class Bridge(Home):
    """Signing in through the Horizon launcher, with a stand-in for its CLI."""

    def fake_launcher(self, owner: bool) -> Path:
        session = self.home / "session-abc.json"
        listing = json.dumps({
            "accounts": [{"name": "Alex", "uuid": "u1", "selected": True}],
            "sign_in_configured": True,
            "owner": owner,
        })
        exe = self.home / "horizon-launcher"
        exe.write_text(
            "#!/bin/sh\n"
            'if [ "$2" = sign-in ]; then\n'
            "  echo 'To sign in, open https://microsoft.com/link in a browser and enter the code ABCD1234' >&2\n"
            "  echo 'Signed in as Alex.'\n"
            f'elif [ "$3" = select ]; then echo \'{{}}\'; echo "$4" > \'{self.home}/selected\'\n'
            'elif [ "$3" = list ]; then cat <<\'EOF\'\n' + listing + "\nEOF\n"
            f'elif [ "$3" = session ] && [ "$4" = u1 ]; then\n'
            f"  printf '%s' '{{\"name\":\"Alex\",\"uuid\":\"u1\",\"access_token\":\"t\",\"user_type\":\"msa\"}}' > '{session}'\n"
            f'  echo \'{{"session_file": "{session}"}}\'\n'
            "fi\n"
        )
        exe.chmod(0o755)
        return exe

    def test_owner_session_is_read_once(self):
        from honoka import horizon_bridge

        exe = self.fake_launcher(owner=True)
        with mock.patch.dict(os.environ, {"HONOKA_HORIZON_LAUNCHER": str(exe)}):
            self.assertEqual(horizon_bridge.owner_account(), {"name": "Alex", "uuid": "u1"})
            name, body = horizon_bridge.session_json()
        self.assertEqual(name, "Alex")
        self.assertEqual(json.loads(body)["access_token"], "t")
        self.assertFalse((self.home / "session-abc.json").exists())  # nothing with a token left on disk

    def test_sign_in_from_the_command_line(self):
        # macOS 11: Horizon.app's window needs macOS 12, its program's commands don't.
        from honoka import horizon_bridge

        exe = self.fake_launcher(owner=True)
        seen = []
        with mock.patch.dict(os.environ, {"HONOKA_HORIZON_LAUNCHER": str(exe)}):
            name = horizon_bridge.sign_in(lambda link, code: seen.append((link, code)))
        self.assertEqual(name, "Alex")
        self.assertEqual(seen, [("https://microsoft.com/link", "ABCD1234")])
        self.assertEqual((self.home / "selected").read_text().strip(), "Alex")

    def test_no_owner_no_session(self):
        from honoka import horizon_bridge

        exe = self.fake_launcher(owner=False)
        with mock.patch.dict(os.environ, {"HONOKA_HORIZON_LAUNCHER": str(exe)}):
            self.assertIsNone(horizon_bridge.owner_account())
            with self.assertRaises(horizon_bridge.BridgeError):
                horizon_bridge.session_json()

    def test_no_launcher(self):
        from honoka import horizon_bridge

        with mock.patch.dict(os.environ, {"HONOKA_HORIZON_LAUNCHER": str(self.home / "missing")}), \
                mock.patch("shutil.which", return_value=None), \
                mock.patch.object(horizon_bridge.sys, "platform", "linux"):
            self.assertIsNone(horizon_bridge.find_launcher())
            with self.assertRaises(horizon_bridge.BridgeError):
                horizon_bridge.owner_account()


if __name__ == "__main__":
    unittest.main()
