"""Tests for StreamDescriptor channel_names CSV-safety validation."""

import pytest

from modlink_sdk.models import StreamDescriptor

# Minimal valid kwargs for constructing a StreamDescriptor
_BASE = dict(
    device_id="test_device.01",
    stream_key="eeg",
    payload_type="signal",
    nominal_sample_rate_hz=250.0,
    chunk_size=32,
)


def make_descriptor(**kwargs) -> StreamDescriptor:
    return StreamDescriptor(**{**_BASE, **kwargs})


# --- Happy path ---


def test_valid_channel_names_accepted():
    d = make_descriptor(channel_names=("Fp1", "Fp2", "Cz"))
    assert d.channel_names == ("Fp1", "Fp2", "Cz")


def test_empty_tuple_accepted():
    d = make_descriptor(channel_names=())
    assert d.channel_names == ()


def test_single_valid_name_accepted():
    d = make_descriptor(channel_names=("EEG_1",))
    assert d.channel_names == ("EEG_1",)


# --- CSV-unsafe rejections ---


def test_comma_rejected():
    with pytest.raises(ValueError, match="not CSV-safe"):
        make_descriptor(channel_names=("ch1,ch2",))


def test_newline_rejected():
    with pytest.raises(ValueError, match="not CSV-safe"):
        make_descriptor(channel_names=("ch1\nch2",))


def test_carriage_return_rejected():
    with pytest.raises(ValueError, match="not CSV-safe"):
        make_descriptor(channel_names=("ch1\rch2",))


def test_null_byte_rejected():
    with pytest.raises(ValueError, match="not CSV-safe"):
        make_descriptor(channel_names=("ch1\0ch2",))


def test_empty_string_rejected():
    with pytest.raises(ValueError, match="not CSV-safe"):
        make_descriptor(channel_names=("",))


def test_leading_whitespace_rejected():
    with pytest.raises(ValueError, match="not CSV-safe"):
        make_descriptor(channel_names=(" Fp1",))


def test_trailing_whitespace_rejected():
    with pytest.raises(ValueError, match="not CSV-safe"):
        make_descriptor(channel_names=("Fp1 ",))


def test_error_message_contains_name():
    with pytest.raises(ValueError, match="'bad,name'"):
        make_descriptor(channel_names=("bad,name",))


def test_second_invalid_name_in_tuple_rejected():
    # First name is valid; second has a comma — should still raise
    with pytest.raises(ValueError, match="not CSV-safe"):
        make_descriptor(channel_names=("Fp1", "bad,name"))
