"""Tests for the secrets redaction guard applied to learner memory writes."""

from secrets_filter import redact_secrets

# ── Positive cases: secrets MUST be redacted ──────────────────────────────


def test_redacts_verification_code():
    out = redact_secrets("Your verification code is 482913 for login.")
    assert "482913" not in out
    assert "[REDACTED]" in out
    # The surrounding context is preserved.
    assert "verification code" in out


def test_redacts_otp_label():
    out = redact_secrets("OTP: 123456")
    assert "123456" not in out
    assert "[REDACTED]" in out


def test_redacts_code_is_phrase():
    out = redact_secrets("your code is 90210 now")
    assert "90210" not in out


def test_redacts_code_keyword_after_digits():
    # Real-world shape captured by the learner: digits then "(Verification code)".
    out = redact_secrets("    - 28849 (Verification code)")
    assert "28849" not in out
    assert "[REDACTED]" in out
    assert "Verification code" in out  # label kept


def test_keeps_zip_label_after_digits():
    # "90210 zip code" must NOT be treated as a verification code.
    text = "They moved to 90210 zip code last year."
    assert redact_secrets(text) == text


def test_redacts_openai_style_key():
    out = redact_secrets("key sk-abcdEFGH0123456789ijklmnop here")
    assert "sk-abcdEFGH0123456789ijklmnop" not in out
    assert "[REDACTED]" in out


def test_redacts_github_token():
    out = redact_secrets("token ghp_0123456789abcdefghijABCDEFGHIJ012345")
    assert "ghp_0123456789abcdefghijABCDEFGHIJ012345" not in out


def test_redacts_aws_key():
    out = redact_secrets("AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_redacts_password_assignment():
    out = redact_secrets("password: hunter2swordfish")
    assert "hunter2swordfish" not in out
    assert "password" in out  # label kept, value gone


def test_redacts_ssn():
    out = redact_secrets("SSN 123-45-6789 on file")
    assert "123-45-6789" not in out


def test_redacts_credit_card_luhn_valid():
    out = redact_secrets("card 4111 1111 1111 1111 expires soon")
    assert "4111 1111 1111 1111" not in out
    assert "[REDACTED]" in out


def test_redacts_private_key_block():
    blob = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAA\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    out = redact_secrets(f"here it is: {blob}")
    assert "b3BlbnNzaC1rZXktdjEAAAAA" not in out
    assert "[REDACTED]" in out


# ── Negative cases: benign content MUST be left intact ────────────────────


def test_keeps_day_rate():
    text = "User's day rate is $700 and they work in 2026."
    assert redact_secrets(text) == text


def test_keeps_model_name_and_year():
    text = "Running gemma4-26b on a 64GB machine since 2026."
    assert redact_secrets(text) == text


def test_keeps_phone_and_email():
    text = "Contact: +17066805805 or kineticstudio@icloud.com"
    assert redact_secrets(text) == text


def test_keeps_zip_code():
    # "zip code 90210" must NOT be treated as an OTP/verification code.
    text = "They live in zip code 90210."
    assert redact_secrets(text) == text


def test_keeps_area_code():
    text = "The area code is 212 for that region."
    assert redact_secrets(text) == text


def test_empty_string():
    assert redact_secrets("") == ""
