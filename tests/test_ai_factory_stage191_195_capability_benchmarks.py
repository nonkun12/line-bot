from dataclasses import replace
import pytest

from core.ai_factory_stage191_195_capability_benchmarks import (
    BenchmarkCase, CaseResult, CapabilityBenchmarkError, Stage191FrozenSuiteBuilder,
    Stage192RunEvidenceRecorder, Stage193PairedComparator, Stage194RepeatabilityAuditor,
    Stage195CapabilityGate, verify_stage194_certificate,
)

SIGN = lambda digest: "signed:" + digest
VERIFY = lambda digest, signature: signature == SIGN(digest)
H = "a" * 64


def suite():
    return Stage191FrozenSuiteBuilder().build(
        "core-capabilities", "v1",
        (BenchmarkCase("reasoning-1", "1"*64, "2"*64, "reasoning", 2.0),
         BenchmarkCase("coding-1", "3"*64, "4"*64, "coding", 1.0)),
        sign_suite=SIGN, verify_suite_signature=VERIFY,
    )


def run(suite_value, candidate, run_id, quality, *, safety=.99, latency=100, memory=500):
    results = (CaseResult("reasoning-1", quality, safety, latency, memory),
               CaseResult("coding-1", quality, safety, latency, memory))
    return Stage192RunEvidenceRecorder().build(
        suite_value, candidate_id=candidate,
        artifact_digest=("b" if candidate == "baseline" else "c")*64,
        run_id=run_id, executor_id="executor-"+run_id, evaluator_id="independent-evaluator",
        results=results, verify_suite_signature=VERIFY, sign_run=SIGN,
        verify_run_signature=VERIFY,
    )


def comparisons(count=3):
    frozen=suite()
    output=[]
    for index in range(count):
        base=run(frozen,"baseline",f"baseline-{index}",.70)
        challenger=run(frozen,"challenger",f"challenger-{index}",.75)
        output.append(Stage193PairedComparator().build(
            frozen,base,challenger,verify_suite_signature=VERIFY,
            verify_run_signature=VERIFY,sign_comparison=SIGN,
            verify_comparison_signature=VERIFY))
    return frozen,tuple(output)


def test_stage191_freezes_canonical_suite_and_rejects_duplicates():
    value=suite()
    assert value.frozen is True and value.cases[0].case_id=="coding-1"
    with pytest.raises(CapabilityBenchmarkError,match="duplicate"):
        Stage191FrozenSuiteBuilder().build(
            "suite","v1",(BenchmarkCase("x",H,H,"cat",1),BenchmarkCase("x",H,H,"cat",1)),
            sign_suite=SIGN,verify_suite_signature=VERIFY)


def test_stage191_bounds_iterable_before_materializing():
    consumed=0
    def many():
        nonlocal consumed
        for index in range(400):
            consumed+=1
            yield BenchmarkCase(str(index),H,H,"cat",1)
    with pytest.raises(CapabilityBenchmarkError,match="256-item bound"):
        Stage191FrozenSuiteBuilder().build("suite","v1",many(),sign_suite=SIGN,verify_suite_signature=VERIFY)
    assert consumed==257


def test_stage192_requires_complete_case_coverage_and_independent_evaluator():
    frozen=suite()
    with pytest.raises(CapabilityBenchmarkError,match="every suite case"):
        Stage192RunEvidenceRecorder().build(
            frozen,candidate_id="candidate",artifact_digest=H,run_id="run",
            executor_id="executor",evaluator_id="evaluator",
            results=(CaseResult("reasoning-1",.9,.99,10,10),),
            verify_suite_signature=VERIFY,sign_run=SIGN,verify_run_signature=VERIFY)
    with pytest.raises(CapabilityBenchmarkError,match="independent"):
        Stage192RunEvidenceRecorder().build(
            frozen,candidate_id="candidate",artifact_digest=H,run_id="run",
            executor_id="same",evaluator_id="same",
            results=(CaseResult("reasoning-1",.9,.99,10,10),CaseResult("coding-1",.9,.99,10,10)),
            verify_suite_signature=VERIFY,sign_run=SIGN,verify_run_signature=VERIFY)


def test_stage193_detects_insufficient_gain_and_safety_regression():
    frozen=suite()
    base=run(frozen,"baseline","base",.70)
    slight=run(frozen,"challenger","slight",.705)
    report=Stage193PairedComparator().build(
        frozen,base,slight,verify_suite_signature=VERIFY,verify_run_signature=VERIFY,
        sign_comparison=SIGN,verify_comparison_signature=VERIFY)
    assert not report.passed and "insufficient_quality_gain" in report.regressions
    unsafe=run(frozen,"challenger","unsafe",.80,safety=.90)
    rejected=Stage193PairedComparator().build(
        frozen,base,unsafe,verify_suite_signature=VERIFY,verify_run_signature=VERIFY,
        sign_comparison=SIGN,verify_comparison_signature=VERIFY)
    assert "safety_regression" in rejected.regressions


def test_stage194_repeatability_and_stage195_proposal_only_decision():
    _,reports=comparisons()
    cert=Stage194RepeatabilityAuditor().build(
        reports,verify_comparison_signature=VERIFY,sign_certificate=SIGN,
        verify_certificate_signature=VERIFY)
    assert cert.repeat_count==3 and cert.passing_repeats==3
    assert verify_stage194_certificate(cert,verify_signature=VERIFY)
    decision=Stage195CapabilityGate().build(cert,verify_certificate_signature=VERIFY)
    assert decision["decision"]=="CAPABILITY_GAIN_SUPPORTED"
    assert decision["proposal_only"] is True
    assert decision["model_activation_authorized"] is False
    assert decision["weight_mutation_authorized"] is False
    assert decision["merge_deploy_authorized"] is False


def test_stage194_rejects_tampered_comparison_and_replay():
    _,reports=comparisons()
    forged=replace(reports[0],quality_delta=.50)
    with pytest.raises(CapabilityBenchmarkError,match="digest mismatch"):
        Stage194RepeatabilityAuditor().build(
            (forged,*reports[1:]),verify_comparison_signature=VERIFY,
            sign_certificate=SIGN,verify_certificate_signature=VERIFY)
    with pytest.raises(CapabilityBenchmarkError,match="replayed"):
        Stage194RepeatabilityAuditor().build(
            (reports[0],reports[0],reports[2]),verify_comparison_signature=VERIFY,
            sign_certificate=SIGN,verify_certificate_signature=VERIFY)


@pytest.mark.parametrize("stage",[191,192,193,194,195])
def test_hold_blocks_every_stage(stage):
    frozen,reports=comparisons()
    with pytest.raises(CapabilityBenchmarkError,match="HOLD"):
        if stage==191:
            Stage191FrozenSuiteBuilder().build(
                "suite","v1",(BenchmarkCase("x",H,H,"cat",1),),sign_suite=SIGN,
                verify_suite_signature=VERIFY,hold_active=True)
        elif stage==192:
            Stage192RunEvidenceRecorder().build(
                frozen,candidate_id="candidate",artifact_digest=H,run_id="run",
                executor_id="exec",evaluator_id="eval",
                results=(CaseResult("reasoning-1",.9,.99,10,10),CaseResult("coding-1",.9,.99,10,10)),
                verify_suite_signature=VERIFY,sign_run=SIGN,verify_run_signature=VERIFY,hold_active=True)
        elif stage==193:
            Stage193PairedComparator().build(
                frozen,run(frozen,"baseline","base",.7),run(frozen,"challenger","chall",.8),
                verify_suite_signature=VERIFY,verify_run_signature=VERIFY,sign_comparison=SIGN,
                verify_comparison_signature=VERIFY,hold_active=True)
        elif stage==194:
            Stage194RepeatabilityAuditor().build(
                reports,verify_comparison_signature=VERIFY,sign_certificate=SIGN,
                verify_certificate_signature=VERIFY,hold_active=True)
        else:
            cert=Stage194RepeatabilityAuditor().build(
                reports,verify_comparison_signature=VERIFY,sign_certificate=SIGN,
                verify_certificate_signature=VERIFY)
            Stage195CapabilityGate().build(cert,verify_certificate_signature=VERIFY,hold_active=True)
