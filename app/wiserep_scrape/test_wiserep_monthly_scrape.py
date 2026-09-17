import io
import zipfile

from wiserep_monthly_scrape import (
    extract_csv_text_from_zip,
    find_column,
    identify_search_columns,
    is_zip_payload,
    parse_csv_rows,
)


def test_zip_csv_export_exposes_creation_date():
    csv_text = (
        '"Obj. ID","IAU name","Spec. ID","Creation date"\n'
        '"1","SN 2026mza","91460","2026-05-31 22:30:05"\n'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("wiserep_spectra.csv", csv_text)
    payload = buf.getvalue()

    assert is_zip_payload(payload, "application/zip")
    rows = parse_csv_rows(extract_csv_text_from_zip(payload))
    columns = identify_search_columns(rows)

    assert columns["creation"] == "Creation date"
    assert columns["iau"] == "IAU name"
    assert columns["spec_id"] == "Spec. ID"
    assert find_column(
        rows[0].keys(),
        ("Creation Date (UT)", "Creation Date", "Creation date"),
        ("creation", "date"),
    )
