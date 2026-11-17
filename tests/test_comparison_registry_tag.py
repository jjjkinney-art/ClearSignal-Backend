"""A registry tag in an official name is not a second company in a comparison (2026-11-17; confirmation-2 follow-up).

"Compare the BANK OF AMERICA CORP /DE/ senior notes with its common stock" was ranked as Bank of America versus Deere: the comparison scan read the "DE" of the SEC
registry tag "/DE/" (Delaware) as Deere's ticker. A tag that follows a legal-form word is now masked before the ticker scan; an intentional "$DE" or "DE", slash-separated
ticker lists and real comparisons between different issuers are untouched.
"""
import pytest

from app.services.company_detection import detect_companies, mask_registry_tags


def tickers(text):
    return [c.ticker for c in detect_companies(text)]


@pytest.mark.parametrize("text,expected", [
    ("Compare the BANK OF AMERICA CORP /DE/ senior notes with its common stock", ["BAC"]),     # the defect: the tag is not Deere
    ("Compare Bank of America Corp /DE/ with JPMorgan Chase & Co", ["BAC", "JPM"]),            # a real comparison, tag in the first name
    ("Compare Bank of America Corp /DE/ with Deere & Co /DE/", ["BAC", "DE"]),                 # two tags, two issuers; Deere is named, not tagged
    ("Compare Apple Inc /DE/ with Microsoft", ["AAPL", "MSFT"]),
    ("Compare BAC and $DE", ["BAC", "DE"]),                                                     # an intentional ticker reference
    ("Compare BAC with DE", ["BAC", "DE"]),
    ("Compare Bank of America Corp /DE/ with DE", ["BAC", "DE"]),                              # the tag is masked, the typed DE is not
    ("Compare AAPL/MSFT", ["AAPL", "MSFT"]),                                                    # slash-separated tickers are not a name plus a tag
    ("Compare DE/BAC outlook", ["DE", "BAC"]),
    ("Compare Bank of America Corp. /DE and Apple", ["BAC", "AAPL"]),                           # tag without the closing slash, with a period after the legal form
    ("Compare Bank of America Corp / DE / with Apple", ["BAC", "AAPL"]),                        # tag written with spaces
    ("Compare Alphabet Class A shares with Alphabet Class C shares", ["GOOGL"]),                # the C of "Class C" is a share class, not Citigroup
    ("Compare Citigroup (C) with JPMorgan", ["C", "JPM"]),                                       # the ticker C in its own right is still a ticker
    ("Compare Series B preferred with Bank of America", ["BAC"]),
])
def test_registry_tags_are_not_companies_but_typed_tickers_are(text, expected):
    assert tickers(text) == expected


def test_masking_keeps_offsets_and_touches_only_tags():
    text = "Compare BANK OF AMERICA CORP /DE/ with $DE and AAPL/MSFT"
    masked = mask_registry_tags(text)
    assert len(masked) == len(text) and masked.endswith("with $DE and AAPL/MSFT")
    assert "/DE/" not in masked
    assert mask_registry_tags("No tags here: AAPL, MSFT/NVDA") == "No tags here: AAPL, MSFT/NVDA"


def test_the_class_letter_is_not_a_ticker_in_a_single_company_question_either():
    from app.services.company_detection import resolve_entity
    resolution = resolve_entity("What are the differences between Alphabet Class A shares and Class C shares?")
    assert resolution.context is not None and resolution.context.ticker != "C"
    assert resolve_entity("What is the thesis for C?").context.ticker == "C"          # the ticker C on its own is still Citigroup
