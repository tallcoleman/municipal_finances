import pytest

from municipal_finances.slc import parse_slc, pdf_slc_to_components, slc_to_pdf_format


class TestParseSlc:
    def test_standard_slc(self):
        result = parse_slc("slc.10.L9930.C01.")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01", "sub": ""}

    def test_lettered_schedule(self):
        result = parse_slc("slc.51A.L0410.C01.")
        assert result == {"schedule": "51A", "line_id": "0410", "column_id": "01", "sub": ""}

    def test_other_lettered_schedules(self):
        assert parse_slc("slc.22A.L0210.C02.")["schedule"] == "22A"
        assert parse_slc("slc.74E.L0110.C01.")["schedule"] == "74E"

    def test_non_empty_sub_field(self):
        result = parse_slc("slc.10.L9930.C01.A")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01", "sub": "A"}

    def test_invalid_missing_prefix(self):
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("10.L9930.C01.")

    def test_invalid_short_line_id(self):
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("slc.10.L993.C01.")

    def test_invalid_short_column_id(self):
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("slc.10.L9930.C1.")

    def test_invalid_empty_string(self):
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("")

    def test_invalid_pdf_format_rejected(self):
        with pytest.raises(ValueError, match="Invalid SLC format"):
            parse_slc("SLC 10 9930 01")


class TestSlcToPdfFormat:
    def test_standard_conversion(self):
        assert slc_to_pdf_format("10", "9930", "01") == "SLC 10 9930 01"

    def test_lettered_schedule(self):
        assert slc_to_pdf_format("51A", "0410", "01") == "SLC 51A 0410 01"

    def test_leading_zero_line_id(self):
        assert slc_to_pdf_format("40", "0210", "05") == "SLC 40 0210 05"


class TestPdfSlcToComponents:
    def test_with_slc_prefix(self):
        result = pdf_slc_to_components("SLC 10 9930 01")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01"}

    def test_without_slc_prefix(self):
        result = pdf_slc_to_components("10 9930 01")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01"}

    def test_lettered_schedule(self):
        result = pdf_slc_to_components("SLC 51A 0410 01")
        assert result == {"schedule": "51A", "line_id": "0410", "column_id": "01"}

    def test_wildcard_line_id(self):
        result = pdf_slc_to_components("40 xxxx 05")
        assert result == {"schedule": "40", "line_id": None, "column_id": "05"}

    def test_wildcard_column_id(self):
        result = pdf_slc_to_components("40 9930 xx")
        assert result == {"schedule": "40", "line_id": "9930", "column_id": None}

    def test_wildcard_case_insensitive(self):
        result = pdf_slc_to_components("40 XXXX 05")
        assert result == {"schedule": "40", "line_id": None, "column_id": "05"}

    def test_wildcard_all_fields(self):
        result = pdf_slc_to_components("xx xxxx xx")
        assert result == {"schedule": None, "line_id": None, "column_id": None}

    def test_leading_trailing_whitespace(self):
        result = pdf_slc_to_components("  SLC 10 9930 01  ")
        assert result == {"schedule": "10", "line_id": "9930", "column_id": "01"}

    def test_invalid_too_few_parts(self):
        with pytest.raises(ValueError, match="Invalid PDF SLC format"):
            pdf_slc_to_components("10 9930")

    def test_invalid_empty_string(self):
        with pytest.raises(ValueError, match="Invalid PDF SLC format"):
            pdf_slc_to_components("")


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
        original = "slc.51A.L0410.C03."
        components = parse_slc(original)
        pdf_ref = slc_to_pdf_format(components["schedule"], components["line_id"], components["column_id"])
        parsed_back = pdf_slc_to_components(pdf_ref)

        assert parsed_back["schedule"] == "51A"
        assert parsed_back["line_id"] == "0410"
        assert parsed_back["column_id"] == "03"
