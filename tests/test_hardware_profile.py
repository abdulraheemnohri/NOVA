from nova.hardware_profile import get_hardware_profile


def test_hardware_profile_is_conservative_and_structured():
    result = get_hardware_profile()
    assert "cpu" in result
    assert "memory_total_mb" in result
    assert result["accelerators"]["google_edge_tpu"]["status"] == "unverified"
    assert result["accelerators"]["mali_gpu"]["status"] == "unverified"
    assert result["runtime_recommendation"]["max_optional_tasks"] == 1


def test_gs101_reference_only_when_identity_matches(monkeypatch):
    import nova.hardware_profile as hp

    monkeypatch.setattr(hp, "_getprop", lambda key: {
        "ro.product.model": "Pixel 6",
        "ro.product.vendor.model": "",
        "ro.product.device": "oriole",
        "ro.board.platform": "gs101",
        "ro.soc.model": "",
    }.get(key, ""))
    result = hp.get_hardware_profile()
    assert result["chip_reference"]["name"] == "Google Tensor GS101"
    assert result["accelerators"]["google_edge_tpu"]["status"] == "unverified"
