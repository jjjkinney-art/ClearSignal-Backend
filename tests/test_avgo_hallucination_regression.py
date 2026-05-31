"""
tests/test_avgo_hallucination_regression.py

Regression suite: Broadcom (AVGO) hallucination — $90B Apple buyback
contamination and missing custom ASIC / Jericho networking moat content.

Root cause
----------
The synthesis and quality-agent prompts contained Apple-specific numerical
examples presented as "GOOD writing examples":

    "$90B buyback on declining share count amplifies EPS..."   ← Apple's
    "$165B net-cash position and $90B annual buyback sustain EPS..."  ← Apple's
    "$90B buyback compresses share count..."  ← Apple's
    "95% FCF conversion and $90B annual buyback..."  ← Apple's

These examples were shown to the LLM for every company analysis.  The
model learned from them and copied the $90B figure into AVGO output, even
though Broadcom has no such buyback — it is a net-debt company post-VMware.

Additionally, AVGO was missing from the company knowledge database, so the
depth guard had no keywords to require "custom ASIC", "Jericho", and
"networking silicon" in the synthesised thesis.

Fixes (this commit)
-------------------
1. thesis_synthesizer.py — replaced Apple-specific examples with generic
   company-neutral forms; added explicit CROSS-COMPANY CONTAMINATION
   PREVENTION block forbidding use of Apple's dollar amounts for any other
   ticker.
2. investment_agents/quality_agent.py — replaced "$90B annual buyback"
   example with a generic company-neutral form.
3. app/services/company_knowledge.py — added AVGO knowledge profile with
   correct capital allocation facts (dividend-first, not $90B buyback),
   custom ASIC / Jericho / VMware moat keywords, and major risks including
   Apple wireless-chip in-sourcing and hyperscaler ASIC concentration.

Run
---
    python3 -m pytest tests/test_avgo_hallucination_regression.py -v
"""

from __future__ import annotations

import re
import pytest

from app.services.company_knowledge import (
    get_knowledge_profile,
    get_profile_for_company,
    list_known_tickers,
)
from app.schemas import CompanyContext


# ── AVGO knowledge profile presence and content ───────────────────────────────

class TestAvgoKnowledgeProfile:
    """AVGO must have a knowledge profile with correct ASIC/networking content."""

    def test_avgo_profile_exists(self):
        """AVGO must be in the company knowledge database."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None, (
            "AVGO has no entry in company_knowledge.py. "
            "Without a profile, the depth guard cannot enforce ASIC/Jericho moat "
            "presence, and the LLM has no grounding facts to override Apple examples."
        )

    def test_avgo_profile_resolves_via_company_context(self):
        """get_profile_for_company must resolve AVGO by ticker."""
        company = CompanyContext(ticker="AVGO", company_name="Broadcom Inc.")
        profile = get_profile_for_company(company)
        assert profile is not None
        assert profile.ticker == "AVGO"

    def test_avgo_profile_contains_custom_asic_moat(self):
        """AVGO profile must contain custom ASIC business description."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = (
            profile.business_model
            + " ".join(profile.competitive_advantages)
            + " ".join(profile.primary_revenue_drivers)
        ).lower()
        assert "custom asic" in combined or "asic" in combined, (
            "AVGO profile must describe the custom ASIC / XPU business — "
            "this is the primary AI revenue driver and a key moat."
        )

    def test_avgo_profile_contains_jericho_networking(self):
        """AVGO profile must reference Jericho networking silicon moat."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = (
            profile.business_model
            + " ".join(profile.competitive_advantages)
            + " ".join(profile.primary_revenue_drivers)
        ).lower()
        assert "jericho" in combined, (
            "AVGO profile must reference Jericho networking silicon. "
            "Jericho is the moat in service-provider routing — Cisco and Juniper "
            "both depend on it — and its absence from the profile causes omission "
            "in generated analyses."
        )

    def test_avgo_profile_keywords_include_asic_and_jericho(self):
        """business_model_keywords must include ASIC and Jericho terms."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        keywords_lower = [kw.lower() for kw in profile.business_model_keywords]
        assert any("asic" in kw for kw in keywords_lower), (
            "business_model_keywords must include 'custom ASIC' or 'AI ASIC' — "
            "this triggers the depth guard when the synthesised thesis omits ASIC content."
        )
        assert any("jericho" in kw for kw in keywords_lower), (
            "business_model_keywords must include 'Jericho' — "
            "this triggers the depth guard when networking silicon moat is omitted."
        )

    def test_avgo_profile_keywords_include_vmware(self):
        """business_model_keywords must include VMware (software segment moat)."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        keywords_lower = [kw.lower() for kw in profile.business_model_keywords]
        assert any("vmware" in kw for kw in keywords_lower), (
            "AVGO profile must include 'VMware' as a keyword — "
            "VMware is ~25% of revenue and the software segment moat."
        )

    def test_avgo_profile_has_correct_capital_allocation(self):
        """AVGO profile must not POSITIVELY assert a $90B buyback (Apple's figure).
        Every occurrence of '$90B buyback' in the AVGO profile must be in a
        negative / corrective context ('NOT a $90B buyback', 'does NOT have a
        $90B buyback', etc.)."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = (
            profile.business_model
            + " "
            + profile.rate_sensitivity_note
            + " "
            + (profile.inflation_pass_through or "")
            + " "
            + (profile.recession_behavior or "")
        )
        # Find every occurrence of '$90B buyback' and verify each is negated
        pattern = re.compile(r'.{0,30}\$90B buyback.{0,30}', re.IGNORECASE)
        for match in pattern.finditer(combined):
            ctx = match.group(0).lower()
            is_negated = "not" in ctx or "no " in ctx or "never" in ctx
            assert is_negated, (
                f"AVGO profile contains '$90B buyback' in a non-negated context: "
                f"{match.group(0)!r}. "
                "Every $90B reference in the AVGO profile must be a negation — "
                "e.g. 'NOT a $90B buyback' or 'does NOT have a $90B buyback'. "
                "A positive assertion would hallucinate Apple's buyback for Broadcom."
            )

    def test_avgo_profile_mentions_dividend_capital_return(self):
        """AVGO profile must describe dividend-focused capital return (not Apple buyback)."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = (
            profile.business_model
            + profile.rate_sensitivity_note
        ).lower()
        assert "dividend" in combined, (
            "AVGO profile must describe dividend-focused capital return. "
            "AVGO yields ~3-4% from dividends — this is the primary capital return "
            "mechanism, not a $90B buyback."
        )

    def test_avgo_profile_describes_acquisition_debt(self):
        """AVGO profile must mention the VMware acquisition debt burden."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = (
            profile.business_model
            + profile.rate_sensitivity_note
            + " ".join(profile.major_risks)
        ).lower()
        assert "debt" in combined, (
            "AVGO profile must describe the $70-75B post-VMware acquisition debt. "
            "This is a major difference from Apple's net-cash position."
        )

    def test_avgo_profile_includes_apple_socket_risk(self):
        """AVGO profile must describe Apple wireless chip concentration risk."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = " ".join(profile.major_risks).lower()
        assert "apple" in combined, (
            "AVGO profile must describe Apple wireless chip concentration risk. "
            "Apple is designing wireless chips in-house, creating 3-5yr revenue risk."
        )


# ── Cross-company contamination: prompt template checks ──────────────────────

class TestPromptTemplateContamination:
    """Synthesis and agent prompts must not embed Apple-specific dollar amounts
    as unconditional 'GOOD examples' for use with any ticker."""

    def _load_synthesizer_prompt_template(self) -> str:
        """Load the synthesis prompt builder source for inspection."""
        with open(
            "app/services/thesis_synthesizer.py", encoding="utf-8"
        ) as f:
            return f.read()

    def _load_quality_agent_prompt(self) -> str:
        with open(
            "app/investment_agents/quality_agent.py", encoding="utf-8"
        ) as f:
            return f.read()

    def test_synthesizer_no_bare_90b_buyback_example(self):
        """Synthesis prompt must not present '$90B buyback' as a GOOD example
        without an explicit 'Apple's / do not copy' caveat."""
        source = self._load_synthesizer_prompt_template()
        # Find all lines with $90B
        lines = [(i + 1, line) for i, line in enumerate(source.splitlines())
                 if "$90B" in line]
        for lineno, line in lines:
            # Each $90B occurrence must be guarded by an anti-contamination note
            # (i.e., it exists only in the explicit warning block)
            forbidden_contexts = [
                # These are the old contaminating patterns — should NOT appear
                '"$90B buyback on declining share',
                '"$90B buyback ROI deteriorates',
                '"$90B buyback compresses share count',
                'GOOD: "{ticker}\'s $165B net-cash position and $90B annual',
                '95% FCF conversion and $90B annual buyback',
            ]
            for fc in forbidden_contexts:
                assert fc not in line, (
                    f"Line {lineno}: synthesis prompt still contains bare Apple "
                    f"example '{fc[:60]}' without explicit 'Apple only / do not copy' "
                    f"guard. This causes cross-company fact contamination."
                )

    def test_synthesizer_has_anti_contamination_block(self):
        """Synthesis prompt must contain an explicit CROSS-COMPANY CONTAMINATION block."""
        source = self._load_synthesizer_prompt_template()
        assert "CROSS-COMPANY CONTAMINATION PREVENTION" in source, (
            "thesis_synthesizer.py must contain a CROSS-COMPANY CONTAMINATION PREVENTION "
            "block that explicitly forbids copying Apple dollar amounts to other companies."
        )

    def test_synthesizer_anti_contamination_names_90b(self):
        """The contamination block must specifically call out $90B as Apple's."""
        source = self._load_synthesizer_prompt_template()
        # Find the anti-contamination block
        idx = source.find("CROSS-COMPANY CONTAMINATION PREVENTION")
        assert idx != -1
        block = source[idx: idx + 2000]
        assert "$90B" in block and "Apple" in block, (
            "The contamination prevention block must name '$90B buyback' and 'Apple' "
            "so the LLM cannot claim it did not know the figure was Apple-specific."
        )

    def test_synthesizer_anti_contamination_names_165b(self):
        """The contamination block must call out $165B as Apple's."""
        source = self._load_synthesizer_prompt_template()
        idx = source.find("CROSS-COMPANY CONTAMINATION PREVENTION")
        block = source[idx: idx + 2000]
        assert "$165B" in block and "Apple" in block, (
            "The contamination prevention block must name '$165B net-cash' and 'Apple'."
        )

    def test_quality_agent_no_bare_90b_example(self):
        """Quality agent prompt must not present '$90B annual buyback' as a
        generic GOOD example for any company."""
        source = self._load_quality_agent_prompt()
        assert "95% FCF conversion and $90B annual buyback" not in source, (
            "quality_agent.py still contains '$90B annual buyback' as a GOOD signal "
            "example.  This is an Apple-specific figure that must be replaced with a "
            "generic [company-specific] form to prevent cross-company contamination."
        )

    def test_quality_agent_no_bare_90b_at_all(self):
        """Quality agent prompt must contain no bare '$90B' reference."""
        source = self._load_quality_agent_prompt()
        assert "$90B" not in source, (
            "quality_agent.py must not reference '$90B' in any form. "
            "All dollar amounts in examples must be company-neutral."
        )


# ── AVGO-specific hallucination prevention ────────────────────────────────────

class TestAvgoBuybackHallucination:
    """Tests preventing the specific $90B buyback hallucination for AVGO."""

    def test_avgo_profile_rate_sensitivity_explicitly_excludes_90b(self):
        """rate_sensitivity_note must explicitly exclude the $90B buyback."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        # The note should say AVGO does NOT have a $90B buyback
        text = profile.rate_sensitivity_note
        # It should mention "NOT" or "not" near "90B" or state net-debt
        lower = text.lower()
        assert "net-debt" in lower or "not" in lower, (
            "AVGO rate_sensitivity_note must explicitly state that AVGO does NOT "
            "have a $90B buyback and is a net-debt company. Without this, "
            "the LLM may still hallucinate Apple's buyback for AVGO."
        )

    def test_avgo_profile_business_model_says_not_90b_buyback(self):
        """AVGO business_model must explicitly disclaim the $90B buyback."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        # The business_model should contain language about dividend/not $90B buyback
        text = profile.business_model.lower()
        assert "dividend" in text or "not a $90b buyback" in text, (
            "AVGO business_model must describe its actual capital return (dividends, "
            "deleveraging) to prevent the LLM from inferring a $90B buyback."
        )

    def test_avgo_major_risks_do_not_reference_apple_buyback(self):
        """AVGO major_risks must not reference $90B or Apple's buyback metrics."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined_risks = " ".join(profile.major_risks)
        assert "$90B" not in combined_risks, (
            "AVGO major_risks must not contain $90B — that is Apple's figure."
        )

    def test_avgo_has_apple_mentioned_only_as_customer_risk(self):
        """Apple appears in AVGO profile only as a customer concentration risk,
        not as a source of capital allocation data."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        # Apple should appear in risks (wireless chip socket) but not in
        # business_model as a financial comparator
        risks_lower = " ".join(profile.major_risks).lower()
        assert "apple" in risks_lower, (
            "Apple must appear in AVGO major_risks as a customer concentration risk "
            "(Apple wireless chip in-sourcing threat)."
        )
        # Apple should NOT be in rate_sensitivity_note as a financial benchmark
        rate_note = profile.rate_sensitivity_note.lower()
        if "apple" in rate_note:
            # If Apple is mentioned in rate note, it must be for contrast
            assert "unlike apple" in rate_note or "not apple" in rate_note.replace("unlike", "unlike"), (
                "If Apple is mentioned in AVGO rate_sensitivity_note, it must be "
                "as an explicit contrast (e.g. 'Unlike Apple, AVGO does not have...')."
            )


# ── AVGO ASIC/networking omission prevention ─────────────────────────────────

class TestAvgoAsicNetworkingOmission:
    """Tests ensuring AVGO custom ASIC and Jericho content is present in profile."""

    def test_avgo_primary_drivers_include_ai_asic(self):
        """primary_revenue_drivers must include AI ASIC / custom XPU revenue."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = " ".join(profile.primary_revenue_drivers).lower()
        assert "asic" in combined or "xpu" in combined or "tpu" in combined, (
            "AVGO primary_revenue_drivers must name custom AI ASIC / XPU. "
            "This is the fastest-growing segment (~25-30% of semiconductor revenue) "
            "and a primary re-rating catalyst."
        )

    def test_avgo_primary_drivers_include_networking_silicon(self):
        """primary_revenue_drivers must include networking switching silicon."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = " ".join(profile.primary_revenue_drivers).lower()
        assert "jericho" in combined or "tomahawk" in combined or "networking" in combined, (
            "AVGO primary_revenue_drivers must include networking switching silicon "
            "(Jericho/Tomahawk/Trident). This is a core moat and ~20% of semiconductor revenue."
        )

    def test_avgo_competitive_advantages_include_custom_asic(self):
        """competitive_advantages must describe the custom ASIC co-design moat."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = " ".join(profile.competitive_advantages).lower()
        assert "asic" in combined or "xpu" in combined, (
            "AVGO competitive_advantages must describe the custom ASIC co-design moat. "
            "Multi-year TPU/XPU co-design partnerships create a 2-3 year lead time "
            "advantage that is key to the bull thesis."
        )

    def test_avgo_competitive_advantages_include_jericho(self):
        """competitive_advantages must describe Jericho networking silicon moat."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = " ".join(profile.competitive_advantages).lower()
        assert "jericho" in combined, (
            "AVGO competitive_advantages must describe the Jericho networking silicon moat. "
            "Jericho is the only merchant silicon at service-provider scale — "
            "Cisco and Juniper both rely on it."
        )

    def test_avgo_depth_guard_keywords_are_avgo_specific(self):
        """business_model_keywords must be AVGO-specific, not generic or Apple-specific."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        apple_keywords = {"iphone", "services", "app store", "ios", "mac", "ipad",
                          "airpods", "apple watch", "apple pay"}
        avgo_keywords_lower = {kw.lower() for kw in profile.business_model_keywords}
        contaminated = apple_keywords & avgo_keywords_lower
        assert not contaminated, (
            f"AVGO business_model_keywords contain Apple-specific terms: {contaminated}. "
            "These Apple keywords would cause the depth guard to flag Apple content as "
            "required in AVGO theses."
        )

    def test_avgo_key_metrics_include_asic_revenue(self):
        """key_metrics must include AI ASIC / custom XPU revenue as a KPI."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = " ".join(profile.key_metrics).lower()
        assert "asic" in combined or "xpu" in combined or "ai" in combined, (
            "AVGO key_metrics must include AI ASIC quarterly revenue run rate. "
            "This is the primary inflection signal analysts track for AVGO's AI thesis."
        )

    def test_avgo_key_metrics_include_vmware_subscription(self):
        """key_metrics must include VMware subscription ARR."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        combined = " ".join(profile.key_metrics).lower()
        assert "vmware" in combined or "subscription" in combined, (
            "AVGO key_metrics must include VMware subscription ARR / renewal rate. "
            "The software segment ramp is critical to the thesis."
        )


# ── Integrity: AVGO profile is self-consistent ───────────────────────────────

class TestAvgoProfileIntegrity:
    """The AVGO profile must be internally consistent with known facts."""

    def test_avgo_ticker_is_uppercase(self):
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        assert profile.ticker == "AVGO"

    def test_avgo_company_name_is_broadcom(self):
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        assert "Broadcom" in profile.company_name

    def test_avgo_profile_has_all_required_sections(self):
        """All CompanyKnowledgeProfile required fields must be populated."""
        profile = get_knowledge_profile("AVGO")
        assert profile is not None
        assert profile.business_model, "business_model must be non-empty"
        assert len(profile.primary_revenue_drivers) >= 3, "Must have ≥3 revenue drivers"
        assert len(profile.competitive_advantages) >= 2, "Must have ≥2 competitive advantages"
        assert len(profile.business_model_keywords) >= 8, "Must have ≥8 depth-guard keywords"
        assert len(profile.major_risks) >= 3, "Must have ≥3 major risks"
        assert profile.rate_sensitivity_note, "rate_sensitivity_note must be non-empty"

    def test_avgo_in_known_tickers(self):
        """AVGO must appear in list_known_tickers()."""
        assert "AVGO" in list_known_tickers(), (
            "AVGO must be in the knowledge database's list of known tickers."
        )

    def test_avgo_profile_lowercase_lookup_works(self):
        """get_knowledge_profile must be case-insensitive."""
        p1 = get_knowledge_profile("avgo")
        p2 = get_knowledge_profile("AVGO")
        p3 = get_knowledge_profile("Avgo")
        assert p1 is not None
        assert p2 is not None
        assert p3 is not None
        assert p1.ticker == p2.ticker == p3.ticker == "AVGO"
