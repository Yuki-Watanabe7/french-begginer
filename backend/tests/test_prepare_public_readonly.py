"""公開用フォルダーの境界を合成データだけで検証する（Issue #223）。"""

import hashlib
import json
import os

import prepare_public_readonly as preparation
import pytest


@pytest.fixture
def bundle_input(tmp_path, monkeypatch):
    viewer = tmp_path / "viewer"
    (viewer / "assets").mkdir(parents=True)
    (viewer / "index.html").write_text('<script src="./assets/index-demo.js"></script>')
    (viewer / "assets" / "index-demo.js").write_text("// synthetic viewer")
    (viewer / "snapshot.json").write_bytes(preparation.SYNTHETIC.read_bytes())
    monkeypatch.setattr(preparation, "VIEWER_DIR", viewer)
    return viewer, preparation.SYNTHETIC, tmp_path / "public"


def test_only_viewer_and_exact_snapshot_enter_bundle(bundle_input):
    viewer, snapshot, out = bundle_input
    target, digest, count = preparation.prepare_bundle(snapshot=snapshot, out=out)
    assert count == 3
    assert digest == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert (target / "snapshot.json").read_bytes() == snapshot.read_bytes()
    assert {
        p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()
    } == {
        "index.html",
        "assets/index-demo.js",
        "snapshot.json",
        ".nojekyll",
    }
    assert not (viewer / ".nojekyll").exists()


def test_selected_snapshot_replaces_demo_without_changing_bytes(bundle_input):
    viewer, snapshot, out = bundle_input
    payload = json.loads(snapshot.read_bytes())
    payload["cards"] = [
        {
            "card_id": "card-001",
            "item_type": "vocabulary",
            "canonical_form": "livre",
            "meaning_ja": "本",
        }
    ]
    candidate = out.parent / "selected.json"
    candidate.write_text(json.dumps(payload, ensure_ascii=False))
    target, digest, count = preparation.prepare_bundle(snapshot=candidate, out=out)
    assert count == 1
    assert digest == hashlib.sha256(candidate.read_bytes()).hexdigest()
    assert (target / "snapshot.json").read_bytes() == candidate.read_bytes()
    assert (viewer / "snapshot.json").read_bytes() == snapshot.read_bytes()


@pytest.mark.parametrize(
    "name", ["index.html", "snapshot.json", "assets/index-demo.js"]
)
def test_incomplete_viewer_is_rejected(bundle_input, name):
    viewer, snapshot, out = bundle_input
    (viewer / name).unlink()
    with pytest.raises(ValueError, match="3ファイル"):
        preparation.prepare_bundle(snapshot=snapshot, out=out)
    assert not out.exists()


@pytest.mark.parametrize("name", [".env", "tutor.db", "assets/index-demo.js.map"])
def test_extra_files_are_rejected_without_output(bundle_input, name):
    viewer, snapshot, out = bundle_input
    (viewer / name).write_text("private sentinel")
    with pytest.raises(ValueError, match="許可外"):
        preparation.prepare_bundle(snapshot=snapshot, out=out)
    assert not out.exists()


@pytest.mark.parametrize("link_type", ["symbolic", "hard"])
def test_linked_assets_are_rejected(bundle_input, link_type):
    viewer, snapshot, out = bundle_input
    asset = viewer / "assets" / "index-demo.js"
    outside = viewer.parent / "outside.js"
    asset.rename(outside)
    if link_type == "symbolic":
        asset.symlink_to(outside)
    else:
        os.link(outside, asset)
    with pytest.raises(ValueError):
        preparation.prepare_bundle(snapshot=snapshot, out=out)
    assert not out.exists()


@pytest.mark.parametrize("change", ["private_field", "secret", "null", "timestamp"])
def test_invalid_snapshot_never_leaks_values_or_creates_output(
    bundle_input, change, capsys
):
    _, snapshot, out = bundle_input
    payload = json.loads(snapshot.read_bytes())
    secret = "sk-private-sentinel-0123456789abcdefghijklmnop"
    if change == "private_field":
        payload["learning_events"] = [secret]
    elif change == "secret":
        payload["cards"][0]["meaning_ja"] = secret
    elif change == "null":
        payload["cards"][0]["level"] = None
    else:
        payload["generated_at"] = "2026-11-03T09:30:00+00:00"
    candidate = out.parent / "candidate.json"
    candidate.write_text(json.dumps(payload))
    assert preparation.main(["--snapshot", str(candidate), "--out", str(out)]) == 1
    assert secret not in capsys.readouterr().err
    assert not out.exists()


def test_existing_and_git_outputs_are_rejected(bundle_input):
    _, snapshot, out = bundle_input
    out.mkdir()
    (out / "keep").write_text("old approved version")
    with pytest.raises(ValueError, match="既にある"):
        preparation.prepare_bundle(snapshot=snapshot, out=out)
    assert (out / "keep").read_text() == "old approved version"
    (out / ".git").mkdir()
    with pytest.raises(ValueError, match="Git 作業ツリー"):
        preparation.prepare_bundle(snapshot=snapshot, out=out / "inside")


def test_duplicate_json_keys_are_rejected_before_private_value_can_be_hidden(
    bundle_input,
):
    _, snapshot, out = bundle_input
    candidate = out.parent / "duplicate.json"
    candidate.write_text(
        snapshot.read_text().replace(
            '"meaning_ja": "こんにちは"',
            '"meaning_ja": "private sentinel", "meaning_ja": "こんにちは"',
        )
    )
    with pytest.raises(ValueError, match="重複したキー"):
        preparation.prepare_bundle(snapshot=candidate, out=out)
    assert not out.exists()


def test_failed_copy_leaves_no_partial_bundle(bundle_input, monkeypatch):
    _, snapshot, out = bundle_input

    def fail_copy(*args):
        raise OSError("copy failed")

    monkeypatch.setattr(preparation.shutil, "copyfile", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        preparation.prepare_bundle(snapshot=snapshot, out=out)
    assert not out.exists()
