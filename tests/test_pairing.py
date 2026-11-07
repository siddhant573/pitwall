import hashlib
import hmac as std_hmac
import json
import os
import stat

from pitwall import seal
from pitwall.pairing import PairingStore, host_id


def test_hmac_matches_stdlib():
    for key in (b"", b"k", b"x" * 100):
        assert seal.hmac_sha256(key, b"msg") == std_hmac.new(key, b"msg", hashlib.sha256).digest()


def handshake(dev_keys, host_key, host="H1", hn=None):
    dev = seal.DeviceAuth(dev_keys, rand=os.urandom)
    dn = bytes.fromhex(dev.challenge()["nonce"])
    hn = hn or os.urandom(16)
    reply, got_host, dev_session = dev.handle({"type": "auth", "host": host, "hn": hn.hex(),
                                               "mac": seal.auth_mac(host_key, dn, hn)})
    return dev, dn, hn, reply, got_host, dev_session


def test_random_key_is_256_bits():
    k = seal.new_key()
    assert len(k) == 32 and k != seal.new_key()


def test_mutual_auth_and_matching_session_keys():
    key = seal.new_key()
    dev, dn, hn, reply, host, dev_session = handshake({"H1": key}, key)
    assert reply["type"] == "auth_ok" and host == "H1"
    assert seal.check_dev_mac(key, dn, hn, reply["mac"])
    assert dev_session == seal.session_key(key, dn, hn) != key


def test_wrong_key_unknown_host_and_nonce_reuse_rejected():
    key = seal.new_key()
    assert handshake({"H1": key}, seal.new_key())[4] is None
    assert handshake({"H1": key}, key, host="H2")[4] is None
    dev, dn, hn, reply, host, _ = handshake({"H1": key}, key)
    again = dev.handle({"type": "auth", "host": "H1", "hn": hn.hex(), "mac": seal.auth_mac(key, dn, hn)})
    assert again[1] is None   # a challenge can be answered once


def test_failed_auth_consumes_challenge():
    key = seal.new_key()
    dev = seal.DeviceAuth({"H1": key}, rand=os.urandom)
    dn = bytes.fromhex(dev.challenge()["nonce"])
    hn = os.urandom(16)
    assert dev.handle({"type": "auth", "host": "H1", "hn": hn.hex(), "mac": "00" * 32})[1] is None
    assert dev.handle({"type": "auth", "host": "H1", "hn": hn.hex(), "mac": seal.auth_mac(key, dn, hn)})[1] is None


def test_fake_device_without_key_fails_dev_mac():
    key = seal.new_key()
    assert not seal.check_dev_mac(key, b"d" * 16, b"h" * 16, "00" * 32)
    assert not seal.check_dev_mac(key, b"d" * 16, b"h" * 16, "zz")


def test_no_code_pairing_left():
    assert not hasattr(seal, "pair_mac") and not hasattr(seal.DeviceAuth, "start_pairing")


def test_seal_roundtrip_tamper_and_replay():
    key, nonce = b"k" * 32, b"n" * 16
    s, o = seal.Sealer(key, nonce, "h2d"), seal.Opener(key, nonce, "h2d")
    line = '{"v":1,"type":"board","label":"café-🏎️"}'.encode()
    m1, m2 = s.seal(line), s.seal(b"second")
    assert "café" not in json.dumps(m1)
    assert o.open(m1) == line
    assert o.open(m1) is None            # replay
    assert o.open(m2) == b"second"
    bad = dict(s.seal(b"x"), t="00" * 16)
    assert o.open(bad) is None           # bad tag
    other_dir = seal.Opener(key, nonce, "d2h")
    assert other_dir.open(s.seal(b"y")) is None
    assert o.open({"type": "sealed", "n": "x", "d": "!!", "t": "zz"}) is None


def test_store_file_mode_and_roundtrip(tmp_path):
    st = PairingStore(tmp_path / "pairing.json")
    st.add("UID1", {"key": "ab", "name": "pitwall-UID1"})
    assert stat.S_IMODE((tmp_path / "pairing.json").stat().st_mode) == 0o600
    assert PairingStore(tmp_path / "pairing.json").get("UID1")["key"] == "ab"


def test_host_id_is_stable(tmp_path):
    a = host_id(tmp_path)
    assert a == host_id(tmp_path) and len(a) == 16
