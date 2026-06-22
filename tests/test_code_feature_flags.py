"""Feature-flag SDK call detection.

A new ``CodeFields.feature_flags`` slot surfaces feature-flag client
call sites detected in the snippet. Each entry is a
``{"vendor", "key"}`` dict capturing the feature-flag vendor and
the flag key referenced in the call.

Recognised vendors:

* ``launchdarkly`` -- ``ldClient.variation`` / ``boolVariation`` /
  ``stringVariation`` / ``variation_detail``
* ``statsig`` -- ``Statsig.checkGate`` / ``getExperiment`` /
  ``getConfig`` / ``getLayer``
* ``unleash`` -- ``unleash.isEnabled`` / ``client.isEnabled``
* ``optimizely`` -- ``optimizely.isFeatureEnabled`` / ``.activate``
* ``split`` -- ``client.getTreatment`` / ``splitClient.getTreatment``
* ``posthog`` -- ``posthog.isFeatureEnabled`` / ``getFeatureFlag``
* ``flagsmith`` -- ``flagsmith.hasFeature`` / ``has_feature``
* ``configcat`` -- ``configcat.getValue`` / ``get_value``

Output preserves first-seen-in-text order, deduped on (vendor, key),
capped at 50 entries.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_feature_flags

# ---- edge cases --------------------------------------------------


def test_empty_string_returns_empty_list():
    assert extract_feature_flags("") == []


def test_whitespace_only_returns_empty_list():
    assert extract_feature_flags("   \n\n  ") == []


def test_plain_code_no_flags_returns_empty_list():
    code = "def foo():\n    return 1\n"
    assert extract_feature_flags(code) == []


# ---- LaunchDarkly ------------------------------------------------


def test_launchdarkly_ldclient_variation():
    code = 'ldClient.variation("my-flag", user, false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "my-flag"}]


def test_launchdarkly_bool_variation():
    code = 'ldClient.boolVariation("new-checkout", user, false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "new-checkout"}]


def test_launchdarkly_string_variation():
    code = 'ldClient.stringVariation("theme-flag", user, "default")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "theme-flag"}]


def test_launchdarkly_json_variation():
    code = 'ldClient.jsonVariation("config-flag", user, {})\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "config-flag"}]


def test_launchdarkly_number_variation():
    code = 'ldClient.numberVariation("rate-limit", user, 100)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "rate-limit"}]


def test_launchdarkly_python_variation_detail():
    code = 'ld_client.variation_detail("py-flag", user, False)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "py-flag"}]


def test_launchdarkly_bare_client_prefix():
    code = 'client.variation("feature.beta", user, false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "feature.beta"}]


# ---- Statsig -----------------------------------------------------


def test_statsig_check_gate_camelcase():
    code = 'Statsig.checkGate("my-gate")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "statsig", "key": "my-gate"}]


def test_statsig_check_gate_snakecase():
    code = 'statsig.check_gate("my_gate")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "statsig", "key": "my_gate"}]


def test_statsig_get_experiment():
    code = 'statsig.getExperiment("exp-name")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "statsig", "key": "exp-name"}]


def test_statsig_get_config():
    code = 'statsig.getConfig("my-config")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "statsig", "key": "my-config"}]


def test_statsig_get_layer():
    code = 'statsig.getLayer("my-layer")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "statsig", "key": "my-layer"}]


def test_statsig_bare_check_gate_without_prefix():
    """Statsig SDKs (JS/Python) allow bare checkGate when imported."""
    code = 'if (checkGate("bare-gate")) { ... }\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "statsig", "key": "bare-gate"}]


# ---- Unleash -----------------------------------------------------


def test_unleash_is_enabled_camelcase():
    code = 'unleash.isEnabled("new-feature")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "unleash", "key": "new-feature"}]


def test_unleash_is_enabled_snakecase():
    code = 'unleash.is_enabled("py_flag")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "unleash", "key": "py_flag"}]


def test_unleash_client_is_enabled():
    code = 'client.isEnabled("toggle-x")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "unleash", "key": "toggle-x"}]


def test_unleash_toggle_client_prefix():
    code = 'toggleClient.isEnabled("toggle-y")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "unleash", "key": "toggle-y"}]


# ---- Optimizely --------------------------------------------------


def test_optimizely_is_feature_enabled_camelcase():
    code = 'optimizely.isFeatureEnabled("opti-flag", userId)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "optimizely", "key": "opti-flag"}]


def test_optimizely_is_feature_enabled_snakecase():
    code = 'optimizely.is_feature_enabled("py-opti", user_id)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "optimizely", "key": "py-opti"}]


def test_optimizely_activate():
    code = 'optimizely.activate("exp-key", userId)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "optimizely", "key": "exp-key"}]


def test_optimizely_get_variation():
    code = 'optimizely.getVariation("variation-test", userId)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "optimizely", "key": "variation-test"}]


def test_optimizely_get_feature_variable_string():
    code = 'optimizely.getFeatureVariableString("feature-key", "var", userId)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "optimizely", "key": "feature-key"}]


def test_optimizely_client_prefix():
    code = 'optimizelyClient.activate("client-exp", userId)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "optimizely", "key": "client-exp"}]


# ---- Split.io ----------------------------------------------------


def test_split_get_treatment():
    code = 'client.getTreatment("split-flag", userId)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "split", "key": "split-flag"}]


def test_split_get_treatment_snakecase():
    code = 'client.get_treatment("py-split", user_id)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "split", "key": "py-split"}]


def test_split_split_client_prefix():
    code = 'splitClient.getTreatment("flag-x", userId)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "split", "key": "flag-x"}]


def test_split_get_treatment_with_config():
    code = 'client.getTreatmentWithConfig("config-flag", userId)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "split", "key": "config-flag"}]


# ---- PostHog -----------------------------------------------------


def test_posthog_is_feature_enabled_camelcase():
    code = 'posthog.isFeatureEnabled("posthog-flag")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "posthog", "key": "posthog-flag"}]


def test_posthog_is_feature_enabled_snakecase():
    code = 'posthog.is_feature_enabled("py_posthog")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "posthog", "key": "py_posthog"}]


def test_posthog_get_feature_flag():
    code = 'posthog.getFeatureFlag("ff-name")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "posthog", "key": "ff-name"}]


def test_posthog_get_feature_flag_payload():
    code = 'posthog.getFeatureFlagPayload("payload-flag")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "posthog", "key": "payload-flag"}]


# ---- Flagsmith ---------------------------------------------------


def test_flagsmith_has_feature_camelcase():
    code = 'flagsmith.hasFeature("smith-flag")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "flagsmith", "key": "smith-flag"}]


def test_flagsmith_has_feature_snakecase():
    code = 'flagsmith.has_feature("py_smith")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "flagsmith", "key": "py_smith"}]


def test_flagsmith_flags_prefix():
    code = 'flags.is_feature_enabled("flags-prefix")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "flagsmith", "key": "flags-prefix"}]


def test_flagsmith_get_value():
    code = 'flagsmith.getValue("value-flag")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "flagsmith", "key": "value-flag"}]


# ---- ConfigCat ---------------------------------------------------


def test_configcat_get_value_camelcase():
    code = 'configcat.getValue("isAwesome", false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "configcat", "key": "isAwesome"}]


def test_configcat_get_value_snakecase():
    code = 'configcat.get_value("is_awesome", False)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "configcat", "key": "is_awesome"}]


def test_configcat_get_value_async():
    code = 'configcat.getValueAsync("async-flag", false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "configcat", "key": "async-flag"}]


def test_configcat_client_prefix():
    code = 'configCatClient.getValue("client-flag", false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "configcat", "key": "client-flag"}]


# ---- Flag key character set --------------------------------------


def test_dashed_flag_key():
    code = 'ldClient.variation("feature-new-checkout", user, false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "feature-new-checkout"}]


def test_dotted_flag_key():
    code = 'ldClient.variation("new.checkout.feature", user, false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "new.checkout.feature"}]


def test_snake_case_flag_key():
    code = 'statsig.check_gate("new_checkout_feature")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "statsig", "key": "new_checkout_feature"}]


def test_mixed_case_flag_key():
    code = 'ldClient.variation("FeatureFlag123", user, false)\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "FeatureFlag123"}]


def test_single_quotes_accepted():
    code = "ldClient.variation('single-quoted', user, false)\n"
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "single-quoted"}]


def test_flag_key_with_digits():
    code = 'statsig.checkGate("flag-v2")\n'
    out = extract_feature_flags(code)
    assert out == [{"vendor": "statsig", "key": "flag-v2"}]


# ---- Multi-flag / multi-vendor -----------------------------------


def test_multiple_launchdarkly_flags_each_recorded():
    code = (
        'ldClient.variation("flag-a", u, false)\n'
        'ldClient.variation("flag-b", u, true)\n'
        'ldClient.variation("flag-c", u, false)\n'
    )
    out = extract_feature_flags(code)
    assert out == [
        {"vendor": "launchdarkly", "key": "flag-a"},
        {"vendor": "launchdarkly", "key": "flag-b"},
        {"vendor": "launchdarkly", "key": "flag-c"},
    ]


def test_multi_vendor_in_same_snippet():
    code = (
        'ldClient.variation("ld-flag", u, false)\n'
        'statsig.checkGate("st-flag")\n'
        'unleash.isEnabled("ul-flag")\n'
        'posthog.isFeatureEnabled("ph-flag")\n'
    )
    out = extract_feature_flags(code)
    vendors = sorted(e["vendor"] for e in out)
    assert vendors == ["launchdarkly", "posthog", "statsig", "unleash"]
    keys = sorted(e["key"] for e in out)
    assert keys == ["ld-flag", "ph-flag", "st-flag", "ul-flag"]


def test_same_vendor_key_pair_deduped():
    """A flag referenced multiple times yields one entry."""
    code = (
        'if (ldClient.variation("same-flag", u, false)) { foo(); }\n'
        'else if (ldClient.variation("same-flag", u, false)) { bar(); }\n'
    )
    out = extract_feature_flags(code)
    assert out == [{"vendor": "launchdarkly", "key": "same-flag"}]


def test_first_seen_order_preserved():
    code = (
        'posthog.isFeatureEnabled("c-flag")\n'
        'ldClient.variation("a-flag", u, false)\n'
        'statsig.checkGate("b-flag")\n'
    )
    out = extract_feature_flags(code)
    keys = [e["key"] for e in out]
    assert keys == ["c-flag", "a-flag", "b-flag"]


def test_max_50_cap_enforced():
    parts: list[str] = []
    for i in range(75):
        parts.append(f'ldClient.variation("flag-{i:03d}", u, false);')
    code = "\n".join(parts)
    out = extract_feature_flags(code)
    assert len(out) == 50


# ---- Negative cases ----------------------------------------------


def test_no_quotes_around_key_rejected():
    """Unquoted argument is not a string literal -> not a flag key."""
    code = "ldClient.variation(flag_var, user, false)\n"
    out = extract_feature_flags(code)
    assert out == []


def test_flag_key_with_space_rejected():
    """Vendor docs discourage spaces; we reject them."""
    code = 'ldClient.variation("flag with space", user, false)\n'
    out = extract_feature_flags(code)
    assert out == []


def test_flag_key_starting_with_digit_rejected():
    """Our regex requires the key to start with a letter."""
    code = 'ldClient.variation("123-flag", user, false)\n'
    out = extract_feature_flags(code)
    assert out == []


def test_random_function_call_with_string_not_matched():
    """A non-vendor call with a string arg is not a feature flag."""
    code = 'someOtherFunc("not-a-flag", x)\n'
    out = extract_feature_flags(code)
    assert out == []


# ---- enrich_code integration -------------------------------------


def test_enrich_code_populates_feature_flags():
    code = (
        'ldClient.variation("ld-flag", user, false)\n'
        'statsig.checkGate("statsig-flag")\n'
    )
    fields = enrich_code(None, OCRResult(text=code))
    flags = fields.feature_flags
    assert len(flags) == 2
    vendors = sorted(e["vendor"] for e in flags)
    assert vendors == ["launchdarkly", "statsig"]


def test_enrich_code_empty_feature_flags_for_plain_code():
    code = "def foo():\n    return 1\n"
    fields = enrich_code(None, OCRResult(text=code))
    assert fields.feature_flags == []


def test_enrich_code_caller_supplied_feature_flags_wins():
    code = 'ldClient.variation("real-flag", user, false)\n'
    existing = CodeFields(
        code=code,
        feature_flags=[{"vendor": "custom", "key": "custom-flag"}],
    )
    fields = enrich_code(existing, OCRResult(text=code))
    assert fields.feature_flags == [{"vendor": "custom", "key": "custom-flag"}]


def test_default_feature_flags_is_empty_list():
    fields = CodeFields()
    assert fields.feature_flags == []


# ---- Realistic multi-line snippets -------------------------------


def test_realistic_react_component_with_launchdarkly():
    code = """
function CheckoutPage({ user }) {
  const newCheckout = ldClient.variation("new-checkout-flow", user, false);
  const betaUI = ldClient.boolVariation("beta-ui", user, false);
  return newCheckout ? <NewFlow /> : <OldFlow />;
}
"""
    out = extract_feature_flags(code)
    assert {"vendor": "launchdarkly", "key": "new-checkout-flow"} in out
    assert {"vendor": "launchdarkly", "key": "beta-ui"} in out


def test_realistic_python_with_statsig():
    code = """
def get_user_treatment(user):
    if statsig.check_gate("show_premium_widget"):
        return "premium"
    cfg = statsig.get_config("widget_config")
    return cfg.get_string("variant", "control")
"""
    out = extract_feature_flags(code)
    assert {"vendor": "statsig", "key": "show_premium_widget"} in out
    assert {"vendor": "statsig", "key": "widget_config"} in out
