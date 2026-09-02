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


def test_stronger_evidence_wins_over_list_position():
    """A framework with more signature hits must beat one that merely sorts earlier.

    Selecting by list position lets a single incidental dependency mask a
    framework with two independent signature files.
    """
    got = infer_toolkit([
        r"C:\app\mfc42.dll",
        r"C:\windows\system32\mscoree.dll",
        r"C:\app\clr.dll",
    ])
    assert got.toolkit == "dotnet"
    assert "mfc" in got.competing


def test_colliding_frameworks_are_reported_as_ambiguous():
    """Contested inference must say so rather than returning a clean guess."""
    got = infer_toolkit([r"C:\app\mfc42.dll", r"C:\app\vcl170.bpl"])
    assert got.confidence == "ambiguous"
    assert got.competing


def test_single_framework_is_not_marked_ambiguous():
    """The ordinary case must be unaffected by the ambiguity path."""
    got = infer_toolkit([r"C:\app\rtl170.bpl", r"C:\app\vcl170.bpl"])
    assert got.toolkit == "delphi-vcl"
    assert got.confidence == "high"
    assert got.competing == []


# --- window classes, when no runtime is loaded --------------------------
#
# A statically linked application drags in no framework runtime, so the
# module list cannot identify it even in principle. Observed on a real
# target: 122 modules loaded, not one a framework signature, while the
# window classes named the toolkit unambiguously.

VCL_CLASSES = [
    "TApplication", "TSfShellWin", "TPanel", "TAdvPanel",
    "TsfCommandButton", "TAdvToolBar",
]


def test_window_classes_identify_a_statically_linked_target():
    result = infer_toolkit(["ntdll.dll", "kernel32.dll", "user32.dll"],
                           class_names=VCL_CLASSES)

    assert result.toolkit == "delphi-vcl"
    assert result.source == "window-classes"
    assert result.evidence, "an inference with no evidence is not reviewable"
    assert all(e.startswith("class:") for e in result.evidence)


def test_class_inference_never_claims_high_confidence():
    """Weaker evidence than a loaded runtime, and it must say so.

    A component library or theme can borrow another toolkit's naming
    convention, so this fingerprint is suggestive rather than decisive.
    """
    result = infer_toolkit([], class_names=VCL_CLASSES)

    assert result.confidence in ("medium", "low")


def test_loaded_modules_still_win_over_classes():
    result = infer_toolkit(["C:/app/mfc140.dll"], class_names=VCL_CLASSES)

    assert result.toolkit == "mfc"
    assert result.source == "modules"


def test_unreadable_modules_are_not_reported_as_no_signature():
    """None and [] are different answers.

    An empty list is a real finding about a statically linked target. A
    module list that could not be read is no finding at all, and the
    profile has to be able to tell a reader which one it is holding.
    """
    unreadable = infer_toolkit(None, class_names=[])
    assert unreadable.toolkit == "unknown"
    assert unreadable.modules_readable is False

    clean_look = infer_toolkit([], class_names=[])
    assert clean_look.toolkit == "unknown"
    assert clean_look.modules_readable is True


def test_classes_still_identify_the_toolkit_when_modules_are_unreadable():
    result = infer_toolkit(None, class_names=VCL_CLASSES)

    assert result.toolkit == "delphi-vcl"
    assert result.modules_readable is False


def test_an_embedded_browser_is_reported_from_its_window_class():
    """The profile calls this significant: those regions are a web
    document the window tree cannot see into, so they need a different
    driver from the rest of the application."""
    result = infer_toolkit([], class_names=VCL_CLASSES + ["Chrome_WidgetWin_1"])

    assert result.toolkit == "delphi-vcl"
    assert "embedded-webview" in result.secondary


def test_no_evidence_at_all_stays_unknown():
    result = infer_toolkit([], class_names=["SomeVendorThing", "Static"])

    assert result.toolkit == "unknown"
    assert result.source == "none"


def test_media_foundation_is_not_mistaken_for_mfc():
    """`mfc*.dll` matched `mfcore.dll`, which is Media Foundation Core.

    Found by sweeping live applications: Explorer came back as MFC at
    medium confidence on the strength of it. Media Foundation is loaded by
    anything touching audio or video, so the loose pattern mislabelled a
    large share of ordinary programs.
    """
    for innocent in ("mfcore.dll", "mfplat.dll", "mfreadwrite.dll", "mf.dll"):
        result = infer_toolkit([rf"C:\Windows\System32\{innocent}"])
        assert result.toolkit != "mfc", innocent


def test_real_mfc_runtimes_are_still_matched():
    """The narrowed pattern has to keep catching what it was written for."""
    for genuine in ("mfc140.dll", "mfc140u.dll", "mfc42.dll", "mfc42u.dll"):
        result = infer_toolkit([rf"C:\app\{genuine}"])
        assert result.toolkit == "mfc", genuine
