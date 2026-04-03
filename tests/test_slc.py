import pytest

from municipal_finances.slc import parse_slc, pdf_slc_to_components, slc_to_pdf_format


class TestParseSlc:
    def test_standard_slc(self):
        """A well-formed numeric schedule SLC is parsed into all four components."""
        result = parse_slc("slc.10.L9930.C01.")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01", "sub": ""}

    def test_lettered_schedule(self):
        """A schedule code with a letter suffix (e.g. 51A) is preserved exactly."""
        result = parse_slc("slc.51A.L0410.C01.")
        assert result == {"schedule": "51A", "line_id": "0410", "column_id": "01", "sub": ""}

    def test_other_lettered_schedules(self):
        """Multiple lettered schedule variants (22A, 74E) are each parsed correctly."""
        assert parse_slc("slc.22A.L0210.C02.")["schedule"] == "22A"
        assert parse_slc("slc.74E.L0110.C01.")["schedule"] == "74E"

    def test_non_empty_sub_field(self):
        """A non-empty sub field (trailing segment after the last dot) is captured."""
        result = parse_slc("slc.10.L9930.C01.A")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01", "sub": "A"}

    def test_invalid_missing_prefix(self):
        """A string missing the leading 'slc.' prefix raises ValueError."""
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("10.L9930.C01.")

    def test_invalid_short_line_id(self):
        """A line ID with fewer than 4 digits raises ValueError."""
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("slc.10.L993.C01.")

    def test_invalid_short_column_id(self):
        """A column ID with fewer than 2 digits raises ValueError."""
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("slc.10.L9930.C1.")

    def test_invalid_empty_string(self):
        """An empty string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("")

    def test_invalid_pdf_format_rejected(self):
        """The space-separated PDF format is rejected; parse_slc only accepts the database format."""
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("SLC 10 9930 01")


class TestSlcToPdfFormat:
    def test_standard_conversion(self):
        """Components are joined into the space-separated PDF reference format."""
        assert slc_to_pdf_format("10", "9930", "01") == "SLC 10 9930 01"

    def test_lettered_schedule(self):
        """A lettered schedule code is included verbatim in the PDF format."""
        assert slc_to_pdf_format("51A", "0410", "01") == "SLC 51A 0410 01"

    def test_leading_zero_line_id(self):
        """Leading zeros in line_id are preserved, not stripped."""
        assert slc_to_pdf_format("40", "0210", "05") == "SLC 40 0210 05"


class TestPdfSlcToComponents:
    def test_with_slc_prefix(self):
        """The 'SLC' prefix is accepted and stripped; components are returned correctly."""
        result = pdf_slc_to_components("SLC 10 9930 01")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01"}

    def test_without_slc_prefix(self):
        """A bare three-part reference without the 'SLC' prefix is also accepted."""
        result = pdf_slc_to_components("10 9930 01")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01"}

    def test_lettered_schedule(self):
        """A lettered schedule code in a PDF reference is preserved exactly."""
        result = pdf_slc_to_components("SLC 51A 0410 01")
        assert result == {"schedule": "51A", "line_id": "0410", "column_id": "01"}

    def test_wildcard_line_id(self):
        """A wildcard line token ('xxxx') is returned as None, indicating all lines."""
        result = pdf_slc_to_components("40 xxxx 05")
        assert result == {"schedule": "40", "line_id": None, "column_id": "05"}

    def test_wildcard_column_id(self):
        """A wildcard column token ('xx') is returned as None, indicating all columns."""
        result = pdf_slc_to_components("40 9930 xx")
        assert result == {"schedule": "40", "line_id": "9930", "column_id": None}

    def test_wildcard_case_insensitive(self):
        """Wildcard tokens are matched case-insensitively ('XXXX' is treated the same as 'xxxx')."""
        result = pdf_slc_to_components("40 XXXX 05")
        assert result == {"schedule": "40", "line_id": None, "column_id": "05"}

    def test_wildcard_all_fields(self):
        """All three fields can be wildcarded simultaneously, each returning None."""
        result = pdf_slc_to_components("xx xxxx xx")
        assert result == {"schedule": None, "line_id": None, "column_id": None}

    def test_leading_trailing_whitespace(self):
        """Leading and trailing whitespace around the full string is ignored."""
        result = pdf_slc_to_components("  SLC 10 9930 01  ")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01"}

    def test_invalid_too_few_parts(self):
        """A string with only two space-separated tokens raises ValueError."""
        with pytest.raises(ValueError, match="Invalid PDF SLC format"):
            pdf_slc_to_components("10 9930")

    def test_invalid_empty_string(self):
        """An empty string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid PDF SLC format"):
            pdf_slc_to_components("")

    def test_invalid_short_line_id(self):
        """A line ID with fewer than 4 digits raises ValueError."""
        with pytest.raises(ValueError, match="Invalid PDF SLC format"):
            pdf_slc_to_components("40 993 05")

    def test_invalid_long_line_id(self):
        """A line ID with more than 4 digits raises ValueError."""
        with pytest.raises(ValueError, match="Invalid PDF SLC format"):
            pdf_slc_to_components("40 99300 05")

    def test_invalid_short_column_id(self):
        """A column ID with fewer than 2 digits raises ValueError."""
        with pytest.raises(ValueError, match="Invalid PDF SLC format"):
            pdf_slc_to_components("40 9930 5")

    def test_invalid_long_column_id(self):
        """A column ID with more than 2 digits raises ValueError."""
        with pytest.raises(ValueError, match="Invalid PDF SLC format"):
            pdf_slc_to_components("40 9930 005")


class TestRoundTrip:
    def test_parse_then_to_pdf_then_parse(self):
        """parse_slc -> slc_to_pdf_format -> pdf_slc_to_components produces consistent results."""
        original = "slc.10.L9930.C01."
        components = parse_slc(original)
        pdf_ref = slc_to_pdf_format(components["schedule"], components["line_id"], components["column_id"])
        parsed_back = pdf_slc_to_components(pdf_ref)

        assert parsed_back["schedule"] == components["schedule"]
        assert parsed_back["line_id"] == components["line_id"]
        assert parsed_back["column_id"] == components["column_id"]

    def test_round_trip_lettered_schedule(self):
        """Round-trip conversion preserves a lettered schedule code (51A) through both formats."""
        original = "slc.51A.L0410.C03."
        components = parse_slc(original)
        pdf_ref = slc_to_pdf_format(components["schedule"], components["line_id"], components["column_id"])
        parsed_back = pdf_slc_to_components(pdf_ref)

        assert parsed_back["schedule"] == "51A"
        assert parsed_back["line_id"] == "0410"
        assert parsed_back["column_id"] == "03"
