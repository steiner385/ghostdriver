from ghostdriver.probe.toolkit import infer_toolkit


def test_identifies_delphi_vcl_from_runtime_packages():
    got = infer_toolkit([
        r"C:\app\rtl170.bpl", r"C:\app\vcl170.bpl", r"C:\windows\user32.dll",
    ])
    assert got.toolkit == "delphi-vcl"
    assert got.confidence == "high"


def test_identifies_delphi_vcl_from_memory_manager_alone():
    got = infer_toolkit([r"C:\app\borlndmm.dll", r"C:\windows\user32.dll"])
    assert got.toolkit == "delphi-vcl"


def test_identifies_dotnet():
    got = infer_toolkit([r"C:\windows\system32\mscoree.dll", r"C:\app\clr.dll"])
    assert got.toolkit == "dotnet"


def test_identifies_java():
    assert infer_toolkit([r"C:\jre\bin\jvm.dll"]).toolkit == "java"


def test_identifies_mfc():
    assert infer_toolkit([r"C:\app\mfc42.dll"]).toolkit == "mfc"


def test_identifies_vb6():
    assert infer_toolkit([r"C:\windows\msvbvm60.dll"]).toolkit == "vb6"


def test_identifies_powerbuilder():
    assert infer_toolkit([r"C:\app\pbvm190.dll"]).toolkit == "powerbuilder"


def test_identifies_qt():
    assert infer_toolkit([r"C:\app\Qt5Core.dll"]).toolkit == "qt"


def test_reports_embedded_webview_alongside_host_toolkit():
    got = infer_toolkit([r"C:\app\vcl170.bpl", r"C:\app\WebView2Loader.dll"])
    assert got.toolkit == "delphi-vcl"
    assert "embedded-webview" in got.secondary


def test_matching_is_case_insensitive():
    assert infer_toolkit([r"C:\APP\VCL170.BPL"]).toolkit == "delphi-vcl"


def test_unknown_toolkit_is_reported_not_guessed():
    got = infer_toolkit([r"C:\windows\system32\user32.dll"])
    assert got.toolkit == "unknown"
    assert got.confidence == "low"


def test_evidence_names_the_matching_modules():
    got = infer_toolkit([r"C:\app\vcl170.bpl", r"C:\windows\user32.dll"])
    assert any("vcl170.bpl" in e for e in got.evidence)
    assert not any("user32.dll" in e for e in got.evidence)
